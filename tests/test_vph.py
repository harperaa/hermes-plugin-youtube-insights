from datetime import datetime, timedelta, timezone
import json

import yti_vph


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_calculate_vph_basic():
    published = (NOW - timedelta(hours=10)).isoformat()
    assert yti_vph.calculate_vph(1000, published, now=NOW) == 100


def test_calculate_vph_minimum_age_clamped():
    published = NOW.isoformat()  # zero hours old -> clamps to 0.1h
    assert yti_vph.calculate_vph(50, published, now=NOW) == 500


def test_calculate_vph_bad_date():
    assert yti_vph.calculate_vph(1000, "not-a-date", now=NOW) == 0
    assert yti_vph.calculate_vph(1000, "", now=NOW) == 0


def test_calculate_vph_z_suffix():
    published = "2026-08-01T02:00:00Z"
    assert yti_vph.calculate_vph(100, published, now=NOW) == 10


def test_compute_trend_accelerating():
    assert yti_vph.compute_trend([100, 100, 200, 300]) == "accelerating"


def test_compute_trend_decelerating():
    assert yti_vph.compute_trend([300, 300, 100, 100]) == "decelerating"


def test_compute_trend_flat():
    assert yti_vph.compute_trend([100, 101, 99, 100]) == "flat"


def test_compute_trend_short_series():
    assert yti_vph.compute_trend([]) == "flat"
    assert yti_vph.compute_trend([5]) == "flat"


def test_compute_trend_boundary_ten_percent():
    # Exactly +10% is NOT accelerating (strict >)
    assert yti_vph.compute_trend([100, 110]) == "flat"
    assert yti_vph.compute_trend([100, 111]) == "accelerating"


def test_jaccard_identical():
    assert yti_vph.jaccard_similarity("focus on retention", "focus on retention") == 1.0


def test_jaccard_disjoint():
    assert yti_vph.jaccard_similarity("alpha beta", "gamma delta") == 0.0


def test_jaccard_partial():
    sim = yti_vph.jaccard_similarity("a b c d", "a b x y")
    assert abs(sim - 2 / 6) < 1e-9


def test_jaccard_empty():
    assert yti_vph.jaccard_similarity("", "") == 0.0


def _write_meta(youtube_dir, date, channel, slug, stamp, meta):
    d = youtube_dir / date / channel / slug / "metadata"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stamp}.json").write_text(json.dumps(meta))


def test_collect_videos_from_disk(tmp_path):
    ydir = tmp_path / "youtube"
    meta1 = {"video_id": "abc", "title": "Video A", "author_name": "@chan",
             "published": (NOW - timedelta(hours=100)).isoformat(),
             "viewCount": 1000, "link": "https://www.youtube.com/watch?v=abc"}
    meta2 = dict(meta1, viewCount=3000)
    _write_meta(ydir, "2026-07-30", "chan", "video-a", "2026-07-30-0300", meta1)
    _write_meta(ydir, "2026-07-30", "chan", "video-a", "2026-07-31-0300", meta2)

    videos = yti_vph.collect_videos_from_disk(ydir, now=NOW)
    assert len(videos) == 1
    v = videos[0]
    assert v["videoId"] == "abc"
    assert v["views"] == 3000  # latest snapshot wins
    assert v["sparklinePoints"] == [1000, 3000]
    assert v["snapshotCount"] == 2
    assert v["trendDirection"] == "accelerating"
    assert v["vph"] == 30


def test_collect_videos_sorted_by_vph(tmp_path):
    ydir = tmp_path / "youtube"
    pub = (NOW - timedelta(hours=10)).isoformat()
    _write_meta(ydir, "2026-08-01", "c1", "slow", "2026-08-01-0100",
                {"video_id": "slow", "title": "s", "published": pub, "viewCount": 10})
    _write_meta(ydir, "2026-08-01", "c1", "fast", "2026-08-01-0100",
                {"video_id": "fast", "title": "f", "published": pub, "viewCount": 10000})
    videos = yti_vph.collect_videos_from_disk(ydir, now=NOW)
    assert [v["videoId"] for v in videos] == ["fast", "slow"]


def test_collect_ignores_bad_files(tmp_path):
    ydir = tmp_path / "youtube"
    d = ydir / "2026-08-01" / "c" / "v" / "metadata"
    d.mkdir(parents=True)
    (d / "2026-08-01-0100.json").write_text("{not json")
    (d / "badname.json").write_text(json.dumps({"video_id": "x", "published": "2026-01-01"}))
    assert yti_vph.collect_videos_from_disk(ydir, now=NOW) == []


def test_missing_dir(tmp_path):
    assert yti_vph.collect_videos_from_disk(tmp_path / "nope") == []
