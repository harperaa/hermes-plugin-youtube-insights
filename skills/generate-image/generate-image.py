#!/usr/bin/env python3
"""Generate images via xAI Grok's image model (the only sanctioned path).

Auth resolution order:
  1. XAI_API_KEY environment variable, if set.
  2. The hermes xai-oauth access token from ~/.hermes/auth.json
     (credential_pool["xai-oauth"][0]) — present after `hermes auth add xai-oauth`.

Usage:
  python3 generate-image.py --prompt "..." --out /path/to/image.jpg \
      [--n 1] [--model grok-imagine-image] [--aspect-ratio 16:9]

Default model: grok-imagine-image. Pass --model grok-imagine-image-quality
for the higher-quality variant. The API returns JPEG bytes — prefer a .jpg
output extension. With --n > 1, outputs are suffixed -1, -2, ...
Non-2xx API responses are printed verbatim so the caller can see the real error.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1")
DEFAULT_MODEL = "grok-imagine-image"


def resolve_token() -> str:
    key = os.environ.get("XAI_API_KEY", "").strip()
    if key:
        return key
    auth_path = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "auth.json"
    try:
        store = json.loads(auth_path.read_text())
        pool = store.get("credential_pool", {}).get("xai-oauth") or []
        entry = pool[0] if pool else {}

        def find_access_token(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("access_token", "accessToken") and isinstance(v, str) and len(v) > 20:
                        return v
                    found = find_access_token(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = find_access_token(item)
                    if found:
                        return found
            return None

        token = find_access_token(entry)
        if token:
            return token
    except (OSError, json.JSONDecodeError):
        pass
    sys.exit("ERROR: no xAI credential — set XAI_API_KEY or run `hermes auth add xai-oauth`.")


def generate(prompt: str, out: Path, n: int, model: str,
             aspect_ratio: str | None = None) -> list[Path]:
    token = resolve_token()
    payload_body: dict = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "response_format": "b64_json",
    }
    if aspect_ratio:
        payload_body["aspect_ratio"] = aspect_ratio
    body = json.dumps(payload_body).encode()
    req = urllib.request.Request(
        f"{API_BASE}/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.4.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: xAI images API returned HTTP {exc.code}:\n{detail}")

    images = payload.get("data") or []
    if not images:
        sys.exit(f"ERROR: no images in response:\n{json.dumps(payload)[:2000]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i, img in enumerate(images):
        if len(images) == 1:
            target = out
        else:
            target = out.with_name(f"{out.stem}-{i + 1}{out.suffix}")
        if img.get("b64_json"):
            target.write_bytes(base64.b64decode(img["b64_json"]))
        elif img.get("url"):
            dl = urllib.request.Request(img["url"], headers={"User-Agent": "curl/8.4.0"})
            with urllib.request.urlopen(dl, timeout=300) as r:
                target.write_bytes(r.read())
        else:
            sys.exit(f"ERROR: image entry has neither b64_json nor url: {json.dumps(img)[:500]}")
        written.append(target)
        if img.get("revised_prompt"):
            print(f"revised prompt [{i + 1}]: {img['revised_prompt'][:200]}")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--aspect-ratio", default=None,
                    help="e.g. 16:9 — verified supported by the xAI API")
    args = ap.parse_args()
    for path in generate(args.prompt, args.out, args.n, args.model,
                         aspect_ratio=args.aspect_ratio):
        print(f"saved: {path}")


if __name__ == "__main__":
    main()
