"""Graph-side retrieval: vector hit on entities -> neighborhood context.

Design carried over from the Medical-Graph-RAG research clone (its
`simple_graphrag.py` draft), with its fatal flaws fixed: it called a
`VectorRetriever.search` method that does not exist in camel and read an
`m.title` property the schema never writes. Here the vector layer is Neo4j's
native index over the same embedding model the RAG chunks use, and traversal
reads real properties.

The graph is keyed by file (gid = file_id): KB membership is a view over
files, so attach/detach needs no graph work — only upload and deletion do.
"""

import asyncio
import logging
import os

log = logging.getLogger(__name__)

# Guards against degenerate hits (truncated or empty vectors), NOT against
# irrelevance. Measured on the deployed e5-large index: an on-topic query tops
# out at 0.936 while "melting point of tungsten" against the same medical
# entities still scores 0.874-0.894, so absolute cosine barely discriminates and
# no threshold here separates them. What keeps an off-topic query out of the
# graph branch is the relation-cue router in orchestrator.py plus the gid filter
# (only graphs of files in the searched KB are candidates) -- both upstream.
MIN_SCORE = 0.35
AUGMENT_TIMEOUT_S = int(os.getenv('GRAPHRAG_QUERY_TIMEOUT', '20'))


def graph_config() -> dict:
    """Read knobs live so an admin edit applies without a restart."""
    from open_webui.config import RAG_EMBEDDING_QUERY_PREFIX

    return {
        'enabled': os.getenv('GRAPHRAG_ENABLED', 'False').lower() == 'true',
        'top_entities': int(os.getenv('GRAPHRAG_TOP_ENTITIES', '6')),
        'depth': int(os.getenv('GRAPHRAG_TRAVERSAL_DEPTH', '2')),
        'limit_per': int(os.getenv('GRAPHRAG_NEIGHBOR_LIMIT', '12')),
        'query_prefix': RAG_EMBEDDING_QUERY_PREFIX,
    }


def format_graph_context(found: list[dict], neighbors: list[dict], max_chars: int = 6000) -> str:
    """Render entity summaries + relation triples as LLM-readable lines."""
    lines: list[str] = []
    by_id = {f'{r["gid"]}|{r["id"]}': r for r in found}
    for r in found:
        desc = (r.get('description') or '').strip()
        if desc:
            lines.append(f'Сущность: {r["name"]} ({r.get("type") or "?"}). {desc}')

    seen_rel: set[tuple] = set()
    for n in neighbors:
        key = (n['from_gid'], n['from_id'], n['mid'], tuple(n.get('types') or ()))
        if key in seen_rel:
            continue
        seen_rel.add(key)
        hops = n.get('hops') or 1
        entity = by_id.get(f'{n["from_gid"]}|{n["from_id"]}')
        src_name = entity['name'] if entity else n.get('from_id', '?')
        chain = ' -> '.join([src_name, n['mname']])
        rels = ' / '.join(n.get('types') or [])
        strengths = [round(s, 2) for s in (n.get('strengths') or [])]
        line = f'Связь: {chain} [{rels}]'
        if strengths:
            line += f' (уверенность {min(strengths):.2f})'
        if hops > 1:
            line += f' (через {hops - 1} посредников)'
        lines.append(line)

    text = '\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit('\n', 1)[0]
    return text


async def graph_retrieve_embedding(embedding: list[float], gids: list[str]) -> str | None:
    """Expand the graph around entities near `embedding` within `gids`."""
    from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, get_graph

    cfg = graph_config()
    if not gids or not embedding:
        return None
    try:
        graph = get_graph()
    except GraphUnavailableError as e:
        log.info('graphrag: graph unavailable: %s', e)
        return None

    k = cfg['top_entities']
    # Over-fetch: the gid filter is applied after the ANN top-k, so without a
    # margin a big shared graph could return zero usable hits for this KB.
    found = await asyncio.to_thread(graph.vector_search, embedding, k * 4, gids)
    found = [f for f in found if (f.get('score') or 0) >= MIN_SCORE][:k]
    if not found:
        return None

    pairs = {(f['id'], f['gid']) for f in found}
    neighbors = await asyncio.to_thread(graph.neighbors, list(pairs), cfg['depth'], cfg['limit_per'])
    context = format_graph_context(found, neighbors)
    if not context:
        return None

    log.info(
        'graphrag: graph context built: %d entities, %d neighbors, %d chars',
        len(found),
        len(neighbors),
        len(context),
    )
    return context


def _insert_graph_document(query_result: dict, item: dict, context: str) -> None:
    """Prepend the graph triples to the vector search result.

    First position, so the LLM reads the relation summary before the chunks it
    cites; parallel arrays (distances/ids) are kept aligned. The file id of the
    KB itself anchors provenance — the triples are cross-file knowledge.
    """
    documents = query_result.get('documents')
    metadatas = query_result.get('metadatas')
    if not documents or not metadatas or not documents[0] or len(documents) != len(metadatas):
        return
    documents[0].insert(0, context)
    metadatas[0].insert(
        0,
        {
            'source': f'{item.get("name") or item.get("id")}: граф знаний',
            'file_id': item.get('id'),
            'name': 'knowledge-graph',
        },
    )
    for key in ('distances', 'ids'):
        rows = query_result.get(key)
        if rows and len(rows) == len(documents) and rows[0] is not None:
            rows[0].insert(0, 0.0 if key == 'distances' else 'graph-context')


async def maybe_augment_with_graph(request, item, query_result, queries, embedding_function, user) -> None:
    """Graph enrichment for one knowledge item; never raises into the chat path.

    Gated on: global switch, the lexical relation router, and the KB's own
    `meta.graph.status == indexed` — an unindexed KB must cost nothing.
    """
    from open_webui.retrieval.graphrag.orchestrator import graph_enabled, should_use_graph

    try:
        if not graph_enabled() or item.get('type') != 'collection' or not query_result:
            return
        graph_queries = [q for q in queries if isinstance(q, str) and q.strip() and should_use_graph(q)]
        if not graph_queries:
            return

        from open_webui.models.knowledge import Knowledges

        kb = await Knowledges.get_knowledge_by_id(item['id'])
        meta = (kb.meta or {}).get('graph') if kb else None
        if not meta or meta.get('status') != 'indexed':
            return
        files = await Knowledges.get_files_by_id(kb.id)
        gids = [f.id for f in files]
        if not gids:
            return

        # Embed only the first routed query: it is the user's own question
        # (expansion paraphrases add nothing the rerank path doesn't see).
        cfg = graph_config()
        embeddings = await embedding_function([graph_queries[0]], prefix=cfg['query_prefix'])
        if not embeddings:
            return
        try:
            context = await asyncio.wait_for(graph_retrieve_embedding(embeddings[0], gids), timeout=AUGMENT_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.info('graphrag: graph retrieve timed out, keeping vector answer')
            return
        if context:
            _insert_graph_document(query_result, item, context)
    except Exception as e:
        log.warning('graphrag: augmentation failed for KB %s: %s', item.get('id'), e)
