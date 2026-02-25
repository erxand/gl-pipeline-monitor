#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
from pathlib import Path

def _maybe_reexec_into_venv():
    script_dir = Path(__file__).resolve().parent
    venv_python = script_dir / ".venv" / "bin" / "python"
    if venv_python.is_file() and os.environ.get("VENV_PREFERRED") != "1":
        os.environ["VENV_PREFERRED"] = "1"
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

_maybe_reexec_into_venv()

print("Running with:", sys.executable)

import asyncio
import shutil
import subprocess
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Header, Footer, Static, RichLog
from textual.timer import Timer
from textual.binding import Binding
from textual.widgets import DataTable
from rich.text import Text

import gitlab
from models import MR
from widgets import MRTable, RetryLog, build_job_detail, fuzzy_match


REFRESH_INTERVAL = 30
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _preflight_check() -> None:
    """Validate glab CLI environment before starting. Exits with a descriptive error on failure."""
    if shutil.which("glab") is None:
        sys.exit(
            "Error: 'glab' CLI not found in PATH.\n"
            "Install it from: https://gitlab.com/gitlab-org/cli"
        )

    result = subprocess.run(["glab", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        sys.exit(
            "Error: 'glab' is not authenticated.\n"
            "Run 'glab auth login' to authenticate."
        )

    result = subprocess.run(
        ["glab", "api", "projects/:fullpath"], capture_output=True
    )
    if result.returncode != 0:
        sys.exit(
            "Error: Not a GitLab repository.\n"
            "Run this tool from a directory that is a GitLab-backed git repository."
        )


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
    #filter-row {
        dock: top;
        height: 1;
        background: $surface;
    }
    #filter-bar {
        width: 1fr;
        padding: 0 1;
    }
    #hotkeys {
        width: auto;
        padding: 0 1;
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
        Binding("q", "quit", "Quit"),
        Binding("m", "show_mine", "Mine", show=False),
        Binding("a", "show_all", "All", show=False),
        Binding("d", "toggle_drafts", "Drafts", show=False),
        Binding("slash", "start_search", "Search", show=False),
        Binding("r", "toggle_retry", "Retry", show=False),
        Binding("enter", "select_cursor", "Expand", show=False),
        Binding("o", "open_mr", "Open", show=False),
        Binding("f", "force_refresh", "Refresh", show=False),
        Binding("j", "mr_down", "Down", show=False),
        Binding("k", "mr_up", "Up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.mrs: list[MR] = []
        self.show_drafts = False
        self.mine_only = True
        self.search_query: str = ""
        self._searching: bool = False
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._countdown_timer: Timer | None = None
        self._refresh_task: asyncio.Task | None = None
        self._current_user_id: int | None = None
        self._refreshing: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="header-bar")
        with Horizontal(id="filter-row"):
            yield Static(id="filter-bar")
            yield Static(id="hotkeys")
        yield MRTable(id="mr-table")
        yield RichLog(id="detail-panel", max_lines=200)
        yield RetryLog(id="retry-log", max_lines=100)

    def on_mount(self) -> None:
        self._update_header()
        self._update_filter_bar()
        self._update_hotkeys()
        self.query_one("#mr-table", MRTable).loading = True
        self._countdown_timer = self.set_interval(1, self._tick)
        self._spinner_timer = self.set_interval(0.15, self._spin, pause=True)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        self._refresh_task = asyncio.ensure_future(self._do_refresh())

    def _update_header(self) -> None:
        mins = self.seconds_until_refresh // 60
        secs = self.seconds_until_refresh % 60
        self.query_one("#header-bar", Static).update(
            f"GL Pipeline Monitor | Next refresh: {mins}:{secs:02d}"
        )

    def _update_filter_bar(self) -> None:
        t = Text()

        def pill(label: str, active: bool) -> None:
            t.append(f" {label} ", style="bold underline" if active else "dim")

        pill("m Mine", self.mine_only)
        t.append("  ")
        pill("a All", not self.mine_only)
        t.append("  ")
        pill("d Drafts", self.show_drafts)

        t.append("  ")
        t.append(" / ", style="bold underline" if (self._searching or self.search_query) else "dim")
        if self._searching:
            t.append(self.search_query + "▊")
        elif self.search_query:
            t.append(self.search_query, style="dim")
        else:
            t.append("search...", style="dim")

        self.query_one("#filter-bar", Static).update(t)

    def _update_hotkeys(self) -> None:
        spinner = f" {_SPINNER_FRAMES[self._spinner_frame]}" if self._refreshing else ""
        self.query_one("#hotkeys", Static).update(
            f"r retry · ↵ expand · o open · f refresh{spinner} · esc quit"
        )

    def _spin(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._update_hotkeys()

    def _tick(self) -> None:
        self.seconds_until_refresh -= 1
        if self.seconds_until_refresh <= 0:
            self.seconds_until_refresh = REFRESH_INTERVAL
            self._schedule_refresh()
        self._update_header()

    async def _do_refresh(self) -> None:
        self._refreshing = True
        self._spinner_timer.resume()
        self._update_hotkeys()
        log = self.query_one("#retry-log", RetryLog)
        try:
            try:
                if self._current_user_id is None:
                    self._current_user_id = await gitlab.fetch_current_user_id()
                mrs = await gitlab.fetch_mrs(current_user_id=self._current_user_id)
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
                    mr.unresolved_threads = await gitlab.fetch_unresolved_threads(mr.iid)
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
        finally:
            self._refreshing = False
            self._spinner_timer.pause()
            self._update_hotkeys()

    def _visible_mrs(self) -> list[MR]:
        mrs = self.mrs
        if self.mine_only:
            mrs = [mr for mr in mrs if mr.assigned_to_me]
        if not self.show_drafts:
            mrs = [mr for mr in mrs if not mr.is_draft]
        if self.search_query:
            mrs = [mr for mr in mrs if fuzzy_match(mr.title, self.search_query)[0] is not None]
        return mrs

    def _render_table(self) -> None:
        table = self.query_one("#mr-table", MRTable)
        table.loading = False
        # Preserve selected row across re-render
        selected_key = None
        if table.row_count > 0 and table.cursor_row is not None and table.cursor_row < table.row_count:
            selected_key = table.ordered_rows[table.cursor_row].key.value
        table.populate(self._visible_mrs(), search_query=self.search_query)
        if selected_key is not None:
            for idx, row in enumerate(table.ordered_rows):
                if row.key.value == selected_key:
                    table.move_cursor(row=idx)
                    break
        self._update_filter_bar()

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

    # --- Key handling ---

    def on_key(self, event: Key) -> None:
        if not self._searching:
            return
        event.prevent_default()
        if event.key == "escape":
            self._searching = False
            self.search_query = ""
        elif event.key == "enter":
            self._searching = False
        elif event.key == "backspace":
            self.search_query = self.search_query[:-1]
        elif event.character and event.character.isprintable():
            self.search_query += event.character
        self._render_table()

    # --- Actions ---

    def action_show_mine(self) -> None:
        self.mine_only = True
        self._render_table()

    def action_show_all(self) -> None:
        self.mine_only = False
        self._render_table()

    def action_toggle_drafts(self) -> None:
        self.show_drafts = not self.show_drafts
        self._render_table()

    def action_start_search(self) -> None:
        self._searching = True
        self._update_filter_bar()

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

    def action_mr_down(self) -> None:
        self.query_one("#mr-table", MRTable).action_cursor_down()

    def action_mr_up(self) -> None:
        self.query_one("#mr-table", MRTable).action_cursor_up()

    def action_force_refresh(self) -> None:
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._schedule_refresh()
        self._update_header()


if __name__ == "__main__":
    _preflight_check()
    PipelineMonitor().run()
