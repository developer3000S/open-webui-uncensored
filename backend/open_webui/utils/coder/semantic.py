"""Semantic search over a GitHub repository for the Coder section (§22.2).

Strategy:
  1. Fast lexical pre-filter across candidate files (single pass over tree +
     batched file fetch) to build a small candidate pool.
  2. If an embedding model is configured on the server, re-rank the candidate
     chunks by cosine similarity between the query embedding and per-file
     embeddings (cached in-memory per repo/branch/commit with TTL).
  3. Otherwise fall back to TF-IDF-style scoring (no external dependencies).

The module never blocks the request when embeddings are unavailable — semantic
ranking is best-effort and degrades gracefully to lexical ranking.
"""

import logging
import math
import re
import time
from collections import Counter

log = logging.getLogger(__name__)

# In-memory cache: key -> (expires_at, {path: vector})
_EMBED_CACHE: dict[str, tuple[float, dict[str, list[float]]]] = {}
CACHE_TTL_SECONDS = 15 * 60
MAX_CANDIDATES = 120

_CODE_EXT = re.compile(
    r'\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|scala|c|h|cpp|hpp|cs|rb|php|swift|lua|vue|svelte|sql|sh|bash|zsh|yaml|yml|json|toml|ini|cfg|md|txt|html|css|scss|less|xml)$',
    re.IGNORECASE,
)
_SKIP_DIR = re.compile(r'(^|/)(node_modules|\.git|dist|build|out|vendor|venv|__pycache__|\.next|coverage|target)/', re.IGNORECASE)


def is_code_path(path: str) -> bool:
    return bool(_CODE_EXT.search(path)) and not _SKIP_DIR.search(path)


_TOKEN_RE = re.compile(r'[A-Za-z_À-я]{2,}|\d+')


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def lexical_score(query_tokens: list[str], text: str) -> float:
    """Simple BM25-ish term coverage score without dependencies."""
    if not query_tokens:
        return 0.0
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    n = len(tokens)
    score = 0.0
    for q in query_tokens:
        tf = counts.get(q, 0)
        if tf:
            score += (tf / n) ** 0.5
    # bonus for exact substring match (identifiers etc.)
    lowered = text.lower()
    joined = ' '.join(query_tokens)
    if joined and joined in lowered:
        score += 1.0
    return score / max(1, len(query_tokens))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def embed_texts(request, user, texts: list[str]) -> list[list[float]] | None:
    """Best-effort embedding of texts using the server-configured embedding pipeline.

    Uses the app-level ``request.app.state.MODELS`` registry (same source as
    ``/api/v1/embeddings``). Returns None when no embedding model is configured
    or the call fails — callers must then fall back to lexical ranking.
    """
    try:
        from open_webui.utils.embeddings import generate_embeddings

        models = getattr(getattr(request, 'app', None), 'state', None)
        models = getattr(models, 'MODELS', None) if models else None
        if not models:
            return None

        candidates = []
        for mid, m in models.items():
            if not isinstance(m, dict):
                continue
            mtype = (m.get('type') or '').lower()
            name = mid.lower()
            if mtype == 'embedding' or 'embed' in name or 'embed' in (m.get('name') or '').lower():
                candidates.append(mid)
        if not candidates:
            return None

        response = await generate_embeddings(
            request,
            {'model': candidates[0], 'input': texts},
            user,
            bypass_filter=True,
        )
        data = response.get('data') if isinstance(response, dict) else None
        if not data:
            return None
        # preserve index order
        vectors: list[list[float]] = [[] for _ in texts]
        for item in data:
            vectors[item.get('index', 0)] = item.get('embedding') or []
        if any(not v for v in vectors):
            return None
        return vectors
    except Exception:  # noqa: BLE001 - semantic layer is strictly best-effort
        log.debug('coder semantic search: embedding unavailable, falling back to lexical', exc_info=True)
        return None


def _cache_get(key: str) -> dict[str, list[float]] | None:
    entry = _EMBED_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _EMBED_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict[str, list[float]]) -> None:
    _EMBED_CACHE[key] = (time.time() + CACHE_TTL_SECONDS, value)
    # opportunistic pruning
    now = time.time()
    if len(_EMBED_CACHE) > 64:
        for k, (exp, _) in list(_EMBED_CACHE.items()):
            if exp < now:
                _EMBED_CACHE.pop(k, None)


async def rank_files(
    request,
    user,
    query: str,
    files: dict[str, str],
    cache_key: str,
    top_k: int = 15,
) -> list[dict]:
    """Rank {path: content} files against a natural-language query.

    Returns a list of {'path', 'score', 'snippet'} dicts sorted by score desc.
    """
    query_tokens = tokenize(query)
    paths = list(files.keys())[:MAX_CANDIDATES]

    # 1. lexical pre-filter to keep embedding volume sane
    scored_lexical: dict[str, float] = {}
    for p in paths:
        s = lexical_score(query_tokens, files[p])
        if s > 0:
            scored_lexical[p] = s
    shortlist = sorted(scored_lexical.items(), key=lambda kv: kv[1], reverse=True)[:40]
    if not shortlist:
        shortlist = [(p, 0.0) for p in paths[:20]]

    vectors = _cache_get(cache_key)
    need_embed = [p for p, _ in shortlist if vectors is None or p not in (vectors or {})]

    embedded = False
    if need_embed:
        new_vectors = await embed_texts(request, user, [files[p][:4000] for p in need_embed])
        if new_vectors is not None and all(new_vectors):
            vectors = dict(vectors or {})
            for p, v in zip(need_embed, new_vectors):
                vectors[p] = v
            _cache_put(cache_key, vectors)
            embedded = True

    results = []
    if embedded and vectors:
        qvec_list = await embed_texts(request, user, [query])
        qvec = qvec_list[0] if qvec_list and qvec_list[0] else None
        if qvec:
            for p, lex in shortlist:
                sim = cosine_similarity(qvec, vectors.get(p, []))
                score = 0.7 * sim + 0.3 * lex
                if score > 0.01:
                    results.append({'path': p, 'score': round(score, 4), 'mode': 'semantic'})
            results.sort(key=lambda r: r['score'], reverse=True)
            return results[:top_k]

    # lexical fallback
    for p, lex in shortlist:
        snippet = _best_snippet(query_tokens, files[p])
        results.append({'path': p, 'score': round(lex, 4), 'mode': 'lexical', 'snippet': snippet})
    return results[:top_k]


def _best_snippet(query_tokens: list[str], text: str, window: int = 3) -> str:
    lines = text.split('\n')
    best_idx, best_hits = 0, -1
    for i in range(len(lines)):
        seg = lines[i : i + window]
        hits = sum(1 for line in seg for q in query_tokens if q in line.lower())
        if hits > best_hits:
            best_idx, best_hits = i, hits
    return '\n'.join(f'{j + 1}: {lines[j]}' for j in range(best_idx, min(len(lines), best_idx + window)))[:1200]
