from __future__ import annotations

from textual.widgets import DataTable, RichLog
from rich.text import Text

from models import MR, Job

STATUS_ICONS = {
    "success": ("✓", "green"),
    "failed": ("✗", "red"),
    "running": ("●", "steel_blue"),
    "pending": ("○", "dim"),
    "canceled": ("⊘", "dim"),
    "skipped": ("⊘", "dim"),
    "manual": ("○", "dim"),
    "created": ("○", "dim"),
    "waiting_for_resource": ("○", "dim"),
}


def status_text(status: str) -> Text:
    icon, style = STATUS_ICONS.get(status, ("?", "dim"))
    return Text(f"{icon} {status}", style=style)


def pipeline_status_text(mr: MR) -> Text:
    if mr.pipeline is None:
        return Text("no pipeline", style="dim")
    return status_text(mr.pipeline.status)


def approval_text(mr: MR) -> Text:
    if mr.approved:
        return Text("✅")
    return Text("")


class MRTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.cursor_foreground_priority = "renderable"

    def populate(self, mrs: list[MR]) -> None:
        self.clear(columns=True)
        self.add_columns("MR", "Title", "Branch", "Pipeline", "Appr.", "Retry", "Threads")
        for mr in mrs:
            retry_indicator = Text("🔄", style="bold") if mr.auto_retry else Text("")
            title = mr.title
            if len(title) > 60:
                title = title[:57] + "..."
            branch = mr.branch
            if len(branch) > 30:
                branch = branch[:27] + "..."
            self.add_row(
                Text(f"!{mr.iid}"),
                Text(title),
                Text(branch, style="dim"),
                pipeline_status_text(mr),
                approval_text(mr),
                retry_indicator,
                Text(str(mr.unresolved_threads), style="yellow" if mr.unresolved_threads > 0 else "white"),
                key=str(mr.iid),
            )


def format_duration(secs: float | None) -> str:
    if secs is None:
        return ""
    secs = int(secs)
    if secs >= 60:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs}s"


def build_job_detail(mr: MR) -> Text:
    if mr.pipeline is None:
        return Text("No pipeline data")
    lines = Text()
    for stage in mr.pipeline.stages:
        lines.append(f"  {stage}:\n", style="cyan")
        stage_jobs = sorted(
            [j for j in mr.pipeline.jobs if j.stage == stage], key=lambda j: j.id
        )
        for job in stage_jobs:
            icon, style = STATUS_ICONS.get(job.status, ("?", "dim"))
            dur = format_duration(job.duration)
            dur_part = f" ({dur})" if dur else ""
            allow_tag = " (allowed to fail)" if job.allow_failure else ""
            lines.append(f"    {icon} ", style=style)
            lines.append(f"{job.name}{dur_part}")
            if allow_tag:
                lines.append(allow_tag, style="dim italic")
            lines.append("\n")
    return lines


class RetryLog(RichLog):
    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
