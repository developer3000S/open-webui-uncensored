"""Background export worker for Coder (NFR-08, §14).

``/export/start`` no longer performs the Git Data API sequence inside the
HTTP request. It creates a job with status ``queued`` and schedules this
worker as an asyncio task; the client polls ``GET /export/jobs/{job_id}``.

The worker opens its own DB session (the request session is closed once the
response is sent) and writes terminal status + audit events itself.
"""

import asyncio
import logging
import time

from open_webui.internal.db import get_async_db
from open_webui.models.coder import CoderAudit, CoderExportJobs
from open_webui.utils.coder.github_client import GitHubAPIError
from open_webui.utils.coder.metrics import observe_export_job

log = logging.getLogger(__name__)

# keep strong references to in-flight tasks so they are not garbage collected
_active_tasks: set[asyncio.Task] = set()


def schedule_export(job_id: str, user_id: str, token: str, form_dict: dict, correlation_id: str | None = None) -> asyncio.Task:
    """Fire-and-forget an export job on the running event loop."""
    task = asyncio.create_task(_run_export(job_id, user_id, token, form_dict, correlation_id))
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task


async def _record_audit(user_id: str, action: str, target: str, payload: dict, correlation_id: str | None, db) -> None:
    try:
        await CoderAudit.record(
            user_id=user_id,
            action=action,
            target=target,
            payload=payload,
            correlation_id=correlation_id,
            db=db,
        )
    except Exception:
        log.debug('coder export worker: audit record failed', exc_info=True)


async def _run_export(job_id: str, user_id: str, token: str, form_dict: dict, correlation_id: str | None) -> None:
    # Local import to avoid a circular dependency at module load time
    from open_webui.routers.coder import _execute_export_job

    started = time.perf_counter()
    owner = form_dict.get('owner', '')
    repo = form_dict.get('repo', '')
    branch = form_dict.get('branch', '')
    target = f'{owner}/{repo}:{branch}'

    try:
        async with get_async_db() as db:
            await CoderExportJobs.update(job_id, {'status': 'running'}, db)
            await _record_audit(user_id, 'export_started', target, {'job_id': job_id}, correlation_id, db)
            await db.commit()

        commit_sha, pr_url, pr_number = await _execute_export_job(job_id, token, form_dict)

        duration = time.perf_counter() - started
        async with get_async_db() as db:
            await CoderExportJobs.update(
                job_id,
                {'status': 'completed', 'commit_sha': commit_sha, 'pr_url': pr_url, 'pr_number': pr_number},
                db,
            )
            await _record_audit(
                user_id,
                'export_completed',
                target,
                {'job_id': job_id, 'commit_sha': commit_sha, 'pr_url': pr_url, 'duration_seconds': round(duration, 2)},
                correlation_id,
                db,
            )
            await db.commit()
        observe_export_job('completed', duration)
    except GitHubAPIError as exc:
        duration = time.perf_counter() - started
        log.warning(f'Coder export job {job_id} failed: {exc.code}: {exc.message}')
        try:
            async with get_async_db() as db:
                await CoderExportJobs.update(job_id, {'status': 'failed', 'error': f'{exc.code}: {exc.message}'}, db)
                await _record_audit(user_id, 'export_failed', target, {'job_id': job_id, 'code': exc.code}, correlation_id, db)
                await db.commit()
        except Exception:
            log.exception('Coder export worker: failed to persist error state')
        observe_export_job('failed', duration)
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - started
        log.exception('Coder export job %s failed unexpectedly', job_id)
        try:
            async with get_async_db() as db:
                await CoderExportJobs.update(job_id, {'status': 'failed', 'error': str(exc)[:500]}, db)
                await _record_audit(user_id, 'export_failed', target, {'job_id': job_id, 'code': 'CODER_EXPORT_FAILED'}, correlation_id, db)
                await db.commit()
        except Exception:
            log.exception('Coder export worker: failed to persist error state')
        observe_export_job('failed', duration)
