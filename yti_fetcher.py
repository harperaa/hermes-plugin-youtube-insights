"""transcriptapi.com client + fetch job.

Port of the original runFetchJobPlan: for each tracked channel, pull the
latest videos, skip Shorts (link contains /shorts/ or duration < 120s),
fetch transcripts for videos inside the lookback window, and write the
exact same on-disk artifacts the original produced:

    youtube/{date}/{channel-slug}/{video-slug}/transcript.json
    youtube/{date}/{channel-slug}/{video-slug}/transcript.txt
    youtube/{date}/{channel-slug}/{video-slug}/metadata/{YYYY-MM-DD-HHMM}.json

plus DB rows (videos + vph_snapshots) so the dashboard reads fast.

HTTP is injectable (``http_get``) so tests never hit the network.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from . import yti_paths, yti_store, yti_vph
except ImportError:  # pragma: no cover
    import yti_paths  # type: ignore
    import yti_store  # type: ignore
    import yti_vph  # type: ignore

API_BASE = os.environ.get("YTI_API_BASE", "https://transcriptapi.com/api/v2")
DEFAULT_LOOKBACK_DAYS = 30

HttpGet = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


def _default_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    # transcriptapi.com sits behind Cloudflare, which rejects Python-urllib's
    # default signature with error 1010; a curl-style UA passes.
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:  # non-2xx still has a body
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, {"error": f"non-JSON response: {body[:200]}"}


def channel_latest_url(channel: str) -> str:
    return f"{API_BASE}/youtube/channel/latest?channel={urllib.parse.quote(channel)}"


def transcript_url(video_id: str) -> str:
    return (f"{API_BASE}/youtube/transcript?video_url={urllib.parse.quote(video_id)}"
            f"&format=json&include_timestamp=true&send_metadata=true")


def is_short(link: str, duration_seconds: Optional[float]) -> bool:
    """Shorts filter: /shorts/ link, or a transcript shorter than 120s."""
    if link and "/shorts/" in link:
        return True
    if duration_seconds is not None and duration_seconds < 120:
        return True
    return False


def run_fetch(
    conn,
    api_key: str,
    *,
    youtube_dir: Optional[Path] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    http_get: Optional[HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Optional[datetime] = None,
    log: Callable[[str], None] = lambda m: None,
) -> dict[str, Any]:
    """Fetch latest videos + transcripts for every tracked channel."""
    http_get = http_get or _default_http_get
    ydir = youtube_dir or yti_paths.youtube_dir()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    headers = {"Authorization": f"Bearer {api_key}"}

    channels = yti_store.list_channels(conn)
    summary: dict[str, Any] = {
        "channels": len(channels),
        "videos_seen": 0,
        "transcripts_fetched": 0,
        "skipped_shorts": 0,
        "errors": [],
    }
    if not channels:
        summary["errors"].append("no channels tracked")
        return summary

    for channel in channels:
        try:
            status, channel_data = http_get(channel_latest_url(channel), headers)
            results = channel_data.get("results")
            if channel_data.get("error") or not isinstance(results, list):
                snippet = json.dumps(channel_data)[:200]
                msg = f"channel {channel} failed (HTTP {status}): {channel_data.get('error') or snippet}"
                if status in (401, 403):
                    msg += " — transcript API key rejected; re-check TRANSCRIPT_API_KEY"
                log(msg)
                summary["errors"].append(msg)
                continue

            channel_slug = yti_paths.sanitize(channel.lstrip("@"))

            for video in results:
                vid = str(video.get("videoId") or video.get("video_id") or "")
                title = str(video.get("title") or "untitled")
                published = str(video.get("published") or "")
                link = str(video.get("link") or "")
                if not vid or not published:
                    continue
                if "/shorts/" in link:
                    summary["skipped_shorts"] += 1
                    continue

                pub = yti_vph._parse_dt(published)
                within_lookback = bool(pub and pub >= cutoff)

                slug = yti_paths.sanitize(title)
                date_str = (pub or now).date().isoformat()
                video_dir = ydir / date_str / channel_slug / slug
                metadata_dir = video_dir / "metadata"
                metadata_dir.mkdir(parents=True, exist_ok=True)

                summary["videos_seen"] += 1
                transcript_json = video_dir / "transcript.json"
                has_transcript = transcript_json.exists()
                duration_seconds: Optional[int] = None

                if not has_transcript and within_lookback:
                    try:
                        t_status, t_data = http_get(transcript_url(vid), headers)
                        if not t_data.get("error") and t_status < 400:
                            segments = t_data.get("transcript") or []
                            duration = segments[-1].get("start", 0) if segments else 0
                            if duration < 120:
                                summary["skipped_shorts"] += 1
                                continue
                            transcript_json.write_text(json.dumps(t_data, indent=2))
                            txt = "\n".join(
                                f"[{s.get('start')}s] {s.get('text', '')}" for s in segments
                            )
                            (video_dir / "transcript.txt").write_text(txt)
                            duration_seconds = round(duration)
                            yti_store.upsert_video(conn, {
                                "video_id": vid,
                                "title": title,
                                "channel_handle": channel,
                                "channel_slug": channel_slug,
                                "published": published,
                                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                                "link": f"https://www.youtube.com/watch?v={vid}",
                                "view_count": int(video.get("viewCount") or 0),
                                "duration_seconds": duration_seconds,
                                "transcript_path": str(
                                    transcript_json.relative_to(ydir.parent)
                                ),
                                "status": "transcribed",
                            })
                            summary["transcripts_fetched"] += 1
                    except Exception as exc:  # noqa: BLE001
                        log(f"transcript error for {vid}: {exc}")
                        summary["errors"].append(f"transcript {vid}: {exc}")

                # metadata snapshot (always — feeds VPH tracking). Duration is
                # recomputed from transcript.json (last start + duration) like
                # the original, which differs from the video-state value (last
                # start only).
                if transcript_json.exists():
                    try:
                        t_data = json.loads(transcript_json.read_text())
                        segs = t_data.get("transcript") or []
                        if segs:
                            last = segs[-1]
                            duration_seconds = round(
                                (last.get("start") or 0) + (last.get("duration") or 0)
                            )
                    except (OSError, json.JSONDecodeError):
                        duration_seconds = None

                metadata: dict[str, Any] = {
                    "video_id": vid,
                    "title": title,
                    "author_name": channel,
                    "published": published,
                    "viewCount": video.get("viewCount") or 0,
                    "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                    "link": f"https://www.youtube.com/watch?v={vid}",
                }
                if duration_seconds is not None:
                    metadata["duration_seconds"] = duration_seconds
                stamp = yti_vph.meta_snapshot_stamp(now)
                (metadata_dir / f"{stamp}.json").write_text(json.dumps(metadata, indent=2))

                # DB mirror: video row (discovered at minimum) + snapshot
                if not yti_store.get_video(conn, vid):
                    yti_store.upsert_video(conn, {
                        "video_id": vid,
                        "title": title,
                        "channel_handle": channel,
                        "channel_slug": channel_slug,
                        "published": published,
                        "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                        "link": f"https://www.youtube.com/watch?v={vid}",
                        "view_count": int(video.get("viewCount") or 0),
                        "duration_seconds": duration_seconds,
                        "status": "discovered",
                    })
                else:
                    yti_store.upsert_video(conn, {
                        "video_id": vid,
                        "view_count": int(video.get("viewCount") or 0),
                    })
                yti_store.add_snapshot(
                    conn, vid, int(video.get("viewCount") or 0), ts=now.isoformat()
                )

            sleep(0.5)  # rate limit between channels
        except Exception as exc:  # noqa: BLE001
            log(f"channel {channel} failed: {exc}")
            summary["errors"].append(f"channel {channel}: {exc}")

    yti_store.set_meta(conn, "last_fetch_run", yti_store.now_iso())
    return summary


def trends_from_db(conn, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Trends table from the DB (VPH-desc), same shape as collect_videos_from_disk."""
    now = now or datetime.now(timezone.utc)
    rows = conn.execute("SELECT * FROM videos").fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        snaps = yti_store.snapshots_for(conn, r["video_id"])
        points = [v for _, v in snaps] or [r["view_count"]]
        latest_views = points[-1]
        out.append({
            "videoId": r["video_id"],
            "title": r["title"],
            "author": r["channel_handle"] or r["channel_slug"] or "Unknown",
            "published": r["published"],
            "views": latest_views,
            "vph": yti_vph.calculate_vph(latest_views, r["published"], now=now),
            "thumbnail": r["thumbnail"],
            "link": r["link"],
            "sparklinePoints": points,
            "snapshotCount": len(snaps),
            "trendDirection": yti_vph.compute_trend([float(p) for p in points]),
            "duration": r["duration_seconds"],
            "status": r["status"],
        })
    out.sort(key=lambda v: v["vph"], reverse=True)
    return out


def reindex_from_disk(conn, youtube_dir: Optional[Path] = None) -> int:
    """Rebuild DB videos/snapshots from workspace metadata files (migration aid)."""
    ydir = youtube_dir or yti_paths.youtube_dir()
    count = 0
    for meta_file in yti_vph.find_metadata_files(ydir):
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        vid = str(meta.get("video_id") or meta.get("videoId") or "")
        ts = yti_vph.parse_meta_timestamp(meta_file)
        if not vid or ts is None:
            continue
        yti_store.upsert_video(conn, {
            "video_id": vid,
            "title": meta.get("title") or "Unknown",
            "channel_handle": meta.get("author_name") or "",
            "published": meta.get("published") or "",
            "thumbnail": meta.get("thumbnail_url") or "",
            "link": meta.get("link") or f"https://www.youtube.com/watch?v={vid}",
            "view_count": int(meta.get("viewCount") or 0),
            "duration_seconds": meta.get("duration_seconds"),
        })
        yti_store.add_snapshot(conn, vid, int(meta.get("viewCount") or 0),
                               ts=ts.isoformat())
        count += 1
    return count
