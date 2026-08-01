---
name: digest-url-liveness-gate
description: >
  Mandatory URL-liveness gate for the Cybersecurity x AI digest. Runs BEFORE a digest
  is marked done or delivered: does a real browser-UA GET on every cited source URL
  (following redirects, with backoff retries), FAILS the digest on any genuinely dead
  citation (404/410/DNS-fail, or a soft-404 such as a cross-domain redirect that remaps
  the article id onto unrelated content), and treats 403/429/timeout/5xx as INCONCLUSIVE
  — retried, then held for review, never auto-quarantined — so real-but-bot-blocked links
  (BleepingComputer, Cloudflare-fronted sites) survive. Also flags hallucination tells:
  prior-year-dated URLs on a current-year digest, and one URL cited as the source for
  several different stories. Use every time a digest is produced. Exists because the
  gemini_local digest model repeatedly hallucinates source URLs and soft "never fabricate"
  instructions do not stop it.
tags: [research, quality-gate]
---

# Digest URL-Liveness Gate

**Non-negotiable rule: a digest is NOT done until every cited URL passes this gate.**

The digest model (gemini_local) has, in multiple LIVE scheduled runs, fabricated source
URLs — plausibly-shaped links that hard-404 (`github.blog/2026-07-14-...`), soft-404
(`nextgov.com/.../397940/` 301-redirects cross-domain to a 2024 route-fifty.com finance
story — HTTP 200 but the cited content does not exist), or reuse a single dead 2024 Forbes
404 as the "source" for three different 2026 stories. A digest marked `done` is **not**
proof the sources are real. This gate makes fabrication mechanically impossible to ship.

## Why a naive checker is not enough

Two naive checks both give WRONG answers, in opposite directions:
- **Bare-UA / HEAD check** OVER-flags: anti-bot walls (Cloudflare/Akamai) return 403/429 to
  a weak or absent User-Agent even for live pages → real citations reported "dead".
- **"final code == 200" check** UNDER-flags: a fabricated URL can still resolve 200 because
  the CMS maps an unknown article id onto an unrelated page (a soft-404).

The gate uses a real browser UA + GET + follow-redirects + backoff, and distinguishes a
genuine death from an anti-bot block.

## When to run

Run the gate on the finished digest markdown **before** you:
- mark the digest routine issue `done`, OR
- post / deliver / circulate the digest anywhere.

If the gate fails, the digest does not ship as-is. Fix and re-run.

## How to run

```bash
# from the Harper Content working dir where digests are written:
python3 scripts/verify-digest-links.py --gate <digest.md>

# examples / other modes:
python3 scripts/verify-digest-links.py <digest.md>            # plain report
python3 scripts/verify-digest-links.py --json <digest.md>     # machine-readable
cat draft.md | python3 scripts/verify-digest-links.py -        # from stdin
```

The canonical copy lives in this skill (`scripts/verify-digest-links.py`); an identical
runtime copy sits in the digest working dir at `Harper Content/scripts/`. It is
dependency-free (Python 3 stdlib + the system `curl`) — no pip install, runs on the gemini
host and in the CMO delivery workspace alike.

## Reading the result — gate on the EXIT CODE, not the prose

| Exit | Meaning | Action |
|------|---------|--------|
| `0`  | **PASS** — no dead URLs | Ship. Spot-check any INCONCLUSIVE / tell lines first. |
| `2`  | **FAIL** — ≥1 dead URL | **DO NOT SHIP.** Drop or regenerate every DROP-listed citation, then re-run until exit 0. |
| `1`  | usage error | Fix the invocation. |

## Verdicts

- **LIVE** — reachable and the cited page still exists. Good.
- **DEAD** — genuine failure → gate fails. One of: DNS-fail / connection-refused, HTTP
  404/410, or a **soft-404** (redirect off the original registrable domain, deep link
  bounced to the site homepage, the descriptive slug wiped across a redirect, or a
  "page not found" body).
- **INCONCLUSIVE** — 403 / 429 / timeout / 5xx after backoff retries. The **anti-false-
  positive guard**: these hosts (BleepingComputer, Cloudflare-fronted, rate-limited)
  return these to automated checkers yet are real. The gate does **NOT** quarantine them
  — it surfaces them as HOLD (recheck). Never ship one silently; confirm with a second
  check or a browser.

## Hallucination tells (advisory — do NOT change the exit code)

Even when a URL resolves, the gate flags for review:
- **Stale year** — a URL path dated to a prior year on a current-year digest (`/2024/` on
  a 2026 digest).
- **Reused source** — the same URL cited under two or more *different* story sections (the
  trailing "Sources"/"References" roundup is excluded so this doesn't fire on every digest).
  Note: one genuine story discussed across multiple sections can legitimately reuse a
  source, so treat this as a prompt to review — the hard fabrication signal is a reused
  source that is ALSO dead or stale-dated.

## Fix workflow when the gate fails

1. For each DROP (dead) URL, either (a) find the real source with a fresh web search and
   replace the link, or (b) drop the claim entirely. Never ship a claim whose only source
   is a dead link.
2. For each HOLD (recheck) URL, confirm it in a browser; keep only if genuinely live.
3. Re-run the gate. Repeat until exit 0.
4. Only then mark the digest done / deliver it.

## Validation

Verified against the two reference digests in `Harper Content/quarantine-fabricated-urls/`:
- the fabricated 2026-07-16-0441Z digest → **FAIL, exit 2** (8/9 URLs dead: 6 hard-404,
  the nextgov cross-domain soft-404, the skadden "page not found" soft-404; the one
  remaining is a sophos redirect held INCONCLUSIVE; the dead Forbes 404 correctly flagged
  as reused across 3 stories).
- the CMO-verified clean 2026-07-16-0000 digest → **PASS, exit 0** (15/15 live, 0 dead,
  0 inconclusive — including BleepingComputer, which a bare-UA check would have mis-flagged).
