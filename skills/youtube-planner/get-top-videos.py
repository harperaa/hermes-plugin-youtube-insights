#!/usr/bin/env python3
"""
Find top N videos by VPH from youtube workspace.
"""

import os
import sys
import json
import glob
from datetime import datetime, timezone
from pathlib import Path

def calculate_vph(views, published_str):
    """Calculate views per hour since publish"""
    try:
        published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
        now = datetime.now(published.tzinfo)
        hours_since = (now - published).total_seconds() / 3600
        if hours_since < 0.1:
            hours_since = 0.1
        return int(views / hours_since)
    except:
        return 0

def main():
    workspace = Path(os.environ.get('YOUTUBE_DIR', 'youtube'))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    # Find all metadata files
    pattern = str(workspace / '*/*/*/metadata/*.json')
    metadata_files = glob.glob(pattern)

    # Group by video and get latest snapshot
    video_map = {}

    for filepath in metadata_files:
        try:
            with open(filepath) as f:
                meta = json.load(f)

            video_id = meta.get('video_id') or meta.get('videoId')
            if not video_id:
                continue

            # Get video directory (go up 2 levels from metadata file)
            video_dir = Path(filepath).parent.parent

            # Parse timestamp from filename
            filename = Path(filepath).stem
            try:
                ts = datetime.strptime(filename, "%Y-%m-%d-%H%M")
            except:
                continue

            # Keep latest snapshot for each video
            if video_id not in video_map or ts > video_map[video_id]['timestamp']:
                video_map[video_id] = {
                    'meta': meta,
                    'timestamp': ts,
                    'video_dir': video_dir
                }
        except:
            continue

    # Calculate VPH and prepare list
    videos = []
    for video_id, data in video_map.items():
        meta = data['meta']
        published = meta.get('published', '')
        view_count = meta.get('viewCount', 0)

        if not published:
            continue

        try:
            views = int(view_count)
        except:
            continue

        vph = calculate_vph(views, published)

        videos.append({
            'video_id': video_id,
            'title': meta.get('title', 'Unknown'),
            'author': meta.get('author_name') or meta.get('author', 'Unknown'),
            'published': published,
            'views': views,
            'vph': vph,
            'video_dir': str(data['video_dir']),
            'has_transcript': (data['video_dir'] / 'transcript.txt').exists(),
            'has_analysis': (data['video_dir'] / 'analysis.md').exists()
        })

    # Sort by VPH descending
    videos = sorted(videos, key=lambda v: v['vph'], reverse=True)

    # Print top N
    print(f"Top {limit} videos by VPH:\n")
    for i, v in enumerate(videos[:limit], 1):
        status = '✓ analyzed' if v['has_analysis'] else ('⚠ no transcript' if not v['has_transcript'] else '→ needs analysis')
        print(f"[{i}] VPH: {v['vph']:,} | Views: {v['views']:,}")
        print(f"    {v['author']} - {v['title'][:60]}")
        print(f"    {status}")
        print(f"    {v['video_dir']}")
        print()

if __name__ == '__main__':
    main()
