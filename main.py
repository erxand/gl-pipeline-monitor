#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, RichLog
from textual.timer import Timer
from textual.binding import Binding
from textual.widgets import DataTable
from rich.text import Text

import gitlab
from models import MR
from widgets import MRTable, RetryLog, build_job_detail

REFRESH_INTERVAL = 30


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class PipelineMonitor(App):
    TITLE = "GitLab MRs"

    CSS = """
    #header-bar {
        dock: top;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }
    #hotkeys {
        dock: top;
        height: 1;
        background: $surface;
        padding: 0 1;
        text-align: right;
        color: $text-muted;
    }
    #mr-table {
        height: 1fr;
    }
    #mr-table > .datatable--cursor {
        background: $surface;
        text-style: bold;
    }
    #mr-table > .datatable--hover {
        background: transparent;
        text-style: none;
    }
    #detail-panel {
        height: auto;
        border-top: solid $primary;
        padding: 0 1;
        display: none;
    }
    #retry-log {
        dock: bottom;
        height: 6;
        border-top: solid $accent;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("a", "toggle_all", "All MRs", show=False),
        Binding("d", "toggle_drafts", "Drafts", show=False),
        Binding("r", "toggle_retry", "Retry", show=False),
        Binding("enter", "select_cursor", "Expand", show=False),
        Binding("o", "open_mr", "Open", show=False),
        Binding("f", "force_refresh", "Refresh", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.mrs: list[MR] = []
        self.show_drafts = False
        self.mine_only = True
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._countdown_timer: Timer | None = None
        self._refresh_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="header-bar")
        yield Static(
            "a all MRs · d drafts · r retry · ↵ expand · o open · f refresh · esc quit",
            id="hotkeys",
        )
        yield MRTable(id="mr-table")
        yield RichLog(id="detail-panel", max_lines=200)
        yield RetryLog(id="retry-log", max_lines=100)

    def on_mount(self) -> None:
        self._update_header()
        self._countdown_timer = self.set_interval(1, self._tick)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        self._refresh_task = asyncio.ensure_future(self._do_refresh())

    def _update_header(self) -> None:
        drafts_label = "ON" if self.show_drafts else "OFF"
        scope_label = "All" if not self.mine_only else "Mine"
        mins = self.seconds_until_refresh // 60
        secs = self.seconds_until_refresh % 60
        header = self.query_one("#header-bar", Static)
        header.update(
            f"GL Pipeline Monitor | MRs: {scope_label} | Drafts: {drafts_label} | "
            f"Next refresh: {mins}:{secs:02d}"
        )

    def _tick(self) -> None:
        self.seconds_until_refresh -= 1
        if self.seconds_until_refresh <= 0:
            self.seconds_until_refresh = REFRESH_INTERVAL
            self._schedule_refresh()
        self._update_header()

    async def _do_refresh(self) -> None:
        log = self.query_one("#retry-log", RetryLog)
        try:
            mrs = await gitlab.fetch_mrs(mine_only=self.mine_only)
        except Exception as e:
            log.write(f"[yellow]{_ts()}[/] [red]Error fetching MRs: {e}[/]")
            return

        # Preserve auto_retry and expanded state from previous data
        old_state = {mr.iid: (mr.auto_retry, mr.expanded) for mr in self.mrs}
        for mr in mrs:
            prev = old_state.get(mr.iid, (False, False))
            mr.auto_retry = prev[0]
            mr.expanded = prev[1]

        # Fetch pipelines concurrently
        async def enrich(mr: MR) -> None:
            try:
                mr.pipeline = await gitlab.fetch_pipeline(mr.iid)
                mr.approved = await gitlab.fetch_approvals(mr.iid)
                if mr.pipeline and (mr.pipeline.is_active or mr.expanded):
                    mr.pipeline.jobs = await gitlab.fetch_jobs(mr.pipeline.id)
            except Exception:
                pass

        await asyncio.gather(*(enrich(mr) for mr in mrs))

        self.mrs = mrs
        self._render_table()
        self._render_detail()

        # Run auto-retry immediately after refresh
        await self._retry_check()

    def _visible_mrs(self) -> list[MR]:
        if self.show_drafts:
            return self.mrs
        return [mr for mr in self.mrs if not mr.is_draft]

    def _render_table(self) -> None:
        table = self.query_one("#mr-table", MRTable)
        # Preserve selected row across re-render
        selected_key = None
        if table.row_count > 0 and table.cursor_row is not None and table.cursor_row < table.row_count:
            selected_key = table.ordered_rows[table.cursor_row].key.value
        table.populate(self._visible_mrs())
        if selected_key is not None:
            for idx, row in enumerate(table.ordered_rows):
                if row.key.value == selected_key:
                    table.move_cursor(row=idx)
                    break

    def _selected_mr(self) -> MR | None:
        table = self.query_one("#mr-table", MRTable)
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            return None
        row_key = table.ordered_rows[table.cursor_row].key
        for mr in self.mrs:
            if str(mr.iid) == row_key.value:
                return mr
        return None

    def _render_detail(self) -> None:
        panel = self.query_one("#detail-panel", RichLog)
        mr = self._selected_mr()
        if mr and mr.expanded:
            panel.clear()
            panel.write(build_job_detail(mr))
            panel.styles.display = "block"
        else:
            panel.styles.display = "none"

    async def _auto_retry_mr(self, mr: MR) -> None:
        if mr.pipeline is None:
            return
        log = self.query_one("#retry-log", RetryLog)
        failed_jobs = [
            j for j in mr.pipeline.jobs if j.is_failed and not j.allow_failure
        ]
        if not failed_jobs:
            log.write(
                f"[yellow]{_ts()}[/] [dim]No failed jobs for [bold]!{mr.iid}[/] to retry[/]"
            )
        for job in failed_jobs:
            log.write(
                f"[yellow]{_ts()}[/] Retrying [bold]!{mr.iid}[/] "
                f"job [cyan]{job.name}[/] ({job.id})..."
            )
            ok, err = await gitlab.retry_job(job.id)
            if ok:
                log.write(f"[yellow]{_ts()}[/]   [green]✓ Retry triggered[/]")
            else:
                log.write(f"[yellow]{_ts()}[/]   [red]✗ Retry failed: {err}[/]")

    async def _retry_check(self) -> None:
        retry_mrs = [mr for mr in self.mrs if mr.auto_retry and mr.pipeline]
        if not retry_mrs:
            return
        # Fetch fresh job data for these MRs
        for mr in retry_mrs:
            try:
                mr.pipeline.jobs = await gitlab.fetch_jobs(mr.pipeline.id)
            except Exception:
                pass
            await self._auto_retry_mr(mr)

    # --- Actions ---

    def action_toggle_all(self) -> None:
        self.mine_only = not self.mine_only
        self._update_header()
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._schedule_refresh()

    def action_toggle_drafts(self) -> None:
        self.show_drafts = not self.show_drafts
        self._render_table()
        self._update_header()

    async def action_toggle_retry(self) -> None:
        mr = self._selected_mr()
        if mr:
            mr.auto_retry = not mr.auto_retry
            self._render_table()
            log = self.query_one("#retry-log", RetryLog)
            state = "ON" if mr.auto_retry else "OFF"
            log.write(f"[yellow]{_ts()}[/] Auto-retry for [bold]!{mr.iid}[/]: {state}")
            if mr.auto_retry:
                # Ensure we have jobs loaded, then retry immediately
                if mr.pipeline and not mr.pipeline.jobs:
                    mr.pipeline.jobs = await gitlab.fetch_jobs(mr.pipeline.id)
                await self._auto_retry_mr(mr)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        for mr in self.mrs:
            if str(mr.iid) == event.row_key.value:
                mr.expanded = not mr.expanded
                if mr.expanded and mr.pipeline and not mr.pipeline.jobs:
                    mr.pipeline.jobs = await gitlab.fetch_jobs(mr.pipeline.id)
                self._render_detail()
                break

    async def action_open_mr(self) -> None:
        mr = self._selected_mr()
        if mr:
            await gitlab.open_mr_in_browser(mr.iid)

    def action_force_refresh(self) -> None:
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._schedule_refresh()
        self._update_header()


if __name__ == "__main__":
    PipelineMonitor().run()
