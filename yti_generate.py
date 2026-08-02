"""Single-video content generation — the Trends page ✨ button.

Port of the paperclip harper-cmo "Generate similar video script" flow onto
the hermes chat-only worker architecture: one kanban task per click (born
assigned, priority, instant dispatch — same lifecycle as Value Creator
steps), the worker runs gap-finder Mode A + content-creator itself, the
scripts land in the plugin workspace (surfaced on the Artifacts tab) AND as
kanban attachments, and the row's ✨ / spinner / ↗ states derive from the
task exactly like paperclip's issue states (open → spinner, 30-minute
staleness window, done → re-generate + review link).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from . import yti_fetcher, yti_paths, yti_store
    from .yti_analysis import (
        _kanban,
        _kanban_task_open,
        kick_dispatcher,
        resolve_kanban_assignee,
    )
except ImportError:  # standalone import (dashboard plugin_api path)
    import yti_fetcher  # type: ignore
    import yti_paths  # type: ignore
    import yti_store  # type: ignore
    from yti_analysis import (  # type: ignore
        _kanban,
        _kanban_task_open,
        kick_dispatcher,
        resolve_kanban_assignee,
    )

GENERATION_META_KEY = "generation_tasks"
STALE_MINUTES = 30
GENERATION_SKILLS = (
    "youtube-insights:youtube-gap-finder",
    "youtube-insights:youtube-content-creator",
    "youtube-insights:youtube-video-analyst",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:60] or "video"


def generation_task_title(video_title: str) -> str:
    return f"Video Script: {video_title}"


def _load_map(conn) -> dict[str, Any]:
    raw = yti_store.get_meta(conn, GENERATION_META_KEY)
    try:
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _save_map(conn, mapping: dict[str, Any]) -> None:
    yti_store.set_meta(conn, GENERATION_META_KEY, json.dumps(mapping))


def _build_brief(video: dict[str, Any], workspace: Path) -> str:
    video_id = video["video_id"]
    title = video.get("title") or video_id
    url = video.get("link") or f"https://www.youtube.com/watch?v={video_id}"
    transcript_rel = video.get("transcript_path") or ""
    transcript_abs = (workspace / transcript_rel) if transcript_rel else None
    transcript_exists = bool(transcript_abs and transcript_abs.exists())
    analysis_abs = transcript_abs.parent / "analysis.md" if transcript_abs else None
    analysis_exists = bool(analysis_abs and analysis_abs.exists())

    today = _now().strftime("%Y-%m-%d")
    out_dir = workspace / "youtube" / today / "recommended" / _slug(title)

    if analysis_exists:
        step0 = [
            "### Step 0 — Prerequisites (already satisfied — skip)",
            f"`analysis.md` is already present at {analysis_abs}. Proceed to Step 1.",
        ]
    elif transcript_exists:
        step0 = [
            "### Step 0 — Prerequisite: generate analysis.md (run this FIRST, yourself)",
            f"`analysis.md` is not yet present. The transcript IS present at",
            f"{transcript_abs}. Run the `youtube-insights:youtube-video-analyst`",
            f"skill on it and save the output to exactly {analysis_abs}. Verify",
            f'with `test -f "{analysis_abs}" && echo VERIFIED`, then continue.',
            "Do NOT stop after Step 0 because analysis.md now exists — that is",
            "the expected state; Steps 1-3 are the actual deliverable.",
        ]
    else:
        step0 = [
            "### Step 0 — Blocked: transcript missing",
            "Neither `analysis.md` nor a transcript exists for this video yet",
            "(the intelligence-refresh job has not fetched it). Post a kanban",
            "comment explaining the block, then block this task with kind",
            "`needs_input` and reason 'transcript missing: waiting on the next",
            "intelligence refresh'. Do NOT invent content without the source.",
        ]

    return "\n".join([
        "## MANDATORY: Generate similar-but-unique content based on this ONE video.",
        "",
        f"**Source video:** {title}",
        f"**Channel:** {video.get('channel_name') or ''}"
        f"{' (' + video['channel_handle'] + ')' if video.get('channel_handle') else ''}",
        f"**Video ID:** {video_id}",
        f"**Video URL:** {url}",
        f"**Video workspace directory:** {transcript_abs.parent if transcript_abs else '_not yet available_'}",
        f"**Transcript:** {transcript_abs or '_not yet available_'}{' ✓' if transcript_exists else ' (missing)'}",
        f"**Analysis:** {analysis_abs or '_n/a_'}{' ✓' if analysis_exists else ' (missing — Step 0)'}",
        f"**Output directory:** {out_dir}",
        "",
        "You do ALL steps yourself in this session — no subtasks, no delegation.",
        "Work autonomously; only block (needs_input) if Step 0 says so.",
        "",
        *step0,
        "",
        "### Step 1 — Concepts (gap-finder Mode A)",
        "Run the `youtube-insights:youtube-gap-finder` skill in **Mode A",
        "(Single-Source Video)** — its dedicated branch. Do NOT run the",
        "workspace sweep. Pass explicitly:",
        f"  - Source video URL: {url}",
        f"  - Source video ID: {video_id}",
        f"  - Source analysis.md: {analysis_abs or '(from Step 0)'}",
        f"  - Output directory: {out_dir}/",
        "Also call `yt_search_insights` for the video's main themes so concepts",
        "cite the knowledge base. Mode A output is EXACTLY 3 files:",
        f"  - {out_dir}/concepts.md",
        f"  - {out_dir}/concepts-hot-take.md",
        f"  - {out_dir}/concepts-contrarian.md",
        "",
        "### Step 2 — Scripts (content-creator on ALL 3 concepts)",
        "Run the `youtube-insights:youtube-content-creator` skill on each",
        "concept file to produce matching script-outline files in the same",
        "folder (script-outline.md, script-outline-hot-take.md,",
        "script-outline-contrarian.md — all formats the skill prescribes,",
        "exact spoken lines, a Visual field per beat). The scripts must be",
        "SIMILAR in topic/angle to the source video but UNIQUE — net-new",
        "information gain; use the source analysis.md to see what it already",
        "covers and deliberately go beyond it. Do NOT generate images — the",
        "graphics stage runs only after a human approves the scripts.",
        "",
        "### Step 3 — Publish the artifacts",
        f"Write {out_dir}/SUMMARY.md (source video, the 3 concepts' titles and",
        "angles, evidence/insights cited, file paths). Then attach SUMMARY.md",
        "and all 3 script-outline files to THIS kanban task with the",
        "`kanban_attach` tool so reviewers see them on the task, and finish",
        "with `kanban_complete` whose summary lists every file path. The",
        "files under the workspace youtube/ tree appear on the YouTube",
        "Insights Artifacts tab — that is the review surface; leave them in",
        "place.",
        "",
        "### CRITICAL RULES",
        f"- Every output file goes under exactly {out_dir}/ — no alternate paths.",
        "- Do NOT run a gap-finder workspace sweep over the top-10 — Mode A,",
        "  this one source video only.",
    ])


def create_generation_task(video_id: str) -> dict[str, Any]:
    """Create (or reuse a still-open) generation task for one video."""
    kb = _kanban()
    if kb is None:
        return {"error": "kanban unavailable"}
    conn = yti_store.connect()
    try:
        video = yti_store.get_video(conn, video_id)
        if not video:
            # Fetched-but-unindexed video (e.g. DB rebuilt): reindex from the
            # workspace metadata files before giving up.
            try:
                yti_fetcher.reindex_from_disk(conn)
                video = yti_store.get_video(conn, video_id)
            except Exception:
                video = None
        if not video:
            return {"error": f"unknown videoId: {video_id}"}
        mapping = _load_map(conn)
        entry = mapping.get(video_id) or {}
        existing = entry.get("taskId")
        with kb.connect_closing() as conn_kb:
            if existing and _kanban_task_open(kb, conn_kb, existing):
                task = kb.get_task(conn_kb, existing)
                age_min = _age_minutes(entry.get("createdAt"))
                if task is not None and age_min is not None and age_min < STALE_MINUTES:
                    return {"ok": True, "taskId": existing, "already": True}
            task_id = kb.create_task(
                conn_kb,
                title=generation_task_title(video.get("title") or video_id),
                body=_build_brief(video, yti_paths.workspace_dir()),
                assignee=resolve_kanban_assignee(),
                created_by="youtube-insights",
                workspace_kind="scratch",
                skills=list(GENERATION_SKILLS),
                priority=10,  # user-initiated: jump the queue
            )
        mapping[video_id] = {"taskId": task_id, "createdAt": _now_iso()}
        _save_map(conn, mapping)
    except Exception as exc:
        return {"error": f"could not create the generation task: {exc}"}
    finally:
        conn.close()
    kick_dispatcher()
    return {"ok": True, "taskId": task_id}


def _age_minutes(created_at: Optional[str]) -> Optional[float]:
    if not created_at:
        return None
    try:
        t = datetime.fromisoformat(created_at)
        return (_now() - t).total_seconds() / 60.0
    except ValueError:
        return None


def _find_worker_session(kanban_task_id: str) -> Optional[str]:
    """Exact-match lookup of the dispatcher-spawned worker session (the same
    rule the Value Creator page uses — LIKE matches bleed across tasks)."""
    try:
        import os
        import sqlite3
        try:
            from hermes_constants import get_hermes_home
            db = str(get_hermes_home() / "state.db")
        except ImportError:
            db = os.path.expanduser(
                os.path.join(os.environ.get("HERMES_HOME", "~/.hermes"), "state.db"))
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT session_id FROM messages WHERE role = 'user' "
                "AND content = ? ORDER BY id DESC LIMIT 1",
                (f"work kanban task {kanban_task_id}",),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except Exception:
        return None


def generation_states() -> dict[str, dict[str, Any]]:
    """Per-video ✨ state for the Trends page: open | stale | done (+ links)."""
    kb = _kanban()
    if kb is None:
        return {}
    conn = yti_store.connect()
    try:
        mapping = _load_map(conn)
    finally:
        conn.close()
    if not mapping:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        with kb.connect_closing() as conn_kb:
            for video_id, entry in mapping.items():
                task_id = entry.get("taskId")
                if not task_id:
                    continue
                task = kb.get_task(conn_kb, task_id)
                if task is None or getattr(task, "status", "") == "archived":
                    continue
                status = getattr(task, "status", "")
                age = _age_minutes(entry.get("createdAt"))
                if status == "done":
                    ui = "done"
                elif age is not None and age >= STALE_MINUTES:
                    ui = "stale"
                else:
                    ui = "open"
                out[video_id] = {
                    "taskId": task_id,
                    "status": ui,
                    "kanbanStatus": status,
                    "sessionId": _find_worker_session(task_id),
                }
    except Exception:
        return out
    return out


# ---------------------------------------------------------------------------
# Produce: graphics + PDF for ONE approved script (Artifacts tab button).
# Paperclip's Phase 6/6b flow — images per beat + thumbnails + production
# PDF — run by a single hermes worker on an existing script-outline file.
# ---------------------------------------------------------------------------

PRODUCE_META_KEY = "produce_tasks"
PRODUCE_SKILLS = (
    "youtube-insights:youtube-content-creator",
    "youtube-insights:generate-image",
)


def _build_produce_brief(script_abs: Path) -> str:
    script_dir = script_abs.parent
    assets_dir = script_dir / "assets"
    pdf_path = script_dir / (script_abs.stem + ".pdf")
    return "\n".join([
        "## MANDATORY: Produce graphics + production PDF for ONE approved script.",
        "",
        f"**Script:** {script_abs}",
        f"**Assets directory:** {assets_dir}/",
        f"**PDF output:** {pdf_path}",
        "",
        "You run EVERY phase yourself in this session. The",
        "youtube-content-creator skill's Mode B text says to delegate Phase 6",
        "and 6b to a Graphics Creator agent — that applies to a multi-agent",
        "deployment and is OVERRIDDEN here: there is no other agent, YOU run",
        "Phase 6 and Phase 6b directly.",
        "",
        "1. Load `youtube-insights:youtube-content-creator` and run **Mode B**",
        "   (images-and-pdf) against the script above.",
        "2. **Phase 6 — images:** one image per beat (from each beat's Visual",
        "   field) plus 3 thumbnail options, ALL via the",
        "   `youtube-insights:generate-image` skill (grok imagine + its",
        "   mandatory verify_image QA and baseline-reference check). Beat",
        "   images MUST pass the baseline as the source image:",
        "   `--input \"<generate-image skill dir>/youtube-baseline-reference.png\"`",
        "   (image-to-image via xAI images/edits) — thumbnails do NOT take the",
        "   baseline input. Its Absolute Rules apply: never substitute",
        "   PIL/canvas/ImageMagick or any hand-rolled generator. Save",
        f"   everything under {assets_dir}/ using the skill's naming",
        "   convention.",
        f"3. **Phase 6b — PDF:** produce the production PDF at {pdf_path}",
        "   (landscape, one image per page — thumbnails first, then each beat",
        "   image in order).",
        "4. **Publish:** attach the PDF and the 3 thumbnails to THIS kanban",
        "   task with `kanban_attach`; leave every file in place (they appear",
        "   on the YouTube Insights Artifacts tab). Then `kanban_complete`",
        "   with a summary listing every file produced.",
    ])


def create_produce_task(rel_path: str) -> dict[str, Any]:
    """Create (or reuse a still-open) produce task for one script file."""
    kb = _kanban()
    if kb is None:
        return {"error": "kanban unavailable"}
    try:
        from . import yti_workspace
    except ImportError:  # standalone import
        import yti_workspace  # type: ignore
    workspace = yti_paths.workspace_dir()
    script_abs = yti_workspace.resolve_inside_workspace(workspace, rel_path or "")
    if script_abs is None or not script_abs.exists():
        return {"error": f"script not found in workspace: {rel_path}"}
    if script_abs.suffix.lower() != ".md":
        return {"error": "produce runs on markdown script files"}
    conn = yti_store.connect()
    try:
        mapping_raw = yti_store.get_meta(conn, PRODUCE_META_KEY)
        try:
            mapping = json.loads(mapping_raw) if mapping_raw else {}
            if not isinstance(mapping, dict):
                mapping = {}
        except ValueError:
            mapping = {}
        entry = mapping.get(rel_path) or {}
        existing = entry.get("taskId")
        with kb.connect_closing() as conn_kb:
            if existing and _kanban_task_open(kb, conn_kb, existing):
                age = _age_minutes(entry.get("createdAt"))
                if age is not None and age < STALE_MINUTES:
                    return {"ok": True, "taskId": existing, "already": True}
            task_id = kb.create_task(
                conn_kb,
                title=f"Produce: {script_abs.stem}",
                body=_build_produce_brief(script_abs),
                assignee=resolve_kanban_assignee(),
                created_by="youtube-insights",
                workspace_kind="scratch",
                skills=list(PRODUCE_SKILLS),
                priority=10,
            )
        mapping[rel_path] = {"taskId": task_id, "createdAt": _now_iso()}
        yti_store.set_meta(conn, PRODUCE_META_KEY, json.dumps(mapping))
    except Exception as exc:
        return {"error": f"could not create the produce task: {exc}"}
    finally:
        conn.close()
    kick_dispatcher()
    return {"ok": True, "taskId": task_id}


def produce_states() -> dict[str, dict[str, Any]]:
    """Per-script produce state for the Artifacts tab (open|stale|done)."""
    kb = _kanban()
    if kb is None:
        return {}
    conn = yti_store.connect()
    try:
        raw = yti_store.get_meta(conn, PRODUCE_META_KEY)
    finally:
        conn.close()
    try:
        mapping = json.loads(raw) if raw else {}
        if not isinstance(mapping, dict):
            return {}
    except ValueError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        with kb.connect_closing() as conn_kb:
            for rel_path, entry in mapping.items():
                task_id = entry.get("taskId")
                if not task_id:
                    continue
                task = kb.get_task(conn_kb, task_id)
                if task is None or getattr(task, "status", "") == "archived":
                    continue
                status = getattr(task, "status", "")
                age = _age_minutes(entry.get("createdAt"))
                ui = ("done" if status == "done"
                      else "stale" if (age is not None and age >= STALE_MINUTES)
                      else "open")
                out[rel_path] = {
                    "taskId": task_id,
                    "status": ui,
                    "kanbanStatus": status,
                    "sessionId": _find_worker_session(task_id),
                }
    except Exception:
        return out
    return out
