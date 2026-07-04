from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from .models import JobKind, JobStatus, QueueStatus, RetryStrategy


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""
    organization_name: str = "Default Organization"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectCreate(BaseModel):
    organization_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    priority: int = 0
    concurrency_limit: int = Field(default=5, ge=1, le=100)
    retry_strategy: RetryStrategy = RetryStrategy.exponential
    max_attempts: int = Field(default=3, ge=1, le=50)
    base_delay_seconds: int = Field(default=30, ge=0)
    max_delay_seconds: int = Field(default=3600, ge=1)
    rate_limit_per_minute: int = Field(default=0, ge=0)
    shard_key: str = "default"


class QueueUpdate(BaseModel):
    priority: int | None = None
    concurrency_limit: int | None = Field(default=None, ge=1, le=100)
    status: QueueStatus | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=0)


class JobCreate(BaseModel):
    kind: JobKind = JobKind.immediate
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    delay_seconds: int = Field(default=0, ge=0)
    run_at: datetime | None = None
    cron_expression: str = ""
    batch_key: str = ""
    dependency_job_id: str = ""
    max_attempts: int | None = Field(default=None, ge=1, le=50)


class BatchJobCreate(BaseModel):
    jobs: list[JobCreate] = Field(min_length=1, max_length=500)
    batch_key: str = Field(min_length=1, max_length=64)


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class JobFilter(BaseModel):
    status: JobStatus | None = None
    queue_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
