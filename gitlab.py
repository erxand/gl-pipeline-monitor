from __future__ import annotations

import asyncio
import json

from models import Job, MR, Pipeline


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()


async def fetch_mrs(mine_only: bool = True) -> list[MR]:
    cmd = ["glab", "mr", "list", "--per-page=100", "--output=json"]
    if mine_only:
        cmd.append("--assignee=@me")
    raw = await _run(cmd)
    if not raw.strip():
        return []
    data = json.loads(raw)
    return [
        MR(
            iid=item["iid"],
            title=item["title"],
            branch=item["source_branch"],
            web_url=item["web_url"],
        )
        for item in data
        if item.get("state") == "opened"
    ]


async def fetch_pipeline(mr_iid: int) -> Pipeline | None:
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/pipelines"]
    )
    if not raw.strip():
        return None
    data = json.loads(raw)
    if not data:
        return None
    p = data[0]
    return Pipeline(id=p["id"], status=p["status"], web_url=p.get("web_url", ""))


async def fetch_jobs(pipeline_id: int) -> list[Job]:
    raw = await _run(
        [
            "glab",
            "api",
            f"projects/:fullpath/pipelines/{pipeline_id}/jobs?per_page=100",
        ]
    )
    if not raw.strip():
        return []
    data = json.loads(raw)
    return [
        Job(
            id=j["id"],
            name=j["name"],
            stage=j["stage"],
            status=j["status"],
            duration=j.get("duration"),
            allow_failure=j.get("allow_failure", False),
            web_url=j.get("web_url", ""),
        )
        for j in data
    ]


async def fetch_approvals(mr_iid: int) -> bool | None:
    """Return True if MR is approved per its approval rules, False if not, None on error."""
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/approvals"]
    )
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
        return data.get("approved", False)
    except (json.JSONDecodeError, KeyError):
        return None


async def fetch_unresolved_threads(mr_iid: int) -> int:
    """Return the count of unresolved discussion threads on an MR."""
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/discussions?per_page=100"]
    )
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
        return sum(
            1 for d in data
            if any(n.get("resolvable") and not n.get("resolved") for n in d.get("notes", []))
        )
    except (json.JSONDecodeError, KeyError):
        return 0


async def retry_job(job_id: int) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "glab", "api", "--method", "POST",
        f"projects/:fullpath/jobs/{job_id}/retry",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    raw = stdout.decode()
    err = stderr.decode().strip()
    try:
        data = json.loads(raw)
        if data.get("id") is not None:
            return True, ""
        return False, data.get("message", err or "Unknown error")
    except (json.JSONDecodeError, KeyError):
        return False, err or raw or "Unknown error"


async def open_mr_in_browser(mr_iid: int) -> None:
    await _run(["glab", "mr", "view", "--web", str(mr_iid)])
