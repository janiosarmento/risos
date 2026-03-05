# JavaScript Architecture

## Overview

The frontend uses **Alpine.js** with a zero-build architecture. All JS files are loaded via `<script defer>` tags in `index.html`, ordered so that stores register before components, and everything before Alpine starts.

## File Structure

```
htdocs/static/js/
├── stores/             # Alpine.store() — shared state
│   ├── auth.js         # token, login(), logout(), fetchApi()
│   ├── i18n.js         # locale, translations, t(), loadLocale()
│   ├── ui.js           # toast, confirmModal, theme, applyTheme()
│   └── prefs.js        # all preference values (19 properties), sync/save
├── components/         # Mixins spread into app() via ...xxxMixin
│   ├── postDetail.js   # post viewing, navigation, summary, export
│   ├── settings.js     # settings panel, CRUD, AI, tag merge, topics, prefs
│   └── curation.js     # AI curation, batch ops, export selection
└── app.js              # main app() function, orchestration, init
```

## Patterns

### Stores (`Alpine.store()`)
Registered in `alpine:init` event. Hold state that is truly shared or framework-level (auth, i18n, UI, preferences). Accessed via `Alpine.store('name')` or `$store.name` in HTML.

### Mixins (plain objects spread into `app()`)
```js
const settingsMixin = { /* state + methods */ };
// In app():
return { ...postDetailMixin, ...settingsMixin, ...curationMixin, ... };
```
This preserves `this` context — mixin methods can access all app-level state (`this.posts`, `this.feeds`, `this.fetchApi()`, etc.) because they're spread into the same object.

**Why not `Alpine.data()`?** Components created with `Alpine.data()` have isolated scopes and can't access the parent `x-data="app()"` scope. Since most methods depend heavily on shared state, the mixin pattern is more practical.

### Getter/Setter Delegation
App-level properties that live in stores are exposed as getter/setters in `app()` so the HTML doesn't need to change:
```js
get token() { return Alpine.store('auth').token; },
set token(v) { Alpine.store('auth').token = v; },
```

### Script Loading Order
All scripts use `defer` and execute in document order:
1. Stores (auth → i18n → ui → prefs)
2. Components (postDetail → settings → curation)
3. app.js (defines `app()`, references all mixins)
4. Alpine CDN (calls `alpine:init`, then starts)

### Cache Busting
`APP_VERSION` is defined once in `index.html` `<head>`. All script/CSS tags are generated via `document.write` using this variable. Format: `YYYYMMDD` + letter suffix (e.g., `20260305c`).
