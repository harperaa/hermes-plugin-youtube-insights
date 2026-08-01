---
name: youtube-planner
description: Competitive intelligence dashboard for YouTube. Tracks competitor videos, pulls transcripts, monitors view velocity (VPH), and generates a sortable HTML dashboard showing trending videos with sparkline charts. Use when you want to analyze competitor performance, track viral videos, plan content strategy, or add new competitor channels to track.
homepage: https://github.com/anthropics/claude-code
user-invocable: true
---

# YouTube Planner

Competitive intelligence dashboard for YouTube creators. Monitors competitor channels, tracks view velocity, and surfaces trending videos with visual trend charts.

## When to use this skill

- User invokes `/youtube-planner` or `youtube-planner`
- User asks to "add [channel] to competitors" or "track [channel]"
- User wants to "update the dashboard" or "refresh competitor data"
- User asks about competitor video performance or trending content

## What it does

1. **Fetches latest videos** from competitor channels (configured in `competitors.json`)
2. **Pulls transcripts** (via youtube-full skill, respecting cache)
3. **Tracks metadata over time** — saves timestamped snapshots to calculate VPH and trends
4. **Generates dashboard** — sortable HTML table with sparkline charts showing view trajectory

## Setup

Add competitor channels to `competitors.json`:

```json
{
  "competitors": [
    "@realrobtheaiguy",
    "@aiadvantage",
    "@matthewberman"
  ]
}
```

## How to run

```
youtube-planner
```

Or target specific date:

```
youtube-planner --date 2026-02-16
```

## Workflow

### 1. Fetch latest videos for each competitor (Python script)

**Use direct Python/curl approach** for efficient batch processing:
- Read competitors from `competitors.json`
- Fetch latest 15 videos from each channel (free endpoint) using curl in parallel
- Save each to `workspace/group/youtube/{date}/{channel-name}/latest.json`
- **First run**: Filter to videos published in last 30 days
- **Subsequent runs**: Filter to videos published in last 24 hours

**First run detection**: Check if any metadata files exist in `workspace/group/youtube/`. If empty, this is the first run.

### 2. Process all videos (Python script)

**Use direct Python script** to process all videos efficiently:

1. Collect all videos from `latest.json` files that match the time range
2. For each video:
   - Check transcript cache: `find workspace/group/youtube -path "*/{channel-slug}/{title-slug}/transcript.txt"`
   - If not found, fetch transcript via curl to TranscriptAPI
   - Save transcript.json and transcript.txt
   - Always save new metadata snapshot to `metadata/{timestamp}.json`
3. Use rate limiting (0.25s between API calls) to respect API limits
4. Process in batches or all at once depending on count

**Python approach is faster and more reliable** than spawning hundreds of agents.

### 3. Generate dashboard

Run the dashboard generator:

```bash
python3 scripts/generate-dashboard.py
```

Output: `workspace/group/youtube/dashboard.html`

## Dashboard features

- **Sortable columns**: Click headers to sort by VPH, views, date
- **Default sort**: Highest VPH (views per hour since publish)
- **Columns**: Thumbnail, Title, Channel, Published, Views, VPH, Trend
- **Trend sparklines**: Mini chart showing view count progression from all metadata snapshots
- **Click thumbnails**: Opens video in new tab

## Trend visualization

The Trend column shows an inline sparkline chart based on all metadata files in `metadata/`:

- **X-axis**: Time (from first snapshot to latest)
- **Y-axis**: View count
- **Visual**: SVG mini line chart (80px × 30px)
- **Color**: Green if accelerating, red if decelerating, gray if flat

Example progression:
```
metadata/2026-02-16-0800.json → 1,200 views
metadata/2026-02-16-1200.json → 2,500 views
metadata/2026-02-16-1600.json → 4,100 views
```

Sparkline shows upward curve → green chart

## File organization

```
workspace/group/youtube/
  dashboard.html
  2026-02-16/
    rob-the-ai-guy/
      latest.json
      google-geminis-new-upgrades/
        transcript.txt
        transcript.json
        metadata/
          2026-02-16-0800.json
          2026-02-16-1200.json
          2026-02-16-1600.json
```

**VPH calculation**: `views / hours_since_publish`

**Trend direction**: Compare VPH from last 2 snapshots:
- If latest VPH > previous VPH by 10%+: accelerating (green)
- If latest VPH < previous VPH by 10%+: decelerating (red)
- Otherwise: flat (gray)

## Files created

| Path | Purpose |
|------|---------|
| `workspace/group/youtube/dashboard.html` | Sortable table with sparkline charts |
| `workspace/group/youtube/{date}/{channel}/latest.json` | Channel's latest 15 videos |
| `workspace/group/youtube/{date}/{channel}/{video}/transcript.txt` | Cached transcript |
| `workspace/group/youtube/{date}/{channel}/{video}/metadata/{datetime}.json` | Timestamped view count snapshot |

## Rules

- **First run behavior**: Pull all videos from last 30 days to bootstrap data
- **Subsequent runs**: Only process videos from last 24 hours to track recent uploads
- Transcript is cached forever (never re-fetch unless user says "refresh")
- Metadata is NEVER cached — always save new timestamped file in `metadata/` subdirectory
- Dashboard updates every time skill runs
- Competitors list is in `competitors.json` at skill base directory
- Sparklines render for videos with 2+ metadata snapshots

## Adding new competitors

When the user asks to add a new channel (e.g., "add @ChannelHandle to competitors"), automatically:

1. **Update competitors.json**:
   ```bash
   # Read current competitors
   competitors=$(cat scripts/competitors.json)
   # Add new channel to the list
   # Use Edit tool to add the channel
   ```

2. **Fetch last 30 days of data**:
   ```bash
   python3 scripts/catch-up-channel.py @ChannelHandle
   ```

3. **Regenerate dashboard**:
   ```bash
   python3 scripts/generate-dashboard.py
   ```

**Important**: Always use the catch-up script for new channels to bootstrap with 30 days of historical data, even if other competitors are in "24-hour mode".

## Example usage

```
# First run: Fetches all videos from last 30 days
youtube-planner

# Subsequent runs: Only fetch videos from last 24 hours
youtube-planner

# Force specific date range (override auto-detection)
youtube-planner --date 2026-02-15

# Add new competitor (handled automatically)
# User says: "add @DanKoeTalks to competitors"
# Skill will: update competitors.json → fetch 30 days → regenerate dashboard
```

## Output

At the end, confirm:
- Number of competitors checked
- Number of new transcripts fetched (API credits used)
- Number of metadata snapshots saved
- Dashboard location: `workspace/group/youtube/dashboard.html`
