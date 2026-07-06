# Dashboard Design Guide

How the Media Agent dashboard is styled, and how to tweak it — by hand or with
**Claude Design**.

---

## Where the design lives

All visual decisions are centralized in two files. Touch these, not the JSX,
when you want to change how things look:

| File | Owns |
|---|---|
| `tailwind.config.js` | **Tokens** — the `dark` neutral scale, `accent` colors, fonts, animations |
| `src/index.css` | **Components** — `.card`, `.badge*`, `.btn*` classes (`@layer components`) |

The React components (`src/components/*.jsx`) only reference **semantic classes**
(`bg-dark-800`, `text-accent-blue`, `card`, `badge badge-healthy`, `btn btn-primary`).
They contain almost no raw hex or one-off values, so a token change in the two
files above ripples through the whole UI.

### Token vocabulary

- **Neutrals** — `dark-50` (lightest text) … `dark-800` (page bg) … `dark-900` (deepest).
  Backgrounds: `dark-800` page, `dark-700` cards, `dark-600` inputs.
  Text: `dark-100` primary, `dark-300`/`dark-400` secondary, `dark-500` muted.
- **Accents** — `accent-blue` (primary/actions), `accent-green` (healthy/downloads),
  `accent-yellow` (warning), `accent-red` (error), `accent-purple`.
- **Fonts** — `font-sans` (Inter), `font-mono` (JetBrains Mono).

### Component classes (edit these to restyle globally)

- `.card` — the panel surface (radius, border, blur, padding).
- `.badge` + `.badge-healthy | -warning | -error | -available` — status pills.
- `.btn` + `.btn-primary | -ghost | -danger` — buttons.

**Example — make it warmer:** change `accent.blue` in `tailwind.config.js` from
`#58a6ff` to your brand color, and every button, link, progress bar, and active
tab updates at once. To round the corners more, bump `border-radius` inside
`.card`/`.btn` in `index.css`.

---

## Tweaking locally

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173, proxies /api to :8088
# edit tailwind.config.js / index.css — hot reloads
npm run build      # outputs to ../src/static (what the container serves)
```

The FastAPI app serves the built app at `/dashboard`. In Docker the build runs
automatically (see `Dockerfile` stage 1), so a rebuild ships the new design:

```bash
docker compose up -d --build
```

---

## Tweaking with Claude Design

Claude Design (claude.ai/design) lets you edit a **design-system project**
visually and sync it back to this repo. The flow uses the `/design-sync` skill
in Claude Code:

1. **Run** `/design-sync` in an interactive Claude Code session (it needs your
   claude.ai design login — a headless/web session can't do the OAuth).
2. It creates (or reuses) a design-system project and pushes the dashboard's
   components/tokens as preview cards, one at a time.
3. Edit colors, spacing, and component styles visually in claude.ai/design.
4. Pull the changes back; apply them to `tailwind.config.js` / `index.css`.
5. `npm run build` (or `docker compose up -d --build`) to ship.

**Keep it sync-friendly:** because tokens and component styles are centralized
and the JSX stays semantic, each component maps cleanly to one design card.
When adding UI, prefer a new token or a `@layer components` class over inline
arbitrary values (`bg-[#123456]`, `rounded-[7px]`) so the design stays
round-trippable.

---

## Mobile

The dashboard is mobile-first:

- `<meta name="viewport">` is set (`index.html`).
- Grids scale by breakpoint: `grid-cols-1 sm: md: lg:` on services, providers,
  quick actions.
- The header collapses labels and shrinks on small screens; the auto-refresh
  label is hidden under `sm`.
- The chat view uses `100dvh` (dynamic viewport height) so mobile browser chrome
  doesn't clip the input.

Test at ~360px wide (small phone) after any layout change — nothing should
scroll horizontally, and tap targets should stay comfortably sized.
