#!/usr/bin/env python3
"""
verify-digest-links.py — trustworthy source-URL verifier for the Cyber x AI digest.

WHY THIS EXISTS (HARA-3988)
---------------------------
Two naive link-checkers both give WRONG answers on the digest, in OPPOSITE directions:

  1. Bare-UA HEAD check  (`curl -o /dev/null -w '%{http_code}' -L <url>`, what the CMO
     used) OVER-flags: anti-bot walls (Cloudflare/Akamai) return 403/429 to a weak/absent
     User-Agent even for perfectly live pages. Skadden returned 403 bare -> 200 with a real
     browser UA. Result: real citations reported "dead".

  2. Bare "final code == 200" check (what a follow-redirects browser-UA GET would report)
     UNDER-flags: a fabricated URL can still resolve 200 because the CMS maps an unknown
     article-id onto an UNRELATED page. Nextgov `.../ai-can-now.../397940/` 301-redirects
     cross-domain to `route-fifty.com/finance/2024/07/states-take-more-measured.../397940/`
     — a 2024 ESG finance story. HTTP 200, but the cited content does not exist. This is a
     SOFT-404: "200" is a false PASS.

A trustworthy detector must therefore:
  * use a real browser UA, GET (not HEAD), follow redirects, retry with backoff + jitter
    delay so we don't self-inflict a rate-limit "dead";
  * treat 403 / 429 / timeout / 5xx as INCONCLUSIVE (retry, then flag for review) — NOT dead;
  * flag as DEAD only on a GENUINE failure: DNS/conn refused, 404/410, or a SOFT-404
    (cross-registrable-domain redirect, redirect to homepage, slug wiped, or a
    "page not found" body).

CLASSES
-------
  LIVE          verified reachable and the cited page still exists
  DEAD          genuine failure — DROP this citation before delivery
  INCONCLUSIVE  anti-bot / transient — could not confirm; hold for a second check, do not ship silently

Exit code: 0 if no DEAD links, 2 if any DEAD link found (so it can gate a delivery step).

USAGE
  python3 scripts/verify-digest-links.py <digest.md> [<digest2.md> ...]
  python3 scripts/verify-digest-links.py --gate <digest.md>      # print DROP list, exit 2 on any dead
  python3 scripts/verify-digest-links.py --json <digest.md>      # machine-readable
  cat file | python3 scripts/verify-digest-links.py -            # read urls/markdown from stdin
"""
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAX_TIME = 25          # per-request seconds
RETRIES = 3            # attempts on inconclusive (403/429/5xx/timeout)
BACKOFF = 2.0          # base seconds between retries (grows linearly) + inter-url delay
INTER_URL_DELAY = 0.8  # polite delay between distinct URLs to avoid self-rate-limiting
BODY_SNIFF = 4000      # bytes of body to sniff for soft-404 phrases

# Multi-label public suffixes we care about, so eTLD+1 comparison doesn't treat
# `a.co.uk` and `b.co.uk` as the same site. Extend as needed.
MULTI_TLDS = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "org.au", "co.nz",
    "co.jp", "com.br", "co.in", "co.za", "com.sg", "com.mx", "gov.au",
}

SOFT_404_PHRASES = (
    "page not found", "404 not found", "page you requested", "page you were looking for",
    "no longer available", "cannot be found", "doesn't exist", "does not exist",
    "sorry, we couldn", "content is not available", "has been removed",
)

URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`]+")

# Ephemeral OFF-FORMAT redirect wrappers (HARA-4009).
# A digest citation MUST be a resolved DIRECT source URL. Search-grounding redirect
# wrappers — most notably Gemini's `vertexaisearch...grounding-api-redirect/` — are:
#   (a) ephemeral: the token expires, after which the wrapper soft-404s to an unrelated
#       homepage, so no reader can reach the cited source; and
#   (b) off-format: they are never the resolved article URL a reader can cite or trust.
# They must fail the gate DETERMINISTICALLY, independent of what they resolve to on the
# network right now. Relying on the soft-404 off-site check is NOT enough: a wrapper that
# happens to 403 / time out is scored only INCONCLUSIVE (HOLD), so a whole batch of
# grounding wrappers coming back 403/timeout would report "0 DEAD" and PASS the gate.
# Fire d2840d37 shipped 22 such wrappers (0 live / 21 DEAD / 1 INCONCLUSIVE) — the lone
# inconclusive is exactly the slip this rule closes.
OFFFORMAT_REDIRECT_RE = re.compile(
    r"^https?://("
    r"[a-z0-9.-]*vertexaisearch\.cloud\.google\.com/grounding-api-redirect/"  # Gemini grounding
    r"|[a-z0-9.-]*\.google\.com/grounding-api-redirect/"                        # any google grounding host
    r"|www\.google\.com/url\?"                                                   # google click-through
    r"|www\.bing\.com/ck/a\?"                                                    # bing click-through
    r"|duckduckgo\.com/l/\?"                                                     # ddg click-through
    r")",
    re.I,
)


def offformat_redirect_reason(url: str):
    """DEAD reason if `url` is an ephemeral off-format search/grounding redirect wrapper
    rather than a resolved direct source URL, else None. Checked BEFORE the network probe
    so the verdict is deterministic and needs no request."""
    if OFFFORMAT_REDIRECT_RE.match(url):
        return ("off-format: ephemeral search-grounding redirect wrapper, not a resolved "
                "direct source URL (token expires -> soft-404 to an unrelated page; "
                "unverifiable regardless of current HTTP status)")
    return None


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last3 = ".".join(parts[-3:])
    last2 = ".".join(parts[-2:])
    # if the last two labels form a known multi-label suffix, keep three labels
    for suf in MULTI_TLDS:
        if host.endswith("." + suf) or host == suf:
            return ".".join(parts[-3:]) if len(parts) >= 3 else host
    return last2


def norm_path(p: str) -> str:
    p = (p or "/").rstrip("/")
    return p if p else "/"


def slug_tokens(path: str):
    """Meaningful alnum tokens (len>=4) from a URL path, for slug-preservation checks."""
    toks = re.findall(r"[a-z0-9]+", (path or "").lower())
    return {t for t in toks if len(t) >= 4 and not t.isdigit()}


def _clean_url(raw: str) -> str:
    u = re.split(r"\]\(", raw)[0]           # `url](url` duplication
    return u.rstrip(".,;:!)]}>\"'")


def extract_urls(text: str):
    """Extract + clean URLs from markdown, dedup preserving order."""
    seen, out = set(), []
    for raw in URL_RE.findall(text):
        u = _clean_url(raw)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def build_reuse_map(text: str):
    """
    Map each URL -> list of DISTINCT story/section labels it is cited under, so we can
    flag the classic hallucination tell of one source URL reused across several unrelated
    stories (e.g. a single dead 2024 Forbes 404 cited as the source for 3 different 2026
    items). The label is the nearest preceding markdown heading or bold lead-in.
    """
    # The trailing "## Sources" / "References" roundup legitimately lists every URL once,
    # so it must NOT count as a second "story" — otherwise the tell fires on every digest.
    sources_re = re.compile(r"^(sources?|references?|further reading|read more|links?|"
                            r"citations?|appendix)\b", re.I)
    reuse = {}
    current = "(top)"
    in_sources = False
    for line in text.splitlines():
        h = re.match(r"\s{0,3}(#{1,6})\s+(.*)", line)
        if h:
            current = h.group(2).strip()[:90]
            in_sources = bool(sources_re.match(current))
        elif not in_sources:
            b = re.match(r"\s*(?:[-*]\s+)?\*\*(.+?)\*\*", line)  # bold lead-in as a story label
            if b:
                current = b.group(1).strip()[:90]
        if in_sources:
            continue  # don't attribute the roundup list as a distinct story
        for raw in URL_RE.findall(line):
            u = _clean_url(raw)
            if not u:
                continue
            reuse.setdefault(u, [])
            if current not in reuse[u]:
                reuse[u].append(current)
    return reuse


def curl_probe(url: str):
    """One browser-UA GET, follow redirects. Returns dict with code, final url, body sample."""
    body_file = None
    try:
        import tempfile
        fd, body_file = tempfile.mkstemp(prefix="vdl_", suffix=".body")
        os.close(fd)
        fmt = "%{http_code}\t%{url_effective}\t%{num_redirects}"
        proc = subprocess.run(
            ["curl", "-sS", "-L", "--compressed",
             "-A", BROWSER_UA,
             "--max-time", str(MAX_TIME),
             "--max-redirs", "10",
             "-o", body_file,
             "-w", fmt, url],
            capture_output=True, text=True, timeout=MAX_TIME + 8,
        )
        rc = proc.returncode
        code, final, nredir = "000", url, "0"
        if proc.stdout.strip():
            fields = proc.stdout.strip().split("\t")
            code = fields[0] if len(fields) > 0 else "000"
            final = fields[1] if len(fields) > 1 and fields[1] else url
            nredir = fields[2] if len(fields) > 2 else "0"
        body = ""
        try:
            with open(body_file, "rb") as fh:
                body = fh.read(BODY_SNIFF).decode("utf-8", "ignore").lower()
        except OSError:
            pass
        return {"rc": rc, "code": code, "final": final, "nredir": nredir,
                "body": body, "stderr": proc.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"rc": 28, "code": "000", "final": url, "nredir": "0", "body": "", "stderr": "timeout"}
    finally:
        if body_file and os.path.exists(body_file):
            try:
                os.remove(body_file)
            except OSError:
                pass


def classify(url: str, r: dict):
    """Return (klass, reason). klass in {LIVE, DEAD, INCONCLUSIVE}."""
    rc = r["rc"]
    code = r["code"]
    final = r["final"]
    body = r["body"]

    # hard network failures
    if rc in (6,):
        return "DEAD", "DNS could not resolve host"
    if rc in (7,):
        return "DEAD", "connection refused"
    if rc in (28,) or code == "000":
        return "INCONCLUSIVE", "timeout / no response (retry or check manually)"

    try:
        icode = int(code)
    except ValueError:
        return "INCONCLUSIVE", f"non-numeric status {code!r}"

    if icode in (404, 410):
        return "DEAD", f"HTTP {icode} not found"
    if icode in (403, 429) or 500 <= icode < 600:
        return "INCONCLUSIVE", f"HTTP {icode} (anti-bot/transient — not proof of a dead link)"
    if icode in (301, 302, 303, 307, 308):
        # -L exhausted redirects without landing on a terminal 2xx
        return "INCONCLUSIVE", f"redirect chain did not terminate in 2xx (last {icode})"
    if not (200 <= icode < 300):
        return "INCONCLUSIVE", f"unexpected HTTP {icode}"

    # --- 2xx: still must guard against SOFT-404 ---
    o, f = urlsplit(url), urlsplit(final)
    o_reg, f_reg = registrable_domain(o.hostname or ""), registrable_domain(f.hostname or "")

    if o_reg and f_reg and o_reg != f_reg:
        return "DEAD", f"soft-404: redirected off-site {o_reg} -> {f_reg} (id remapped to unrelated content)"

    o_path, f_path = norm_path(o.path), norm_path(f.path)
    if o_path not in ("/", "") and f_path in ("/", ""):
        return "DEAD", "soft-404: deep link redirected to site homepage"

    # slug wiped: original had a descriptive slug but none of its tokens survive the redirect
    o_toks = slug_tokens(o.path)
    if o_toks and f_path != o_path:
        f_toks = slug_tokens(f.path)
        if o_toks and not (o_toks & f_toks):
            return "DEAD", f"soft-404: slug not preserved across redirect ({o_path} -> {f_path})"

    # body-based soft-404 (only trust it on short/obvious pages)
    for phrase in SOFT_404_PHRASES:
        if phrase in body:
            return "DEAD", f"soft-404: body says '{phrase}'"

    return "LIVE", f"HTTP {icode}" + (f" (redirected to {final})" if final != url else "")


def date_smell(url, digest_year):
    """Flag a year-in-path that predates the digest by >1 year (classic hallucination tell)."""
    if not digest_year:
        return None
    m = re.search(r"/((?:19|20)\d{2})/", urlsplit(url).path)
    if not m:
        return None
    y = int(m.group(1))
    if y < digest_year - 1:
        return f"path dated {y} on a {digest_year} digest"
    return None


def verify_urls(urls, digest_year=None):
    results = []
    for i, url in enumerate(urls):
        off = offformat_redirect_reason(url)
        if off:
            # deterministic DEAD — no network probe needed
            results.append({
                "url": url, "class": "DEAD", "reason": off,
                "final": url, "http": "—", "attempts": 0,
                "smell": date_smell(url, digest_year),
            })
            continue
        if i:
            time.sleep(INTER_URL_DELAY)
        r = curl_probe(url)
        klass, reason = classify(url, r)
        attempt = 1
        while klass == "INCONCLUSIVE" and attempt < RETRIES and "timeout" not in reason and "redirect" not in reason:
            time.sleep(BACKOFF * attempt)
            r = curl_probe(url)
            klass, reason = classify(url, r)
            attempt += 1
        smell = date_smell(url, digest_year)
        results.append({
            "url": url, "class": klass, "reason": reason,
            "final": r["final"], "http": r["code"], "attempts": attempt,
            "smell": smell,
        })
    return results


def guess_digest_year(text, path):
    m = re.search(r"(20\d{2})-\d{2}-\d{2}", os.path.basename(path or ""))
    if m:
        return int(m.group(1))
    m = re.search(r"\b(20\d{2})-\d{2}-\d{2}\b", text)
    return int(m.group(1)) if m else None


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    gate = "--gate" in flags
    as_json = "--json" in flags

    if not args:
        print(__doc__)
        return 1

    all_results = []
    for path in args:
        if path == "-":
            text, label, year = sys.stdin.read(), "<stdin>", None
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            label = path
        year = guess_digest_year(text, None if path == "-" else path)
        urls = extract_urls(text)
        if not urls:
            print(f"[{label}] no URLs found", file=sys.stderr)
            continue
        reuse_map = build_reuse_map(text)
        if not as_json:
            print(f"\n=== {label}  ({len(urls)} unique URLs, digest year={year}) ===")
        res = verify_urls(urls, year)
        for r in res:
            r["source"] = label
            stories = reuse_map.get(r["url"], [])
            r["reused_in"] = stories if len(stories) > 1 else []
        all_results.extend(res)
        if not as_json:
            for r in res:
                mark = {"LIVE": "LIVE ", "DEAD": "DEAD ", "INCONCLUSIVE": "INCON"}[r["class"]]
                smell = f"  ⚠ {r['smell']}" if r["smell"] else ""
                print(f"  [{mark}] {r['http']:>3}  {r['url']}")
                print(f"          {r['reason']}{smell}")
                if r["reused_in"]:
                    print(f"          ⚠ tell: one URL cited as the source for "
                          f"{len(r['reused_in'])} different stories: "
                          f"{'; '.join(r['reused_in'])}")

    dead = [r for r in all_results if r["class"] == "DEAD"]
    incon = [r for r in all_results if r["class"] == "INCONCLUSIVE"]
    live = [r for r in all_results if r["class"] == "LIVE"]

    if as_json:
        print(json.dumps({
            "total": len(all_results), "live": len(live),
            "dead": len(dead), "inconclusive": len(incon),
            "results": all_results,
        }, indent=2))
    else:
        reused = [r for r in all_results if r.get("reused_in")]
        print(f"\nSUMMARY: {len(live)} live, {len(dead)} DEAD, {len(incon)} inconclusive "
              f"(of {len(all_results)} citations)")
        if reused:
            print(f"TELL: {len(reused)} URL(s) cited as the source for multiple different "
                  f"stories (classic fabrication signal — review even if live).")
        if gate and (dead or incon or reused):
            print("\nPRE-DELIVERY GATE — do NOT ship these as-is:")
            for r in dead:
                print(f"  DROP (dead): {r['url']}  — {r['reason']}")
            for r in incon:
                print(f"  HOLD (recheck): {r['url']}  — {r['reason']}")
            for r in reused:
                print(f"  REVIEW (reused source): {r['url']}  — cited under "
                      f"{len(r['reused_in'])} stories: {'; '.join(r['reused_in'])}")

    return 2 if dead else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
