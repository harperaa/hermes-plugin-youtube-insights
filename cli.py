"""`hermes youtube-insights ...` CLI subcommands."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

CRON_NAME = "youtube-intelligence-refresh"
CRON_SCHEDULE = "0 3 * * *"
CRON_PROMPT = (
    "Run the YouTube intelligence refresh. Step 1: call the yt_fetch_videos "
    "tool to pull the latest videos and transcripts for all tracked channels. "
    "Step 2: call yt_trigger_analysis (default limit and ordering). Step 3: "
    "for EACH work item in the result, follow its 'instructions' field "
    "exactly — load the youtube-insights:youtube-video-analyst skill, read "
    "the transcript file, write the analysis.md output file, and record "
    "10-15 insights per video with the yt_add_insight tool. Do NOT raise the "
    "analysis limit to catch up a backlog — the cap is deliberate pacing; the "
    "long tail defers to the next daily window. Do NOT write insight files to "
    "disk yourself; insights are stored ONLY via the yt_add_insight tool. "
    "Finish with a one-paragraph summary of videos fetched, analyzed, and "
    "insights added."
)

# Second routine, ported from paperclip's "YouTube Content Pipeline"
# (0 6,18 * * *). Scope-reduced: gap analysis + concepts + human-review
# summary. Script writing and graphics moved to digital-marketing-pro.
PIPELINE_NAME = "youtube-content-pipeline"
PIPELINE_SCHEDULE = "0 6,18 * * *"
PIPELINE_PROMPT = (
    "Content pipeline: turn YouTube competitive intelligence into content "
    "concepts for human review. Prerequisite: the youtube-intelligence-"
    "refresh job should have run so transcripts and insights exist. "
    "Step 1 — Research: call the yt_search_insights tool with several broad "
    "queries (hooks, structure, topics, audience, offers) to map the insight "
    "landscape; note saturated vs underserved topics. Also call yt_trending "
    "to get the current top videos by VPH. "
    "Step 2 — Gap analysis: load the youtube-insights:youtube-gap-finder "
    "skill and run it against the top 10 VPH videos and the insight map. "
    "Produce about 3 content concepts with net-new information gain. Save "
    "each concept as a markdown file at youtube/{today}/recommended/"
    "{topic-slug}/concept.md inside the youtube-insights plugin workspace "
    "directory (the same workspace root where yt_fetch_videos writes the "
    "youtube/{date} folders; ask yt_trending for workspaceRoot if unsure). "
    "Step 3 — Review handoff: write a summary of all concepts (title, angle, "
    "evidence, why it wins) to youtube/{today}/recommended/SUMMARY.md and "
    "finish by printing that summary for human review. Do NOT write scripts "
    "or generate images — script and asset production is handled separately "
    "(digital-marketing-pro) after a human approves the concepts."
)


def _hermes_argv() -> list[str]:
    exe = shutil.which("hermes")
    if exe:
        return [exe]
    return [sys.executable, "-m", "hermes_cli.main"]


def setup(subparser) -> None:
    sub = subparser.add_subparsers(dest="yti_cmd")
    p_cron = sub.add_parser("setup-cron",
                            help="Install the scheduled jobs: intelligence refresh "
                                 "(daily 03:00) and content pipeline (06:00/18:00)")
    p_cron.add_argument("--apply", action="store_true",
                        help="Create the job now (default: print the command)")
    p_cron.add_argument("--schedule", default=CRON_SCHEDULE,
                        help=f"Cron schedule (default: '{CRON_SCHEDULE}')")
    sub.add_parser("status", help="Show channels, video counts, and insight stats")
    sub.add_parser("reindex", help="Rebuild the video DB from workspace metadata files")


def handle(args) -> int:
    cmd = getattr(args, "yti_cmd", None)
    if cmd == "setup-cron":
        jobs = [
            (args.schedule, CRON_PROMPT, CRON_NAME),
            (PIPELINE_SCHEDULE, PIPELINE_PROMPT, PIPELINE_NAME),
        ]
        rc = 0
        for schedule, prompt, name in jobs:
            argv = _hermes_argv() + [
                "cron", "create", schedule, prompt, "--name", name,
            ]
            if args.apply:
                proc = subprocess.run(argv)
                rc = rc or proc.returncode
            else:
                shown = " ".join(f'"{a}"' if " " in a else a for a in argv)
                print(f"# {name} ({schedule})\n  {shown}\n")
        if not args.apply:
            print("Re-run with --apply to create both jobs now.")
        return rc

    try:
        from . import yti_store, yti_insights, yti_fetcher
    except ImportError:  # pragma: no cover
        import yti_store, yti_insights, yti_fetcher  # type: ignore

    if cmd == "reindex":
        conn = yti_store.connect()
        n = yti_fetcher.reindex_from_disk(conn)
        conn.close()
        print(f"Reindexed {n} metadata snapshots from workspace.")
        return 0

    # default / "status"
    conn = yti_store.connect()
    channels = yti_store.list_channels(conn)
    videos = conn.execute("SELECT COUNT(*) c FROM videos").fetchone()["c"]
    transcribed = conn.execute(
        "SELECT COUNT(*) c FROM videos WHERE status IN ('transcribed','analyzing','analyzed')"
    ).fetchone()["c"]
    stats = yti_insights.insight_stats(conn)
    conn.close()
    print(json.dumps({
        "channels": channels,
        "videos": videos,
        "withTranscripts": transcribed,
        "insights": stats["totalInsights"],
        "insightSources": stats["totalSources"],
        "categories": stats["categories"],
    }, indent=2))
    return 0
