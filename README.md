# youtube-insights — hermes plugin

> Aligned with the mentoring of **Dr. Allen Harper, AI Cyber Value Creator** — join the community at [AI Cyber Value Creators on Skool](https://www.skool.com/ai-cyber-value-creators).


YouTube competitive intelligence for [Hermes Agent](https://hermes-agent.nousresearch.com):
track competitor channels, pull transcripts, rank videos by **views-per-hour
(VPH)** with trend direction, and mine transcripts into a **deduplicated,
searchable insight knowledge base** — with a dashboard tab (Trends + Insights
pages), agent tools, slash commands, and a daily cron pipeline.

This is the hermes port of the intelligence core of a former proprietary
plugin, released under MIT. Content production (scripts, images, campaigns)
is intentionally out of scope — pair it with
[digital-marketing-pro](https://github.com/indranilbanerjee/digital-marketing-pro)
for marketing execution; its agents can consume this plugin's insights via
the `yt_search_insights` / `yt_trending` tools and the workspace files.

## Install

```bash
hermes plugins install harperaa/hermes-plugin-long-form --enable
```

You'll be prompted for `TRANSCRIPT_API_KEY`
([transcriptapi.com](https://transcriptapi.com)). Manage it later in the
dashboard under **Settings → Environment**.

## What you get

**Dashboard tab** (`YouTube Insights`):
- **Trends** — sortable video table (thumbnail, title, channel, published,
  duration, views, VPH, trend sparkline), stat cards, tracked-channel
  manager, Refresh (fetch) and Analyze (queue insight extraction) buttons.
- **Insights** — full-text search (SQLite FTS5/BM25), category filter,
  most-sourced/most-recent sort, expandable cards with source videos,
  timestamps, and quotes; pagination; delete.

**Agent tools** (toolset `youtube_insights`):
`yt_add_channel`, `yt_remove_channel`, `yt_list_channels`,
`yt_fetch_videos`, `yt_trending`, `yt_trigger_analysis`,
`yt_add_insight`, `yt_search_insights`.

**Slash commands:** `/yt` (summary), `/yt-analyze` (queue analysis).

**Skills** (load with `skill_view("youtube-insights:<name>")`):
`youtube-video-analyst`, `youtube-gap-finder`, `ideal-mechanics`,
`youtube-planner` (+ standalone dashboard scripts), `digest-url-liveness-gate`.

**Cron:** `hermes youtube-insights setup-cron --apply` installs the daily
03:00 intelligence refresh (fetch → trigger analysis → analyst skill →
insights).

## How insights dedup works

New insights retrieve candidates via FTS5, merge automatically at Jaccard
word overlap ≥ 0.7 (the new source video is linked to the existing insight),
and for borderline matches optionally ask the host LLM (`ctx.llm`) — no
external embedding service required.

## Data layout

Everything lives in `~/.hermes/plugins-data/youtube-insights/`:

```
data.db                        # SQLite: videos, snapshots, insights (FTS5), queue
workspace/youtube/{date}/{channel}/{video}/
    transcript.json|txt        # full transcript with timestamps
    metadata/{ts}.json         # view-count snapshots (feeds VPH + sparklines)
    analysis.md                # analyst skill output
workspace/insights/{id}.md     # one markdown file per insight
```

## Development

```bash
git clone https://github.com/harperaa/hermes-plugin-long-form
ln -s "$PWD/youtube-insights" ~/.hermes/plugins/youtube-insights
hermes plugins enable youtube-insights
python -m pytest            # 58 unit tests, no network needed
```

## License

MIT — see [LICENSE](LICENSE).
