# YouTube Creator — feature spec (harper-cmo)

> **Status:** IMPLEMENTED + v2 control redesign (typecheck + build green; validated live).
> **Date:** 2026-06-28 (v1) · 2026-06-29 (v2)
> **Owner page:** new `youtube-creator` page in the harper-cmo plugin.
>
> **Implementation notes:**
> - Worker: creator types + run state + QMD/company-context helpers + stage brief
>   builders + `registerCreatorDataHandlers` / `registerCreatorActionHandlers`
>   (inline in `src/worker.ts`, wired in `setup()`). New capabilities
>   `issue.documents.read` / `issue.documents.write` (read/save script artifacts).
> - UI: `YouTubeCreatorPage` (+ `IdeateStage` / `ScriptStage` / `BeatEditor` /
>   `ProduceStage` → `ProduceConfig`/`ProduceResults` / `CompanyContextPanel` /
>   `TopicCard` / `AssetThumb`) in `src/ui/index.tsx`; new sidebar link + `CreatorIcon`;
>   Trends ✨ `handleGenerate` now redirects to `youtube-creator?videoId=…&source=trends`.
> - Constants: `PAGE_ROUTES.creator`, slot/export names, creator DATA/ACTION keys,
>   `IMAGE_STYLE_PRESETS` / `DEFAULT_IMAGE_STYLE`, `creatorRunKey`.
>
> **v2 — user-control redesign (see §13):** per-beat editable scripts, pick ONE format
> per topic, and per-beat image selection so only the chosen format's chosen beats are
> produced. Plus fixes found in live testing (host-API company-context import, artifact
> work-product registration, script workspace-file fallback, friendlier status labels).
>
> - Pending / follow-ups: extend `scripts/e2e-upstream-test.sh` to assert the new
>   page slot + creator action issue creation; apply the artifact-registration fix to the
>   legacy ✨ generate-content brief; release via the gated `pnpm run dist` (held until
>   requested).

## 1. Goal

A **one-stop YouTube Creator page**: the user ideates topic/outline concepts, turns
them into detailed scripts (in the 3 formats) using our YouTube skills — grounded in
our **insights DB (QMD)** and our **company context (ICP/problem/solution/offer)** —
and then produces the full package (images + final PDF) so they can record. The
existing ✨ AI button on the YouTube Trends page redirects here with that video's
context so the user completes the flow on this page.

## 2. Requirements (consolidated from the request thread)

1. New `youtube-creator` page + sidebar entry. One-stop **3-stage cockpit**:
   **Ideate → Script (3 formats) → Produce (images + PDF)**.
2. **Human-approval gates** between stages.
3. **QMD insights DB**: powers topic suggestions + per-topic supporting insights, and
   grounds the Stage-2 script brief.
4. **Company context** (ICP / Problem / Solution / Offer): injected into the script
   brief. Sourced in a way that respects plugin independence (see §6).
5. **Per-output review** for every output (topics, each of the 3 scripts, images/PDF):
   **markdown preview + inline edit (save back) + "redo with feedback"** (re-invokes
   the owning agent with the user's notes).
6. **Trends ✨ button → redirects** to this page with `videoId` context; user completes
   the flow here (button no longer creates the CMO issue directly).
7. **Outputs reuse the canonical workspace paths** (`youtube/{date}/recommended/{topic-slug}/…`
   — `script-outline*.md`, `assets/{format}/*.png`, Phase-6b PDFs) **and** are linked into
   the host platform's artifacts surface exactly as today (scripts → documents,
   images/PDFs → issue attachments). **No parallel storage.**
8. **Optional image-style selector** (Stage 3) with recommended presets, feeding the
   Graphics Creator brief / `generate-image`. Default = current behavior.

## 3. Reuse (do not reinvent)

Same agents: **CMO** (orchestrate), **Content Creator** (`youtube-gap-finder` +
`youtube-content-creator` → scripts), **Graphics Creator** (`generate-image` + Phase-6b
PDF). Same skills, same artifact surfaces (issue documents `script-standard/-hot-take/-contrarian`,
attachments for images/PDFs), same canonical workspace layout, same state patterns
(`ctx.state` project/company scoped). The new work is: the page UI, a handful of
stage-scoped worker actions/briefs, QMD + company-context wiring, per-output edit/revise
loops, image-style option, and the Trends redirect.

The "3 formats" = **standard / hot-take / contrarian** (already produced by
`youtube-gap-finder` + `youtube-content-creator`).

## 4. The 3 stages

### Stage 1 — Ideate (topics + QMD + company context)
- Free-form topic list editor (add / edit / reorder / remove draft topics). Markdown
  preview + edit per topic.
- **Suggest from insights**: `creator-suggest-topics` data handler runs `qmdQuery` over the
  company insight collection (`qmdCollectionNameForCompany`) → candidate topics/angles.
- Per topic, **supporting insights** pulled from QMD (`creator-topic-insights`) — carried
  into the Stage-2 brief.
- **Company Context panel** (ICP / Problem / Solution / Offer) — editable; see §6.
- Output: a curated topic set + per-topic insight refs + company context, saved to the
  `creator-run` record. Approve → Stage 2.

### Stage 2 — Script (3 formats, via our skills)
- "Generate scripts" → `creator-flesh-topics` action creates a **Content-Creator issue**
  whose brief runs `youtube-gap-finder` + `youtube-content-creator` for the curated
  topics, **seeded with the QMD insights + company context**, producing
  **standard / hot-take / contrarian** as issue documents (`script-standard/-hot-take/-contrarian`)
  AND the canonical `script-outline*.md` files in the workspace.
- Page polls the issue; renders all three inline (`MarkdownPreview`).
- **Per-script review:** edit-in-place (save → `creator-save-script` writes the issue doc +
  workspace file) and **redo-with-feedback** (`creator-revise-script` re-invokes Content
  Creator on that format with the user's notes). Approve → Stage 3.

### Stage 3 — Produce (images + PDF, optional style)
- **Optional image-style selector** (see §7). Then "Produce" → `creator-produce` creates a
  **Graphics-Creator issue**: `generate-image` (beat images + thumbnails per format) +
  Phase-6b `sharp`/`pdfkit` PDF, written to canonical `assets/{format}/` + topic-slug PDFs,
  uploaded as issue attachments.
- Page shows the image gallery + per-format PDF download links.
- **Per-image review:** redo-with-feedback (`creator-revise-images`, format + notes →
  re-invoke Graphics Creator); PDF rebuilds from images. Done.

## 5. QMD usage (the insights DB)

- `qmdQuery(collection, query, …)` (from `src/qmd.ts`) against
  `qmdCollectionNameForCompany(companyId)`.
- Stage 1: topic suggestions + per-topic supporting-insight retrieval (reuse / extend the
  existing `search-insights` semantics).
- Stage 2: retrieved insights are embedded into the script brief so scripts are grounded
  in the existing knowledge base, with source attribution.

## 6. Company context (ICP / Problem / Solution / Offer) — independence-safe

The ICP/problem/solution/offer originate in the **ai-cyber-value-creator** plugin
(`company-context.md`). Per the standing rule, **harper-cmo and ai-cyber-value-creator stay
independent — no cross-plugin state sharing** (sanctioned exchange is via workspace files).

Design:
- harper-cmo owns an **editable Company Context panel** (ICP / Problem / Solution / Offer)
  persisted in its **own** state (`creator-company-context`, project-scoped).
- **Best-effort import** button (`creator-import-company-context`): if a `company-context.md`
  is reachable in the workspace, parse ICP/Problem/Solution/Offer and pre-fill; else the user
  fills/pastes manually. No hard dependency on the other plugin.
- The context is injected into the Stage-2 brief so scripts speak to the ICP/problem/solution/offer.

## 7. Image style (optional, Stage 3)

`generate-image` supports a sketchnote-on-paper "beat visual" style (current default, warm
cream + pastel + hand-drawn, anchored to `youtube-baseline-reference.png`) and a saturated
"whiteboard" technical-diagram style. Add an **optional style selector** with recommended
presets that maps to a style directive (and baseline `--input` choice) injected into the
produce brief:

- **Sketchnote on paper** *(default, recommended for explainer/educational)* — current beat style.
- **Whiteboard diagram** — saturated markers; good for technical/architecture breakdowns.
- **Bold minimalist** — flat, high-contrast, few elements.
- **Photographic / cinematic** — realistic scenes.
- **Retro / comic** — playful, illustrated.
- (Thumbnails keep the bold high-contrast thumbnail style unless the user opts to match.)

Optional: if untouched, use the current default. Selection stored on the `creator-run`.

## 8. Trends ✨ redirect

Change `handleGenerate` on the Trends page: instead of calling `generate-content`, navigate
to `/{companyPrefix}/youtube-creator?videoId=<id>&source=trends`. The Creator page reads
`videoId` from `window.location.search` (plugin UI is trusted same-origin; no SDK route-param
hook exists — this is the clean path), pre-seeds Stage 1 with that video as a topic (title +
`analysis.md` + its QMD insights), and the user completes the flow.

## 9. New surface (constants)

- **PAGE_ROUTES.creator** = `youtube-creator`; **SLOT_IDS.creatorPage** = `yt-intel-creator-page`;
  **EXPORT_NAMES.creatorPage** = `YouTubeCreatorPage`.
- **DATA_KEYS:** `creator-run`, `creator-suggest-topics`, `creator-topic-insights`,
  `creator-company-context`.
- **ACTION_KEYS:** `creator-save-run`, `creator-set-company-context`,
  `creator-import-company-context`, `creator-flesh-topics`, `creator-revise-script`,
  `creator-save-script`, `creator-produce`, `creator-revise-images`.
- **STATE:** `creatorRunKey(runId)` (project-scoped run record), `creator-runs-index`.

`creator-run` record shape (project-scoped): `{ id, createdAt, status, source ('manual'|'trends'),
seedVideoId?, topics: [{ id, title, notes, insightRefs[] }], companyContext (snapshot),
imageStyle?, scriptIssueId?, produceIssueId?, stage ('ideate'|'script'|'produce'|'done'),
approvals: { ideate?, script? } }`.

## 10. UI building blocks

Reuse existing patterns from `src/ui/index.tsx`: `MarkdownPreview` (review), the editable-markdown
+ save pattern from `WorkspaceDeliverablesPage`, `useCompanyData`/`useCompanyAction`, the dark
inline-CSS palette, the ring spinner for in-flight issues, and the issue-status polling pattern
used by the Trends ✨ button.

## 11. Testing / release

- `pnpm typecheck` + `pnpm build` green.
- Extend the plugin **e2e** (`scripts/e2e-upstream-test.sh`) to cover the new page registration +
  the creator actions' issue creation.
- Release via the **gated** `pnpm run dist` flow — **held until explicitly requested**.

## 12. Open defaults (proceeding unless told otherwise)

- Trends ✨ button **replaces** direct-generate with the redirect (does not also create the issue).
- Company context is harper-cmo-owned + best-effort import (independence-safe), not a hard
  cross-plugin read.
- Image style defaults to the current sketchnote beat style; thumbnails stay bold.
- One `creator-run` per flow; the page lists recent runs to resume.

## 13. v2 — user-control redesign + live-test fixes (2026-06-29)

Driven by user feedback after the first working run ("I want more control").

### Stage 2 — Scripts: review · edit beats · pick one
- Still generate all 3 formats (text-only, cheap to compare).
- Per topic: **format tabs** (Standard / Hot take / Contrarian) each with a **"pick"**
  button — the user chooses the ONE format to produce.
- The active tab renders a **`BeatEditor`**: the script-outline.md is parsed into beats
  (`parseScriptBeats`), each beat an editable card (heading + body incl. spoken lines +
  Visual), with **move ↑/↓, remove, + Add beat, Save edits** (reassembled →
  `creator-save-script`), plus **redo-whole-script-with-feedback**.
- "Approve picks → configure images" requires a pick for every topic; sets each
  `topic.pickedFormat` and advances to `produce`. **No images generated yet.**

### Stage 3 — Produce: per-beat image control, picked format only
- **`ProduceConfig`** (before generating): per topic, lists the picked script's image
  beats with a **checkbox (include/skip)** + **editable Visual prompt** per beat, a
  **"3 thumbnails" toggle**, the **image-style** selector, and a live **total image
  count**. "Generate" builds a `CreatorProduceSpec` and calls `creator-produce` with it.
- **`ProduceResults`** (after): status + gallery + per-topic **redo-with-feedback**, and
  **"↺ Reconfigure & regenerate"** back to the config.
- Worker: `buildProduceBrief` now emits per-topic blocks for **only the picked format**
  and **only the included beats** (with the user's edited visual prompts), and instructs
  "do NOT generate other variants or unlisted beats." `creator-produce` accepts + persists
  `produceSpec` on the run; `CreatorTopic.pickedFormat` carries the choice.

### Data-model additions
- `CreatorTopic.pickedFormat?`, `CreatorRun.produceSpec?`
  (`{ topics: [{ topicId, format, beats: [{label, visual, include}], includeThumbnails }] }`).

### Fixes found in live testing
- **Company-context import** was looking only under harper-cmo's own workspace, but the
  ai-value-creator writes `company-context.md` into a *different project's* workspace on an
  unrelated filesystem root. Now `importCompanyContext` enumerates **all the company's
  project workspaces via the host API** (`ctx.projects.list` + `listWorkspaces`) and scans
  each — and the `creator-company-context` data handler **auto-imports + caches** on first
  load (no button click).
- **Artifacts:** produce only created issue *attachments*, so images didn't appear in
  the platform's **Artifacts list** (which is driven by *work products*). The produce +
  revise-images briefs now register each PDF + image as an **artifact work product** via
  an upload helper (PDFs primary, beat images secondary), with an API
  fallback. (Legacy ✨ generate-content brief still pending the same fix.)
- **Script display robustness:** the run handler falls back to reading the canonical
  `script-outline*.md` workspace file when the issue document isn't on the parent issue
  (the CMO often delegates publishing to a child whose `$PAPERCLIP_ISSUE_ID` differs).
- **Friendlier status labels:** `blocked` → "working (delegated to specialist)", etc.

### Backfill pattern (for an already-produced run)
Post a user comment on the produce issue with `reopen:true, resume:true` instructing the
agent to register the existing files as artifacts (no regeneration) — reopens + wakes the
assignee. Used to backfill HARA-3348.

## 14. v3 — one run = ONE video (2026-06-29)

Correction: v2 created a separate video (3 format scripts) **per topic**. The intended
model is **one run = one video**: the Content Creator **synthesizes ALL the run's topics
into a single cohesive video**, then writes the 3 format variants (standard / hot-take /
contrarian) of that one video.

### Data-model change
- `CreatorRun.videoSlug` (one workspace folder per run) + `CreatorRun.pickedFormat`
  (run-level, replaces per-topic `pickedFormat`).
- Script doc keys are now run-level: `script-standard` / `script-hot-take` /
  `script-contrarian` (not per-topic-slug). One folder: `youtube/<date>/recommended/<videoSlug>/`.
- `CreatorProduceSpec` collapses to a single video: `{ format, beats, includeThumbnails }`.
- `creator-save-script` / `creator-revise-script` / `creator-revise-images` take **format**
  only (no `topicId`). The run-data handler returns `scripts: [{format, body}]` (3) and
  `assets: [{path, kind}]` (one folder).

### UI change
- Stage 2 shows the **topics folded into one video** (read-only), then **3 format tabs**
  with one run-level **pick**; `BeatEditor` per active format.
- Stage 3 (`ProduceConfig`) configures the **one** picked video: per-beat include + visual
  + thumbnails + style → produces only that variant.

### Briefs
- `buildScriptBrief`: "Combine ALL topics into ONE video, 3 formats in ONE folder."
- `buildProduceBrief`: "ONE video, ONLY the picked variant + listed beats."

## 15. Scripts as artifacts (2026-06-29)

Per request: **final scripts are registered as artifact work products**, not only issue
documents — so they appear in the Artifacts view alongside the images.
- `buildScriptBrief` step (d): register the 3 `script-outline*.md` files as artifacts.
- `buildProduceBrief`: also register the **final picked** script as an artifact next to the
  images + PDF.
