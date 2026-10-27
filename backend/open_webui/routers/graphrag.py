"""Admin API for the knowledge-graph layer.

Endpoints are deliberately thin: state lives in Neo4j (the graph), in
`file.data.graph` (per-file job progress) and in `knowledge.meta.graph` (KB
rollup), so a restart loses only the running asyncio task, never the data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.models.access_grants import AccessGrants
from open_webui.models.knowledge import Knowledges
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)

router = APIRouter()


def _graph_state() -> dict:
    from open_webui.config import GRAPHRAG_LLM_MODEL
    from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, get_graph

    state = {
        'enabled': os.getenv('GRAPHRAG_ENABLED', 'False').lower() == 'true',
        'mode': os.getenv('GRAPHRAG_MODE', 'auto'),
        'model': GRAPHRAG_LLM_MODEL,
        'uri_configured': bool(os.getenv('NEO4J_URI')),
        'connected': False,
        'error': None,
        'stats': None,
    }
    try:
        graph = get_graph()
        graph.verify()
        state['connected'] = True
        state['stats'] = graph.stats()
    except GraphUnavailableError as e:
        state['error'] = str(e)[:300]
    except Exception as e:
        state['error'] = str(e)[:300]
    return state


@router.get('/status')
async def graph_status(request: Request, user=Depends(get_admin_user)):
    """Global switch state, Neo4j reachability, graph size, live jobs."""
    from open_webui.retrieval.graphrag.worker import _running

    state = await asyncio.to_thread(_graph_state)
    models = getattr(request.app.state, 'MODELS', {}) or {}
    state['model_available'] = any(
        m in models or f'ollama:{m}' in models for m in (state['model'], state['model'].split(':')[0])
    )
    state['jobs'] = {fid: job.snapshot() for fid, job in _running.items()}
    return state


async def _require_kb_write(kb_id: str, user) -> None:
    kb = await Knowledges.get_knowledge_by_id(kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Knowledge base not found')
    if (
        user.role != 'admin'
        and kb.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id, resource_type='knowledge', resource_id=kb.id, permission='write'
        )
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not authorized')


@router.post('/knowledge/{kb_id}/index')
async def index_knowledge_base(request: Request, kb_id: str, user=Depends(get_admin_user)):
    """(Re)build the graph for every file of a knowledge base.

    Idempotent: chunks already in the graph are skipped, so this doubles as the
    resume button for an interrupted run.
    """
    await _require_kb_write(kb_id, user)
    state = await asyncio.to_thread(_graph_state)
    if not state['enabled']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='GRAPHRAG_ENABLED is false — set it in .env and restart',
        )
    if not state['connected']:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Neo4j unavailable: {state["error"]}',
        )

    from open_webui.retrieval.graphrag.neo4j_client import get_graph
    from open_webui.retrieval.graphrag.worker import schedule_graph_index

    files = await Knowledges.get_files_by_id(kb_id)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Knowledge base has no files')

    graph = get_graph()
    scheduled = []
    for f in files:
        if schedule_graph_index(request.app, f.id, user.id):
            scheduled.append(f.id)
    return {'scheduled': scheduled, 'total_files': len(files), 'skipped_running': len(files) - len(scheduled)}


@router.get('/knowledge/{kb_id}/status')
async def knowledge_base_graph_status(kb_id: str, user=Depends(get_admin_user)):
    """Per-file graph progress for one knowledge base."""
    await _require_kb_write(kb_id, user)
    from open_webui.retrieval.graphrag.worker import get_job

    files = await Knowledges.get_files_by_id(kb_id)
    out = []
    for f in files:
        job = get_job(f.id)
        snapshot = job.snapshot() if job else (f.data or {}).get('graph')
        out.append(
            {
                'file_id': f.id,
                'filename': f.filename,
                'graph': snapshot,
                'chunks': (f.data or {}).get('total_chunks'),
            }
        )
    kb = await Knowledges.get_knowledge_by_id(kb_id)
    return {'knowledge_base_id': kb_id, 'meta': (kb.meta or {}).get('graph') if kb else None, 'files': out}


@router.delete('/knowledge/{kb_id}')
async def delete_knowledge_base_graph(kb_id: str, user=Depends(get_admin_user)):
    """Drop the graph of every file in a KB (the KB and its vectors stay)."""
    await _require_kb_write(kb_id, user)
    from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, get_graph
    from open_webui.retrieval.graphrag.worker import get_job

    files = await Knowledges.get_files_by_id(kb_id)
    removed = 0
    try:
        graph = get_graph()
    except GraphUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)[:300])
    for f in files:
        job = get_job(f.id)
        if job and not job.done:
            job.cancel.set()
        removed += await asyncio.to_thread(graph.delete_gid, f.id)
    kb = await Knowledges.get_knowledge_by_id(kb_id)
    meta = dict(kb.meta or {}) if kb else {}
    meta.pop('graph', None)
    await Knowledges.update_knowledge_meta_by_id(kb_id, meta)
    return {'deleted_nodes': removed, 'files': len(files)}


@router.get('/knowledge/{kb_id}/graph')
async def inspect_knowledge_base_graph(kb_id: str, limit: int = 30, user=Depends(get_admin_user)):
    """Top entities by degree — a cheap sanity view of what extraction produced."""
    await _require_kb_write(kb_id, user)
    from open_webui.retrieval.graphrag.neo4j_client import GraphUnavailableError, get_graph

    files = await Knowledges.get_files_by_id(kb_id)
    try:
        graph = get_graph()
    except GraphUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)[:300])
    per_file = {}
    for f in files:
        per_file[f.filename] = await asyncio.to_thread(graph.top_entities, f.id, limit)
    return {'knowledge_base_id': kb_id, 'by_file': per_file}


# ── Adaptive RAG orchestrator admin API (ТЗ §9.8, §4.7, §11.3, §4.2.2) ──


@router.get('/orchestrator/status')
async def orchestrator_status(user=Depends(get_admin_user)):
    """Effective orchestration config: flags, thresholds, budgets, quality."""
    from open_webui.retrieval.graphrag import orch_api

    return await orch_api.status_snapshot()


@router.patch('/orchestrator/settings')
async def orchestrator_update_settings(payload: dict, user=Depends(get_admin_user)):
    """Hot-retune orchestration knobs (stored under rag.orchestrator.*)."""
    from open_webui.retrieval.graphrag import orch_api

    return await orch_api.update_settings(payload if isinstance(payload, dict) else {})


@router.get('/orchestrator/traces')
async def orchestrator_traces(
    limit: int = 50,
    intent: str | None = None,
    status_filter: str | None = None,
    action: str | None = None,
    since_hours: float | None = None,
    user=Depends(get_admin_user),
):
    """Recent TraceRecords (§9.8) without candidate payloads."""
    from open_webui.retrieval.graphrag import orch_api

    filters = {'limit': limit, 'intent': intent, 'status': status_filter, 'action': action}
    if since_hours:
        filters['since_ts'] = time.time() - since_hours * 3600
    return {'traces': await asyncio.to_thread(orch_api.list_traces, **filters)}


@router.get('/orchestrator/traces/{trace_id}')
async def orchestrator_trace_detail(trace_id: str, user=Depends(get_admin_user)):
    """Full trace incl. candidates and evaluation report (explainability §15.6)."""
    from open_webui.retrieval.graphrag import orch_api

    trace = await asyncio.to_thread(orch_api.get_trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Trace not found')
    return trace


@router.get('/orchestrator/explain/{trace_id}')
async def orchestrator_explain(trace_id: str, user=Depends(get_admin_user)):
    """Compact "why this answer" projection of a trace for UI panels (rec §4)."""
    from open_webui.retrieval.graphrag import orch_api

    explained = await asyncio.to_thread(orch_api.explain_trace, trace_id)
    if explained is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Trace not found')
    return explained


@router.post('/orchestrator/feedback')
async def orchestrator_feedback(payload: dict, user=Depends(get_admin_user)):
    """Store explicit feedback (§4.7) and calibrate confidence per intent."""
    from open_webui.retrieval.graphrag import orch_api

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='JSON object required')
    rating = payload.get('rating')
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='rating must be an integer')
        if rating not in (-1, 1, 2, 3, 4, 5):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='rating must be -1/+1 or 1..5')
        payload['rating'] = rating
    return await orch_api.submit_feedback(payload)


@router.get('/orchestrator/metrics')
async def orchestrator_metrics(hours: int = 24, user=Depends(get_admin_user)):
    """Drift metrics (§11.3): latency p50/p95, refusal shares, feedback quality."""
    from open_webui.retrieval.graphrag import trace_store

    hours = max(1, min(int(hours), 24 * 30))
    return await asyncio.to_thread(trace_store.metrics_summary, hours)


@router.get('/orchestrator/policy')
async def orchestrator_policy_get(user=Depends(get_admin_user)):
    """Effective policy document (defaults merged with stored overlay)."""
    from open_webui.retrieval.graphrag import orch_api

    return await orch_api.get_policy()


@router.put('/orchestrator/policy')
async def orchestrator_policy_put(doc: dict, user=Depends(get_admin_user)):
    """Validate-and-store the policy-as-code document (§4.2.2)."""
    from open_webui.retrieval.graphrag import orch_api

    try:
        return await orch_api.put_policy(doc)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
