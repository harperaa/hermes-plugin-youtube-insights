#!/usr/bin/env python3
"""
Generate YouTube competitive intelligence dashboard from metadata snapshots.
"""
import json
import glob
import os
from datetime import datetime
from pathlib import Path

WORKSPACE = os.environ.get("YT_WORKSPACE") or os.path.join(os.getcwd(), "youtube")


def parse_timestamp(filename):
    """Extract datetime from metadata filename: 2026-02-16-1430.json"""
    stem = Path(filename).stem
    try:
        return datetime.strptime(stem, "%Y-%m-%d-%H%M")
    except ValueError:
        return None


def calculate_vph(views, published_str):
    """Calculate views per hour since publish"""
    published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
    now = datetime.now(published.tzinfo)
    hours_since = (now - published).total_seconds() / 3600
    if hours_since < 0.1:
        hours_since = 0.1  # Avoid division by zero
    return int(views / hours_since)


def generate_sparkline(data_points):
    """Generate SVG sparkline from list of (timestamp, views) tuples"""
    if len(data_points) < 2:
        return '<svg width="80" height="30"></svg>'

    # Sort by timestamp
    data_points = sorted(data_points, key=lambda x: x[0])

    views = [v for _, v in data_points]
    min_views = min(views)
    max_views = max(views)

    # Prevent division by zero
    if max_views == min_views:
        max_views = min_views + 1

    # Normalize to SVG coordinates
    width = 80
    height = 30
    padding = 2

    points = []
    for i, (_, view_count) in enumerate(data_points):
        x = padding + (i / (len(data_points) - 1)) * (width - 2 * padding)
        y = height - padding - ((view_count - min_views) / (max_views - min_views)) * (height - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    # Determine color based on trend
    if len(views) >= 2:
        # Compare first half avg to second half avg
        mid = len(views) // 2
        first_half_avg = sum(views[:mid]) / mid
        second_half_avg = sum(views[mid:]) / (len(views) - mid)

        if second_half_avg > first_half_avg * 1.1:
            color = "#22c55e"  # green (accelerating)
        elif second_half_avg < first_half_avg * 0.9:
            color = "#ef4444"  # red (decelerating)
        else:
            color = "#9ca3af"  # gray (flat)
    else:
        color = "#9ca3af"

    polyline = f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>'
    return f'<svg width="{width}" height="{height}" style="vertical-align: middle;">{polyline}</svg>'


def collect_videos():
    """Scan workspace and collect all videos with metadata"""
    videos = []

    # Find all metadata directories
    pattern = f"{WORKSPACE}/*/*/*/metadata/*.json"
    metadata_files = glob.glob(pattern)

    # Group by video
    video_map = {}

    for filepath in metadata_files:
        # Parse metadata
        try:
            with open(filepath) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Handle both video_id and videoId field names
        video_id = meta.get('video_id') or meta.get('videoId', '')
        if not video_id:
            continue

        # Get timestamp
        ts = parse_timestamp(filepath)
        if not ts:
            continue

        # Group by video
        if video_id not in video_map:
            video_map[video_id] = {
                'meta': meta,
                'snapshots': []
            }

        video_map[video_id]['snapshots'].append((ts, int(meta.get('viewCount', 0))))

    # Process each video
    for video_id, data in video_map.items():
        meta = data['meta']
        snapshots = data['snapshots']

        # Get latest snapshot
        latest_snapshot = max(snapshots, key=lambda x: x[0])
        latest_views = latest_snapshot[1]

        # Calculate VPH
        published = meta.get('published', '')
        if not published:
            continue

        vph = calculate_vph(latest_views, published)

        # Generate sparkline
        sparkline = generate_sparkline(snapshots)

        videos.append({
            'videoId': video_id,
            'title': meta.get('title', 'Unknown'),
            'author': meta.get('author_name') or meta.get('author', 'Unknown'),
            'published': published,
            'views': latest_views,
            'vph': vph,
            'thumbnail': meta.get('thumbnail_url') or meta.get('thumbnail', ''),
            'link': meta.get('link') or f"https://www.youtube.com/watch?v={video_id}",
            'sparkline': sparkline,
            'snapshot_count': len(snapshots)
        })

    return videos


def generate_html(videos):
    """Generate sortable HTML dashboard"""

    # Sort by VPH descending by default
    videos = sorted(videos, key=lambda v: v['vph'], reverse=True)

    rows = []
    for v in videos:
        published_dt = datetime.fromisoformat(v['published'].replace('Z', '+00:00'))
        published_str = published_dt.strftime('%Y-%m-%d %H:%M')

        rows.append(f"""
        <tr>
            <td><a href="{v['link']}" target="_blank"><img src="{v['thumbnail']}" width="120" alt="thumbnail"></a></td>
            <td><a href="{v['link']}" target="_blank">{v['title']}</a></td>
            <td>{v['author']}</td>
            <td data-sort="{published_dt.timestamp()}">{published_str}</td>
            <td data-sort="{v['views']}">{v['views']:,}</td>
            <td data-sort="{v['vph']}">{v['vph']:,}</td>
            <td>{v['sparkline']}<br><small>{v['snapshot_count']} snapshots</small></td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>YouTube Competitive Intelligence Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            max-width: 1400px;
            margin: 20px auto;
            padding: 20px;
            background: #f9fafb;
        }}
        h1 {{
            color: #111827;
            border-bottom: 3px solid #3b82f6;
            padding-bottom: 10px;
        }}
        .meta {{
            color: #6b7280;
            margin-bottom: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        th {{
            background: #3b82f6;
            color: white;
            padding: 12px;
            text-align: left;
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{
            background: #2563eb;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #e5e7eb;
        }}
        tr:hover {{
            background: #f3f4f6;
        }}
        img {{
            display: block;
            border-radius: 4px;
        }}
        a {{
            color: #3b82f6;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .sort-indicator {{
            margin-left: 5px;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <h1>YouTube Competitive Intelligence Dashboard</h1>
    <div class="meta">
        <strong>{len(videos)}</strong> videos tracked | Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    <table id="dashboard">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Thumbnail</th>
                <th onclick="sortTable(1)">Title <span class="sort-indicator"></span></th>
                <th onclick="sortTable(2)">Channel <span class="sort-indicator"></span></th>
                <th onclick="sortTable(3)">Published <span class="sort-indicator"></span></th>
                <th onclick="sortTable(4)">Views <span class="sort-indicator"></span></th>
                <th onclick="sortTable(5)">VPH <span class="sort-indicator">↓</span></th>
                <th onclick="sortTable(6)">Trend <span class="sort-indicator"></span></th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>

    <script>
        let sortDirection = {{}};

        function sortTable(colIndex) {{
            const table = document.getElementById('dashboard');
            const tbody = table.tBodies[0];
            const rows = Array.from(tbody.rows);

            // Toggle sort direction
            if (sortDirection[colIndex] === undefined) {{
                sortDirection[colIndex] = true; // descending first
            }} else {{
                sortDirection[colIndex] = !sortDirection[colIndex];
            }}

            const isDescending = sortDirection[colIndex];

            rows.sort((a, b) => {{
                let aVal = a.cells[colIndex].getAttribute('data-sort') || a.cells[colIndex].textContent;
                let bVal = b.cells[colIndex].getAttribute('data-sort') || b.cells[colIndex].textContent;

                // Try numeric comparison
                const aNum = parseFloat(aVal.replace(/,/g, ''));
                const bNum = parseFloat(bVal.replace(/,/g, ''));

                if (!isNaN(aNum) && !isNaN(bNum)) {{
                    return isDescending ? bNum - aNum : aNum - bNum;
                }}

                // String comparison
                return isDescending ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
            }});

            // Clear all indicators
            document.querySelectorAll('.sort-indicator').forEach(el => el.textContent = '');

            // Set indicator
            table.tHead.rows[0].cells[colIndex].querySelector('.sort-indicator').textContent = isDescending ? '↓' : '↑';

            // Re-append rows
            rows.forEach(row => tbody.appendChild(row));
        }}
    </script>
</body>
</html>
"""

    return html


def main():
    videos = collect_videos()

    if not videos:
        print("No videos found. Run youtube-planner to fetch data first.")
        return

    html = generate_html(videos)

    output_path = f"{WORKSPACE}/dashboard.html"
    with open(output_path, 'w') as f:
        f.write(html)

    print(f"✓ Dashboard generated: {output_path}")
    print(f"  {len(videos)} videos tracked")


if __name__ == '__main__':
    main()
