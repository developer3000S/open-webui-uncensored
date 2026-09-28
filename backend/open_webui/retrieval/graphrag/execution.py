"""Execution Layer dispatcher (ТЗ §4.2.5 режимы 1–5, §4.3.1 контракт).

Runs an ExecutionPlan against the pipeline adapters: parallel for ensemble
plans, sequential-with-dependencies for deep plans, single otherwise. Every
task gets its own timeout and retry budget; a task that dies yields a failed
CandidateResponse rather than an exception, so one broken pipeline can never
sink the request (§5.2 надёжность). The global plan deadline bounds the whole
dispatch, and remaining latency/cost budget is threaded into the runtime so
later tasks (agentic) can be cut short by what earlier ones spent (§15.1).

De-escalation (§10.3): in sequential mode, once a stage produces a candidate
whose self-confidence clears `min_overall_score`, later stages are skipped —
further sources would not add information worth their latency.
"""

from __future__ import annotations

import asyncio
import logging
import time

from open_webui.retrieval.graphrag.models import CandidateResponse, ExecutionPlan, PlanTask
from open_webui.retrieval.graphrag.pipeline_adapters import ADAPTERS, PIPELINE_COST_UNITS
from open_webui.retrieval.graphrag.settings import OrchestratorSettings

log = logging.getLogger(__name__)


def insufficient(pool, settings: OrchestratorSettings) -> bool:
    """Escalation predicate for §10.4 `insufficient(candidates, policy)`.

    True when no candidate clears the overall bar, or the best one is weakly
    grounded / self-reports failure — the conditions under which another rung
    of the ladder is worth its latency (§10.2 п.1–2).
    """
    good = [c for c in pool if c.status == 'success']
    if not good:
        return True
    best = max(good, key=lambda c: c.self_confidence)
    # Explicit parentheses: escalation triggers when the best candidate is
    # below the bar, OR when it looks like an empty zero-latency stub.
    return (best.self_confidence < settings.min_overall_score) or (
        best.metadata.latency_ms == 0 and not best.answer_text
    )


class Pool(list):
    """Candidate Response Pool (§4.4.1): per-request, tenant-isolated by
    construction (lives only inside this dispatch), TTL trivially satisfied
    because it is garbage after synthesis."""

    def dedup(self) -> 'Pool':
        seen: set[str] = set()
        out = Pool()
        for c in self:
            key = (c.answer_text or '')[:200].strip()
            if not key:
                out.append(c)
                continue
            if key in seen:
                c.steps.append({'note': 'deduplicated against identical candidate (§4.4.2 п.3)'})
                continue
            seen.add(key)
            out.append(c)
        return out


async def _run_task(task: PlanTask, ctx, policy, runtime, settings) -> tuple[CandidateResponse, dict]:
    adapter = ADAPTERS.get(task.pipeline)
    if adapter is None:
        cand = CandidateResponse(
            pipeline=task.pipeline, task_id=task.task_id, status='failed',
            error_code='unknown_pipeline',
        )
        return cand, {'task_id': task.task_id, 'pipeline': task.pipeline, 'status': 'failed',
                      'error_code': 'unknown_pipeline', 'duration_ms': 0}

    attempts = max(1, task.retry_policy.attempts)
    last: CandidateResponse | None = None
    started = time.time()
    run_notes: list[str] = []
    for attempt in range(attempts):
        try:
            cand = await asyncio.wait_for(
                adapter(task, ctx, policy, runtime),
                timeout=max(0.5, task.timeout_ms / 1000.0),
            )
        except TimeoutError:
            last = CandidateResponse(
                pipeline=task.pipeline, task_id=task.task_id, status='failed',
                error_code='timeout',
            )
            run_notes.append(f'timeout after {task.timeout_ms}ms (attempt {attempt + 1})')
        except Exception as e:
            log.warning('orchestrator: %s task crashed: %s', task.pipeline, e)
            last = CandidateResponse(
                pipeline=task.pipeline, task_id=task.task_id, status='failed',
                error_code=f'{type(e).__name__}',
            )
            run_notes.append(f'error: {str(e)[:160]}')
        if last.status != 'failed':
            break
        if attempt + 1 < attempts:
            await asyncio.sleep(last.metadata.latency_ms / 1000.0 * 0 + task.retry_policy.backoff_ms / 1000.0)

    duration_ms = int((time.time() - started) * 1000)
    last.metadata.latency_ms = duration_ms
    run = {
        'task_id': task.task_id,
        'pipeline': task.pipeline,
        'started_at': started,
        'duration_ms': duration_ms,
        'status': last.status,
        'error_code': last.error_code,
        'notes': ([{'notes': run_notes}] and run_notes) or [],
    }
    # Budget bookkeeping for subsequent waves (§15.1).
    runtime['spent_latency_ms'] = runtime.get('spent_latency_ms', 0) + duration_ms
    runtime['spent_cost_units'] = runtime.get('spent_cost_units', 0.0) + PIPELINE_COST_UNITS.get(task.pipeline, 0.05)
    if last.status != 'failed':
        runtime.setdefault('by_pipeline', {})[task.pipeline] = last
    return last, run


async def execute_plan(plan: ExecutionPlan, ctx, policy, runtime, settings: OrchestratorSettings):
    """Dispatch a plan; returns (pool, pipeline_runs)."""
    pool = Pool()
    runs: list[dict] = []
    if not plan.tasks:
        return pool, runs

    deadline = time.time() + max(0.5, plan.global_timeout_ms / 1000.0)
    tasks_by_id = {t.task_id: t for t in plan.tasks}

    if plan.mode == 'sequential':
        for task in sorted(plan.tasks, key=lambda t: t.priority):
            if time.time() > deadline:
                runs.append({'task_id': task.task_id, 'pipeline': task.pipeline, 'status': 'skipped',
                             'error_code': 'global_deadline', 'duration_ms': 0})
                continue
            cand, run = await _run_task(task, ctx, policy, runtime, settings)
            pool.append(cand)
            runs.append(run)
            good = [c for c in pool if c.status == 'success' and c.self_confidence >= settings.min_overall_score]
            if good:
                for rest in plan.tasks:
                    if rest.task_id not in {r['task_id'] for r in runs}:
                        runs.append({'task_id': rest.task_id, 'pipeline': rest.pipeline, 'status': 'skipped',
                                     'error_code': 'deescalated (§10.3 sufficient candidate found)',
                                     'duration_ms': 0})
                break
    elif plan.mode == 'single':
        task = plan.tasks[0]
        cand, run = await _run_task(task, ctx, policy, runtime, settings)
        pool.append(cand)
        runs.append(run)
    else:  # parallel / conditional / agentic-wave: run all, bounded by deadline
        remaining = max(0.5, deadline - time.time())
        coros = [_run_task(t, ctx, policy, runtime, settings) for t in plan.tasks]
        done, pending = await asyncio.wait(coros, timeout=remaining)
        for fut in done:
            try:
                cand, run = fut.result()
                pool.append(cand)
                runs.append(run)
            except Exception as e:  # defensive: futures shouldn't raise (_run_task catches)
                log.warning('orchestrator: parallel task future raised %s', e)
        for fut in pending:
            fut.cancel()
        # Tasks whose futures were cancelled still need a trace row.
        ran_ids = {r['task_id'] for r in runs}
        for t in plan.tasks:
            if t.task_id not in ran_ids:
                pool.append(CandidateResponse(
                    pipeline=t.pipeline, task_id=t.task_id, status='failed', error_code='global_deadline'))
                runs.append({'task_id': t.task_id, 'pipeline': t.pipeline, 'status': 'failed',
                             'error_code': 'global_deadline', 'duration_ms': 0})

    # Candidate cap from policy (§4.2.2 п.7): keep best N non-failed.
    ok = [c for c in pool if c.status != 'failed']
    bad = [c for c in pool if c.status == 'failed']
    cap = policy.max_candidates or settings.max_candidates
    ok.sort(key=lambda c: c.self_confidence, reverse=True)
    pool = Pool(ok[:cap] + bad)
    return pool.dedup(), runs
