"""Script-format linter — the mechanical acceptance gate for produced
script-outline files.

The content-creator skill's format contract (flowing spoken lines, beat word
budgets that match timestamps, spoken-sentence hooks, no AI-isms) proved
unenforceable by prompt alone — workers kept emitting terse concept lists.
This linter turns the contract into findings a worker MUST clear before a
script task may complete: the yt_lint_script tool runs it on demand, and the
kanban completion validator re-opens tasks whose scripts still fail.

Pure python, no LLM. Lenient by design: it flags only what the contract
states unambiguously, so a compliant script always lints clean.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# Spoken delivery baseline used by the skill (Beat Writing Rule 1).
WORDS_PER_MINUTE = 150
# A beat may be a little lean or dense before it becomes a finding.
BUDGET_LOW = 0.70   # < 70% of the wpm target = thin
BUDGET_HIGH = 1.60  # > 160% = overstuffed (timestamps are lying)
FRAGMENT_WORDS = 10  # spoken lines under this are fragments...
FRAGMENTS_ALLOWED_PER_SECTION = 1  # ...but one punch line per beat is fine
HOOK_MIN_WORDS = 6

_AI_ISMS = re.compile(
    r"\b(delve|unpack|unlock|leverage|robust|seamless|elevate|empower|"
    r"game-chang\w*|revolutioniz\w*|tapestry|myriad|plethora|harness|"
    r"foster)\b"
    r"|in today's fast-paced|ever-evolving landscape|important to note",
    re.IGNORECASE)

_SECTION_RE = re.compile(r"^## +(.+?) *$")
_SPAN_RE = re.compile(r"\((\d+):(\d{2})\s*-\s*(\d+):(\d{2})\)")
_BEAT_RE = re.compile(r"^Beat \d+", re.IGNORECASE)
_TIMED_TITLES = ("synthesis", "cta")


def _split_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = {"title": m.group(1).strip(), "lines": []}
            sections.append(current)
            continue
        if current is not None:
            current["lines"].append(line)
    return sections


def _span_seconds(title: str) -> Optional[int]:
    m = _SPAN_RE.search(title)
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    return end - start if end > start else None


def _classify_lines(lines: list[str]) -> dict[str, Any]:
    """Split a section's bullet lines into spoken lines, hook, and fields."""
    spoken: list[str] = []
    hook: Optional[str] = None
    has_visual = False
    for raw in lines:
        s = raw.strip()
        if not (s.startswith("- ") or s.startswith("* ")):
            continue
        body = s[2:].strip()
        if body.startswith("**-> HOOK INTO NEXT**"):
            hook = body.split(":", 1)[1].strip() if ":" in body else ""
            # markdown emphasis wrappers don't make a hook spoken text
            hook = hook.strip("*_ ").strip()
            continue
        if body.lower().startswith("**visual**"):
            has_visual = True
            continue
        if body.startswith("["):        # production direction
            continue
        if body.startswith("**"):       # structured field (Type, Delivery, …)
            continue
        spoken.append(body)
    return {"spoken": spoken, "hook": hook, "has_visual": has_visual}


def lint_script(text: str) -> dict[str, Any]:
    """Lint one script-outline markdown document.

    Returns {ok, findings: [{section, kind, message}], stats}.
    """
    findings: list[dict[str, str]] = []
    stats: dict[str, Any] = {"beats": 0, "spokenWords": 0}

    def flag(section: str, kind: str, message: str) -> None:
        findings.append({"section": section, "kind": kind, "message": message})

    sections = _split_sections(text)
    beat_titles = [s["title"] for s in sections if _BEAT_RE.match(s["title"])]
    if not beat_titles:
        flag("(document)", "structure",
             "no '## Beat N: …' sections found — the script must follow the "
             "content-creator template (## Beat 1: NAME (X:XX-X:XX) …)")

    for sec in sections:
        title = sec["title"]
        is_beat = bool(_BEAT_RE.match(title))
        is_timed = is_beat or any(
            title.lower().startswith(t) for t in _TIMED_TITLES)
        if not is_timed:
            continue
        parts = _classify_lines(sec["lines"])
        spoken = parts["spoken"]
        words = sum(len(l.split()) for l in spoken)
        if parts["hook"] is not None:
            words += len(parts["hook"].split())
        stats["spokenWords"] += words
        if is_beat:
            stats["beats"] += 1

        # 1. word budget vs the claimed timestamp span
        dur = _span_seconds(title)
        if dur and dur >= 30:
            target = dur / 60.0 * WORDS_PER_MINUTE
            if words < target * BUDGET_LOW:
                flag(title, "thin_beat",
                     f"{words} spoken words for a {dur}s span — at "
                     f"~{WORDS_PER_MINUTE} wpm this needs ≈{int(target)} "
                     f"words. Expand with substance (a worked example, a "
                     f"number, a story, a failure case) or shrink the "
                     f"timestamps.")
            elif words > target * BUDGET_HIGH:
                flag(title, "overstuffed_beat",
                     f"{words} spoken words for a {dur}s span (≈{int(target)} "
                     f"fit) — cut or widen the timestamps.")

        # 2. fragment lines (terse concept-list bullets)
        frags = [l for l in spoken if len(l.split()) < FRAGMENT_WORDS]
        if len(frags) > FRAGMENTS_ALLOWED_PER_SECTION:
            sample = "; ".join(f'"{f}"' for f in frags[:3])
            flag(title, "fragment_lines",
                 f"{len(frags)} spoken lines under {FRAGMENT_WORDS} words "
                 f"({sample}). One short punch line per beat is allowed; every "
                 f"other line must be a full conversational sentence or two "
                 f"(15-35 words) that continues the previous line's thought.")

        # 3. quoted lines
        quoted = [l for l in spoken if l.startswith(('"', "“"))]
        if quoted:
            flag(title, "quoted_lines",
                 f"{len(quoted)} spoken lines wrapped in quotation marks — "
                 f"spoken lines are plain text, never quoted.")

        # 4. beat-only structural fields
        if is_beat:
            hook = parts["hook"]
            if hook is None:
                flag(title, "missing_hook",
                     "no '-> HOOK INTO NEXT' line — every beat ends with one.")
            elif (len(hook.split()) < HOOK_MIN_WORDS
                  or not re.search(r"[.?!]$", hook)):
                flag(title, "fragment_hook",
                     f'HOOK INTO NEXT is "{hook}" — it must be a complete '
                     f"spoken sentence or question the creator reads aloud "
                     f'(e.g. "So next, let me show you the five-minute ritual '
                     f'that makes this automatic."), never a title fragment.')
            if not parts["has_visual"]:
                flag(title, "missing_visual",
                     "no '**Visual**:' field — every beat needs one (it "
                     "drives image generation).")

        # 5. banned AI-isms
        for l in spoken:
            m = _AI_ISMS.search(l)
            if m:
                flag(title, "ai_ism",
                     f'banned AI-ism "{m.group(0)}" in: "{l[:80]}"')

    return {"ok": not findings, "findings": findings, "stats": stats}


def lint_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except OSError as exc:
        return {"ok": False, "findings": [
            {"section": "(file)", "kind": "missing_file",
             "message": f"could not read {path}: {exc}"}], "stats": {}}
    result = lint_script(text)
    result["path"] = str(path)
    return result


def lint_folder(folder: Path) -> dict[str, Any]:
    """Lint every script-outline*.md directly in `folder`. Missing variants
    are findings too — the pipeline contract names all three files."""
    expected = ("script-outline.md", "script-outline-hot-take.md",
                "script-outline-contrarian.md")
    files: dict[str, Any] = {}
    ok = True
    for name in expected:
        p = folder / name
        if not p.exists():
            files[name] = {"ok": False, "findings": [
                {"section": "(file)", "kind": "missing_file",
                 "message": f"{name} not found in {folder} — the contract "
                            f"places all three variants directly in the "
                            f"topic folder (no scripts/ subdirectory)."}],
                "stats": {}}
            ok = False
            continue
        result = lint_file(p)
        files[name] = result
        ok = ok and result["ok"]
    return {"ok": ok, "files": files}
