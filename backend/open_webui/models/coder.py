import logging
import time
from uuid import uuid4

from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Boolean, Column, Index, String, Text, UniqueConstraint, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


####################
# Coder DB Schema
####################


class CoderGithubConnection(Base):
    __tablename__ = 'coder_github_connection'

    id = Column(Text, primary_key=True)
    # §22.2 «Несколько GitHub-подключений»: уникальность обеспечена частичным
    # уникальным индексом по (user_id, github_host) — см. миграцию c0d3r4m1c7h1.
    user_id = Column(Text, nullable=False)
    github_login = Column(Text, nullable=True)
    github_user_id = Column(Text, nullable=True)
    github_host = Column(Text, nullable=False, default='github.com')  # github.com или домен GH Enterprise
    access_token_encrypted = Column(Text, nullable=False)  # AES-256-GCM, секрет никогда не покидает сервер
    token_type = Column(Text, nullable=False, default='oauth')
    scopes = Column(JSON, nullable=True)
    is_default = Column(Boolean, nullable=False, default=True)  # подключение, используемое по умолчанию
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_coder_github_connection_user_id', 'user_id'),)


class CoderProject(Base):
    __tablename__ = 'coder_project'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    owner = Column(Text, nullable=False)  # github owner/login
    repo = Column(Text, nullable=False)  # repository name
    default_branch = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'owner', 'repo', name='uq_coder_project_user_repo'),
        Index('ix_coder_project_user_id', 'user_id'),
    )


class CoderExportJob(Base):
    __tablename__ = 'coder_export_job'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    project_id = Column(Text, nullable=True)
    owner = Column(Text, nullable=False)
    repo = Column(Text, nullable=False)
    base_branch = Column(Text, nullable=False)
    branch = Column(Text, nullable=False)
    commit_message = Column(Text, nullable=False)
    changeset = Column(JSON, nullable=False)  # validated change set snapshot
    status = Column(Text, nullable=False, default='pending')  # pending | running | completed | failed
    error = Column(Text, nullable=True)
    commit_sha = Column(Text, nullable=True)
    pr_url = Column(Text, nullable=True)
    pr_number = Column(Text, nullable=True)
    idempotency_key = Column(Text, nullable=False, unique=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('ix_coder_export_job_user_id', 'user_id'),
        Index('ix_coder_export_job_status', 'status'),
    )


class CoderAuditEvent(Base):
    __tablename__ = 'coder_audit_event'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    action = Column(Text, nullable=False)  # e.g. github_connect | export_start | export_completed | export_failed
    target = Column(Text, nullable=True)  # e.g. owner/repo[:branch]
    payload = Column(JSON, nullable=True)  # без секретов и без содержимого файлов
    # §11.4: correlation/id контекста запроса для склейки событий одного вызова
    correlation_id = Column(Text, nullable=True)
    # §11.4: сетевой контекст события
    ip_address = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('ix_coder_audit_event_user_id', 'user_id'),
        Index('ix_coder_audit_event_created_at', 'created_at'),
    )


####################
# Pydantic Models
####################


class CoderGithubConnectionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    github_login: str | None = None
    github_user_id: str | None = None
    github_host: str = 'github.com'
    token_type: str
    scopes: list | None = None
    is_default: bool = True
    created_at: int
    updated_at: int


class CoderProjectForm(BaseModel):
    owner: str
    repo: str
    default_branch: str | None = None


class CoderProjectModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    owner: str
    repo: str
    default_branch: str | None = None
    meta: dict | None = None
    created_at: int
    updated_at: int


class CoderExportJobModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    project_id: str | None = None
    owner: str
    repo: str
    base_branch: str
    branch: str
    commit_message: str
    changeset: dict
    status: str
    error: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    pr_number: str | None = None
    idempotency_key: str
    created_at: int
    updated_at: int


class CoderAuditEventModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    action: str
    target: str | None = None
    payload: dict | None = None
    correlation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: int


####################
# Change Set schemas (used by router & validation)
####################


class CoderChangeFile(BaseModel):
    action: str  # create | update | delete
    path: str
    content: str | None = None


class CoderChangeSet(BaseModel):
    files: list[CoderChangeFile] = []


class CoderExportForm(BaseModel):
    owner: str
    repo: str
    base_branch: str
    branch: str
    commit_message: str
    changeset: CoderChangeSet
    idempotency_key: str
    connection_id: str | None = None  # §22.2 multi-GitHub: which account to export with


####################
# Tables
####################


class CoderGithubConnections:
    async def get_by_user_id(self, user_id: str, db: AsyncSession) -> CoderGithubConnection | None:
        """Default connection for a user (multi-GitHub §22.2): prefer is_default, then newest."""
        result = await db.execute(
            select(CoderGithubConnection)
            .where(CoderGithubConnection.user_id == user_id)
            .order_by(CoderGithubConnection.is_default.desc(), CoderGithubConnection.updated_at.desc())
        )
        return result.scalars().first()

    async def get_by_id(self, connection_id: str, user_id: str, db: AsyncSession) -> CoderGithubConnection | None:
        result = await db.execute(
            select(CoderGithubConnection).where(
                CoderGithubConnection.id == connection_id, CoderGithubConnection.user_id == user_id
            )
        )
        return result.scalars().first()

    async def list_by_user_id(self, user_id: str, db: AsyncSession) -> list[CoderGithubConnection]:
        result = await db.execute(
            select(CoderGithubConnection)
            .where(CoderGithubConnection.user_id == user_id)
            .order_by(CoderGithubConnection.is_default.desc(), CoderGithubConnection.updated_at.desc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        user_id: str,
        github_login: str | None,
        github_user_id: str | None,
        access_token_encrypted: str,
        scopes: list | None = None,
        github_host: str = 'github.com',
        db: AsyncSession = None,
    ) -> CoderGithubConnection:
        now = int(time.time())
        # one connection per (user, host) — re-authorizing replaces the token for that host
        result = await db.execute(
            select(CoderGithubConnection).where(
                CoderGithubConnection.user_id == user_id, CoderGithubConnection.github_host == github_host
            )
        )
        connection = result.scalars().first()
        if connection:
            connection.github_login = github_login
            connection.github_user_id = github_user_id
            connection.access_token_encrypted = access_token_encrypted
            connection.scopes = scopes
            connection.updated_at = now
            await db.flush()
            return connection
        has_other = (await self.list_by_user_id(user_id, db)) != []
        connection = CoderGithubConnection(
            id=str(uuid4()),
            user_id=user_id,
            github_login=github_login,
            github_user_id=github_user_id,
            github_host=github_host,
            access_token_encrypted=access_token_encrypted,
            scopes=scopes,
            # first connection becomes default; subsequent ones are secondary
            is_default=not has_other,
            created_at=now,
            updated_at=now,
        )
        db.add(connection)
        await db.flush()
        return connection

    async def set_default(self, connection_id: str, user_id: str, db: AsyncSession) -> bool:
        connection = await self.get_by_id(connection_id, user_id, db)
        if not connection:
            return False
        others = await self.list_by_user_id(user_id, db)
        for c in others:
            c.is_default = c.id == connection.id
        await db.flush()
        return True

    async def delete_by_id(self, connection_id: str, user_id: str, db: AsyncSession) -> bool:
        """Delete a single connection; if it was the default, promote the newest remaining one."""
        remaining = await self.list_by_user_id(user_id, db)
        target = next((c for c in remaining if c.id == connection_id), None)
        if not target:
            return False
        was_default = target.is_default
        await db.delete(target)
        await db.flush()
        if was_default:
            rest = [c for c in remaining if c.id != connection_id]
            if rest:
                rest[0].is_default = True
                await db.flush()
        return True

    async def delete_by_user_id(self, user_id: str, db: AsyncSession) -> bool:
        await db.execute(delete(CoderGithubConnection).where(CoderGithubConnection.user_id == user_id))
        return True


class CoderProjects:
    async def get_by_id(self, project_id: str, db: AsyncSession) -> CoderProject | None:
        result = await db.execute(select(CoderProject).where(CoderProject.id == project_id))
        return result.scalars().first()

    async def get_by_user_repo(self, user_id: str, owner: str, repo: str, db: AsyncSession) -> CoderProject | None:
        result = await db.execute(
            select(CoderProject).where(
                CoderProject.user_id == user_id, CoderProject.owner == owner, CoderProject.repo == repo
            )
        )
        return result.scalars().first()

    async def list_by_user_id(self, user_id: str, db: AsyncSession) -> list[CoderProject]:
        result = await db.execute(
            select(CoderProject).where(CoderProject.user_id == user_id).order_by(CoderProject.updated_at.desc())
        )
        return result.scalars().all()

    async def upsert(self, user_id: str, form: CoderProjectForm, db: AsyncSession) -> CoderProject:
        now = int(time.time())
        project = await self.get_by_user_repo(user_id, form.owner, form.repo, db)
        if project:
            project.default_branch = form.default_branch or project.default_branch
            project.updated_at = now
            await db.flush()
            return project
        project = CoderProject(
            id=str(uuid4()),
            user_id=user_id,
            owner=form.owner,
            repo=form.repo,
            default_branch=form.default_branch,
            created_at=now,
            updated_at=now,
        )
        db.add(project)
        await db.flush()
        return project

    async def delete(self, project_id: str, db: AsyncSession) -> bool:
        result = await db.execute(delete(CoderProject).where(CoderProject.id == project_id))
        return result.rowcount > 0


class CoderExportJobs:
    async def get_by_id(self, job_id: str, db: AsyncSession) -> CoderExportJob | None:
        result = await db.execute(select(CoderExportJob).where(CoderExportJob.id == job_id))
        return result.scalars().first()

    async def get_by_idempotency_key(self, idempotency_key: str, db: AsyncSession) -> CoderExportJob | None:
        result = await db.execute(select(CoderExportJob).where(CoderExportJob.idempotency_key == idempotency_key))
        return result.scalars().first()

    async def list_by_user_id(self, user_id: str, db: AsyncSession, limit: int = 50) -> list[CoderExportJob]:
        result = await db.execute(
            select(CoderExportJob)
            .where(CoderExportJob.user_id == user_id)
            .order_by(CoderExportJob.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def create(
        self,
        user_id: str,
        owner: str,
        repo: str,
        base_branch: str,
        branch: str,
        commit_message: str,
        changeset: dict,
        idempotency_key: str,
        project_id: str | None = None,
        db: AsyncSession = None,
    ) -> CoderExportJob:
        now = int(time.time())
        job = CoderExportJob(
            id=str(uuid4()),
            user_id=user_id,
            project_id=project_id,
            owner=owner,
            repo=repo,
            base_branch=base_branch,
            branch=branch,
            commit_message=commit_message,
            changeset=changeset,
            status='pending',
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        await db.flush()
        return job

    async def update(self, job_id: str, data: dict, db: AsyncSession) -> CoderExportJob | None:
        job = await self.get_by_id(job_id, db)
        if not job:
            return None
        for key, value in data.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = int(time.time())
        await db.flush()
        return job


class CoderAudit:
    async def record(
        self,
        user_id: str,
        action: str,
        target: str | None = None,
        payload: dict | None = None,
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        db: AsyncSession = None,
    ) -> CoderAuditEvent:
        event = CoderAuditEvent(
            id=str(uuid4()),
            user_id=user_id,
            action=action,
            target=target,
            payload=payload,
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=int(time.time()),
        )
        db.add(event)
        await db.flush()
        return event

    async def list_by_user_id(self, user_id: str, db: AsyncSession, limit: int = 100) -> list[CoderAuditEvent]:
        result = await db.execute(
            select(CoderAuditEvent)
            .where(CoderAuditEvent.user_id == user_id)
            .order_by(CoderAuditEvent.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_all(self, db: AsyncSession, limit: int = 100) -> list[CoderAuditEvent]:
        """Admin overview: audit events across all users (§14.1)."""
        result = await db.execute(
            select(CoderAuditEvent).order_by(CoderAuditEvent.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def cleanup_old_events(self, retention_days: int, db: AsyncSession) -> int:
        """Delete audit events older than specified retention period (in days)."""
        from sqlalchemy import delete, select
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
        stmt = delete(CoderAuditEvent).where(CoderAuditEvent.created_at < cutoff_time)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount


####################
# Singleton instances
####################

CoderGithubConnections = CoderGithubConnections()
CoderProjects = CoderProjects()
CoderExportJobs = CoderExportJobs()
CoderAudit = CoderAudit()
