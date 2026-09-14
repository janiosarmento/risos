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

## Mobile flex-row gotcha (watch for this in every remaining step)

Found twice already (step 11's nav rail, step 13's Add Feed row): a
`flex` row with one flexible item (`flex-1 min-w-0` — an input, usually)
next to one or more items that don't shrink (a `<select>` sized to its
longest option, a button with `min-w-[Npx]`/`whitespace-nowrap`). On a
phone the non-shrinking siblings claim their full width first and the
lone flexible item gets squeezed to a sliver — technically not
overflowing anything, so it's easy to miss without testing at phone
width. Checked every other `<input>`/`<select>`/button row in the
current template (2026-09-13) and found no other live instance, but
steps 14+ still touch several forms with the same shape (topic rename,
tag-merge canonical rename, tag-suggestion search) — when restyling
each one, either give the row `flex flex-col sm:flex-row` (stack on
mobile, row from `sm:` up — the step 13 fix) or drop the fixed
min-width/no-shrink constraint so the flexible item can actually win
space back.

## Dialog shell contract (Settings, Assistant, confirm)

Every full dialog uses the same shell: `--md-surface-container-high` fill,
28px radius, `shadow-xl`, a `bg-black/50 backdrop-blur-sm` scrim, and —
the two parts that are easy to drop — **`min-w-0`** and a **fixed height
(`h-[90vh] md:h-[80vh]`), never `max-h-*`**. Both come from live bugs the
user reported on step 11: `max-h` makes the dialog resize as its content
changes, so the whole thing jumps under the pointer; without `min-w-0` a
child's intrinsic width can push the dialog wider than a phone screen.
Inside the shell, header and any toolbar rows are `flex-none` and only the
body gets `flex-1 min-h-0 overflow-y-auto`.

Caught again on 2026-09-14: the Assistant modal (step 19) said its shell
"matches the Settings dialog", but it had been written against the
pre-fix version and carried `max-h-[90vh] md:max-h-[85vh]`, no `min-w-0`,
`bg-black/60` and `shadow-2xl`. Restyling a dialog means re-checking this
list, not copying whatever the neighbouring dialog looked like at the time.

Same pass also brought the Assistant's interior in line, at the user's
request: `max-w-4xl` so both full dialogs share one footprint, `text-lg`
title and 24px close icon like every other dialog header, list rows on
the Settings row treatment (`bg-surface-container rounded-2xl p-3`,
previously `rounded-lg p-2`), footer buttons on the standard `px-4 py-2`
pill (the primary one lost a one-off `active:scale-[0.98]`), and the
related-posts list no longer scrolls inside the body's scroll — one
scroller, with the action bar `sticky bottom-0` so it stays reachable.

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
- [x] **5. Sidebar nav** (2a/2b) — Unread/Suggested filter buttons, the
  Topics folder + topic items, and the Categories/Feeds tree all now use
  24px-radius pills (`rounded-[24px]`) and `--md-*` tokens: plain active
  state = secondary-container, Suggested's active state = primary-container
  (the handoff's "destaque IA" component rule) with its icon/count always
  tinted primary even when inactive. Sidebar background, all its internal
  borders, and unread-count badges (now plain tinted text instead of solid
  color chips, matching the mockup) also converted. Left untouched (out of
  "nav" scope, for a later pass): the font-scale/mark-read/refresh toolbar
  buttons and the Top Tags chip row — those are toolbar controls and chips,
  not nav list items. The header's separate postFilter row
  (Unread/All/Starred buttons above the post list) is also untouched —
  that's part of the main content header, not the sidebar.
- [x] **6. Post list** (2a/2b) — card radius 16px, keyboard-focus row =
  secondary-container, batch-checkbox-selected row = primary-container,
  unread dot / checkbox / suggestion-score badge (now a solid primary pill,
  was a light purple tag) all on `--md-*` tokens. Tag chips: 8px radius
  (not a pill — that's the handoff's own component rule, pills are for
  filter chips/badges only), filled instead of outlined (active =
  primary, topic tag = secondary-container, plain = surface-container-
  highest). **Title dropped `.font-reading` (Literata) for plain Roboto
  at medium weight**, per the Roboto-everywhere decision from step 1 —
  article/summary body text (`.post-content`/`.summary-content`) still
  uses Literata, that's step 7's concern. Star/like/keep-unread icon
  colors (yellow/teal/blue) deliberately left alone — established
  per-action color coding from risos-visual-cohesion-pass, not part of
  the M3 neutral+primary/secondary/tertiary/error palette.
- [x] **7. Post detail / reading pane** (2c/2d) — kept the real app's
  vertical stack (summary above, original below), not the mockup's
  side-by-side grid: this is an inline accordion row in the post list, not
  a dedicated full-screen view, and a layout restructure is out of scope
  for a skin pass. AI summary panel is now a single flat
  `--md-primary-container` fill (header+body, no internal divider) per the
  handoff's "one full-tonal-fill block" rule; its small buttons use a
  black/white state-layer overlay (`bg-black/5 dark:bg-white/10`, etc.)
  since the `--md-*` tokens are plain hex and don't support Tailwind's
  `/opacity` modifier. Assistant button is now the one filled-primary CTA
  in the action row (was a soft purple chip); original-link/export are
  outlined pills. Skip-summary's active state keeps error-container even
  inside the primary-container panel, for contrast.
  **Also finished the Roboto-everywhere decision from step 1**: dropped
  Literata from `.post-content`/`.summary-content` (the article and AI
  summary body text) — the option the user picked back then ("Roboto para
  tudo") covered body text too, not just titles. Removed `.font-reading`,
  both Literata `@font-face` rules, and the two vendored woff2 files —
  nothing in the app references Literata anymore.
- [x] **8. Buttons/controls sweep** — converted everything generic that
  isn't part of a dedicated later step: sidebar toolbar (font-scale,
  mark-as-read dropdown, refresh, Top Tags chip row), the main header
  toolbar (search field now a pill, select-mode + Unread/All/Starred
  toggle buttons, tag/topic filter indicator chips, the add-to-topic
  dropdown), the confirm modal (28px radius per the handoff's shape scale
  for dialogs) and the login screen. Body background/text also switched
  to `--md-*`.
  **Deliberately left alone**: the toast notification's success/error/info
  colors (green/red/blue) — those are semantic status colors with no
  equivalent role in M3's 5-token palette (primary/secondary/tertiary/
  error/neutral), same reasoning as leaving star/like/keep-unread colors
  alone in step 6. Settings modal (steps 11–17), Assistant modal (step 19),
  and the batch-select toolbar (step 18) are untouched — they have their
  own steps.
  **Follow-up same session**: user caught the header's Starred button
  still building its label as `"Favoritos (327)"` (count glued into the
  text with parens) instead of a separate trailing number like every other
  count since step 5 — fixed. Two more instances of that same `+ ' (' +
  n + ')'` pattern found while checking, both inside the still-untouched
  Settings modal (Topics tab, tag-merge suggestions) — left for steps
  14/15, apply the same fix there.
- [x] **9. Mobile layout** (2g) — **scope decided with the user**: the
  mockup's fixed bottom tab bar doesn't exist in the real app (mobile nav
  today is hamburger → the same sidebar as an overlay) and would be new
  functionality, not a reskin — out of character for every step so far.
  User chose to reskin what exists rather than build it. Turned out there
  was nothing left to do: Risos is one responsive codebase, not separate
  mobile/desktop templates, so the `md:hidden`/`hidden md:inline` mobile
  variants of the sidebar, header toolbar, and post-list cards were
  already converted along with their desktop counterparts in steps 5–8.
  Checked for leftover old-style classes gated on a mobile breakpoint and
  found none; the only `@media (max-width: 768px)` block in `app.css` is
  purely behavioral (scroll/tap-highlight/safe-area), no color to convert.
- [x] **10. Suggested + tag profile** (2h/2i) — same conclusion as step 9:
  nothing left. The mockup's "Seu perfil" panel (clickable learned tags,
  sensitivity/min-tag-weight sliders, ignored-tags list) has no standalone
  equivalent in the real app — that content lives inside the Settings
  modal (General/Data tab), deferred to steps 12/15. The Suggested list
  itself is just the post list under `filter === 'suggested'`, already
  covered by steps 5 (sidebar button) and 6 (cards). The Top Tags chip row
  (step 8) is the closest real equivalent to a clickable tag-profile list
  outside Settings, and is already done.

### Settings — no full mockup, extend the tokens per screen
- [x] **11. Settings shell** — replaced the horizontal top-tab strip with a
  left nav rail matching 2f's `aside` (folder/rss_feed/import_export/
  auto_awesome/label/tune/monitor_heart icons, in the mockup's own order;
  active state = secondary-container, same rule as a plain sidebar filter
  in step 5 — this isn't a "destaque IA" item so no primary tint even for
  the AI tab). No separate mobile markup: the same `<nav>` is a horizontal
  scrollable pill row below `md` and a vertical rail at `md:` and up, same
  "one responsive codebase" approach as step 9. Dialog itself now matches
  the confirm modal's shape/fill (28px radius, `--md-surface-container-
  high`, step 8) instead of the old `bg-white`/`rounded-lg`; widened
  `max-w-2xl` → `max-w-4xl` so the rail has room without starving the
  content pane. Close button switched from a literal `&times;` to a
  `.msym close` icon. Footer's Close button restyled to the same outlined
  pill as the confirm modal's Cancel. Re-subsetted the Material Symbols
  font (v3 → v4) to add `import_export`, `monitor_heart`, `tune` for the
  new rail icons — see "Adding a new icon" above.
  **Deliberately untouched**: every tab's own content (categories/feeds
  lists, AI form, topics, general toggles, OPML, status) — still on the
  old gray-100/blue-600 palette, that's steps 12–17, one tab at a time.
  **Follow-up same day (mobile bugs, user-caught)**: two issues on the
  phone-width nav rail —
  1. The nav `<nav>` row is a flex item with no `min-w-0`, so its default
     `min-width: auto` (its unwrapped, all-7-pills content width) beat
     `overflow-x-auto`: instead of scrolling within itself, it forced the
     whole dialog wider than the screen, pushing later pills off-screen.
     Added `min-w-0` to the `<nav>` (and defensively to the dialog root).
  2. The dialog used `max-h-*`, so it shrank to fit each tab's content —
     switching from a short tab (Categories) to a tall one (AI, Feeds)
     visibly resized/shifted the whole modal. Changed `max-h-[90vh] md:
     max-h-[80vh]` to a fixed `h-[90vh] md:h-[80vh]` so the shell is
     always full-size regardless of which tab is open; only the content
     pane's own `overflow-y-auto` should ever scroll now, never the shell.
- [x] **12. AI tab** — every field (on-demand: Jano secret, base URL, model,
  timeout, max tokens, temperature, presence penalty, summary language,
  curation engine, tags-per-post, related-posts limit; background:
  secret, base URL, model; prompts: system/user + reset-to-defaults)
  moved from `gray-100`/`blue-600` to `--md-*` tokens — inputs/selects/
  textareas as `bg-surface` + `border-outline` + `rounded-lg`, dividers
  to `outline-variant`, refresh icon buttons to the circular outlined
  style from step 6/8, Reset Defaults to the confirm-modal's outlined
  pill, native radios/ranges recolored via Tailwind's `accent-*` instead
  of custom-drawn controls (no interaction reimplemented, per the
  handoff's own instruction). Circuit breaker isn't here — it lives in
  the Status tab (step 17), the mockup's 2f screen bundles it with AI
  but the real app doesn't.
  **Closed a real gap, not just a reskin**: step 3 deliberately skipped
  the mockup's "secret not found" empty state because nothing in the
  app surfaced found/not-found at the time; that plumbing exists now.
  Added a `check_circle`/`error` indicator next to both Jano secret
  fields — `janoSecretValid`/`backgroundJanoSecretValid` in the prefs
  store, populated for free by the *existing* `/admin/validate-secret`
  endpoint (already called on every secret-name change to refresh the
  model list; only added a `refreshSecretStatus()` call at app init so
  the icon is already right before Settings is even opened). No backend
  change — the endpoint already returns only `{valid, masked_key}`,
  never the key, so the non-negotiable "no plaintext key field" rule
  from the handoff wasn't at stake. Re-subsetted the Material Symbols
  font (v4 → v5) to add `check_circle`, `error`.
- [x] **13. Categories/Feeds tab** — add-form input/select/button, list-row
  card (`bg-surface-container rounded-2xl`, was `bg-gray-100 rounded`),
  and edit-mode fields all moved to `--md-*` tokens, matching step 12's
  input treatment. Edit/Delete moved from plain text links to icon-only
  buttons (`.msym edit`/`delete`, both already in the font subset) with
  a `data-tip`/`aria-label`, the circular-icon-button style from steps
  6/8 — same click handlers, only the visual representation changed.
  Save uses the filled-primary pill, Cancel the outlined pill (confirm
  modal's own pair). Feed error `!` recolored to `--md-error`; the
  starred-feed ★ and its amber color are untouched, same "established
  per-action color, not part of the M3 palette" rule as steps 6/8.
  **The plan's own "incl. feed↔category drag-and-drop" note turned out
  to not apply here** — that drag-and-drop (`onFeedDragStart`) lives in
  the main sidebar's feed tree, already restyled in step 5, not in this
  Settings tab; same kind of stale-note-vs-reality gap as steps 9/10.
  **Follow-up same day (mobile bug, user-caught)**: the Add Feed row
  (URL input + category select + Add button, all `flex gap-2` in one
  line) had the same shape as the nav-rail bug from step 11 — the
  select's intrinsic width and the button's `min-w-[120px]` don't
  shrink, so the URL input (the only item with `min-w-0`) was squeezed
  down to a couple of pixels on a phone. Changed the row to
  `flex flex-col sm:flex-row` — each control is full-width, stacked, on
  narrow screens, and the original single-row layout returns at `sm:`
  and up.
- [x] **14. Topics tab** — every element (AI-suggest header button,
  new-topic form, topic-card list, tag chips, inline tag-search
  autocomplete) moved to `--md-*` tokens. AI suggestion review panel
  is now one full-tonal `primary-container` fill, same "one block, no
  internal divider" rule as the post-detail summary panel (step 7);
  Accept is a filled-primary pill, Accept All an inverted
  on-primary-container pill, Dismiss a translucent black/white overlay
  (no plain "on-primary-container-container" token exists, so it uses
  the same `bg-black/10 dark:bg-white/10` state-layer trick as step 7's
  panel buttons). Individual suggestion cards inside it are a plain
  `--md-surface` card so they read as a level above the tinted panel.
  Topic-card drag-over state recolored move = primary (blue, was blue),
  copy = **secondary**, not tertiary — the handoff only ever pairs
  `--md-tertiary-container` with an FAB background, never defines an
  `on-tertiary(-container)` text token, so tertiary had no safe text
  pairing to use here; secondary already had both container + on-color.
  Rename/delete on a topic card moved from a plain `edit`/`&times;`
  text glyph to icon buttons (`.msym edit`/`delete`), matching steps
  6/8/13's row-action convention — same click handlers. Tag-chip and
  suggestion-chip removal glyphs (small inline `&times;` inside a chip)
  were deliberately left as literal glyphs, just recolored
  (`hover:text-[var(--md-error)]`) — matching the established
  convention for inline chip-remove buttons elsewhere in the app (the
  active-filter chips from step 8), which the code already keeps as
  plain glyphs rather than icon spans.
  **Checked against the mobile flex-row gotcha** (noted after step 13):
  every input in a `flex` row here (new-topic name, inline topic
  rename, tag-search box) got `min-w-0`, and none of their sibling
  buttons carry a fixed min-width or `whitespace-nowrap`, so none of
  them can reproduce the step 11/13 squeeze — confirmed by inspection,
  not just applying the fix by rote.
  **The plan's own "incl. tag↔topic drag-and-drop, AI topic/tag
  suggestions" note was already fully implemented** (drag-and-drop
  between topic cards, `suggestTopics()`/`suggestTagsForTopic()`) —
  same kind of stale-note-vs-reality gap as steps 9/10/13; this step
  only reskinned it, no interaction changed.
- [x] **15. General tab** — all 4 accordions (Appearance, Data, Interface,
  Tag Consolidation) and the version/cache footer moved to `--md-*`
  tokens: accordion shells `rounded-2xl` + `surface-container` header
  (was `rounded-lg`/`gray-50`), every number/text input and select
  matching step 12's treatment, checkbox and merge-group checkboxes via
  `accent-[var(--md-primary)]`. Theme picker (Light/Dark/System) is now
  a filled-primary pill for the active choice, outlined for the rest —
  same segmented-button shape as the curation-engine radios, just
  buttons instead of native radios since that's what the existing markup
  already used. Purge-rare-tags sample chips use `error-container` (
  "this will be deleted", the established error-role convention);
  its Purge button is the filled-error pill (step 8's precedent); the
  merge Apply/Analyze buttons are filled-primary (no green "success"
  color — same no-semantic-status-color-outside-the-5-roles rule as
  every other step); selected merge-group card = `primary-container`,
  matching the batch-select row convention from step 6. Select All/
  None and the footer's Reset Circuit Breaker/Clear Cache became plain
  `text-primary hover:underline` text buttons (they were never meant to
  be prominent CTAs).
  **Also fixed the two count-in-label loose ends flagged back in step
  8** (`"tag (N)"` built as one glued string instead of a separate
  trailing number): the purge-sample chips here, and — found still
  unfixed while re-checking — the Topics tab's "AI Suggestions (N)"
  header from step 14, missed there because that step's focus was the
  visual pass, not this specific historical follow-up. Both now split
  label and count into two elements, matching the Starred-button fix.
  **Checked against the mobile flex-row gotcha**: the purge-threshold
  and AI-merge-controls rows already had `flex-wrap`, so no input here
  can reproduce the steps 11/13 squeeze.
- [x] **16. Import/Export tab** (2j) — headings/descriptions to
  `--md-*`, section dividers to `outline-variant`. Choose File is the
  filled-primary pill (the tab's one primary action); Download OPML and
  Export Mímir are outlined pills (secondary actions, same as Preview/
  Reset Defaults elsewhere); Unstar All is the filled-error pill (same
  destructive-action convention as step 15's Purge button). The OPML
  import result message (success/has-errors) is deliberately left on
  its existing `yellow-400`/`green-400` — same "no M3 role fits a
  transient status color" reasoning that left the toast colors alone
  in step 8. Both button rows got `flex-wrap` (checked against the
  mobile flex-row gotcha; neither had a squeeze risk since no sibling
  carries a fixed min-width, but wrapping is free insurance for long
  translated button labels).
- [x] **17. Status tab.** The LLM-queue headline card is now one
  full-tonal `primary-container` block (dropped its decorative corner
  gradient — no `--md-*` equivalent for it, and it wasn't in the
  mockup, just leftover flourish). The 6-tile metrics grid lost its
  per-tile rainbow badges (blue/purple/emerald/orange — no home in the
  app's 5-role palette and never an established per-item color like
  star's amber, which stayed): all now plain `surface-container-
  highest` icon chips on `surface-container` tiles, **except Starred**,
  kept amber — that one IS an established app-wide color (steps 6/8/14).
  Circuit-breaker/scheduler status dots and their text are deliberately
  left on plain green/red — a live on/off indicator, not a button or
  badge, same "no M3 role for a transient status color" reasoning as
  the toast and OPML-result colors (steps 8/16). The health-warning box
  **did** move to `error-container`, unlike those — it's a persistent
  banner, not a transient message, so the error role actually fits.
  Reset/Delete-summaries/Refresh buttons are outlined pills (primary
  for neutral actions, error for the destructive one), matching every
  other settings tab. Translated several Portuguese-only code comments
  found while rewriting this block (`Destaque Principal`, `Grid de
  Métricas Gerais`, `Sistema e IA`, `Ação Manual de Atualização das
  Métricas`, etc.) to English, per the standing "all code in English"
  rule — pre-existing, unrelated to the redesign itself, but this step
  touched every line they were on anyway.
  **All of Settings (steps 11–17) is now done.**

### Cross-cutting, last
- [x] **18. Batch-select toolbar** + ZIP export. The ZIP-export button
  (`exportSelection()`, "Download selected") and the rest of the
  curation-results action row were already done — that whole panel was
  step 4's scope, not noticed as covering this until now. What was
  still on the old palette was specifically the **selection toolbar**
  itself (Select All / Clear / "N selected" / Mark as Read, shown while
  `selectMode` is on): Select All and Clear are now plain text buttons
  (`text-primary hover:underline` / `on-surface-variant`), the count
  text is `on-surface-variant`, and Mark as Read — previously
  `bg-green-600`, this app's one remaining green button — is now the
  filled-primary pill, same no-green-outside-the-5-roles rule as every
  other step. The per-card selection checkbox (step 6) and the whole
  curation panel (step 4) were already correct, confirmed by reading
  rather than assumed. Also translated two Portuguese-only comments
  found in the same post-card block while touching it (`Checkbox para
  seleção`, `Indicador de não lido`) — pre-existing, unrelated to this
  step, fixed in passing since already looking at those lines.
- [x] **19. Assistant modal** (related posts) — the last untouched
  screen, and it had its own pre-redesign purple identity (border,
  gradient header, purple checkboxes/buttons throughout), never
  converted to `--md-*`. Dropped that separate identity in favor of the
  one consistent AI color already used everywhere else: `primary`/
  `primary-container`, same mapping as curation (step 4), the AI
  settings tab (step 12), topic suggestions (step 14), and the status
  tab's LLM queue card (step 17) — a modal-only purple would have
  contradicted all four. Dialog shell now matches the Settings/confirm
  modal shape (28px radius, `surface-container-high`, steps 8/11).
  Header + description + "analyzing post" title merged into one
  full-tonal `primary-container` block with no internal dividers, same
  rule as the post-detail summary panel (step 7) and this step's own
  consolidated-summary panel below; close button is now a `.msym close`
  icon instead of a literal `&times;`. Filter checkboxes lost their
  per-checkbox purple/amber distinction (`accent-[var(--md-primary)]`
  for all four — amber is reserved for star/favorite app-wide, not
  available here). The consolidated-summary panel and its Copy button
  reuse the post-detail summary panel's exact treatment verbatim
  (`text-on-primary-container` body, `bg-black/5 dark:bg-white/10`
  state-layer button — `--md-*` tokens don't support Tailwind's
  `/opacity` modifier).
  **All 20 steps of the Material 3 redesign are now done.**
- [x] **20. Keyboard-shortcut affordances** — turned out there WAS one
  left: the post list's desktop-only keyboard hints footer (J/K
  navigate, [/] feeds, Enter open, Space toggle in select mode) was
  still `bg-gray-50`/`border-gray-200`/`text-gray-400`. Recolored to
  `--md-*`, and went a step further than a plain recolor — each key is
  now a small `<kbd>` chip (`surface-container-highest`, the same
  neutral tinted-chip treatment used for plain tag/topic chips) instead
  of bare text, a clearer "this is a key you press" affordance, which
  is what this step was actually asking for. The inline single-letter
  hints baked into buttons elsewhere (`(A)`/`(N)`/`(X)`/`(M)` — add
  feed, mark-read dropdown, select mode, mark-selected-as-read) needed
  no change: they already inherit `--md-*` color from their
  already-restyled parent buttons via `opacity-60`. No dedicated
  shortcuts-help modal exists in the app — `shortcuts.*` in the locale
  files has exactly these 4 keys, all covered by the footer above.
  **19 of the 20 redesign steps are now done** — only step 19 (Assistant
  modal) remains, skipped for now by request: the user asked for step
  20 before step 19.

## Parked issues (found while redesigning, not part of the redesign itself)

- **AI curation appears broken in prod** (found 2026-09-12, testing step 4).
  **Investigated and fixed 2026-09-13** — see own memory entry
  `risos-curation-not-working` for the full writeup. Short version: nginx
  only ever logged 3 curate attempts, all inside a ~5-minute window that
  overlapped two mid-session redeploys; root causes were (1) gunicorn's
  `--timeout` (120s) shorter than the AI timeout's max (600s) and nginx's
  `proxy_read_timeout`, so a slow-but-fine AI call got its worker killed
  mid-request (502) — bumped both to 630s in `install.sh` and live, and
  (2) an unrelated, much older bug where `alembic/env.py`'s `fileConfig()`
  silently disabled the whole app's `.info()` logging after every startup
  since the very first boot in April, which is why even the one
  genuinely-successful curate request left no server-side trace to
  diagnose from. Fixed in `backend/app/main.py` + `backend/alembic/
  env.py`. Curation itself hasn't been re-tried live since the fix.

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
- 2026-09-12 — **Steps 1–10 all done and deployed this session**, one
  commit + deploy per step, each checked live by the user before the next
  started. Stopping here for the day (user is tired) — **steps 11–17
  (Settings) are next**, deliberately not started: that's the big,
  no-full-mockup part of this plan, better tackled fresh. Nothing is
  half-done or uncommitted; working tree is clean, `main` is at `6dfae35`,
  prod is running it. A session picking this up tomorrow needs nothing
  from this conversation — everything decided is written down above
  (Decisions made so far, Gaps found in the handoff, Parked issues,
  the per-step notes) or in git history (commit messages explain the
  *why* of every visual choice, not just the diff). Read this whole file
  top to bottom before touching step 11; skim `git log` since `0c212ea`
  (the first redesign commit) if something here is unclear.
  Two loose ends to fold into their steps when reached, already noted
  inline above: the two remaining `+ ' (' + n + ')'` count-in-label
  instances (Settings' Topics tab, tag-merge suggestions — steps 14/15),
  and the parked AI-curation bug (unrelated to the redesign, own memory
  entry `risos-curation-not-working`).
- 2026-09-13 — Completed step 11 (Settings shell → left nav rail). No
  sandbox browser available in this session to screenshot it live (no
  project `/run` skill, no Playwright/chromium-cli installed) — this one
  needs the user's own local check before step 12 starts, breaking the
  "viewed running before moving on" habit from steps 1–10 just this once.
- 2026-09-13 — **Steps 12–20 all done and deployed this session**, one
  commit + deploy per step (deploy automated via `ssh fuqu` this
  session, per the user's own request partway through — no longer a
  manual step for the user). User caught and reported two live mobile
  bugs on step 11 same-day (nav-rail overflow, dialog resizing on tab
  switch — both fixed same session, see step 11's own notes) and one
  more on step 13 (Add Feed row squeeze) — all three share one root
  cause (a flex-1/min-w-0 item losing a width fight to non-shrinking
  siblings) now written up as its own "Mobile flex-row gotcha" section
  above so it's checked deliberately, not rediscovered, in any future
  redesign work. Also closed two historical loose ends found along the
  way: the count-in-label pattern from step 8 (fixed in steps 14/15)
  and a handful of Portuguese-only code comments (steps 17/18, unrelated
  to the redesign itself, fixed in passing while those lines were
  already being touched). **The Material 3 redesign (all 20 steps) is
  complete.** Nothing is half-done or uncommitted; working tree is
  clean and prod is running the step-19 commit.
