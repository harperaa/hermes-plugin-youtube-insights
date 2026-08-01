"""Insight knowledge base: add (with dedup), search, stats.

Dedup pipeline (replaces the original's qmd cosine >= 0.65 with hermes-native
mechanics):

  1. FTS5 retrieves the top candidate insights for the new text (bm25).
  2. Jaccard word-overlap >= JACCARD_DUPLICATE (0.7) → automatic duplicate.
  3. Borderline band [JACCARD_BORDERLINE, 0.7) → optional LLM judgment via an
     injectable ``judge`` callable (wired to ``ctx.llm`` by the plugin, absent
     in tests/dashboard) that answers "is this the same insight?".

A duplicate is merged: the new source context is appended (unless that video
is already linked) and last_seen/source_count update — identical behavior to
the original addInsightCore. A new insight also writes an agent-readable
markdown file to workspace/insights/<id>.md like the original did.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from . import yti_paths, yti_store, yti_vph
except ImportError:  # pragma: no cover
    import yti_paths  # type: ignore
    import yti_store  # type: ignore
    import yti_vph  # type: ignore

INSIGHT_CATEGORIES = [
    "strategy", "technical", "creativity", "productivity",
    "business", "psychology", "trend", "career",
]

JACCARD_DUPLICATE = 0.7
JACCARD_BORDERLINE = 0.45
FTS_CANDIDATES = 8

# judge(new_text, candidates:[{id,text}]) -> insight_id | None
Judge = Callable[[str, list[dict[str, str]]], Optional[str]]


def _fts_query(text: str) -> str:
    """Build a lenient OR query of sanitized words for candidate retrieval."""
    words = [w for w in re.findall(r"[a-zA-Z0-9]{3,}", text.lower())]
    if not words:
        return ""
    # Quoted-prefix terms ("cta"*) so singular/plural and stem variants match
    # (qmd's stemming used to absorb this; FTS5 tokens are exact otherwise).
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(words[:20]))


def _candidates(conn, text: str) -> list[dict[str, Any]]:
    q = _fts_query(text)
    if not q:
        return []
    try:
        rows = conn.execute(
            """SELECT i.* FROM insights_fts f
               JOIN insights i ON i.rowid = f.rowid
               WHERE insights_fts MATCH ?
               ORDER BY bm25(insights_fts) LIMIT ?""",
            (q, FTS_CANDIDATES),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # FTS syntax edge case → fall back to full scan
        rows = conn.execute("SELECT * FROM insights").fetchall()
        return [dict(r) for r in rows]


def _write_insight_markdown(insights_dir: Path, insight_id: str, text: str,
                            detail: Optional[str], category: str,
                            source_url: str) -> None:
    insights_dir.mkdir(parents=True, exist_ok=True)
    body = [f"# {text}", "", f"- **Category:** {category}",
            f"- **Source:** {source_url}", f"- **ID:** {insight_id}", ""]
    if detail:
        body += [detail, ""]
    (insights_dir / f"{insight_id}.md").write_text("\n".join(body))


def add_insight(
    conn,
    *,
    text: str,
    category: str,
    source_video_id: str,
    detail: Optional[str] = None,
    context: Optional[str] = None,
    timestamp_ref: Optional[str] = None,
    judge: Optional[Judge] = None,
    insights_dir: Optional[Path] = None,
) -> dict[str, Any]:
    if not text or not category or not source_video_id:
        return {"error": "Missing required fields: text, category, sourceVideoId"}
    if category not in INSIGHT_CATEGORIES:
        return {"error": f"category must be one of: {'|'.join(INSIGHT_CATEGORIES)}"}

    source_url = f"https://www.youtube.com/watch?v={source_video_id}"
    now = yti_store.now_iso()

    # -- find duplicate ------------------------------------------------------
    existing: Optional[dict[str, Any]] = None
    borderline: list[dict[str, str]] = []
    for cand in _candidates(conn, text):
        sim = yti_vph.jaccard_similarity(text, cand["text"])
        if sim >= JACCARD_DUPLICATE:
            existing = cand
            break
        if sim >= JACCARD_BORDERLINE:
            borderline.append({"id": cand["id"], "text": cand["text"]})
    if existing is None and borderline and judge is not None:
        try:
            dup_id = judge(text, borderline)
            if dup_id:
                row = conn.execute(
                    "SELECT * FROM insights WHERE id = ?", (dup_id,)
                ).fetchone()
                if row:
                    existing = dict(row)
        except Exception:  # LLM judgment is best-effort only
            pass

    if existing is not None:
        linked = conn.execute(
            "SELECT 1 FROM insight_sources WHERE insight_id = ? AND video_id = ?",
            (existing["id"], source_video_id),
        ).fetchone()
        if not linked:
            conn.execute(
                """INSERT INTO insight_sources
                   (insight_id, video_id, context, timestamp_ref, source_url, added_at)
                   VALUES (?,?,?,?,?,?)""",
                (existing["id"], source_video_id, context, timestamp_ref,
                 source_url, now),
            )
            conn.execute(
                """UPDATE insights SET
                     source_count = (SELECT COUNT(*) FROM insight_sources
                                     WHERE insight_id = ?),
                     last_seen = ?
                   WHERE id = ?""",
                (existing["id"], now, existing["id"]),
            )
            conn.commit()
        row = conn.execute(
            "SELECT source_count FROM insights WHERE id = ?", (existing["id"],)
        ).fetchone()
        return {
            "content": (f'Linked to existing insight: "{existing["text"]}" '
                        f'({row["source_count"]} sources)'),
            "duplicateOf": existing["id"],
        }

    # -- create new ----------------------------------------------------------
    insight_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO insights(id, text, detail, category, source_count,
                                first_seen, last_seen)
           VALUES (?,?,?,?,1,?,?)""",
        (insight_id, text, detail, category, now, now),
    )
    conn.execute(
        """INSERT INTO insight_sources
           (insight_id, video_id, context, timestamp_ref, source_url, added_at)
           VALUES (?,?,?,?,?,?)""",
        (insight_id, source_video_id, context, timestamp_ref, source_url, now),
    )
    conn.commit()
    _write_insight_markdown(insights_dir or yti_paths.insights_dir(),
                            insight_id, text, detail, category, source_url)
    return {"content": f'Created insight: "{text}" (ID: {insight_id})',
            "id": insight_id}


def _attach_sources(conn, insights: list[dict[str, Any]]) -> None:
    for ins in insights:
        rows = conn.execute(
            """SELECT s.video_id, s.context, s.timestamp_ref, s.source_url,
                      v.title, v.channel_handle
               FROM insight_sources s LEFT JOIN videos v ON v.video_id = s.video_id
               WHERE s.insight_id = ? ORDER BY s.added_at""",
            (ins["id"],),
        ).fetchall()
        ins["sourceContexts"] = [
            {"videoId": r["video_id"], "context": r["context"],
             "timestampRef": r["timestamp_ref"], "sourceUrl": r["source_url"],
             "title": r["title"], "author": r["channel_handle"]}
            for r in rows
        ]


def search_insights(
    conn,
    *,
    query: str = "",
    category: str = "",
    sort_by: str = "sources",
    limit: int = 30,
    offset: int = 0,
    include_sources: bool = True,
) -> dict[str, Any]:
    """FTS5 (bm25) search with category filter, pagination, and sort."""
    params: list[Any] = []
    if query.strip():
        q = _fts_query(query)
        base = ("FROM insights_fts f JOIN insights i ON i.rowid = f.rowid "
                "WHERE insights_fts MATCH ?")
        params.append(q)
        order = "bm25(insights_fts)"
    else:
        base = "FROM insights i WHERE 1=1"
        order = ("i.source_count DESC, i.last_seen DESC"
                 if sort_by == "sources" else "i.last_seen DESC")
    if category:
        base += " AND i.category = ?"
        params.append(category)

    try:
        total = conn.execute(f"SELECT COUNT(*) c {base}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT i.* {base} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    except Exception:
        # FTS syntax edge → LIKE fallback (mirrors original's fallback path)
        like = f"%{query.lower()}%"
        base = "FROM insights i WHERE lower(i.text) LIKE ?"
        params = [like]
        if category:
            base += " AND i.category = ?"
            params.append(category)
        total = conn.execute(f"SELECT COUNT(*) c {base}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT i.* {base} ORDER BY i.source_count DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

    insights = []
    for r in rows:
        d = dict(r)
        insights.append({
            "id": d["id"], "text": d["text"], "detail": d["detail"],
            "category": d["category"], "sourceCount": d["source_count"],
            "firstSeen": d["first_seen"], "lastSeen": d["last_seen"],
        })
    if include_sources:
        _attach_sources(conn, insights)
    return {"insights": insights, "total": total}


def insight_stats(conn) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) c FROM insights").fetchone()["c"]
    sources = conn.execute(
        "SELECT COUNT(DISTINCT video_id) c FROM insight_sources"
    ).fetchone()["c"]
    top = conn.execute(
        "SELECT text, source_count FROM insights ORDER BY source_count DESC LIMIT 1"
    ).fetchone()
    cats: dict[str, int] = {}
    for r in conn.execute(
        "SELECT category, COUNT(*) c FROM insights GROUP BY category"
    ).fetchall():
        cats[r["category"]] = r["c"]
    return {
        "totalInsights": total,
        "totalSources": sources,
        "topInsight": ({"text": top["text"], "sourceCount": top["source_count"]}
                       if top else None),
        "categories": cats,
    }


def delete_insight(conn, insight_id: str,
                   insights_dir: Optional[Path] = None) -> dict[str, Any]:
    conn.execute("DELETE FROM insight_sources WHERE insight_id = ?", (insight_id,))
    conn.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
    conn.commit()
    md = (insights_dir or yti_paths.insights_dir()) / f"{insight_id}.md"
    try:
        md.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


def count_insights_for_video(conn, video_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT insight_id) c FROM insight_sources WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    return row["c"]


def make_llm_judge(complete_text: Optional[Callable[[str], str]]) -> Optional[Judge]:
    """Wrap a plain ``prompt -> text`` completion fn into a borderline judge.

    The plugin's ``register()`` adapts hermes ``ctx.llm.complete(messages)``
    into this shape; tests pass a stub. Best-effort: any failure → None
    (treat as not-a-duplicate).
    """
    if complete_text is None:
        return None

    def judge(text: str, candidates: list[dict[str, str]]) -> Optional[str]:
        listing = "\n".join(f'- id={c["id"]}: "{c["text"]}"' for c in candidates)
        prompt = (
            "You deduplicate a knowledge base of short insights.\n"
            f'New insight: "{text}"\n'
            f"Existing candidates:\n{listing}\n\n"
            "If the new insight expresses the SAME core idea as one candidate, "
            'reply with exactly that id. Otherwise reply "none". '
            "Reply with only the id or none."
        )
        try:
            resp = complete_text(prompt)
            answer = (resp or "").strip().strip('"').splitlines()[0].strip()
        except Exception:
            return None
        valid = {c["id"] for c in candidates}
        return answer if answer in valid else None

    return judge
