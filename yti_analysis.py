"""Analysis fan-out queue + completion validator.

Port of the original runTriggerAnalysis, re-expressed for hermes: instead of
creating paperclip issues assigned to a Researcher agent, trigger-analysis
selects up to ``limit`` transcribed-but-unanalyzed videos (ordered by "vph"
highest-signal-first, or "oldest" FIFO), marks them 'analyzing', enqueues
them, and returns a work item per video whose ``instructions`` text tells the
agent exactly what the original issue description did — run the
youtube-video-analyst skill on the transcript, save analysis.md next to it,
and record 10-15 insights — except insights are recorded with the native
``yt_add_insight`` tool instead of unauthenticated curl calls.

The completion validator preserves the original acceptance gate: analysis.md
exists AND >= MIN_INSIGHTS insights recorded for the video; otherwise retry
up to MAX_RETRIES then mark failed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    from . import yti_paths, yti_store, yti_fetcher
except ImportError:  # pragma: no cover
    import yti_paths  # type: ignore
    import yti_store  # type: ignore
    import yti_fetcher  # type: ignore

DEFAULT_ANALYSIS_LIMIT = 20
ANALYSIS_ORDER_BY = ("vph", "oldest")
DEFAULT_ANALYSIS_ORDER_BY = "vph"
MIN_INSIGHTS = 10
MAX_RETRIES = 2


def _analysis_path(transcript_path: str, workspace: Path) -> Path:
    return (workspace / transcript_path).parent / "analysis.md"


def work_item_instructions(video: dict[str, Any], transcript_abs: Path,
                           analysis_abs: Path) -> str:
    return "\n".join([
        "## MANDATORY: Follow these instructions EXACTLY. Do NOT improvise.",
        "",
        f"**Video:** {video['title']}",
        f"**Channel:** {video.get('author') or video.get('channel_handle', '')}",
        f"**Video ID:** {video['videoId'] if 'videoId' in video else video['video_id']}",
        f"**Transcript:** {transcript_abs}",
        f"**Analysis output:** {analysis_abs}",
        "",
        "## Phase 1: Analyze",
        "Load the `youtube-insights:youtube-video-analyst` skill and run it on "
        "the transcript.",
        f"Save the output to: {analysis_abs}",
        f'Verify it exists: `test -f "{analysis_abs}" && echo VERIFIED`',
        "",
        "## Phase 2: Extract Insights via the yt_add_insight tool",
        "Extract 10-15 insights and call the `yt_add_insight` tool for EACH ONE "
        "with fields:",
        '  text: "10-20 word generalizable principle"',
        '  detail: "2-3 sentences with specific context"',
        "  category: one of strategy|technical|creativity|productivity|business|psychology|trend|career",
        f"  source_video_id: \"{video['videoId'] if 'videoId' in video else video['video_id']}\"",
        '  context: "direct quote from transcript"',
        '  timestamp_ref: "MM:SS"',
        "",
        "## CRITICAL RULES — VIOLATION MEANS TASK FAILURE",
        "- You MUST call the yt_add_insight tool for each insight. It is the "
        "ONLY way to store insights.",
        "- Do NOT write insight files to disk yourself. Do NOT create .jsonl "
        "files or category folders.",
        "- This work item is complete ONLY when analysis.md exists AND "
        "yt_add_insight was called 10+ times.",
        "- The completion validator WILL re-queue this video (max 2 retries) "
        "if these conditions are not met.",
    ])


def trigger_analysis(
    conn,
    *,
    limit: Optional[int] = None,
    order_by: str = DEFAULT_ANALYSIS_ORDER_BY,
    workspace: Optional[Path] = None,
) -> dict[str, Any]:
    limit = int(limit) if isinstance(limit, (int, float)) and limit and limit > 0 \
        else DEFAULT_ANALYSIS_LIMIT
    if order_by not in ANALYSIS_ORDER_BY:
        order_by = DEFAULT_ANALYSIS_ORDER_BY
    workspace = workspace or yti_paths.workspace_dir()

    videos = yti_fetcher.trends_from_db(conn)
    if order_by == "oldest":
        videos.sort(key=lambda v: v.get("published") or "")

    queued: list[dict[str, Any]] = []
    for video in videos:
        if len(queued) >= limit:
            break
        state = yti_store.get_video(conn, video["videoId"])
        if not state or state["status"] != "transcribed":
            continue
        if not state.get("transcript_path"):
            continue
        transcript_abs = workspace / state["transcript_path"]
        analysis_abs = _analysis_path(state["transcript_path"], workspace)

        yti_store.set_video_status(conn, video["videoId"], "analyzing")
        conn.execute(
            """INSERT OR REPLACE INTO analysis_queue
               (video_id, created_at, retries, status)
               VALUES (?, ?, COALESCE((SELECT retries FROM analysis_queue
                                       WHERE video_id = ?), 0), 'pending')""",
            (video["videoId"], yti_store.now_iso(), video["videoId"]),
        )
        conn.commit()
        queued.append({
            "videoId": video["videoId"],
            "title": video["title"],
            "vph": video["vph"],
            "transcript": str(transcript_abs),
            "analysisOutput": str(analysis_abs),
            "instructions": work_item_instructions(video, transcript_abs,
                                                   analysis_abs),
        })

    yti_store.set_meta(conn, "last_analysis_run", yti_store.now_iso())
    return {"triggered": len(queued), "limit": limit, "orderBy": order_by,
            "items": queued}


def validate_analysis(conn, video_id: str,
                      workspace: Optional[Path] = None) -> dict[str, Any]:
    """Acceptance gate: analysis.md exists AND >= MIN_INSIGHTS recorded."""
    try:
        from . import yti_insights
    except ImportError:  # pragma: no cover
        import yti_insights  # type: ignore

    workspace = workspace or yti_paths.workspace_dir()
    state = yti_store.get_video(conn, video_id)
    if not state:
        return {"ok": False, "error": f"unknown video {video_id}"}

    analysis_ok = False
    if state.get("transcript_path"):
        analysis_ok = _analysis_path(state["transcript_path"], workspace).exists()
    insight_count = yti_insights.count_insights_for_video(conn, video_id)
    passed = analysis_ok and insight_count >= MIN_INSIGHTS

    row = conn.execute(
        "SELECT retries FROM analysis_queue WHERE video_id = ?", (video_id,)
    ).fetchone()
    retries = row["retries"] if row else 0

    if passed:
        conn.execute(
            "UPDATE analysis_queue SET status = 'done' WHERE video_id = ?",
            (video_id,),
        )
        yti_store.set_video_status(conn, video_id, "analyzed")
        conn.commit()
        return {"ok": True, "analysis": analysis_ok, "insights": insight_count}

    if retries < MAX_RETRIES:
        conn.execute(
            """UPDATE analysis_queue SET retries = retries + 1,
                   status = 'pending',
                   last_error = ? WHERE video_id = ?""",
            (f"analysis={analysis_ok} insights={insight_count}", video_id),
        )
        yti_store.set_video_status(conn, video_id, "transcribed")
        conn.commit()
        return {"ok": False, "retry": retries + 1, "analysis": analysis_ok,
                "insights": insight_count}

    conn.execute(
        "UPDATE analysis_queue SET status = 'failed', last_error = ? "
        "WHERE video_id = ?",
        (f"exhausted retries: analysis={analysis_ok} insights={insight_count}",
         video_id),
    )
    conn.commit()
    return {"ok": False, "failed": True, "analysis": analysis_ok,
            "insights": insight_count}
