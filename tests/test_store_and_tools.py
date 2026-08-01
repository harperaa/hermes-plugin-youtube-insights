import json

import yti_store
import tools as yti_tools


def test_channel_normalization(conn):
    yti_store.add_channel(conn, "DanKoe")
    yti_store.add_channel(conn, "@DanKoe")  # dedupes
    assert yti_store.list_channels(conn) == ["@DanKoe"]
    yti_store.remove_channel(conn, "DanKoe")
    assert yti_store.list_channels(conn) == []


def test_upsert_video_partial_update(conn):
    yti_store.upsert_video(conn, {"video_id": "v", "title": "T",
                                  "published": "2026-01-01", "view_count": 5})
    yti_store.upsert_video(conn, {"video_id": "v", "view_count": 50})
    row = yti_store.get_video(conn, "v")
    assert row["title"] == "T"
    assert row["view_count"] == 50


def test_meta_roundtrip(conn):
    assert yti_store.get_meta(conn, "x") is None
    yti_store.set_meta(conn, "x", "1")
    assert yti_store.get_meta(conn, "x") == "1"


# -- tool handlers (JSON contract) ------------------------------------------

def test_tool_add_list_remove_channel(tmp_home):
    out = json.loads(yti_tools.yt_add_channel({"handle": "chan1"}))
    assert out["ok"] and out["channels"] == ["@chan1"]
    out = json.loads(yti_tools.yt_list_channels({}))
    assert out["channels"] == ["@chan1"]
    out = json.loads(yti_tools.yt_remove_channel({"handle": "@chan1"}))
    assert out["channels"] == []


def test_tool_errors_are_json(tmp_home):
    assert "error" in json.loads(yti_tools.yt_add_channel({}))
    assert "error" in json.loads(yti_tools.yt_search_insights({}))


def test_tool_fetch_requires_key(tmp_home, monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_API_KEY", raising=False)
    out = json.loads(yti_tools.yt_fetch_videos({}))
    assert "TRANSCRIPT_API_KEY" in out["error"]


def test_tool_add_and_search_insight(tmp_home):
    out = json.loads(yti_tools.yt_add_insight({
        "text": "Ship weekly to compound the algorithm's trust in your channel",
        "category": "strategy", "source_video_id": "abc",
    }))
    assert "Created insight" in out["content"]
    res = json.loads(yti_tools.yt_search_insights({"query": "compound algorithm"}))
    assert res["total"] == 1


def test_tool_trending_empty(tmp_home):
    out = json.loads(yti_tools.yt_trending({}))
    assert out["videos"] == []


def test_tool_trigger_analysis_empty(tmp_home):
    out = json.loads(yti_tools.yt_trigger_analysis({}))
    assert out["triggered"] == 0
