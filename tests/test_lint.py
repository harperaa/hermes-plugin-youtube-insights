"""Script-format linter + completion-gate tests."""
from pathlib import Path

import yti_lint

BAD_BEAT = """
## Beat 5: CONTRACT + ACCOUNTABILITY (6:40-8:00)
- Pilot contract scope is the liability boundary customers feel.
- Prefer under-scoped pilots to over-scoped ceremonies.
- Accountability partners beat solitary oaths for founders building alone.
- Conditional GREEN with expiry is a feature.
- **-> HOOK INTO NEXT**: Higher-order choice rule.
- **Visual**: Small honest contract vs giant unread binder
"""

GOOD_BEAT = """
## Beat 5: CONTRACT + ACCOUNTABILITY (6:40-8:00)
- Here's the part nobody warns you about: your pilot contract's scope is the only liability boundary your customer actually feels, not your intentions and not your roadmap, just the words on that one page.
- So when you're tempted to write a big impressive scope to look serious, flip it around completely. A deliberately under-scoped pilot with three deliverables, two weeks, and one success metric beats an over-scoped ceremony every single time, because you can actually keep it.
- I watched a founder promise a full security program in a pilot and deliver forty percent of it. The customer didn't remember the forty percent that worked; they remembered the sixty percent that was promised and missing.
- And if you're building alone, don't rely on willpower to hold the line here. Get one accountability partner who reviews every scope before it goes out, because a person you'd be embarrassed to show a bloated contract to does more than any oath you swear to yourself.
- One more trick that works: make your approval a conditional green with an expiry date on it. Saying yes for ninety days and then re-reviewing isn't hedging, it's the feature that lets you say yes fast without saying yes forever.
- **-> HOOK INTO NEXT**: Now, all of this assumes you can decide what makes the cut in the first place — so next, let me give you the one rule that makes those choices for you.
- **Visual**: Small honest contract vs giant unread binder
"""


def _kinds(result):
    return sorted({f["kind"] for f in result["findings"]})


def test_bad_beat_flags_thin_fragments_and_hook():
    r = yti_lint.lint_script(BAD_BEAT)
    assert not r["ok"]
    kinds = _kinds(r)
    assert "thin_beat" in kinds
    assert "fragment_lines" in kinds
    assert "fragment_hook" in kinds


def test_good_beat_lints_clean():
    r = yti_lint.lint_script(GOOD_BEAT)
    assert r["ok"], r["findings"]


def test_quoted_lines_and_ai_isms_flagged():
    text = GOOD_BEAT.replace(
        "- One more trick that works:",
        '- "One quoted line that should never appear in a spoken script at all." \n- We leverage a robust seamless',
    )
    r = yti_lint.lint_script(text)
    kinds = _kinds(r)
    assert "quoted_lines" in kinds
    assert "ai_ism" in kinds


def test_missing_visual_and_hook_flagged():
    text = """
## Beat 1: SOMETHING (0:00-1:00)
- This is a perfectly reasonable spoken sentence that carries enough words to be a real line someone says on camera today.
- And this one continues the thought with plenty of substance so the fragment rule stays quiet while we test other rules.
"""
    r = yti_lint.lint_script(text)
    kinds = _kinds(r)
    assert "missing_hook" in kinds
    assert "missing_visual" in kinds


def test_no_beats_is_a_structure_finding():
    r = yti_lint.lint_script("# Title\n\nJust prose, no beats.\n")
    assert _kinds(r) == ["structure"]


def test_overstuffed_beat_flagged():
    filler = "- " + " ".join(["word"] * 40) + ".\n"
    text = ("## Beat 1: X (0:00-0:30)\n" + filler * 6 +
            "- **-> HOOK INTO NEXT**: So next let me show you what happens "
            "when we flip this entirely around.\n"
            "- **Visual**: diagram\n")
    r = yti_lint.lint_script(text)
    assert "overstuffed_beat" in _kinds(r)


def test_lint_folder_missing_variants(tmp_path):
    (tmp_path / "script-outline.md").write_text(GOOD_BEAT)
    r = yti_lint.lint_folder(tmp_path)
    assert not r["ok"]
    assert r["files"]["script-outline.md"]["ok"]
    assert not r["files"]["script-outline-hot-take.md"]["ok"]
