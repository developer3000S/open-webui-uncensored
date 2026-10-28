import logging
import secrets
import time
from uuid import uuid4

from open_webui.env import DATABASE_URL
from sqlalchemy import create_engine, text as sa_text
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
    installation_id = Column(Text, nullable=True)  # приоритет D: GitHub App installation, если токен app_installation
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_coder_github_connection_user_id', 'user_id'),)


class CoderGitHubAppInstallation(Base):
    """Приоритет D (план coder.qwen.ai): установки GitHub App пользователя."""

    __tablename__ = 'coder_github_app_installation'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    github_host = Column(Text, nullable=False, default='github.com')
    installation_id = Column(Text, nullable=False)
    account_login = Column(Text, nullable=True)  # логин user/org, установившей приложение
    account_type = Column(Text, nullable=True)  # User | Organization
    repository_selection = Column(Text, nullable=True)  # all | selected
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'installation_id', name='uq_coder_ghapp_user_installation'),
        Index('ix_coder_ghapp_user_id', 'user_id'),
    )


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


class CoderSandboxSession(Base):
    """§A (план coder.qwen.ai): изолированный sandbox на задачу.

    MVP реализован как файловая песочница в DATA_DIR/sandboxes/<session_id>:
    жизненный цикл create -> active -> paused -> destroyed, TTL-чистка
    выполняется эндпоинтами sandbox и фоновой sweep-операцией.
    """

    __tablename__ = 'coder_sandbox_session'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    mode = Column(Text, nullable=True)  # web-dev | data-viz | visual-design | prototype
    status = Column(Text, nullable=False, default='active')  # active | paused | destroyed
    chat_id = Column(Text, nullable=True)  # §C4: привязка sandbox к задаче (id задачи из coder_task_meta) для fork
    published_share_id = Column(Text, nullable=True)  # §A4 публикация одним кликом
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    last_active_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_coder_sandbox_session_user_id', 'user_id'),)


class CoderTaskMeta(Base):
    """§B/§C: метаданные задач — автосзвание, теги, pin/archive, follow-up."""

    __tablename__ = 'coder_task_meta'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    mode = Column(Text, nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    status = Column(Text, nullable=True)  # running | done | error | None
    share_enabled = Column(Boolean, nullable=False, default=False)  # §C4 публичный шеринг
    share_token = Column(Text, nullable=True)  # opaque-токен ссылки /shared/{token}
    shared_at = Column(BigInteger, nullable=True)  # время включения шаринга (для счётчика лет)
    forked_from = Column(Text, nullable=True)  # chat_id задачи-источника (если это fork)
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'chat_id', name='uq_coder_task_meta_user_chat'),
        Index('ix_coder_task_meta_user_id', 'user_id'),
        Index('ix_coder_task_meta_share_token', 'share_token'),
    )


class CoderSandboxSessionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    mode: str | None = None
    status: str = 'active'
    chat_id: str | None = None
    published_share_id: str | None = None
    meta: dict | None = None
    created_at: int
    updated_at: int
    last_active_at: int


class CoderSandboxCreateForm(BaseModel):
    mode: str | None = None
    template_id: str | None = None
    chat_id: str | None = None  # §C4: id задачи (coder_task_meta) для привязки sandbox и fork


class CoderTaskMetaForm(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    mode: str | None = None
    is_pinned: bool | None = None
    is_archived: bool | None = None
    status: str | None = None


class CoderTaskShareForm(BaseModel):
    """§C4: включение/выключение публичного шаринга задачи."""

    enabled: bool = True


class CoderTaskForkForm(BaseModel):
    """§C4: копирование чужой опубликованной задачи к себе."""

    title: str | None = None


class CoderGitHubAppInstallationForm(BaseModel):
    installation_id: str
    account_login: str | None = None
    account_type: str | None = None
    repository_selection: str | None = None
    github_host: str = 'github.com'


class CoderGitHubAppConnectionForm(BaseModel):
    installation_id: str
    github_host: str = 'github.com'


class CoderTaskMetaModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    chat_id: str
    title: str | None = None
    tags: list | None = None
    mode: str | None = None
    is_pinned: bool = False
    is_archived: bool = False
    status: str | None = None
    share_enabled: bool = False
    share_token: str | None = None
    forked_from: str | None = None
    meta: dict | None = None
    created_at: int
    updated_at: int


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
    installation_id: str | None = None
    created_at: int
    updated_at: int


class CoderGitHubAppInstallationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    github_host: str = 'github.com'
    installation_id: str
    account_login: str | None = None
    account_type: str | None = None
    repository_selection: str | None = None
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
        token_type: str = 'oauth',
        installation_id: str | None = None,
        db: AsyncSession = None,
    ) -> CoderGithubConnection:
        now = int(time.time())
        # GitHub App installation replaces the OAuth row for the same host;
        # personal OAuth does not overwrite an app_installation connection.
        existing = await self.get_by_user_id(user_id, db)
        if (
            existing is not None
            and existing.github_host == github_host
            and existing.token_type == 'app_installation'
            and token_type == 'oauth'
        ):
            token_type = 'app_installation'
            installation_id = installation_id or existing.installation_id
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
            connection.token_type = token_type
            connection.installation_id = installation_id
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
            token_type=token_type,
            installation_id=installation_id,
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


class CoderSandboxSessions:
    async def get_by_id(self, session_id: str, db: AsyncSession) -> CoderSandboxSession | None:
        result = await db.execute(select(CoderSandboxSession).where(CoderSandboxSession.id == session_id))
        return result.scalars().first()

    async def get_by_chat(
        self, user_id: str, chat_id: str, db: AsyncSession
    ) -> CoderSandboxSession | None:
        """§C4: последняя живая sandbox-сессия задачи (для корректного fork)."""
        if not chat_id:
            return None
        result = await db.execute(
            select(CoderSandboxSession)
            .where(
                CoderSandboxSession.user_id == user_id,
                CoderSandboxSession.chat_id == chat_id,
                CoderSandboxSession.status.in_(['active', 'paused']),
            )
            .order_by(CoderSandboxSession.updated_at.desc())
        )
        return result.scalars().first()

    async def list_by_user_id(
        self, user_id: str, db: AsyncSession, statuses: list[str] | None = None
    ) -> list[CoderSandboxSession]:
        stmt = (
            select(CoderSandboxSession)
            .where(CoderSandboxSession.user_id == user_id)
            .order_by(CoderSandboxSession.updated_at.desc())
        )
        if statuses:
            stmt = stmt.where(CoderSandboxSession.status.in_(statuses))
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create(
        self, user_id: str, mode: str | None = None, meta: dict | None = None,
        chat_id: str | None = None, db: AsyncSession = None
    ) -> CoderSandboxSession:
        now = int(time.time())
        session = CoderSandboxSession(
            id=str(uuid4()),
            user_id=user_id,
            mode=mode,
            status='active',
            chat_id=chat_id,
            meta=meta,
            created_at=now,
            updated_at=now,
            last_active_at=now,
        )
        db.add(session)
        await db.flush()
        return session

    async def update(self, session_id: str, data: dict, db: AsyncSession) -> CoderSandboxSession | None:
        session = await self.get_by_id(session_id, db)
        if not session:
            return None
        for key, value in data.items():
            if hasattr(session, key):
                setattr(session, key, value)
        session.updated_at = int(time.time())
        await db.flush()
        return session

    async def touch(self, session_id: str, db: AsyncSession) -> None:
        session = await self.get_by_id(session_id, db)
        if session:
            now = int(time.time())
            session.last_active_at = now
            session.updated_at = now
            await db.flush()

    async def delete_expired(self, ttl_seconds: int, db: AsyncSession) -> int:
        """TTL-чистка sandbox-сессий (§A1 жизненный цикл destroy)."""
        cutoff = int(time.time()) - ttl_seconds
        result = await db.execute(
            delete(CoderSandboxSession).where(
                CoderSandboxSession.last_active_at < cutoff,
                CoderSandboxSession.status != 'destroyed',
            )
        )
        return result.rowcount


class CoderTaskMetas:
    async def get_by_chat(self, user_id: str, chat_id: str, db: AsyncSession) -> CoderTaskMeta | None:
        result = await db.execute(
            select(CoderTaskMeta).where(CoderTaskMeta.user_id == user_id, CoderTaskMeta.chat_id == chat_id)
        )
        return result.scalars().first()

    async def list_by_user_id(
        self,
        user_id: str,
        db: AsyncSession,
        include_archived: bool = False,
        search: str | None = None,
        tag: str | None = None,
    ) -> list[CoderTaskMeta]:
        stmt = (
            select(CoderTaskMeta)
            .where(CoderTaskMeta.user_id == user_id)
            .order_by(CoderTaskMeta.is_pinned.desc(), CoderTaskMeta.updated_at.desc())
        )
        if not include_archived:
            stmt = stmt.where(CoderTaskMeta.is_archived == False)  # noqa: E712
        if search:
            stmt = stmt.where(CoderTaskMeta.title.ilike(f'%{search}%'))
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        if tag:
            rows = [r for r in rows if tag in (r.tags or [])]
        return rows

    async def upsert(
        self, user_id: str, chat_id: str, form: 'CoderTaskMetaForm', db: AsyncSession
    ) -> CoderTaskMeta:
        now = int(time.time())
        row = await self.get_by_chat(user_id, chat_id, db)
        if row:
            for key in ('title', 'tags', 'mode', 'is_pinned', 'is_archived', 'status'):
                value = getattr(form, key, None)
                if value is not None:
                    setattr(row, key, value)
            row.updated_at = now
            await db.flush()
            return row
        row = CoderTaskMeta(
            id=str(uuid4()),
            user_id=user_id,
            chat_id=chat_id,
            title=form.title,
            tags=form.tags,
            mode=form.mode,
            is_pinned=bool(form.is_pinned),
            is_archived=bool(form.is_archived),
            status=form.status,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    async def delete_by_chat(self, user_id: str, chat_id: str, db: AsyncSession) -> bool:
        result = await db.execute(
            delete(CoderTaskMeta).where(CoderTaskMeta.user_id == user_id, CoderTaskMeta.chat_id == chat_id)
        )
        return result.rowcount > 0

    async def set_share(self, user_id: str, chat_id: str, enabled: bool, db: AsyncSession) -> CoderTaskMeta | None:
        """§C4: включить/выключить публичный шеринг задачи (токен генерируется при включении)."""
        row = await self.get_by_chat(user_id, chat_id, db)
        if not row:
            now = int(time.time())
            row = CoderTaskMeta(
                id=str(uuid4()),
                user_id=user_id,
                chat_id=chat_id,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.flush()
        if enabled:
            if not row.share_enabled or not row.share_token:
                row.share_token = secrets.token_urlsafe(24)
            row.share_enabled = True
            row.shared_at = int(time.time())
        else:
            row.share_enabled = False
            row.share_token = None
            row.shared_at = None
        row.updated_at = int(time.time())
        await db.flush()
        return row

    async def get_by_share_token(self, token: str, db: AsyncSession) -> CoderTaskMeta | None:
        """Публичная страница по токenu — только явно расшаренные задачи."""
        if not token:
            return None
        result = await db.execute(
            select(CoderTaskMeta).where(
                CoderTaskMeta.share_token == token, CoderTaskMeta.share_enabled == True  # noqa: E712
            )
        )
        return result.scalars().first()


class CoderGitHubAppInstallations:
    """Приоритет D: учёт установок GitHub App (по одному ряду на installation)."""

    async def list_by_user_id(self, user_id: str, db: AsyncSession) -> list[CoderGitHubAppInstallation]:
        result = await db.execute(
            select(CoderGitHubAppInstallation)
            .where(CoderGitHubAppInstallation.user_id == user_id)
            .order_by(CoderGitHubAppInstallation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_installation(self, user_id: str, installation_id: str, db: AsyncSession):
        result = await db.execute(
            select(CoderGitHubAppInstallation).where(
                CoderGitHubAppInstallation.user_id == user_id,
                CoderGitHubAppInstallation.installation_id == installation_id,
            )
        )
        return result.scalars().first()

    async def upsert(self, user_id: str, form: CoderGitHubAppInstallationForm, db: AsyncSession):
        now = int(time.time())
        row = await self.get_by_installation(user_id, form.installation_id, db)
        if row:
            row.account_login = form.account_login or row.account_login
            row.account_type = form.account_type or row.account_type
            row.repository_selection = form.repository_selection or row.repository_selection
            row.github_host = form.github_host
            row.updated_at = now
            await db.flush()
            return row
        row = CoderGitHubAppInstallation(
            id=str(uuid4()),
            user_id=user_id,
            github_host=form.github_host,
            installation_id=form.installation_id,
            account_login=form.account_login,
            account_type=form.account_type,
            repository_selection=form.repository_selection,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    async def delete_by_installation(self, user_id: str, installation_id: str, db: AsyncSession) -> bool:
        result = await db.execute(
            delete(CoderGitHubAppInstallation).where(
                CoderGitHubAppInstallation.user_id == user_id,
                CoderGitHubAppInstallation.installation_id == installation_id,
            )
        )
        return result.rowcount > 0


def ensure_coder_schema() -> None:
    """Best-effort авто-создание coder-таблиц/колонок при старте.

    Основная схема применяется через Alembic (`alembic upgrade head`); этот
    хелпер страхует sqlite-деплои от запуска до применения миграций и вызывается
    из lifespan приложения. Ошибки не фатальны — только логируются.
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        engine = create_engine(DATABASE_URL.replace('+aiosqlite', ''))
        with engine.begin() as conn:
            inspector = sa_inspect(engine)
            existing_tables = set(inspector.get_table_names())
            if 'coder_github_app_installation' not in existing_tables:
                CoderGitHubAppInstallation.__table__.create(conn, checkfirst=True)
            if 'coder_github_connection' in existing_tables:
                cols = {c['name'] for c in inspector.get_columns('coder_github_connection')}
                if 'installation_id' not in cols:
                    conn.exec_driver_sql('ALTER TABLE coder_github_connection ADD COLUMN installation_id TEXT')
            if 'coder_task_meta' in existing_tables:
                cols = {c['name'] for c in inspector.get_columns('coder_task_meta')}
                if 'share_enabled' not in cols:
                    conn.exec_driver_sql(
                        'ALTER TABLE coder_task_meta ADD COLUMN share_enabled BOOLEAN NOT NULL DEFAULT 0'
                    )
                if 'share_token' not in cols:
                    conn.exec_driver_sql('ALTER TABLE coder_task_meta ADD COLUMN share_token TEXT')
                if 'shared_at' not in cols:
                    conn.exec_driver_sql('ALTER TABLE coder_task_meta ADD COLUMN shared_at BIGINT')
                if 'forked_from' not in cols:
                    conn.exec_driver_sql('ALTER TABLE coder_task_meta ADD COLUMN forked_from TEXT')
            if 'coder_sandbox_session' in existing_tables:
                sb_cols = {c['name'] for c in inspector.get_columns('coder_sandbox_session')}
                if 'chat_id' not in sb_cols:
                    conn.exec_driver_sql('ALTER TABLE coder_sandbox_session ADD COLUMN chat_id TEXT')
        engine.dispose()
        log.debug('[coder] schema ensured')
    except Exception as exc:  # pragma: no cover - best effort
        log.warning(f'[coder] ensure_coder_schema failed (run alembic upgrade head): {exc}')


####################
# Singleton instances
####################

CoderGithubConnections = CoderGithubConnections()
CoderProjects = CoderProjects()
CoderExportJobs = CoderExportJobs()
CoderAudit = CoderAudit()
CoderSandboxSessions = CoderSandboxSessions()
CoderTaskMetas = CoderTaskMetas()
CoderGitHubAppInstallations = CoderGitHubAppInstallations()
