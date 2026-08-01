import json
from datetime import datetime, timedelta, timezone

import yti_fetcher
import yti_store

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _mk_http(channel_results, transcripts=None):
    """Fake http_get: returns canned channel + transcript payloads."""
    transcripts = transcripts or {}
    calls = []

    def http_get(url, headers):
        calls.append(url)
        assert headers.get("Authorization", "").startswith("Bearer ")
        if "/channel/latest" in url:
            return 200, {"results": channel_results}
        if "/transcript" in url:
            for vid, payload in transcripts.items():
                if f"video_url={vid}" in url:
                    return 200, payload
            return 404, {"error": "no transcript"}
        raise AssertionError(f"unexpected url {url}")

    http_get.calls = calls
    return http_get


def _segments(duration, n=10):
    step = duration / n
    return [{"text": f"seg{i}", "start": round(i * step, 2), "duration": step}
            for i in range(n)]


def test_url_builders():
    u = yti_fetcher.channel_latest_url("@Dan Koe")
    assert u.startswith("https://transcriptapi.com/api/v2/youtube/channel/latest?channel=")
    assert "%40Dan%20Koe" in u
    t = yti_fetcher.transcript_url("abc123")
    assert "video_url=abc123" in t
    assert "include_timestamp=true" in t


def test_is_short():
    assert yti_fetcher.is_short("https://youtube.com/shorts/x", None)
    assert yti_fetcher.is_short("", 60)
    assert not yti_fetcher.is_short("https://youtube.com/watch?v=x", 300)
    assert not yti_fetcher.is_short("", None)


def test_run_fetch_no_channels(conn, tmp_path):
    summary = yti_fetcher.run_fetch(conn, "key", youtube_dir=tmp_path / "yt",
                                    http_get=_mk_http([]), sleep=lambda s: None,
                                    now=NOW)
    assert summary["errors"] == ["no channels tracked"]


def test_run_fetch_writes_artifacts(conn, tmp_path):
    yti_store.add_channel(conn, "@TestChan")
    pub = (NOW - timedelta(days=2)).isoformat()
    videos = [{"videoId": "vid1", "title": "Great Video!", "published": pub,
               "link": "https://www.youtube.com/watch?v=vid1", "viewCount": 5000}]
    transcripts = {"vid1": {"transcript": _segments(600)}}
    ydir = tmp_path / "yt"
    summary = yti_fetcher.run_fetch(conn, "key", youtube_dir=ydir,
                                    http_get=_mk_http(videos, transcripts),
                                    sleep=lambda s: None, now=NOW)
    assert summary["transcripts_fetched"] == 1
    assert summary["videos_seen"] == 1

    date_str = pub[:10]
    vdir = ydir / date_str / "testchan" / "great-video"
    assert (vdir / "transcript.json").exists()
    txt = (vdir / "transcript.txt").read_text()
    assert txt.startswith("[0.0s] seg0")
    metas = list((vdir / "metadata").glob("*.json"))
    assert len(metas) == 1
    meta = json.loads(metas[0].read_text())
    assert meta["video_id"] == "vid1"
    assert meta["viewCount"] == 5000
    assert meta["duration_seconds"] == 600

    row = yti_store.get_video(conn, "vid1")
    assert row["status"] == "transcribed"
    assert row["transcript_path"]
    snaps = yti_store.snapshots_for(conn, "vid1")
    assert len(snaps) == 1 and snaps[0][1] == 5000


def test_run_fetch_skips_shorts_by_link(conn, tmp_path):
    yti_store.add_channel(conn, "@TestChan")
    pub = (NOW - timedelta(days=1)).isoformat()
    videos = [{"videoId": "s1", "title": "Short", "published": pub,
               "link": "https://www.youtube.com/shorts/s1", "viewCount": 10}]
    summary = yti_fetcher.run_fetch(conn, "key", youtube_dir=tmp_path / "yt",
                                    http_get=_mk_http(videos),
                                    sleep=lambda s: None, now=NOW)
    assert summary["skipped_shorts"] == 1
    assert summary["videos_seen"] == 0
    assert yti_store.get_video(conn, "s1") is None


def test_run_fetch_skips_short_transcripts(conn, tmp_path):
    yti_store.add_channel(conn, "@TestChan")
    pub = (NOW - timedelta(days=1)).isoformat()
    videos = [{"videoId": "tiny", "title": "Tiny", "published": pub,
               "link": "https://www.youtube.com/watch?v=tiny", "viewCount": 10}]
    transcripts = {"tiny": {"transcript": _segments(60)}}  # < 120s
    summary = yti_fetcher.run_fetch(conn, "key", youtube_dir=tmp_path / "yt",
                                    http_get=_mk_http(videos, transcripts),
                                    sleep=lambda s: None, now=NOW)
    assert summary["transcripts_fetched"] == 0
    assert summary["skipped_shorts"] == 1


def test_run_fetch_outside_lookback_no_transcript_but_snapshot(conn, tmp_path):
    yti_store.add_channel(conn, "@TestChan")
    pub = (NOW - timedelta(days=90)).isoformat()
    videos = [{"videoId": "old1", "title": "Old", "published": pub,
               "link": "https://www.youtube.com/watch?v=old1", "viewCount": 999}]
    http = _mk_http(videos, {"old1": {"transcript": _segments(600)}})
    summary = yti_fetcher.run_fetch(conn, "key", youtube_dir=tmp_path / "yt",
                                    http_get=http, sleep=lambda s: None,
                                    now=NOW, lookback_days=30)
    assert summary["transcripts_fetched"] == 0
    # metadata snapshot still written + DB row discovered
    assert yti_store.get_video(conn, "old1")["status"] == "discovered"
    assert not any("/transcript?" in u for u in http.calls)


def test_run_fetch_channel_error_recorded(conn, tmp_path):
    yti_store.add_channel(conn, "@Bad")

    def http_get(url, headers):
        return 401, {"detail": "unauthorized"}

    summary = yti_fetcher.run_fetch(conn, "bad-key", youtube_dir=tmp_path / "yt",
                                    http_get=http_get, sleep=lambda s: None,
                                    now=NOW)
    assert len(summary["errors"]) == 1
    assert "rejected" in summary["errors"][0]


def test_trends_from_db(conn, tmp_path):
    pub = (NOW - timedelta(hours=10)).isoformat()
    yti_store.upsert_video(conn, {"video_id": "a", "title": "A", "published": pub,
                                  "view_count": 100, "channel_handle": "@c",
                                  "link": "l", "thumbnail": "t"})
    yti_store.add_snapshot(conn, "a", 100, ts=(NOW - timedelta(hours=5)).isoformat())
    yti_store.add_snapshot(conn, "a", 1000, ts=NOW.isoformat())
    trends = yti_fetcher.trends_from_db(conn, now=NOW)
    assert len(trends) == 1
    assert trends[0]["views"] == 1000
    assert trends[0]["sparklinePoints"] == [100, 1000]
    assert trends[0]["vph"] == 100
    assert trends[0]["trendDirection"] == "accelerating"


def test_reindex_from_disk(conn, tmp_path):
    ydir = tmp_path / "yt"
    d = ydir / "2026-07-30" / "chan" / "vid" / "metadata"
    d.mkdir(parents=True)
    pub = (NOW - timedelta(days=2)).isoformat()
    d.joinpath("2026-07-30-0300.json").write_text(json.dumps(
        {"video_id": "r1", "title": "R", "published": pub, "viewCount": 42}))
    n = yti_fetcher.reindex_from_disk(conn, youtube_dir=ydir)
    assert n == 1
    assert yti_store.get_video(conn, "r1")["view_count"] == 42
    assert len(yti_store.snapshots_for(conn, "r1")) == 1
