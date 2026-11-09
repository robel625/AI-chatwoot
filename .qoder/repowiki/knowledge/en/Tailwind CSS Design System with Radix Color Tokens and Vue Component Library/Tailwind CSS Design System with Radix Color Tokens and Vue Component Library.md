---
kind: frontend_style
name: Tailwind CSS Design System with Radix Color Tokens and Vue Component Library
category: frontend_style
scope:
    - '**'
source_files:
    - tailwind.config.js
    - tailwind.superadmin.config.js
    - postcss.config.js
    - theme/colors.js
    - theme/icons.js
    - app/javascript/design-system/histoire.scss
    - app/javascript/dashboard/components-next/CardLayout.vue
    - app/javascript/dashboard/components-next/button/index.vue
---

## Approach

Chatwoot's frontend styling is built on **Tailwind CSS v3** (configured via `tailwind.config.js`), with a dedicated design-system layer under `app/javascript/design-system/` and a component library under `app/javascript/dashboard/components-next/`. The visual tokens (colors, icons) are centralized in `theme/colors.js` and `theme/icons.js`, which Tailwind imports at build time. PostCSS (`postcss.config.js`) runs `postcss-preset-env`, `postcss-import`, `tailwindcss`, and `autoprefixer` in that order.

The project uses **Vue 3 single-file components** (`.vue`) as the UI building blocks. Styles are primarily utility-first Tailwind classes; there is no separate global stylesheet per component — shared styles live in the design-system entry point and in `histoire.scss` for Storybook/Histoire previews.

## Key Files and Packages

- `tailwind.config.js` — main Tailwind configuration: content globs, theme extensions, breakpoints, animations, typography plugin, icon plugin.
- `tailwind.superadmin.config.js` — secondary Tailwind config extending the root one for the super-admin Rails views only.
- `theme/colors.js` — design-token map exporting `woot`, `green`, `yellow`, `slate`, `black`, `red`, `violet` palettes plus a newer `n.*` token namespace (e.g. `n.slate.12`, `n.solid.blue`, `n.alpha.black1`) that maps to CSS custom properties like `--slate-12`, `--solid-blue`, `--alpha-black1`.
- `theme/icons.js` — ~500-line registry of inline SVG icons keyed by name (file types, channels, status/priority indicators, social logos, etc.), consumed through `@egoist/tailwindcss-icons`.
- `postcss.config.js` — PostCSS pipeline wiring Tailwind + autoprefixer.
- `app/javascript/design-system/histoire.scss` — Histoire (Storybook-like) preview stylesheet.
- `app/javascript/dashboard/components-next/**` — the new component library (Accordion, Button, Dialog, Input, Select, Table, TagInput, Switch, Spinner, Avatar, Sidebar, Tabbar, Pagination, Combobox, Popover, DropdownMenu, RadioCard, ColorPicker, etc.).
- `package.json` dependencies include `tailwindcss`, `@tailwindcss/typography`, `@egoist/tailwindcss-icons`, `@radix-ui/colors`, `autoprefixer`, `postcss-preset-env`, `postcss-import`, `@vitejs/plugin-vue`, `vitest`, and `histoire`.

## Architecture and Conventions

### Token-driven theming
Colors are not used as raw hex values in components. Instead, `theme/colors.js` exposes semantic tokens (`woot.500`, `n.solid.blue`, `n.alpha.black1`, `n.border-strong`, `n.button.color`, etc.) which Tailwind merges into its palette. Many tokens resolve to CSS variables (`rgb(var(--slate-12) / <alpha-value>)`), enabling runtime theme switching via the `darkMode: 'class'` setting on the `<html>` element.

### Typography
A custom `typography.bubble` theme extension is defined in `tailwind.config.js` to style Markdown-rendered message bubbles, including heading sizes, list indentation, code block backgrounds, table borders, and RTL-aware blockquote borders. Font families extend the default sans stack with `Inter` and `InterDisplay`.

### Breakpoints
Custom Tailwind breakpoints are declared: `xs: 480px`, `sm: 640px`, `md: 768px`, `lg: 1024px`, `xl: 1280px`, `2xl: 1536px`, `3xl: 1900px`.

### Icon system
Icons are registered via `@egoist/tailwindcss-icons` with a `woot` collection (custom Chatwoot icons) plus bundled collections `lucide`, `logos`, `ri`, `ph`, `material-symbols`, `teenyicons`, `fluent`. Components reference icons through the generated Tailwind icon utilities rather than importing SVGs directly.

### Animations
Shared keyframes and animation names are centralized in `tailwind.config.js`: `wiggle`, `fade-in-up`, `loader-pulse`, `card-select`, `shake`, `shimmer`, `text-shimmer`, `twinkle`, `pop-in`, `fade-in`, `scale-in`, `sheet-in`, `page-progress`. These are reused across dashboard components for loading states, transitions, and micro-interactions.

### Content scanning
Tailwind's `content` array explicitly lists every Vue/JS/ERB path that may emit utility classes, covering:
- Enterprise ERB views
- Widget, V3, Dashboard, Portal, Shared, Survey JS trees
- `components-next` Vue components and helpers/composables
- Rails `app/views/**/*.erb`
This ensures purge works correctly across the monorepo's multiple frontends.

### Super-admin separation
The super-admin Rails UI has its own Tailwind config (`tailwind.superadmin.config.js`) that extends the root config but restricts `content` to super-admin ERB views and the super-admin JS entrypoint, keeping the two builds independent while sharing theme tokens.

### Component library structure
New components under `app/javascript/dashboard/components-next/<ComponentName>/` follow a consistent folder-per-component layout (each containing `index.vue`, `styles.css`, `types.ts`, etc.). This is the migration target replacing older ad-hoc dashboard components.

## Conventions and Constraints

- **Utility-first**: Visual styling is expressed as Tailwind utility classes in `.vue` templates; bespoke CSS is kept minimal and scoped to the design-system entry or Histoire previews.
- **Tokens over literals**: Colors, spacing, and semantic surfaces should come from `theme/colors.js` (`n.*` tokens) rather than hard-coded hex values, so dark mode and brand customization propagate automatically.
- **Dark mode via class strategy**: `darkMode: 'class'` means the app toggles a `dark` class on the document root; components must use tokens that resolve to CSS variables, not static colors, to participate in dark mode.
- **Icon usage through the registry**: New icons are added to `theme/icons.js` and consumed via the `woot` collection registered in `tailwind.config.js`; direct inline SVGs in components are discouraged except for legacy cases.
- **Animation reuse**: Custom animations should be added to the `keyframes`/`animation` sections of `tailwind.config.js` and referenced by their Tailwind animation utility name.
- **Breakpoint naming**: Use the custom breakpoint names (`xs`, `sm`, `md`, `lg`, `xl`, `2xl`, `3xl`) defined in the config rather than arbitrary pixel values.
- **Content paths must stay in sync**: Adding a new Vue/JS source directory requires updating the `content` array in `tailwind.config.js` (and `tailwind.superadmin.config.js` if it belongs to the super-admin build) or Tailwind will strip the utilities at build time.
- **PostCSS ordering**: The pipeline runs `postcss-preset-env` → `postcss-import` → `tailwindcss` → `autoprefixer`; plugins must not reorder this sequence.