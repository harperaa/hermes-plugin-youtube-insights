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
    "10-15 insights per video with the yt_add_insight tool. Finish with a "
    "one-paragraph summary of videos fetched, analyzed, and insights added."
)


def _hermes_argv() -> list[str]:
    exe = shutil.which("hermes")
    if exe:
        return [exe]
    return [sys.executable, "-m", "hermes_cli.main"]


def setup(subparser) -> None:
    sub = subparser.add_subparsers(dest="yti_cmd")
    p_cron = sub.add_parser("setup-cron",
                            help="Install the daily 03:00 intelligence-refresh cron job")
    p_cron.add_argument("--apply", action="store_true",
                        help="Create the job now (default: print the command)")
    p_cron.add_argument("--schedule", default=CRON_SCHEDULE,
                        help=f"Cron schedule (default: '{CRON_SCHEDULE}')")
    sub.add_parser("status", help="Show channels, video counts, and insight stats")
    sub.add_parser("reindex", help="Rebuild the video DB from workspace metadata files")


def handle(args) -> int:
    cmd = getattr(args, "yti_cmd", None)
    if cmd == "setup-cron":
        argv = _hermes_argv() + [
            "cron", "create", args.schedule, CRON_PROMPT, "--name", CRON_NAME,
        ]
        if args.apply:
            proc = subprocess.run(argv)
            return proc.returncode
        shown = " ".join(
            f'"{a}"' if " " in a else a for a in argv
        )
        print("Run this to install the daily intelligence-refresh job "
              "(or re-run with --apply):\n")
        print(f"  {shown}\n")
        return 0

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
