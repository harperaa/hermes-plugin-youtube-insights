---
name: youtube-video-analyst
description: Analyze YouTube video transcripts and extract insights into the knowledge base. Performs forensic video deconstruction (hooks, retention, emotional engineering) AND extracts 10-15 generalizable insights via the add-insight tool. Use when processing video transcripts for competitive intelligence — this skill handles the complete pipeline from raw transcript to indexed insights.
version: 2.0.0
tags:
  - content-analysis
  - youtube
  - viral-content
  - insight-extraction
---

# YouTube Video Analyst + Insight Extractor

Analyze a YouTube video transcript and extract reusable insights into the knowledge base. This skill performs two tasks in sequence — both are required for completion.

## Workflow

This skill always runs two phases. Phase 1 produces the analysis file. Phase 2 uses it to extract insights. Skipping Phase 2 means the work is incomplete and wasted.

### Phase 1: Forensic Video Analysis

Read the transcript and produce `analysis.md` in the same directory. The analysis has three parts:

**Part A: Video Summary (~500-800 words)**
A flowing narrative summary covering the video's thesis, key arguments, evidence, and conclusions. Written as prose, not bullets. Useful as a standalone document for someone who hasn't watched the video.

**Part B: Top 20 Insights**
Numbered list of the 20 most valuable, actionable, or surprising insights. Each is 1-3 sentences. Ordered by impact. Mix of strategic, tactical, and quotable observations.

**Part C: Mechanics Analysis (6 sections)**
1. **Hook Architecture** — primary hook (exact quote, type, psychological mechanism), secondary hooks with timestamps, fill-in-blank templates
2. **Structural Blueprint** — content framework, beat map, pacing pattern, section breakdown with time percentages
3. **Retention Mechanics** — open loops, pattern interrupts, curiosity gaps, payoff points
4. **Emotional Engineering** — emotional arc, trigger words, identity hooks, us-vs-them dynamics
5. **Linguistic Patterns** — power phrases, sentence rhythm, repetition techniques, conversational triggers
6. **Reusable Templates** — complete fill-in-blank script template with 3 opening variations, transition library, CTA templates

Save this as `analysis.md` in the same directory as the transcript.

**After saving, verify the file exists:**
```bash
test -f "{transcript_dir}/analysis.md" && echo "VERIFIED" || echo "MISSING"
```

If MISSING, the file was not saved correctly. Try again.

### Phase 2: Insight Extraction (REQUIRED)

This phase is not optional. The analysis from Phase 1 is only useful if insights are indexed in the knowledge base.

Read the analysis.md you just wrote. For each of the Top 20 Insights (and any additional insights from the mechanics sections), call the `yt_add_insight` tool with:

| Field | What to provide |
|-------|----------------|
| `text` | 10-20 word generalizable principle (universal truth, not video-specific) |
| `detail` | 2-3 sentences with specific context from this video |
| `category` | One of: strategy, technical, creativity, productivity, business, psychology, trend, career |
| `sourceVideoId` | The YouTube video ID (e.g., `dQw4w9WgXcQ`) |
| `context` | Direct quote from the transcript that supports this insight |
| `timestampRef` | MM:SS reference point in the video |

**Guidelines for good insights:**
- Generalize beyond this specific video — "AI commoditizes execution" not "this YouTuber said AI is useful"
- Each insight should stand alone as a principle someone could apply
- Avoid duplicating insights that say the same thing differently
- Include insights from BOTH the summary and the mechanics sections

**Minimum 10 `yt_add_insight` calls required. Target 15.**

The issue is complete only after Phase 2. Count your yt_add_insight calls. If you've made fewer than 10, go back to the analysis and find more.

## Locating the Transcript

Transcripts are in the project workspace under:
```
youtube/{date}/{channel-slug}/{video-slug}/
  transcript.txt      <- Read this
  transcript.json
  metadata/
    {timestamp}.json  <- Video ID, title, views, published
```

To find a specific video by ID:
```bash
grep -rl '"video_id": "VIDEO_ID"' youtube/*/*/metadata/ 2>/dev/null | head -1
```

The video directory is two levels up from the metadata file.

## Output Checklist

Before marking this task complete, verify:
- [ ] `analysis.md` exists in the video directory
- [ ] `analysis.md` contains Video Summary, Top 20 Insights, and 6 mechanics sections
- [ ] Called `yt_add_insight` at least 10 times (target 15)
- [ ] Each insight is a generalizable principle, not a video-specific fact
- [ ] Each insight has a category, context quote, and timestamp reference
