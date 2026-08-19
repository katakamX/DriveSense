# DriveSense visual identity — design plan

**Status: proposal. No code written yet.**

## The problem with what's there now

The current tokens are, almost exactly, one of the generic defaults the brief
warns about: `--surface-base: #08090c` (near-black) plus `--accent: #22d3ee`
(single neon cyan). Body face is Inter, data face is JetBrains Mono. Every
individual choice is defensible; together they are the house style of roughly
every developer-tool landing page since 2021. Nothing about the current design
could not be lifted wholesale onto a log viewer or a crypto exchange.

There is also a live information bug in the current UI. `LiveDrive.tsx` maps
the risk bands like this:

```ts
CALM: 'low',  NORMAL: 'low',  AGGRESSIVE: 'high',  HIGH_RISK: 'critical'
```

Four bands collapse into three colours. `CALM` and `NORMAL` are visually
identical, so the display throws away a distinction the risk engine went to
some trouble to compute.

## What the product actually is

Two facts from the risk engine should drive the entire palette, because they
are unusual and they are load-bearing.

**1. The bands are evenly spaced, deliberately, as a refusal to claim.**
From `backend/app/core/risk/schema.py`:

> Evenly spaced across [0, 100]. Even spacing is a deliberate non-claim: this
> engine does not assert that the step from AGGRESSIVE to HIGH_RISK is worse
> than the step from CALM to NORMAL, because nothing in M8 measured that.

A traffic-light palette (calm green, screaming red) would visually assert
exactly the severity curve the engine explicitly refuses to assert. The colour
steps have to look as evenly spaced as the numbers are.

**2. `HIGH_RISK` is categorically different, not just "more".** The engine
cannot emit `HIGH_RISK` on model opinion alone — the deterministic rule layer
has to fire. It is the one band backed by a different *kind* of evidence.

And one fact from the rest of the system: this product is unusually careful
about the difference between *measured*, *inferred*, and *unknown*. It carries
`provenance` (`RULES_ONLY` / `MODEL_AND_RULES_AGREE` / `MODEL_ONLY`), it
carries `coverage_ratio` (what fraction of the 30-second window actually had
samples), it refuses to impute missing signals, and it already ships a
`StaleNotice` component whose docstring says a page showing "Live" over a
frozen speed *is lying by omission*.

That is the product's actual personality. Not "automotive". **Epistemic
honesty about live measurement.**

---

## The organising principle

> **Colour is a reading, never decoration.**

Three rules follow, and they are the identity:

**Rule 1 — Colour only ever means risk.** There is no brand accent. Buttons,
links, nav highlights, focus rings and icons are all achromatic. The only
saturated colour anywhere in the application is the four-band risk scale. If
something on screen is coloured, it is telling you about driving behaviour.

This is only affordable because this product has a real job for colour. A
generic dashboard cannot do it — it needs an accent for its primary button.

**Rule 2 — Colour drains with certainty.** When the socket drops, live
readouts keep their values but desaturate toward neutral. We are no longer
measuring, so the colour leaves; the number stays, because it is still the
last true thing we knew. This makes the existing `StaleNotice` behaviour a
visual property of the whole surface rather than a banner bolted on top.

**Rule 3 — No score without its evidence.** Every risk score is rendered
adjacent to the trace (below).

---

## Colour — 6 named values

Two neutral anchors, four risk stops. Every remaining grey is derived from the
two anchors by mix, not hand-picked, so the greys cannot drift apart over time.

| Token | Hex | Role |
| --- | --- | --- |
| `--ink` | `#070A0F` | Ground. Near-black with a deliberate blue cast — reads as glass over an instrument, not as "dark mode #1". |
| `--paper` | `#DCE3ED` | Full-strength content. Slightly cool white; never pure `#fff`. |
| `--band-calm` | `#3FB8A4` | CALM |
| `--band-normal` | `#8FAE64` | NORMAL |
| `--band-aggressive` | `#D9A03C` | AGGRESSIVE |
| `--band-high` | `#E2564A` | HIGH_RISK |

Surfaces are `--ink` lightened in even steps; borders and secondary/muted text
are `--paper` mixed down into `--ink` via `color-mix()`. Six decisions instead
of fourteen.

**Why this ramp.** `calm → normal → aggressive` is a smooth sequential
interpolation from teal to amber, passing through olive — even perceptual
steps, matching the engine's even numeric spacing. It reads as a temperature
scale (a *reading*), not a traffic light (a *verdict*). `high` then breaks the
ramp into vermillion, because `HIGH_RISK` genuinely is a categorical break in
the engine, not one more step along the same axis.

The ramp runs on a blue↔yellow axis rather than red↔green for its first three
stops, which survives deuteranopia and protanopia — the two most common forms
— where a traffic light does not. Risk is additionally never encoded by colour
alone: bands keep their text labels, as they already do today.

Restoring four distinct tones also fixes the `CALM`/`NORMAL` collapse noted
above.

## Type — three faces, each with a job

| Role | Face | Why |
| --- | --- | --- |
| Display | **Chakra Petch** | Angular, flat-cut terminals drawn from technical and automotive instrument lettering. Section headers, the hero score. Used in short bursts only. |
| Body | **IBM Plex Sans** | Engineered humanist, drawn for technical products, highly legible at 13–14px where roster tables live. Not Inter. |
| Data | **IBM Plex Mono** | Tabular numerals for scores, timestamps, coordinates, speeds. Shares skeleton and metrics with the body face, so a table mixing prose and figures stays level. |

Body and data are one superfamily so they agree by construction; display
supplies the character. Plex Mono replacing JetBrains Mono is not cosmetic —
pairing the mono to its own sans is what stops mixed rows from looking
assembled from two systems.

**The typographic rule that shows up everywhere:** measurements are
monospaced, tabular and right-aligned; prose is proportional and left-aligned.
Applied without exception, numerals form clean scannable columns.

## Layout

**The instrument band.** Every page carries a persistent horizontal readout
strip directly under the page header: key measurements, mono, tabular, always
in the same position. Justified by the data rather than by taste — telemetry
arrives at 10 Hz and risk at 1 Hz, so these values genuinely move, and a value
that moves must not also move *position*, or it cannot be read at a glance.

- **Live Drive / dashboards** — instrument-forward. Hero score in display face,
  the trace beneath it, supporting tiles in a dense row.
- **Rosters** (drivers, vehicles, trips) — dense tables. Hairline separators,
  no zebra striping, hover as the only row affordance, all numerics
  right-aligned mono. Colour appears only in the risk column.
- **Detail pages** — a "record" shape: identity block, instrument band, then
  stacked evidence sections below.

Existing `Panel`, `Badge` and `StatTile` are re-skinned via tokens, not
replaced. Because `tailwind.config.ts` already reads every colour from CSS
custom properties, most of this lands in `tokens.css`.

## Signature element — the trace

A 30-cell tick strip encoding the 30-second feature window the score was
computed from. Lit cells are seconds with samples; dark cells are gaps. A
small provenance glyph sits at its end: rules-only, model-and-rules-agree, or
model-only.

It renders next to every risk score in the product.

**You never see a number in DriveSense without seeing what it rests on.**

A generic dashboard cannot copy this. It has no `coverage_ratio` and no
`provenance` to draw — the data does not exist. Here it already does, computed
every second, and is currently thrown away by the UI.

---

## Self-critique: would this be different for any other SaaS dashboard?

Being honest about each piece rather than defending all of it:

| Element | Verdict |
| --- | --- |
| Dark instrument ground | ❌ **Fails.** Every devtool and fintech dashboard is dark. Supporting cast only — it must not be sold as the identity. |
| Chakra Petch display face | ⚠️ **Weak.** Suits any vehicle or IoT product. Appropriate, not distinctive. Keep, don't headline. |
| Instrument band | ⚠️ **Partial.** Sticky KPI headers are common. Defensible *here* specifically because the values move at 10 Hz. Justify by the live data, not by novelty. |
| Mono, right-aligned numerics | ⚠️ Good practice, widely used. Keep, don't claim as identity. |
| Colour only ever means risk | ✅ **Passes.** Only affordable because colour has a real job here. Any CRM needs a brand accent and cannot adopt this. |
| Colour drains when stale | ✅ **Passes.** Requires a live socket and a product that distinguishes stale-but-true from unknown. Ties directly to `StaleNotice`. |
| Evenly spaced band ramp | ✅ **Passes.** A direct visual encoding of a documented epistemic choice in this repo's risk engine. |
| The trace | ✅ **Passes strongly.** Literally cannot be rendered without `coverage_ratio` and `provenance`. |

**Revision made after this critique.** The first draft led with the dark
automotive aesthetic and treated the trace as one widget among several. That
draft would have failed the test — the look was doing the work, and the look is
generic. Restructured so the two things that genuinely could not appear in
another product (colour-as-measurement including its staleness behaviour, and
the trace) *are* the identity, and the aesthetic choices are explicitly
labelled supporting cast. The dark ground and the display face earn their place
by being appropriate; they are not the point.

**Residual risk, stated rather than hidden.** Chakra Petch can read as
"gamer/sci-fi" at large sizes. Mitigation: confine it to headers and the single
hero score, at moderate weight and tight tracking. If it still reads wrong once
on screen, swap the display face to Archivo (signage grotesque) — the identity
does not depend on it, which is rather the point of the critique above.

## Constraints carried into build

- All existing functionality, routing, role gating and data fetching untouched
  — this changes how it looks, not what it does.
- Responsive to mobile: the instrument band wraps to two rows; roster tables
  scroll horizontally within their own container rather than the page.
- Visible keyboard focus on every interactive element — a `--paper` ring, which
  stays consistent with "colour means risk" since the ring is achromatic.
- `prefers-reduced-motion` respected: the trace and any value transitions
  become instant rather than animated.
- Three webfonts is a real cost; subset to Latin and `display: swap`, with the
  existing system stack as fallback.
