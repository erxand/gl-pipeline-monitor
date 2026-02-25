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


def fuzzy_match(title: str, query: str) -> tuple[float | None, list[int]]:
    """Greedy subsequence match. Returns (score, indices), or (None, []) on no match."""
    tl = title.lower()
    ti = 0
    indices = []
    for char in query.lower():
        while ti < len(tl) and tl[ti] != char:
            ti += 1
        if ti >= len(tl):
            return None, []
        indices.append(ti)
        ti += 1
    return 0.0, indices


def _highlight_match(title: str, query: str) -> Text:
    if not query:
        return Text(title)
    score, indices = fuzzy_match(title, query)
    if score is None:
        return Text(title)
    idx_set = set(indices)
    t = Text()
    for i, char in enumerate(title):
        t.append(char, style="bold yellow" if i in idx_set else "")
    return t


class MRTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.cursor_foreground_priority = "renderable"

    def populate(self, mrs: list[MR], search_query: str = "") -> None:
        self.clear(columns=True)

        # Size the title column to fill remaining horizontal space.
        # Other fixed columns: MR(6) + Branch(30) + Pipeline(11) + Appr.(5) + Retry(5) + Threads(7) = 64
        # DataTable adds ~2 chars of cell padding per column (left+right) × 7 cols = 14
        other_cols = 64
        cell_padding = 14
        title_width = max(20, self.size.width - other_cols - cell_padding) if self.size.width > 0 else 60

        self.add_column("MR", width=6)
        self.add_column("Title", width=title_width)
        self.add_column("Branch", width=30)
        self.add_column("Pipeline", width=11)
        self.add_column("Appr.", width=5)
        self.add_column("Retry", width=5)
        self.add_column("Threads", width=7)

        for mr in mrs:
            retry_indicator = Text("🔄", style="bold") if mr.auto_retry else Text("")
            branch = mr.branch
            if len(branch) > 30:
                branch = branch[:27] + "..."
            self.add_row(
                Text(f"!{mr.iid}"),
                _highlight_match(mr.title, search_query),
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
