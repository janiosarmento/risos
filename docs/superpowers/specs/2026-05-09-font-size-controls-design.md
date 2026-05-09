# Font Size Controls (A- / A+)

**Date:** 2026-05-09  
**Status:** Approved

## Problem

On tablet the app uses the desktop layout (split-view reading panel). The default font size is comfortable on desktop but slightly small for tablet use. Users need a way to scale text up or down without navigating to settings.

## Solution

Two buttons (`A-` / `A+`) in the sidebar header that adjust a global font scale applied to `html` font-size. Since Tailwind uses `rem` units throughout, scaling the root font size scales all text uniformly without touching any CSS classes.

## Design Decisions

### Placement
Sidebar header, to the right of the app title, alongside the existing settings and logout icons. Hidden on mobile (same visibility rule as the logout button).

### Scale Steps
5 discrete steps indexed 0–4:

| Index | Scale | html font-size |
|-------|-------|---------------|
| 0     | −2    | 88%           |
| 1     | −1    | 94%           |
| 2     | 0 (default) | 100%  |
| 3     | +1    | 112%          |
| 4     | +2    | 125%          |

### Button States
- `A-` is disabled (and visually dimmed) at index 0
- `A+` is disabled (and visually dimmed) at index 4

### Persistence
`sessionStorage` key `rss_font_scale` (integer 0–4). This means:
- Survives page reload within the same browser session
- Resets when the browser tab/window is closed
- Explicitly cleared on logout so a new login always starts at default scale

### Mobile
Buttons hidden on mobile via the same responsive class used for the logout button (`hidden sm:flex` or equivalent — confirm during implementation).

## Implementation Scope

1. **`ui.js` store** — add `fontScale` property (default 2), `increaseFontScale()`, `decreaseFontScale()`, `applyFontScale()` methods. Load from `sessionStorage` on init.
2. **`index.html`** — add `A-` / `A+` buttons in the sidebar header section (lines ~236–249). Wire to store methods.
3. **`app.js` or `auth.js`** — clear `rss_font_scale` from `sessionStorage` on logout.
4. **Version bump** — update `APP_VERSION` in `index.html`.

## Out of Scope

- Persisting font scale across logins
- Per-section scaling (list vs. reading panel independently)
- Font scale in settings modal
