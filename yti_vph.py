"""VPH math, trend classification, and workspace aggregation.

Direct ports of the original plugin's calculateVph / computeTrend /
jaccardSimilarity / findMetadataFiles / collectVideosFromDisk with the same
semantics (thresholds, sort orders, field fallbacks).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def calculate_vph(views: int, published: str,
                  now: Optional[datetime] = None) -> int:
    """views-per-hour since publication (min age 0.1h, rounded)."""
    pub = _parse_dt(published)
    if pub is None:
        return 0
    now = now or datetime.now(timezone.utc)
    hours = (now - pub).total_seconds() / 3600.0
    if hours < 0.1:
        hours = 0.1
    return round(views / hours)


def compute_trend(points: list[float]) -> str:
    """'accelerating' | 'decelerating' | 'flat' via first/second-half means ±10%."""
    if len(points) < 2:
        return "flat"
    mid = len(points) // 2
    first = sum(points[:mid]) / mid
    second = sum(points[mid:]) / (len(points) - mid)
    if second > first * 1.1:
        return "accelerating"
    if second < first * 0.9:
        return "decelerating"
    return "flat"


def jaccard_similarity(a: str, b: str) -> float:
    words_a = {w for w in re.split(r"\s+", (a or "").lower()) if w}
    words_b = {w for w in re.split(r"\s+", (b or "").lower()) if w}
    union = words_a | words_b
    if not union:
        return 0.0
    return len(words_a & words_b) / len(union)


# -- workspace metadata aggregation (youtube/{date}/{channel}/{video}/) ------

_META_STEM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})$")


def find_metadata_files(youtube_dir: Path) -> list[Path]:
    results: list[Path] = []
    if not youtube_dir.is_dir():
        return results
    for d1 in sorted(p for p in youtube_dir.iterdir() if p.is_dir()):
        for d2 in sorted(p for p in d1.iterdir() if p.is_dir()):
            for d3 in sorted(p for p in d2.iterdir() if p.is_dir()):
                meta_dir = d3 / "metadata"
                if not meta_dir.is_dir():
                    continue
                for f in sorted(meta_dir.iterdir()):
                    if f.suffix == ".json":
                        results.append(f)
    return results


def parse_meta_timestamp(filepath: Path) -> Optional[datetime]:
    m = _META_STEM.match(filepath.stem)
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=timezone.utc)


def meta_snapshot_stamp(now: Optional[datetime] = None) -> str:
    """Filename stem for a metadata snapshot: YYYY-MM-DD-HHMM (UTC)."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d-%H%M")


def collect_videos_from_disk(youtube_dir: Path,
                             now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Rebuild the trends table from metadata snapshot files, VPH-desc sorted."""
    video_map: dict[str, dict[str, Any]] = {}
    for filepath in find_metadata_files(youtube_dir):
        try:
            meta = json.loads(filepath.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        vid = str(meta.get("video_id") or meta.get("videoId") or "")
        if not vid:
            continue
        ts = parse_meta_timestamp(filepath)
        if ts is None:
            continue
        entry = video_map.setdefault(vid, {"meta": meta, "snapshots": []})
        entry["snapshots"].append((ts, int(meta.get("viewCount") or meta.get("views") or 0)))

    videos: list[dict[str, Any]] = []
    for vid, data in video_map.items():
        meta = data["meta"]
        published = meta.get("published")
        if not published:
            continue
        snapshots = sorted(data["snapshots"], key=lambda s: s[0])
        latest_views = snapshots[-1][1]
        points = [v for _, v in snapshots]
        videos.append({
            "videoId": vid,
            "title": meta.get("title") or "Unknown",
            "author": meta.get("author_name") or meta.get("author") or "Unknown",
            "published": published,
            "views": latest_views,
            "vph": calculate_vph(latest_views, published, now=now),
            "thumbnail": meta.get("thumbnail_url") or meta.get("thumbnail") or "",
            "link": meta.get("link") or f"https://www.youtube.com/watch?v={vid}",
            "sparklinePoints": points,
            "snapshotCount": len(snapshots),
            "trendDirection": compute_trend(points),
            "duration": meta.get("duration_seconds"),
        })

    videos.sort(key=lambda v: v["vph"], reverse=True)
    return videos
