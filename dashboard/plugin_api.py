"""youtube-insights dashboard backend.

Mounted at /api/plugins/youtube-insights/ by the hermes dashboard. Thin
wrappers over the plugin's yti_* modules — the same code paths the agent
tools use, so the dashboard and tools can't drift.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# The dashboard imports this file standalone (spec_from_file_location), so the
# plugin package isn't importable by name — put the plugin root on sys.path
# and use the yti_-prefixed module names directly.
_PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

import yti_store  # noqa: E402
import yti_fetcher  # noqa: E402
import yti_insights  # noqa: E402
import yti_analysis  # noqa: E402
import yti_paths  # noqa: E402
import yti_workspace  # noqa: E402

router = APIRouter()

_FETCH_LOCK = threading.Lock()
_FETCH_STATE: dict[str, Any] = {"running": False, "last": None}


def _transcript_api_key() -> str:
    key = (os.environ.get("TRANSCRIPT_API_KEY") or "").strip()
    if key:
        return key
    env_file = yti_paths.get_hermes_home() / ".env"
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("TRANSCRIPT_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


@router.get("/videos")
def get_videos() -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        videos = yti_fetcher.trends_from_db(conn)
        if not videos:
            videos = []
        last_fetch = yti_store.get_meta(conn, "last_fetch_run")
        return {"videos": videos, "lastFetchRun": last_fetch,
                "fetchRunning": _FETCH_STATE["running"],
                "hasApiKey": bool(_transcript_api_key())}
    finally:
        conn.close()


@router.get("/channels")
def get_channels() -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        return {"channels": yti_store.list_channels(conn),
                "lookbackDays": yti_fetcher.DEFAULT_LOOKBACK_DAYS}
    finally:
        conn.close()


class ChannelBody(BaseModel):
    handle: str


@router.post("/channels")
def post_channel(body: ChannelBody) -> dict[str, Any]:
    if not body.handle.strip():
        raise HTTPException(400, "handle required")
    conn = yti_store.connect()
    try:
        return {"ok": True, "channels": yti_store.add_channel(conn, body.handle)}
    finally:
        conn.close()


@router.delete("/channels/{handle}")
def delete_channel(handle: str) -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        return {"ok": True, "channels": yti_store.remove_channel(conn, handle)}
    finally:
        conn.close()


@router.post("/fetch")
def post_fetch() -> dict[str, Any]:
    api_key = _transcript_api_key()
    if not api_key:
        return {"error": "TRANSCRIPT_API_KEY is not set — add it in "
                         "Settings → Environment or ~/.hermes/.env"}
    with _FETCH_LOCK:
        if _FETCH_STATE["running"]:
            return {"ok": True, "queued": True, "alreadyRunning": True}
        _FETCH_STATE["running"] = True

    def _run() -> None:
        conn = yti_store.connect()
        try:
            summary = yti_fetcher.run_fetch(conn, api_key)
            _FETCH_STATE["last"] = summary
        except Exception as exc:  # noqa: BLE001
            _FETCH_STATE["last"] = {"errors": [str(exc)]}
        finally:
            _FETCH_STATE["running"] = False
            conn.close()

    threading.Thread(target=_run, name="yti-fetch", daemon=True).start()
    return {"ok": True, "queued": True}


@router.post("/trigger-analysis")
def post_trigger_analysis(body: Optional[dict] = None) -> dict[str, Any]:
    body = body or {}
    conn = yti_store.connect()
    try:
        return yti_analysis.trigger_analysis(
            conn, limit=body.get("limit"),
            order_by=str(body.get("orderBy") or "vph"),
        )
    finally:
        conn.close()


@router.get("/insights")
def get_insights(q: str = "", category: str = "", sortBy: str = "sources",
                 limit: int = 30, offset: int = 0) -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        return yti_insights.search_insights(
            conn, query=q, category=category, sort_by=sortBy,
            limit=max(1, min(limit, 100)), offset=max(0, offset),
        )
    finally:
        conn.close()


@router.get("/insights/stats")
def get_insight_stats() -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        return yti_insights.insight_stats(conn)
    finally:
        conn.close()


@router.delete("/insights/{insight_id}")
def delete_insight(insight_id: str) -> dict[str, Any]:
    conn = yti_store.connect()
    try:
        return yti_insights.delete_insight(conn, insight_id)
    finally:
        conn.close()


# -- workspace deliverables (Artifacts tab) ----------------------------------

class WorkspaceWrite(BaseModel):
    path: str
    content: str


@router.get("/workspace/tree")
def get_workspace_tree() -> dict[str, Any]:
    return {"tree": yti_workspace.build_tree(),
            "workspaceRoot": str(yti_paths.workspace_dir())}


@router.get("/workspace/file")
def get_workspace_file(path: str) -> dict[str, Any]:
    result = yti_workspace.read_file(path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.put("/workspace/file")
def put_workspace_file(body: WorkspaceWrite) -> dict[str, Any]:
    result = yti_workspace.write_file(body.path, body.content)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
