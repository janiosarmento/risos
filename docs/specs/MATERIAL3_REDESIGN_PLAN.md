# Material 3 redesign — persistent task list

Tracks progress on adapting Risos's look to the Material 3 (Google blue
baseline) direction from the design handoff, while keeping every existing
feature. Read this file at the start of any session that resumes this work —
it is the source of truth for what's done and what's left, across sessions.

## Source material

`docs/design/material3-handoff/` — the design deliverable as received from
Claude Design (kept verbatim, including the original file names):

- `HANDOFF_README.md` — the designer's own handoff notes (renamed from
  `README.md` to avoid clashing with a docs index).
- `Risos Redesign (Material).dc.html` — screens 2a–2k, light and dark. The
  chosen direction.
- `Risos Design Handoff.dc.html` — the token/component spec sheet (color,
  type, shape, elevation).
- `Risos Redesign.dc.html` — the Nocturne exploration, kept for reference
  only; **not** the chosen direction.

These are design references (high-fidelity look/behavior), not production
code to copy — see `HANDOFF_README.md` for the designer's own framing.

## Decisions made so far

- **Direction**: Material 3, Google-blue baseline (not Material You dynamic
  color). Nocturne was considered and dropped.
- **Typeface**: the handoff calls for "Google Sans" on headings — that font
  is proprietary to Google and not available to self-host, so this app uses
  **Roboto everywhere** (headings and body) instead, per the standard
  substitution used by non-Google Material 3 implementations. Decided in
  session, 2026-09-12.
- **No new framework**: this stays Tailwind (CDN) + Alpine.js, zero-build.
  The redesign is a token/class-level skin on top of the existing markup —
  no interaction is being reimplemented, per the handoff's own instruction.
- **Fonts stay self-hosted** (`htdocs/static/fonts/`), matching the existing
  Literata setup — no Google Fonts CDN requests at runtime.

## Gaps found in the handoff (read before touching Settings)

The handoff's screens cover the post list, post detail, curation, mobile,
suggested/tag-profile, OPML, and empty/error states well, but Settings is
represented by a single screen (2f) showing a small slice of one tab. The
real `settings.js` has far more surface area that has no matching mockup and
must be extended using the same M3 token rules rather than invented fresh:

- Categories/Feeds CRUD, incl. drag-and-drop of a feed between categories.
- Topics: full CRUD + rename, tag↔topic drag-and-drop (plain = move,
  Alt = copy), AI topic suggestions (suggest/accept one/accept all), AI tag
  suggestions per topic, add-tag-filter-to-topic.
- Two separate AI provider configs (primary + background job), each with its
  own base URL / Jano secret name / model — the mockup only shows one.
- System/user prompt editing with reset-to-defaults.
- Tag maintenance: rare-tag preview/purge, tag-merge suggestions, ignored
  tags list.
- Mímir export's "unstar all" action (only plain export is in the mockup).
- ~15 numeric/toggle preferences (feed update interval, max post age, max
  unread days, toast timeout, related-posts limit, idle refresh, suggestion
  sensitivity, profile min tag frequency, min summary length for suggestion,
  tags per post, blocked terms, feed reverse order).
- Circuit breaker reset (covered), clear-models-cache, delete-unread-
  summaries, system status panel.

Post detail's "Assistant" modal (related-posts search/filter/select,
consolidated summary, mark-processed-read, copy, export-as-markdown) and the
list's keyboard shortcuts / batch-select toolbar are also real features not
shown in the mockup.

**Non-negotiable security rule from the handoff**: never add a plaintext
API-key field or password input to Settings. The only AI-credential field is
the Jano secret name (`jano_secret_name` / `background_jano_secret_name`),
validated server-side against an allowlist
(`backend/app/routes/preferences.py::_validate_jano_secret`); the UI only
shows a found/not-found indicator, never a masked value.

## Adding a new icon (steps 4+ will need this repeatedly)

1. Re-fetch the subset, listing **every** glyph the app now uses (not just
   the new one) — see the `curl` invocation in git history (search commits
   for "icon_names") for the exact URL shape.
2. Overwrite `htdocs/static/fonts/material-symbols-subset.woff2`.
3. **Bump the `?v=N` on that font's `url()` in `app.css`** (and update the
   glyph list in the comment above it) — nginx serves `/static/fonts/` with
   `expires 7d`, the filename never changes, and `html_assembler`'s
   `{{APP_VERSION}}` substitution doesn't reach into `app.css`, so without
   this a browser (or the Cloudflare edge in front of prod) can silently
   go on serving the old font for up to a week after deploying, even
   though the page itself updated. Missing this step is exactly what made
   `task_alt`/`search_off` render as literal text after step 3 first
   shipped — caught by the user, fixed same session.
4. Bump `APP_VERSION` as usual, assemble, commit, deploy.

## How to work through this list

One step at a time. Each step is small enough to view running (`/run`) and
course-correct before moving to the next; each is its own commit. Mark a
step done (`[x]`) with the commit hash once it's live. If a step turns out
too big once you're in it, split it further here rather than doing several
things in one commit.

## Steps

### Foundation
- [x] **1. Typography + M3 CSS tokens.** Self-host Roboto (`htdocs/static/
  fonts/roboto-latin-variable.woff2`), set it as the Tailwind default sans,
  and add the full M3 color/shadow token set as `--md-*` CSS custom
  properties (light on `:root`, dark on `.dark`) in `app.css` — not yet
  consumed anywhere, later steps apply them. Visible effect: app-wide
  typeface change; no color/layout change yet.
- [x] **2. Icons.** Swapped the hand-drawn SVG sprite (`#icon-*` in
  `index.template.html`, plus a few one-off inline SVGs found in Settings >
  Status) for Material Symbols (`.msym` spans), self-hosted as a subset font
  (`htdocs/static/fonts/material-symbols-subset.woff2`). `icon-github`
  stayed an SVG (brand logos aren't in Material Symbols). Commit `198d9a1`.

### Screens with a 1:1 mockup
- [x] **3. Empty states** (2k, 3 of the 4) — post list now distinguishes
  no-feeds-at-all (with an "add feed" button into Settings' Feeds
  accordion), active-search-with-no-matches, an actually-unread-only
  "caught up" state, and a named-filter-is-empty state (says "Suggested",
  "Starred", the feed/category/topic/tag name, etc. instead of wrongly
  claiming "no unread posts"), each with a `.msym` icon and `--md-*` token
  colors — first real consumption of the step 1 tokens. New locale keys in
  both pt-BR.json and en-US.json (`posts.noSearchResults(Desc)`,
  `posts.noPostsGeneric`, `posts.noPostsInContext`, `feeds.noFeedsDesc`,
  `feeds.addFeed`). Commits `7f31916`, `dbe93a8`, `7ad0dde` (two follow-up
  fixes: wrong context wording, and a font-cache-busting bug — see "Adding
  a new icon" above — both caught by the user testing live).
  **Deliberately skipped**: the mockup's 4th state, "secret not found" —
  there's no found/not-found indicator in the real app yet to key it off
  of (that's built in step 12, the AI settings tab); adding one now would
  be inventing behavior ahead of its step. Revisit then.
- [x] **4. AI curation screen** (2e) — the real UI isn't a separate screen
  like the mockup, it's a stats bar + per-post badges inline in the post
  list (curation is run on the currently starred/filtered posts, not a
  dedicated view) — restyled in place rather than forcing a new layout.
  essential = solid primary (like the suggestion-score badge), redundant =
  error container (red = "skip this" here, consistent with
  risos-visual-cohesion-pass's color discipline), situational = secondary
  container, each with a `.msym` icon instead of a ★/✗/? glyph. Also fixed
  a pre-existing i18n bug found while touching this: the essential/
  redundant/situational badge labels were hardcoded English literals even
  under the pt-BR locale — added proper `curation.essential/redundant/
  situational/unclassified/postsAnalyzed` keys to both locale files.
- [ ] **5. Sidebar nav** (Unread/Starred/Suggested/All, Topics, Categories) —
  24px pill items, container-tone accents (2a/2b).
- [ ] **6. Post list** (cards, tag chips, score badge, unread dot) (2a/2b).
  This is also where `.font-reading` (Literata) on post titles gets
  reconsidered against the Roboto-everywhere decision above.
- [ ] **7. Post detail / reading pane** — AI summary as a full
  primary-container panel + original content side (2c/2d). Chrome only
  (buttons, panel), not the Assistant modal's behavior.
- [ ] **8. Buttons/controls sweep** — catch anything left in the old style
  outside the screens already redone (filled/outlined/FAB/switch/chip).
- [ ] **9. Mobile layout** (2g) — bottom nav + narrow list/detail.
- [ ] **10. Suggested + tag profile** (2h/2i).

### Settings — no full mockup, extend the tokens per screen
- [ ] **11. Settings shell** — left nav only (2f's aside).
- [ ] **12. AI tab** — mockup's fields (Jano secret, model, circuit breaker,
  toggles) plus the gaps: background-job config, prompts, curation engine.
- [ ] **13. Categories/Feeds tab** — incl. feed↔category drag-and-drop.
- [ ] **14. Topics tab** — incl. tag↔topic drag-and-drop, AI topic/tag
  suggestions.
- [ ] **15. General tab** — the ~15 numeric/toggle preferences.
- [ ] **16. Import/Export tab** (2j) — OPML + Mímir, incl. "unstar all".
- [ ] **17. Status tab.**

### Cross-cutting, last
- [ ] **18. Batch-select toolbar** + ZIP export.
- [ ] **19. Assistant modal** (related posts).
- [ ] **20. Keyboard-shortcut affordances**, if any visual indicator turns
  out to be needed (probably not).

## Parked issues (found while redesigning, not part of the redesign itself)

- **AI curation appears broken in prod** (found 2026-09-12, testing step 4).
  Not investigated — user suspects free-tier OpenRouter model capacity, not
  a code bug, and asked to park it. Step 4 only touched the curation UI's
  CSS classes/icons, not `curatePosts()` or the `/posts/curate` endpoint.

## Session log

- 2026-09-12 — Retrieved the handoff from the "Risos folder shared" Claude
  Design project (via a downloaded zip, since it's a different project type
  than the design-system projects DesignSync reads). Copied it into the repo.
  Decided the Google Sans → Roboto substitution. Completed step 1, deployed.
  Also found and fixed a pre-existing server-side permission issue blocking
  deploys: `docs/specs/` and `docs/history/` on fuqu were owned by
  `root:root` instead of `www-data:www-data` (the checkout owner) — fixed
  with `chown -R`.
- 2026-09-12 — Completed step 2 (icons → Material Symbols).
