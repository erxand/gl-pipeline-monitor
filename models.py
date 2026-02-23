from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Job:
    id: int
    name: str
    stage: str
    status: str
    duration: float | None = None
    allow_failure: bool = False
    web_url: str = ""

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("success", "failed", "canceled", "skipped")


@dataclass
class Pipeline:
    id: int
    status: str
    web_url: str = ""
    jobs: list[Job] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status in ("running", "pending", "created", "waiting_for_resource")

    @property
    def stages(self) -> list[str]:
        seen: list[str] = []
        for job in sorted(self.jobs, key=lambda j: j.id):
            if job.stage not in seen:
                seen.append(job.stage)
        return seen


@dataclass
class MR:
    iid: int
    title: str
    branch: str
    web_url: str
    pipeline: Pipeline | None = None
    approved: bool | None = None  # None = not yet fetched
    unresolved_threads: int = 0
    auto_retry: bool = False
    expanded: bool = False

    @property
    def is_draft(self) -> bool:
        return self.title.startswith("Draft:")
