# ASK-AI Widget Integration Guide

**Widget Integration Contract: 1.1**

> This is the authoritative integrator-facing guide for embedding the ASK-AI
> Widget into websites. The integration contract version above is a
> documentation/governance version and is independent of the product release
> version (v1.0.x, v1.1, …). Behavior described here is frozen by acceptance
> tests; breaking changes will increment the contract version.

Widget appearance follows a unified model:

```
appearance = icon × shape × theme
```

- **icon** — which launcher artwork is shown
- **shape** — round or rounded-square button
- **theme** — auto / light / dark color treatment

Under the normal integration model you do **not** hard-code appearance at all:
appearance is managed centrally per site by your administrator (see
[Admin-managed Appearance](#admin-managed-appearance)). Changing appearance in
the Admin console updates the real Widget on every page that embeds your
`site_id` — **no changes to your website embed code are required**. Explicit
embed attributes exist as an advanced override for special cases only.

---

## Quick Start

The embed is a **CSS + JS pair** served from your ASK-AI deployment. Add both
to any page:

```html
<link rel="stylesheet" href="https://askai.example.com/widget/ask-ai-widget.css">
<script
  src="https://askai.example.com/widget/widget.js"
  data-api-url="https://askai.example.com"
  data-site-id="camthink-website"
></script>
```

Replace `askai.example.com` with your ASK-AI deployment host and
`camthink-website` with the site experience `site_id` your administrator
assigned to you.

That is the complete integration. A launcher button appears in the bottom-right
corner; clicking it opens the chat panel. Appearance (icon, shape, theme) is
controlled by your administrator unless you add explicit overrides
([Advanced Embed Overrides](#advanced-embed-overrides)).

**Required parameters:** `data-api-url` (the widget must know where your ASK-AI
backend lives; if omitted it defaults to `http://localhost:8000`, which only
works in local development).
**Optional parameters:** everything else — see
[Configuration Reference](#configuration-reference).

## Site Identity

`data-site-id` identifies **which site experience** this page belongs to. It:

- selects the site's content experience (welcome message, starter questions,
  language default);
- selects the site's **appearance** (icon × shape × theme) configured by your
  administrator;
- scopes answer grounding to that site's knowledge.

`site_id` is an **identity, not a credential**. Knowing a `site_id` grants no
access by itself — every request is authorized server-side (see
[Allowed Origins](#allowed-origins)). It is therefore safe to ship it in
public page source. Do not put secrets in any widget attribute.

Pages without `data-site-id` run in legacy public mode (default experience and
default appearance).

## Allowed Origins

Server-side authorization is **Origin-based**. Your administrator registers
the exact origins (e.g. `https://www.yourstore.com`) allowed for your
`site_id`. At runtime the Widget sends your page's `Origin` (or `Referer`) with
every site request; the server:

1. resolves the site — it must exist and be enabled;
2. normalizes your origin (`scheme://host[:port]`, default ports stripped) and
   requires an **exact match** against the site's allowed origins.

No match → the request fails with a generic `403` (the reason is not
disclosed). This is independent of browser CORS: CORS is the browser
enforcement layer, the origin check is the server-side authorization. If your
site is reachable from multiple hosts (e.g. `www.` and apex domain), ask your
administrator to allow **each** origin.

## Appearance Configuration

Under the normal model you configure nothing — appearance flows from the site
experience. The full resolution precedence, checked **per dimension**
(icon / shape / theme independently), is:

| Priority | Source | When it applies |
|---|---|---|
| 1 | Explicit embed attributes (`data-launcher-icon`, `data-launcher-shape`, `data-launcher-theme`) | Present on the embed script / preset element / `window.AskAIConfig` |
| 2 | Persisted site experience appearance (Admin-managed) | You embedded a `data-site-id` |
| 3 | Compatibility defaults | Always (fallback) |

Defaults: `icon = current`, `shape = rounded-square`, `theme = auto`.

**Invalid-value fallback:** unknown or invalid values never break the Widget —
an unknown icon falls back to `current`, an unknown shape to `rounded-square`,
an unknown theme to `auto`. Invalid values written through the Admin console
are rejected with an explicit `422` instead of being stored.

**Per-site behavior:** appearance is stored per site experience. Two sites can
have completely different launchers; every page embedding the same `site_id`
shares its appearance.

## Built-in Launcher Designs

Five icons are built in. Each new icon renders as a brand-orange
(`#f24a00`) launcher with a white vector glyph, in your chosen shape.

| Icon id | Design | Admin label |
|---|---|---|
| `current` | Original launcher (compatibility default — pixel-identical to pre-appearance releases) | 经典(默认) |
| `bot-sparkle` | Outlined robot with a sparkle | 机器人 + 星光 |
| `bubble-sparkle-fill` | Filled chat bubble with a sparkle | 气泡 + 星光 · 填充 |
| `robot-smile` | Friendly smiling robot face | 机器人笑脸 |
| `bubble-sparkle-outline` | Outlined chat bubble with a sparkle | 气泡 + 星光 · 描边 |

Icons are inline vector SVG (the `current` icon is a bundled image) — they
render sharp on high-DPI screens and trigger **zero additional network
requests**.

## Shape Configuration

| Shape id | Result | Admin label |
|---|---|---|
| `round` | Circular launcher | 圆形 |
| `rounded-square` | Rounded square (radius proportional to the 52 px production button) | 圆角方形 |

Shape is an **independent dimension** from icon: any icon combines with either
shape. The compatibility icon `current` keeps its original fixed geometry
(52 px rounded square) — shape selection applies to the four vector icons.

## Theme Configuration

| Theme id | Behavior | Admin label |
|---|---|---|
| `auto` | Follow the visitor's **operating-system** color scheme; react live if it changes | 自动(跟随系统) |
| `light` | Light treatment, ignoring the system setting | 浅色 |
| `dark` | Dark treatment, ignoring the system setting | 深色 |

**Auto semantics (exact):** the Widget evaluates
`window.matchMedia('(prefers-color-scheme: dark)')` — nothing else. If
`matchMedia` is unavailable or reports nothing, the effective theme is
**light**. `auto` subscribes to system theme changes while the page is open.
Explicit `light` / `dark` ignore system changes entirely.

The Widget deliberately does **not** infer your host page's theme (no CSS
class sniffing, no background sampling, no framework dark-mode heuristics).
Theme controls the launcher's supporting contrast treatment (shadow, edge
highlight, glow, focus ring); the brand-orange identity of the vector icons
stays recognizable in both light and dark surroundings.

## Admin-managed Appearance

Administrators manage appearance per site in the Admin console under
**Widget 外观 (Widget Appearance)**:

1. pick the site experience;
2. choose the **icon** from visual previews (rendered by the real Widget);
3. choose the **shape** (圆形 / 圆角方形) and **theme** (自动 / 浅色 / 深色);
4. check the live preview (light and dark page backgrounds), then **Save**.

Saving persists per site. Every page embedding that `site_id` picks up the new
appearance on the Widget's next load — **customer websites never change their
embed code**. Unsaved selections are never persisted; the preview never
generates conversations or traffic.

## Advanced Embed Overrides

For special cases (a campaign page that must pin its look regardless of the
site setting) you may override any dimension explicitly on the embed script:

```html
<script
  src="https://askai.example.com/widget/widget.js"
  data-api-url="https://askai.example.com"
  data-site-id="camthink-website"
  data-launcher-icon="robot-smile"
  data-launcher-shape="round"
  data-launcher-theme="dark"
></script>
```

Overrides are per-dimension: you can pin only `data-launcher-shape="round"`
and let icon/theme keep following the site configuration. The same attributes
work on a preset container element and on the `window.AskAIConfig` global:

```html
<div id="ask-ai-widget-root"
     data-api-url="https://askai.example.com"
     data-site-id="camthink-website"
     data-launcher-icon="bot-sparkle"></div>
<script src="https://askai.example.com/widget/widget.js"></script>
```

```js
window.AskAIConfig = {
  apiUrl: "https://askai.example.com",
  siteId: "camthink-website",
  launcherIcon: "bot-sparkle",
  launcherShape: "round",
  launcherTheme: "auto",
};
```

Overrides exist for exceptional cases; prefer Admin-managed appearance so your
pages stay configurable centrally.

## Configuration Reference

All attributes may be set on the embed `<script>`, on a preset
`#ask-ai-widget-root` element, or (camelCase) on `window.AskAIConfig`.
Resolution order per key: script attribute → preset element attribute →
global → default.

| Attribute | Required | Default | Allowed values |
|---|---|---|---|
| `data-api-url` | **Yes** (prod) | `http://localhost:8000` | Your ASK-AI base URL |
| `data-site-id` | No | – (legacy public mode) | Your assigned site experience id |
| `data-language` | No | auto-detected | e.g. `en`, `zh` |
| `data-primary-color` | No | `#f24a00` | CSS color (chat accent) |
| `data-launcher-icon` | No | `current` | `current` \| `bot-sparkle` \| `bubble-sparkle-fill` \| `robot-smile` \| `bubble-sparkle-outline` |
| `data-launcher-shape` | No | `rounded-square` | `round` \| `rounded-square` |
| `data-launcher-theme` | No | `auto` | `auto` \| `light` \| `dark` |

Note: `data-launcher-icon` / `data-launcher-shape` / `data-launcher-theme`
override the site experience **for that page only** and take effect
immediately on reload — they do not require (and do not perform) any save.

## Integration Examples

**Multi-site storefront** — product pages and the help center share a
deployment but carry different site experiences:

```html
<!-- https://www.yourstore.com/products -->
<script src="https://askai.example.com/widget/widget.js"
        data-api-url="https://askai.example.com"
        data-site-id="yourstore-products"></script>

<!-- https://support.yourstore.com -->
<script src="https://askai.example.com/widget/widget.js"
        data-api-url="https://askai.example.com"
        data-site-id="yourstore-support"></script>
```

Each site keeps its own welcome message, starters, language and appearance.

**Single-page application:** the attributes are read when the Widget script
mounts. For route changes that must switch site identity, load the Widget per
full page load, or preset `#ask-ai-widget-root` per route before the script
runs. The Widget mounts at most one instance per page (double injection is
ignored).

## Updating Existing Integrations

- **v1.0.x embeds (no appearance attributes):** keep working unchanged. The
  upgrade is additive — your launcher looks exactly as before (`current`
  icon). No embed-code change is required by the v1.1 appearance system.
- **To adopt appearance:** do nothing in the embed; ask your administrator to
  set the site's appearance in the Admin console. Embed code changes are only
  needed for the [advanced overrides](#advanced-embed-overrides).
- **Compatibility aliases from earlier revisions** (`data-launcher-style`,
  REV0 style ids such as `assistant-spark`) are deprecated — see
  [Compatibility / Deprecation](#compatibility--deprecation).

## Security Notes

- **Appearance values can never grant access.** Icon/shape/theme are
  presentation-only; site authorization is exclusively
  site-existence + enabled + exact `Origin` match, enforced server-side on
  every site-scoped request (configuration fetch and chat alike).
- `site_id` is an identifier, not a credential — shipping it in public source
  is expected and safe. Never embed API keys or secrets in widget attributes.
- The Widget talks only to your `data-api-url` deployment (site config, chat
  streaming, uploads, feedback). It loads no third-party code.
- The server never discloses *why* authorization failed (unknown site,
  disabled site, or origin mismatch all return the same generic `403`).

## CSP / Asset Behavior

- The Widget ships as two same-origin assets from your deployment:
  `/widget/ask-ai-widget.css` and `/widget/widget.js`. No CDN or third-party
  origins are contacted.
- Launcher icons are **inline** (SVG markup or a bundled data URI) — no image
  requests at render time. If you run a strict CSP, `img-src data:` covers the
  bundled compatibility icon.
- Minimal CSP guidance: allow `script-src` and `style-src` for your ASK-AI
  origin (or serve the two files from your own origin), plus your `connect-src`
  toward the ASK-AI API for chat traffic.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Launcher does not appear | The CSS+JS pair must both be included; check `data-api-url` is reachable; if you pre-create `#ask-ai-widget-root`, it must be empty (a filled container is treated as already-mounted and skipped). |
| Site features fail with `403` | Origin mismatch: the page origin must exactly match an allowed origin of the `site_id` (watch `www.` vs apex, http vs https, non-default ports). Ask your administrator to add the exact origin. |
| Appearance changed in Admin but pages still show the old look | Hard-reload the page (the Widget assets may be browser-cached); confirm the page embeds the same `site_id` you edited; confirm the change was saved. |
| `auto` theme does not follow my site's dark mode | By design: `auto` follows the **operating system** preference only — it does not read your host page's theme. Pin `data-launcher-theme` or set the site theme to `light`/`dark` if you need a fixed look. |
| An unknown/typo appearance value is set | It fails safe: unknown icon → `current`, unknown shape → `rounded-square`, unknown theme → `auto`. Fix the attribute spelling; Admin writes reject invalid values outright. |
| Two Widgets on one page | Not supported: the second injection detects the mounted instance and skips. |

## Compatibility / Deprecation

| Legacy item | Status | Behavior today |
|---|---|---|
| `data-launcher-style` attribute | **Deprecated** | Still parsed; any value resolves to the `current` icon. Use `data-launcher-icon`. |
| REV0 style ids (`assistant-spark`, `chat-bubble`, `orbit-neural`) | **Retired** | Resolve to `current`; they are never silently mapped to new artwork. Re-select an icon in the Admin console. |
| `launcher_style` field in the site-config response | **Deprecated** | Legacy echo only; consume `launcher_icon` / `launcher_shape` / `launcher_theme`. |
| `launcher_theme` | **Canonical** | Unchanged: `auto` \| `light` \| `dark`. |
| Pre-appearance embeds (no attributes) | **Supported** | Unchanged behavior, indefinitely compatible. |

**Widget Integration Contract history:** 1.0 — initial widget bootstrap
(`data-api-url`, `data-site-id`, `data-language`, `data-primary-color`).
1.1 — unified appearance model (`appearance = icon × shape × theme`),
per-site Admin-managed appearance, advanced embed overrides, deprecation of
REV0 style aliases.
