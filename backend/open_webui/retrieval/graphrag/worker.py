"""Graph indexing worker: vector-store chunks -> Neo4j subgraph per file.

Runs as a detached asyncio task on the app loop after embedding completes (the
only moment chunk ids exist). Tasks do not survive a restart, so resume (skip
chunks whose text hash is already in the graph) is the recovery path, and the
whole pass is idempotent via MERGE.

Chunk text is read from the vector store rather than re-split: a KB membership
copy duplicates every chunk into the KB collection with different ids, so the
text hash is the join key that keeps one extraction per unique chunk.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from open_webui.config import (
    GRAPHRAG_CHUNK_CHAR_LIMIT,
    GRAPHRAG_CONCURRENCY,
    GRAPHRAG_EXTRACT_TIMEOUT,
    GRAPHRAG_LLM_MODEL,
    GRAPHRAG_LLM_THINKING,
    GRAPHRAG_MAX_RETRIES,
)
from open_webui.retrieval.graphrag.extractor import parse_extraction
from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, Neo4jGraph
from open_webui.retrieval.graphrag.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    extraction_user_prompt,
)

log = logging.getLogger(__name__)

_running: dict[str, 'GraphJob'] = {}


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


@dataclass
class GraphJob:
    file_id: str
    total: int = 0
    processed: int = 0
    failed: int = 0
    entities: int = 0
    relations: int = 0
    started_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    done: bool = False
    status: str = 'processing'  # processing|completed|failed|cancelled

    def snapshot(self) -> dict:
        return {
            'status': self.status,
            'processed_chunks': self.processed,
            'total_chunks': self.total,
            'failed_chunks': self.failed,
            'percent': round(min(self.processed / self.total, 1.0) * 100, 1) if self.total else 0.0,
            'entities': self.entities,
            'relations': self.relations,
            'error': self.last_error,
            'updated_at': int(time.time()),
        }


def get_job(file_id: str) -> Optional[GraphJob]:
    return _running.get(file_id)


def entity_uid(name: str, gid: str) -> str:
    # The graph `id` property must be stable across chunks that mention the same
    # name; casefold because Cyrillic models emit both nominal cases.
    return hashlib.sha1(f'{gid}|{name.strip().casefold()}'.encode('utf-8')).hexdigest()


def _resolve_model(app) -> str:
    """Accept either the raw ollama tag or the prefixed UI id."""
    models = getattr(app.state, 'MODELS', {}) or {}
    if GRAPHRAG_LLM_MODEL in models:
        return GRAPHRAG_LLM_MODEL
    for candidate in (f'ollama:{GRAPHRAG_LLM_MODEL}', f'{GRAPHRAG_LLM_MODEL}.ollama'):
        if candidate in models:
            return candidate
    raise RuntimeError(f'GRAPHRAG_LLM_MODEL {GRAPHRAG_LLM_MODEL!r} is not among loaded models ({len(models)} known)')


async def _collect_chunks(file_id: str) -> list[dict]:
    """Unique chunks of a file: [{id, hash, text}] from its file- and KB collections.

    KB collections hold every file's chunks, so metadata.file_id filters them;
    the file collection is the file's own and needs no filter.
    """
    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT

    file_collections = [f'file-{file_id}']
    kbs = await Knowledges.get_knowledges_by_file_id(file_id)
    kb_collections = [kb.id for kb in kbs]

    seen: dict[str, dict] = {}

    async def take(collection: str, by_file: bool):
        try:
            res = await ASYNC_VECTOR_DB_CLIENT.get(collection_name=collection)
        except Exception as e:
            log.warning('graphrag: cannot read collection %s: %s', collection, e)
            return
        if not res or not res.get('ids'):
            return
        metadatas = res.get('metadatas') or [{} for _ in res['ids']]
        for cid, doc, meta in zip(res['ids'], res['documents'], metadatas):
            if not doc:
                continue
            if by_file and (meta or {}).get('file_id') not in (None, file_id):
                continue
            h = text_hash(doc)
            if h not in seen:
                seen[h] = {'id': cid, 'hash': h, 'text': doc}

    for collection in file_collections:
        await take(collection, by_file=False)
    for collection in kb_collections:
        await take(collection, by_file=True)
    return list(seen.values())


async def _extract_via_llm(app, user, model: str, text: str) -> str:
    """One chat completion through the production handler on a synthetic request.

    `_build_request` is the same internal-request pattern automations use;
    bypass_filter because the call is system-initiated and the graph model is
    configured by the admin, not selected by the end user.
    """
    from open_webui.utils.automations import _build_request
    from open_webui.utils.chat import generate_chat_completion

    request = _build_request(app)
    # format=json makes Ollama constrain decoding to JSON — the difference
    # between a parseable answer and a 350M model's prose (verified in the
    # extraction benchmark). think=false stops qwen3-family models from
    # spending the whole token budget on hidden reasoning and returning empty
    # content (measured: Qwen3.8-9b produced 0 content tokens without it).
    form_data = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': EXTRACTION_SYSTEM_PROMPT},
            {'role': 'user', 'content': extraction_user_prompt(text[:GRAPHRAG_CHUNK_CHAR_LIMIT])},
        ],
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0},
        'metadata': {'task': 'graphrag_extraction'},
    }
    if GRAPHRAG_LLM_THINKING is not None:
        form_data['think'] = GRAPHRAG_LLM_THINKING
    result = await generate_chat_completion(request, form_data=form_data, user=user, bypass_filter=True)
    if isinstance(result, dict):
        choices = result.get('choices') or []
        if not choices:
            raise RuntimeError('LLM answer has no choices')
        return choices[0].get('message', {}).get('content') or ''
    return str(result)


async def _embed_names(app, names: list[str], user) -> list[list[float]]:
    """Embed entity names with the document prefix (e5 needs query/passage split)."""
    from open_webui.config import RAG_EMBEDDING_CONTENT_PREFIX

    embedding_function = getattr(app.state, 'EMBEDDING_FUNCTION', None)
    if embedding_function is None:
        raise RuntimeError('embedding function is not initialized')
    return await embedding_function(names, prefix=RAG_EMBEDDING_CONTENT_PREFIX, user=user)


async def extract_chunk(app, graph: Neo4jGraph, user, gid: str, chunk: dict, model: str) -> tuple[int, int]:
    await asyncio.to_thread(
        graph.upsert_chunk, gid, chunk['id'], chunk['hash'], chunk['text'][:4000], len(chunk['text']), False
    )
    raw = await _extract_via_llm(app, user, model, chunk['text'])
    parsed = parse_extraction(raw)
    if parsed.error:
        raise RuntimeError(f'extraction failed: {parsed.error}')

    rows = []
    if parsed.entities:
        embeddings = await _embed_names(app, [e.name for e in parsed.entities], user)
        rows = [
            {
                'id': entity_uid(e.name, gid),
                'name': e.name,
                'type': e.type,
                'description': e.description,
                'embedding': emb,
                'chunk_ids': [chunk['id']],
            }
            for e, emb in zip(parsed.entities, embeddings)
        ]
    n_ent = await asyncio.to_thread(graph.upsert_entities, gid, rows)
    rel_rows = [
        {
            'source': entity_uid(r.source, gid),
            'target': entity_uid(r.target, gid),
            'type': r.type,
            'strength': r.strength,
            'evidence': r.evidence,
            'chunk_id': chunk['id'],
        }
        for r in parsed.relations
    ]
    n_rel = await asyncio.to_thread(graph.upsert_relations, gid, rel_rows)
    await asyncio.to_thread(
        graph.upsert_chunk, gid, chunk['id'], chunk['hash'], chunk['text'][:4000], len(chunk['text']), True
    )
    return n_ent, n_rel


async def _write_progress(file_id: str, snapshot: dict) -> None:
    from open_webui.models.files import Files

    try:
        file = await Files.get_file_by_id(file_id)
        if file is None:
            return
        data = dict(file.data or {})
        data['graph'] = snapshot
        await Files.update_file_data_by_id(file_id, data)
    except Exception as e:
        log.debug('graphrag: progress write failed for %s: %s', file_id, e)


async def run_graph_index(app, file_id: str, user_id: str, graph: Neo4jGraph) -> GraphJob:
    """Index every not-yet-indexed chunk of a file. Single-flight per file."""
    from open_webui.models.users import Users

    job = _running.get(file_id)
    if job and not job.done:
        return job
    job = GraphJob(file_id=file_id)
    _running[file_id] = job

    try:
        user = await Users.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError(f'user {user_id} not found')
        model = _resolve_model(app)

        chunks = await _collect_chunks(file_id)
        job.total = len(chunks)
        if not chunks:
            raise RuntimeError('no vector chunks found for file (embedding may still be running)')

        await asyncio.to_thread(graph.ensure_schema)
        existing = await asyncio.to_thread(graph.indexed_chunk_hashes, file_id)
        todo = [c for c in chunks if c['hash'] not in existing]
        job.processed = len(chunks) - len(todo)
        await _write_progress(file_id, job.snapshot())

        semaphore = asyncio.Semaphore(max(GRAPHRAG_CONCURRENCY, 1))

        async def worker(chunk: dict):
            if job.cancel.is_set():
                return
            async with semaphore:
                if job.cancel.is_set():
                    return
                attempts = 0
                while not job.cancel.is_set():
                    try:
                        n_ent, n_rel = await asyncio.wait_for(
                            extract_chunk(app, graph, user, file_id, chunk, model),
                            timeout=GRAPHRAG_EXTRACT_TIMEOUT,
                        )
                        job.entities += n_ent
                        job.relations += n_rel
                        job.processed += 1
                        await _write_progress(file_id, job.snapshot())
                        return
                    except asyncio.CancelledError:
                        raise
                    except GraphUnavailableError as e:
                        job.last_error = str(e)[:400]
                        job.failed += 1
                        job.processed += 1
                        await _write_progress(file_id, job.snapshot())
                        return
                    except Exception as e:
                        attempts += 1
                        msg = str(e)[:300]
                        transient = any(
                            s in msg.lower() for s in ('timeout', 'busy', 'connection', 'server error', '502', '503')
                        )
                        if attempts >= GRAPHRAG_MAX_RETRIES or not transient:
                            job.last_error = f'chunk {chunk["id"]}: {msg}'
                            job.failed += 1
                            job.processed += 1
                            await _write_progress(file_id, job.snapshot())
                            return
                        await asyncio.sleep(min(2**attempts * 15, 300))

        await asyncio.gather(*(worker(c) for c in todo))

        if job.cancel.is_set():
            job.status = 'cancelled'
        elif job.failed and job.processed == job.failed:
            job.status = 'failed'
        else:
            job.status = 'completed'

        if job.status == 'completed':
            from open_webui.models.knowledge import Knowledges

            kbs = await Knowledges.get_knowledges_by_file_id(file_id)
            for kb in kbs:
                meta = dict(kb.meta or {})
                meta['graph'] = {
                    'status': 'indexed',
                    'updated_at': int(time.time()),
                    'entities': job.entities,
                    'relations': job.relations,
                }
                await Knowledges.update_knowledge_meta_by_id(kb.id, meta)
        return job
    except Exception as e:
        log.exception('graphrag: indexing crashed for %s', file_id)
        job.status = 'failed'
        job.last_error = str(e)[:400]
        return job
    finally:
        job.done = True
        await _write_progress(file_id, job.snapshot())


def schedule_graph_index(app, file_id: str, user_id: str) -> Optional[asyncio.Task]:
    """Fire-and-forget; returns None when disabled/unreachable/already running."""
    from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, get_graph
    from open_webui.retrieval.graphrag.orchestrator import graph_enabled

    if not graph_enabled():
        return None
    existing = _running.get(file_id)
    if existing and not existing.done:
        return None
    try:
        graph = get_graph()
    except GraphUnavailableError as e:
        log.info('graphrag: skipping index of %s: %s', file_id, e)
        return None

    async def _main():
        await run_graph_index(app, file_id, user_id, graph)

    task = asyncio.create_task(_main(), name=f'graphrag-index-{file_id}')
    task.add_done_callback(lambda _t: _running.pop(file_id, None))
    return task
