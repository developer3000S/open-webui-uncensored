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
    user_id = Column(Text, nullable=False, unique=True)
    github_login = Column(Text, nullable=True)
    github_user_id = Column(Text, nullable=True)
    access_token_encrypted = Column(Text, nullable=False)  # AES-256-GCM, секрет никогда не покидает сервер
    token_type = Column(Text, nullable=False, default='oauth')
    scopes = Column(JSON, nullable=True)
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
    token_type: str
    scopes: list | None = None
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


####################
# Tables
####################


class CoderGithubConnections:
    async def get_by_user_id(self, user_id: str, db: AsyncSession) -> CoderGithubConnection | None:
        result = await db.execute(select(CoderGithubConnection).where(CoderGithubConnection.user_id == user_id))
        return result.scalars().first()

    async def upsert(
        self,
        user_id: str,
        github_login: str | None,
        github_user_id: str | None,
        access_token_encrypted: str,
        scopes: list | None = None,
        db: AsyncSession = None,
    ) -> CoderGithubConnection:
        now = int(time.time())
        connection = await self.get_by_user_id(user_id, db)
        if connection:
            connection.github_login = github_login
            connection.github_user_id = github_user_id
            connection.access_token_encrypted = access_token_encrypted
            connection.scopes = scopes
            connection.updated_at = now
            await db.flush()
            return connection
        connection = CoderGithubConnection(
            id=str(uuid4()),
            user_id=user_id,
            github_login=github_login,
            github_user_id=github_user_id,
            access_token_encrypted=access_token_encrypted,
            scopes=scopes,
            created_at=now,
            updated_at=now,
        )
        db.add(connection)
        await db.flush()
        return connection

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
        db: AsyncSession = None,
    ) -> CoderAuditEvent:
        event = CoderAuditEvent(
            id=str(uuid4()),
            user_id=user_id,
            action=action,
            target=target,
            payload=payload,
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


####################
# Singleton instances
####################

CoderGithubConnections = CoderGithubConnections()
CoderProjects = CoderProjects()
CoderExportJobs = CoderExportJobs()
CoderAudit = CoderAudit()
