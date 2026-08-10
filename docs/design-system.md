# Alongside — Design System (v1)

> **Alongside** — nobody builds alone.

**Status:** Approved by Jeni, 5 Aug 2026 · **Owner:** Designer seat
**Companion to:** `product-spec.md` (what we're building) · `roadmap.md` (the 14 screens)

This document exists so that **no feature seat ever has to ask a colour question.**
If you're building a screen and something here doesn't answer it, that's a bug in this
document — tell Jeni and I'll fix it.

| Where things live | |
|---|---|
| Tokens (the Tailwind theme) | `templates/partials/_tailwind_config.html` — **Designer owns** |
| Reusable markup | `templates/components/` — **Designer owns** |
| Rendered reference | `design/mockups/v4-components.html` — open it, it's the visual index |
| Palette decision record | `design/mockups/v3-palette-forest.html` |

---

## 1. Colour

Three families with three jobs. The discipline is the whole design: **each family does its
own job and nothing else.** The moment that slips, the screen stops communicating.

### 1.1 `brand` — forest green

Brand, primary buttons, links, active nav, focus rings, the "Still looking" status.

| Step | Hex | On white | Use for |
|---|---|---|---|
| 50 | `#F1F6F2` | 1.09 | Role-chip and highlight grounds |
| 100 | `#DFEAE3` | 1.23 | Avatar tint, hover grounds |
| 200 | `#BCD3C4` | 1.58 | Chip borders |
| 300 | `#8DB29C` | 2.34 | **The only step legible on dark** — the success tick |
| 400 | `#5E9478` | 3.51 | Decoration, large graphics (clears 3:1 for UI marks) |
| 500 | `#3F7A58` | 5.08 | Large text, secondary marks |
| 600 | `#2E6144` | 7.22 | Focus rings, hover on 700 |
| **700** | **`#1F4A34`** | **10.06** | **The brand value.** Buttons, links, active nav |
| 800 | `#183A29` | 12.53 | Chip ink, button hover |
| 900 | `#11291D` | 15.46 | Dark page furniture |

**Why 700 is the brand value:** it gives 10.06:1 as text on white *and* 10.06:1 as a fill
under white text. Same number both directions — that symmetry is the point of going this
deep, and it's what lets one value be both the link colour and the button colour.

**The trap:** a deep brand colour is superb on white and useless on anything dark. Forest-700
on the ink-900 toast is **1.52:1 — invisible.** On dark grounds use **brand-300**.

### 1.2 `ink` — the Mystic Forest sages, used as neutrals

Surfaces, borders, muted text, topic tags.

| Step | Hex | On white | Use for |
|---|---|---|---|
| 50 | `#F7F8F6` | 1.07 | Badge grounds, section dividers |
| 100 | `#EFF0EC` | 1.14 | Page background, topic tags |
| 200 | `#E0E0E0` | 1.32 | Borders, skeletons, disabled fills |
| 300 | `#C9CCC4` | 1.63 | Stronger borders, input outlines |
| 400 | `#A9AE85` | 2.31 | The olive. **Decoration only — never text** |
| 500 | `#8A9188` | 3.24 | Status dots, large UI marks |
| 600 | `#6E7570` | 4.73 | **Lightest legal text on white.** Meta, timestamps, placeholders |
| 700 | `#565C58` | 6.85 | Secondary text, topic-tag ink |
| 800 | `#3C403D` | 10.54 | **Post bodies and comments** |
| 900 | `#232624` | 15.28 | Titles, the dark toast |

### 1.3 `spark` — burnt orange

**The Spark reaction and nothing else.**

| Step | Hex | On white | Use for |
|---|---|---|---|
| 50 | `#FDF3EE` | 1.09 | The sparked pill ground |
| 100 | `#F9E2D6` | 1.24 | Hover ground |
| 200 | `#F0C3AB` | 1.60 | Borders, if ever needed |
| 500 | `#C85A22` | 4.25 | **The filled star** (a graphic — needs 3:1, has 4.25) |
| 600 | `#A8461B` | 5.90 | Spark count on white |
| 700 | `#8A3A14` | 7.79 | **Spark count on the spark-50 pill** (7.13:1 there) |

**The rule, and it is not stylistic:** ember never appears on a button, a link, a banner,
a badge or a nav item. Its entire power is that it shows up roughly **once per screen**.
Spark drives feed ranking — if people don't notice it, good ideas don't rise. The moment
ember lands on a CTA, Spark stops meaning anything.

### 1.4 Why this palette works — and the trap in judging it

The Mystic Forest family spans 128° of hue but only **4–23% saturation**. That low chroma
is why nothing in it can carry Spark: on a page built entirely from muted colour, a muted
control can't announce itself.

Measured on the real screens, the sparked-vs-unsparked contrast is **2.13 for forest and
1.65 for ember** — *the numbers favour forest.* They're wrong, because contrast ratio
measures luminance only and is blind to hue. What makes a control findable mid-scroll is
looking like a **different kind of thing** from its neighbours. In a forest-only feed the
sparked Spark is a green pill under a row of green role chips: legible, but it reads as one
more tag. Ember is 131° away from the brand and reads as a different category instantly.

**Never settle a colour question with a contrast ratio alone.** Ratios tell you whether
something is *readable*, never whether it's *findable*.

---

## 2. Type

**No webfont, on purpose.** The system stack renders Roboto on Android and Segoe on Windows:
zero download, zero layout shift, instant first paint over 4G on the mid-range phones our
users actually have. Personality lives in the wordmark and the colour, not a 90KB font file.

| Role | Size / line-height | Tailwind | Notes |
|---|---|---|---|
| Display | 28 / 34 bold | `text-[28px] leading-[34px] font-bold` | Landing hero only |
| h1 | 22 / 28 semibold | `text-[22px] leading-7 font-semibold` | Post detail title |
| h2 | 18 / 24 semibold | `text-lg leading-snug font-semibold` | Feed card title |
| Body | 16 / 26 | `text-base leading-relaxed` | Post detail, comments |
| Card body | 15 / 23 | `text-[15px] leading-relaxed` | Feed card excerpt |
| Small | 14 / 20 | `text-sm` | Names, buttons, secondary |
| XS | 12 / 16 | `text-xs` | Chips, counts, timestamps |

**Never below 16px on a form control.** Below 16px, iOS Safari zooms the viewport on focus
and leaves the user scrolled sideways mid-form.

**The one exception to the 12px floor:** bottom-tab labels are 11px (`text-[11px]`). At
375px, 12px wraps "Messages" onto two lines. The label is a redundant cue there — the icon
and `aria-current` carry the meaning — so shrinking it costs nothing load-bearing. This is
the *only* sanctioned exception; don't cite it elsewhere.

Titles get `text-balance`. Body copy never does.

---

## 3. Spacing, shape, elevation

**Spacing** — 4px base. Use only `1 2 3 4 6 8 12` (4→48px). Card padding 16 mobile /
20 desktop. Screen gutter 16. Prefer flex/grid + `gap` over per-element margins.

**Radius** — chips and pills `rounded-full` · inputs and buttons `rounded-lg` (8) ·
cards, images and banners `rounded-xl`/`rounded-2xl` (12/16) · avatars `rounded-full`.

**Elevation** — **borders, not shadows.** One shadow token, only for things that genuinely
float over the page: toasts, sheets, dropdowns. Flat renders faster and looks less dated.

**Layout ceiling** — the centre column stops at 640px on desktop. A post is text, and text
past ~70 characters per line is harder to read, not more impressive.

---

## 4. Components

Everything below is in `templates/components/`. Each file's header comment is the full API —
this table is the index.

| Include | What it is |
|---|---|
| `_icon.html` | The icon set. `{% include ... with name="spark" %}` |
| `_btn_class.html` | Button **class string** — for when you need your own `hx-*` attributes |
| `_button.html` | Ready-made button or link |
| `_field.html` | Labelled input/textarea with hint + error, fully wired for a11y |
| `_avatar.html` | Avatar with initials fallback (`_avatar_inner.html` is internal) |
| `_chip_role.html` | Role-needed chip — brand-tinted, the matching signal |
| `_chip_tag.html` | Topic tag — grey, deliberately quiet |
| `_badges.html` | Stage + commitment + status badges |
| `_spark.html` | **The Spark control** |
| `_post_card.html` | The feed card, composed of the above |
| `_empty_state.html` | Empty state |
| `_toast.html` | Success toast |
| `_banner.html` | Error / warning banner |
| `_skeleton_card.html` | Loading skeleton for infinite scroll |
| `_app_bar.html` | Top bar (branded, or back + heading) |
| `_tab_bar.html` | Bottom navigation |

### 4.1 Buttons

Two ways in, because HTMX needs attribute freedom:

```django
{# simple #}
{% include "components/_button.html" with label="Follow" variant="secondary" %}

{# when you need hx-* or x-* #}
<button class="{% include 'components/_btn_class.html' with variant='primary' %}"
        hx-post="{% url 'social:follow' user.pk %}" hx-swap="outerHTML">Follow</button>
```

Variants: `primary` (forest fill) · `secondary` (outline) · `ghost` · `danger`.
Sizes: `md` 44px default · `lg` 48px. **There is no 36px size** — see §7.
Every form submit goes `full` width on mobile.

### 4.2 Chips — the distinction matters

Role chips are **brand-tinted**; topic tags are **grey**. That contrast is what lets a
joiner find "Android dev" while scrolling. Do not make topic tags brand-coloured — the
moment everything is tinted, the one thing people are scanning for disappears.

### 4.3 Badges — stage, commitment, status

These are the anti-ghosting design (`product-spec.md` §4.8), not decoration. They're the
reason nobody wastes three weeks on a "serious startup" that was a weekend doodle.

**Stage gets a 3-segment meter** because stage is *ordinal* — just an idea → already
building → launched. The meter says "1 of 3" before you read the word. **Commitment gets a
dot** because it's binary: hollow olive for casual, filled brand for serious.

Every badge carries its word. Colour never carries meaning alone — with a green brand,
red/green colour blindness is a bigger risk for us than for a blue app.

### 4.4 Spark

```django
{% include "components/_spark.html" with post=post %}
```

`hx-post` toggles and the view returns the same partial, swapped `outerHTML`, so the count
comes from the server and two tabs can't disagree. State lives on `aria-pressed`, and the
icon changes outline→solid so it survives greyscale. 44px minimum, always.

Vocabulary: it is a **Spark**. Never a like. Counts read "42 sparks."

### 4.5 Empty states

Empty states are not filler — for a new user they *are* the product, and an empty screen
saying "No results" is how a portfolio demo dies in ten seconds. Three rules:

1. Say **why** it's empty, not just that it is.
2. Give exactly **one** way out, as a real button.
3. **Never blame the user.** "No ideas match those filters" — not "You have no results."
   Filters cause this far more often than the words do.

**Feed and Home never use an empty state.** The cascading fallback (`product-spec.md` §4.3)
means they're never empty; they get a labelled divider explaining where the posts came from
("Popular in Design this week — because the feed should never be empty").

---

## 5. Success, error, warning — with a green brand

**Success is not a green surface.** Conventional success green `#2E7D32` sits 26° from our
brand and scores **1.96:1** against it. Two greens that close cannot signal different
things, and a green bar on a green-branded app reads as chrome, not confirmation.

So confirmation is a **dark neutral toast with a pale-green tick** — green becomes the mark
of approval inside the message rather than the field it sits on.

| State | Ground | Ink | Icon | Role |
|---|---|---|---|---|
| Success | `ink-900` | white | `check` in `brand-300` | `status` |
| Error | `bad-50` + `bad-200` border | `bad-700` | `alert-circle` in `bad-600` | `alert` |
| Warning | `warn-50` + `warn-200` border | `warn-700` | `alert-triangle` in `warn-600` | `status` |

**Warning is amber-YELLOW `#8A6100`, not amber-orange.** Conventional warning amber
(`#B45309`) is **8° from Spark's ember** — a warning banner in that colour reads as an
enormous Spark. Ours is 24° away with a large lightness gap.

**Known tight spot:** error red is 15° from ember. It's safe because an error is always an
icon-and-text banner inside a form, never a filled pill in a card's action row, so they
never share a context. **If a future design puts a red pill next to a Spark, revisit this.**

**The rule underneath all of it:** every state is an **icon plus words**. Colour only
reinforces. Any state that would be ambiguous in greyscale is wrong, whatever the ratios say.

Copy: say what happened and what to do. No apologies, no "Oops!". A control says exactly
what happens — "Publish", then a toast that says "Your idea is live."

---

## 6. HTMX patterns

| Pattern | How |
|---|---|
| Toggle (spark, save, follow) | `hx-post` + `hx-swap="outerHTML"`, view returns the same partial |
| Infinite scroll | Last item wraps `hx-get=...?page=N hx-trigger="revealed" hx-swap="outerHTML"` around `_skeleton_card.html` |
| Busy state | `[.htmx-request_&]:hidden` on the label, `[.htmx-request_&]:inline-flex` on the spinner. **There is no `htmx-request:` Tailwind variant** — reaching for one fails silently |
| Inline errors | Swap the field partial, never a full-page error for a partial failure |
| Feed ↔ Home | One shell, one tab control, swap only the list |

CSRF is handled once by `hx-headers` on `<body>` in `base.html` — no seat needs to repeat it.

---

## 7. Accessibility — non-negotiable

- **Touch targets.** Two tiers, and the distinction is real rather than a loophole:
  - **44×44 minimum for controls** — buttons, icon buttons, form fields, nav items, Spark,
    save, follow, anything destructive. No exceptions, no 36px "desktop-only" variant.
  - **32px minimum height with 8px separation for inline text links and dense chips**
    (topic tags, role chips). Forcing a row of tag pills to 44px makes them the loudest
    thing on a card, which defeats the point of tags being quiet. 32px still clears
    WCAG 2.2 AA (2.5.8 asks 24×24); the 44 figure is the stricter AAA / Apple HIG target
    we hold ourselves to for things people actually press to *do* something.

  If you're unsure which tier something is in, ask: does tapping it *change state*, or
  does it *navigate*? State changes are 44. Navigation can be 32.

  **One named exception:** a control nested inside another control — the "remove" × on an
  editable role chip — may be 32×32 provided its parent row is a full 44. The parent is
  what the thumb aims at; the × is a refinement within it.
- **Contrast: AA (4.5:1) for text, 3:1 for meaningful graphics.** `ink-600` is the lightest
  legal text colour on white. `ink-400` is decoration only.
- **Focus: visible on everything focusable.** `focus-visible:ring-2 ring-brand-600
  ring-offset-2`. Every component here already carries it — don't remove it.
- **Colour is never the only signal.** Icon + word, always.
- **Motion respects `prefers-reduced-motion`** — use `motion-safe:` on anything that moves.
- **375px with no horizontal scroll.** Verified on every component in this system.

---

## 8. Change request for the Architect (via Jeni)

`templates/base.html` is the Architect's file, so I haven't touched it. One thing in it now
contradicts §5:

The `{% if messages %}` block renders success as `border-ok-600 bg-ok-50 text-ok-700` — a
**green surface**, which is exactly the pattern we've moved away from. It still renders
legibly (I pointed the `ok` tokens at the brand ramp so nothing looks broken), so this is
tidy-up, not breakage.

**Suggested replacement** for the success branch of that block:

```django
{% if message.tags == 'success' %}
  {% include "components/_toast.html" with message=message %}
{% elif message.tags == 'error' %}
  {% include "components/_banner.html" with kind="error" title=message %}
{% else %}
  {% include "components/_banner.html" with kind="warning" title=message %}
{% endif %}
```

Also minor: the nav placeholder uses `fill-brand-500`, which is now a mid-green. The
wordmark should be `fill-brand-700`. `_app_bar.html` already does this — that block is
meant to be replaced by it anyway.

---

## 9. What changed from the first mockup, and why

`design/mockups/v1-design-system-feed-post.html` is **superseded**. It proposed a warm ember
brand; the product went forest green. Keep it for history, don't build from it.

Fixed on the way through — all of these were real defects in v1:

| Was | Now |
|---|---|
| Input placeholder `ink-400`, **2.52:1** — and v1's own rules banned ink-400 for text | `ink-600`, 4.73:1 |
| Stale-post nudge amber, **3.07:1** | `warn-700` on `warn-50`, 7.47:1 |
| "Reported" chip, **4.28:1** | `bad-700`, 8.07:1 |
| A 70%-opacity tint at **4.17:1** | Solid ink, 8.8:1 |
| Comment bubble and Messages used **the same icon** | Messages is an envelope; the bubble means comment only |
| Filter chips, ⋯ and Message drawn at **36px** against a stated 44px rule | All 44px |
| Focus rings drawn on only some controls | On every interactive component |
| Stage shown as a flat dot, throwing away its ordinality | 3-segment meter |

---

## 10. Open

- **Dark mode** is not in v1. Every colour is a token, so it's a token swap in Phase 2
  rather than a rewrite — but it is deliberately not designed yet.
- **Follow-with-a-note** (`product-spec.md` §4.4) has no design yet. It's where a joiner
  says "I'd want the Android role", which is a real moment.
- **12 of the 14 screens** are still to design. Feed and Post detail carry every component
  here, so the system is proven; the rest is application.
