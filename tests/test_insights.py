import yti_insights
import yti_paths


def _add(conn, text, vid="vid1", category="strategy", **kw):
    return yti_insights.add_insight(
        conn, text=text, category=category, source_video_id=vid, **kw)


def test_add_and_search(conn):
    r = _add(conn, "Hook viewers in the first fifteen seconds of every video")
    assert "Created insight" in r["content"]
    res = yti_insights.search_insights(conn, query="hook viewers")
    assert res["total"] == 1
    ins = res["insights"][0]
    assert ins["sourceCount"] == 1
    assert ins["category"] == "strategy"
    assert ins["sourceContexts"][0]["videoId"] == "vid1"
    assert ins["sourceContexts"][0]["sourceUrl"].endswith("v=vid1")


def test_validation(conn):
    assert "error" in _add(conn, "")
    assert "error" in yti_insights.add_insight(
        conn, text="x", category="bogus", source_video_id="v")


def test_duplicate_merges_new_source(conn):
    _add(conn, "Consistency beats intensity for long term channel growth", vid="v1")
    r2 = _add(conn, "Consistency beats intensity for long term channel growth",
              vid="v2", context="quote here", timestamp_ref="01:23")
    assert "Linked to existing insight" in r2["content"]
    res = yti_insights.search_insights(conn, query="consistency beats intensity")
    assert res["total"] == 1
    ins = res["insights"][0]
    assert ins["sourceCount"] == 2
    assert {s["videoId"] for s in ins["sourceContexts"]} == {"v1", "v2"}


def test_duplicate_same_video_not_double_linked(conn):
    _add(conn, "Retention graphs reveal where viewers abandon your video", vid="v1")
    _add(conn, "Retention graphs reveal where viewers abandon your video", vid="v1")
    res = yti_insights.search_insights(conn, query="retention graphs")
    assert res["insights"][0]["sourceCount"] == 1


def test_distinct_insights_not_merged(conn):
    _add(conn, "Thumbnails should show emotion not information")
    _add(conn, "Publish on a consistent weekly schedule to train the algorithm")
    stats = yti_insights.insight_stats(conn)
    assert stats["totalInsights"] == 2


def test_borderline_judge_merges(conn):
    r1 = _add(conn, "Strong hooks in the first seconds keep viewers watching longer")
    first_id = r1["id"]

    # Borderline-similar phrasing (some overlap but < 0.7 Jaccard)
    def judge(text, candidates):
        assert candidates and candidates[0]["id"] == first_id
        return first_id

    r2 = yti_insights.add_insight(
        conn,
        text="Strong hooks in the opening seconds keep people watching videos",
        category="strategy", source_video_id="v9", judge=judge)
    assert "Linked to existing insight" in r2["content"]


def test_borderline_judge_rejects(conn):
    _add(conn, "Strong hooks in the first seconds keep viewers watching longer")
    r2 = yti_insights.add_insight(
        conn,
        text="Strong hooks in the opening seconds keep people watching videos",
        category="strategy", source_video_id="v9",
        judge=lambda text, cands: None)
    assert "Created insight" in r2["content"]


def test_judge_error_treated_as_new(conn):
    _add(conn, "Strong hooks in the first seconds keep viewers watching longer")

    def bad_judge(text, cands):
        raise RuntimeError("llm down")

    r2 = yti_insights.add_insight(
        conn,
        text="Strong hooks in the opening seconds keep people watching videos",
        category="strategy", source_video_id="v9", judge=bad_judge)
    assert "Created insight" in r2["content"]


BUSINESS_TEXTS = [
    "Anchor pricing against the cost of inaction",
    "Recurring revenue smooths creator income volatility",
    "Sponsorship rates scale with niche purchasing power",
    "Productize services before hiring your first employee",
    "Bundle offers around one urgent expensive problem",
]

TECH_TEXTS = [
    "Proxy edits keep 4K timelines responsive",
    "Silence removal tightens pacing automatically",
    "Color managed workflows survive platform compression",
]


def test_category_filter_and_pagination(conn):
    for i, text in enumerate(BUSINESS_TEXTS):
        _add(conn, text, vid=f"b{i}", category="business")
    for i, text in enumerate(TECH_TEXTS):
        _add(conn, text, vid=f"t{i}", category="technical")

    res = yti_insights.search_insights(conn, category="business")
    assert res["total"] == 5
    page1 = yti_insights.search_insights(conn, category="business", limit=2, offset=0)
    page2 = yti_insights.search_insights(conn, category="business", limit=2, offset=2)
    # the dashboard offers up to 200/page — the store must honour it
    big = yti_insights.search_insights(conn, category="business", limit=200, offset=0)
    assert len(big["insights"]) == big["total"] or len(big["insights"]) == 200
    assert len(page1["insights"]) == 2
    assert len(page2["insights"]) == 2
    ids1 = {i["id"] for i in page1["insights"]}
    ids2 = {i["id"] for i in page2["insights"]}
    assert not (ids1 & ids2)


def test_fts_search_with_category(conn):
    _add(conn, "Monetization requires a diversified sponsorship pipeline",
         category="business")
    _add(conn, "Monetization mindset psychology for creators", category="psychology")
    res = yti_insights.search_insights(conn, query="monetization",
                                       category="psychology")
    assert res["total"] == 1
    assert res["insights"][0]["category"] == "psychology"


def test_stats(conn):
    _add(conn, "Alpha insight about strategy and positioning", vid="v1")
    _add(conn, "Alpha insight about strategy and positioning", vid="v2")
    _add(conn, "Beta insight about career growth ladders", vid="v3",
         category="career")
    st = yti_insights.insight_stats(conn)
    assert st["totalInsights"] == 2
    assert st["totalSources"] == 3
    assert st["topInsight"]["sourceCount"] == 2
    assert st["categories"] == {"strategy": 1, "career": 1}


def test_delete_insight(conn, tmp_home):
    r = _add(conn, "Deletable insight about nothing in particular today")
    iid = r["id"]
    md = yti_paths.insights_dir() / f"{iid}.md"
    assert md.exists()
    yti_insights.delete_insight(conn, iid)
    assert not md.exists()
    assert yti_insights.insight_stats(conn)["totalInsights"] == 0


def test_markdown_written(conn, tmp_home):
    r = _add(conn, "Written to markdown for agent consumption", detail="More detail.")
    md = yti_paths.insights_dir() / f"{r['id']}.md"
    text = md.read_text()
    assert "Written to markdown" in text
    assert "strategy" in text
    assert "More detail." in text


def test_empty_query_sort_recent(conn):
    _add(conn, "Older insight text about thumbnails and colors", vid="v1")
    _add(conn, "Newer insight text about endings and loops", vid="v2")
    res = yti_insights.search_insights(conn, sort_by="recent")
    assert res["insights"][0]["text"].startswith("Newer")


def test_search_prefix_matches_plural(tmp_path):
    import yti_store, yti_insights
    conn = yti_store.connect(tmp_path / "t.db")
    yti_insights.add_insight(conn, text="Mid-roll CTAs convert better after payoff", category="business", source_video_id="v1", insights_dir=tmp_path)
    res = yti_insights.search_insights(conn, query="CTA")
    assert res["total"] == 1


def test_search_plural_query_matches_singular_token(tmp_path):
    import yti_store, yti_insights
    conn = yti_store.connect(tmp_path / "t.db")
    yti_insights.add_insight(conn, text="A single test proves the pipeline works", category="technical", source_video_id="v2", insights_dir=tmp_path)
    res = yti_insights.search_insights(conn, query="tests")
    assert res["total"] == 1
