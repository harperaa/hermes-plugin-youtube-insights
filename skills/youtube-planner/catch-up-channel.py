#!/usr/bin/env python3
"""
Catch up a single competitor channel with last 30 days of videos.
Usage: python3 catch-up-channel.py @ChannelHandle
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

def sanitize(text):
    """Convert text to filesystem-safe slug"""
    return '-'.join(filter(None, (''.join(c if c.isalnum() or c == '-' else '-' for c in text.lower())).split('-')))[:80]

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 catch-up-channel.py @ChannelHandle")
        sys.exit(1)

    channel = sys.argv[1]
    api_key = os.environ.get('TRANSCRIPT_API_KEY')
    if not api_key:
        print("Error: TRANSCRIPT_API_KEY not set")
        sys.exit(1)

    # Setup paths (workspace-relative; agents run from the company workspace cwd)
    workspace_root = Path(os.getcwd())
    base = workspace_root / 'youtube'
    base.mkdir(parents=True, exist_ok=True)

    # Fetch latest videos from channel
    print(f"Fetching latest videos from {channel}...")
    result = subprocess.run([
        'curl', '-s',
        f'https://transcriptapi.com/api/v2/youtube/channel/latest?channel={channel}',
        '-H', f'Authorization: Bearer {api_key}'
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error fetching videos: {result.stderr}")
        sys.exit(1)

    data = json.loads(result.stdout)
    if 'error' in data:
        print(f"API Error: {data['error']}")
        sys.exit(1)

    videos = data.get('results', [])
    channel_name = sanitize(channel.lstrip('@'))

    # Filter to last 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    filtered = []
    for v in videos:
        pub_str = v.get('published', '')
        if pub_str:
            pub_date = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
            if pub_date >= cutoff:
                filtered.append(v)

    print(f"Found {len(filtered)} videos from last 30 days")

    # Process each video
    transcript_count = 0
    metadata_count = 0

    for i, video in enumerate(filtered, 1):
        vid = video.get('videoId')
        title = video.get('title', 'untitled')
        views = video.get('viewCount', 0)
        published = video.get('published', '')

        slug = sanitize(title)
        pub_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
        date_str = pub_date.strftime('%Y-%m-%d')

        video_dir = base / date_str / channel_name / slug
        metadata_dir = video_dir / 'metadata'
        metadata_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [{i}/{len(filtered)}] → {channel_name}/{slug}")

        # Check transcript cache
        cache_search = subprocess.run([
            'find', str(base), '-path', f'*/{channel_name}/{slug}/transcript.txt'
        ], capture_output=True, text=True)

        # Fetch transcript if not cached
        if not cache_search.stdout.strip():
            print(f"    Fetching transcript...")
            fetch_result = subprocess.run([
                'curl', '-s',
                f'https://transcriptapi.com/api/v2/youtube/transcript?video_url={vid}&format=json&include_timestamp=true&send_metadata=true',
                '-H', f'Authorization: Bearer {api_key}'
            ], capture_output=True, text=True)

            if fetch_result.returncode == 0:
                try:
                    transcript_data = json.loads(fetch_result.stdout)
                    if 'error' not in transcript_data:
                        # Save transcript.json
                        with open(video_dir / 'transcript.json', 'w') as f:
                            json.dump(transcript_data, f, indent=2)

                        # Save transcript.txt
                        with open(video_dir / 'transcript.txt', 'w') as f:
                            for item in transcript_data.get('transcript', []):
                                start = item.get('start', 0)
                                text = item.get('text', '')
                                f.write(f"[{start}s] {text}\n")

                        transcript_count += 1
                        time.sleep(0.25)  # Rate limiting
                    else:
                        print(f"    Error: {transcript_data.get('error')}")
                except json.JSONDecodeError:
                    print(f"    Error: Invalid JSON response")
        else:
            print(f"    Using cached transcript")

        # Always save new metadata snapshot
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')
        metadata_file = metadata_dir / f'{timestamp}.json'

        metadata = {
            'video_id': vid,
            'title': title,
            'author_name': channel,
            'published': published,
            'viewCount': views,
            'thumbnail_url': f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',
            'link': f'https://www.youtube.com/watch?v={vid}'
        }

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        metadata_count += 1

    print(f"\n✓ Catch-up complete for {channel}")
    print(f"  Transcripts fetched: {transcript_count}")
    print(f"  Metadata snapshots: {metadata_count}")
    print(f"  API credits used: {transcript_count}")

if __name__ == '__main__':
    main()
