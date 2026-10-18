# HighWater Dashboard: Design (Member 1)

The interface is a decision-support tool for people under time pressure. Prioritise clarity, hierarchy and honesty over decoration.

## 1. Principles

1. **Map first.** The map and key stats stay visible; the header stays compact.
2. **Colour is a signal, not decoration.** Red means HIGH risk. The page background is never red.
3. **Never colour alone.** Every risk colour pairs with a text label, icon or pattern.
4. **Say what you do not know.** UNKNOWN and "Not available" are first-class states.
5. **Show where data comes from.** DEMO MODE, timestamps and provenance are always visible.

## 2. Design tokens

All values live in `config/theme.js` and are exposed as Tailwind theme extensions or CSS variables.

### Colour

| Token | Hex | Use |
|---|---|---|
| `navy-900` | `#0B1F33` | Header, primary navigation |
| `navy-700` | `#16344F` | Header accents, headings on light |
| `surface` | `#F4F6F8` | Page background |
| `card` | `#FFFFFF` | Cards, panels |
| `border` | `#D5DBE1` | Dividers and card borders |
| `text` | `#1B2733` | Body text |
| `text-muted` | `#5B6B7B` | Secondary text |
| `flood` | `#2B8CC4` | Flood extent fill and outline (fill opacity 0.35) |
| `risk-high` | `#C62828` | HIGH |
| `risk-medium` | `#E69F00` | MEDIUM |
| `risk-low` | `#2E7D32` | LOW |
| `risk-unknown` | `#6B7280` | UNKNOWN |
| `route` | `#6A1B9A` | Rescue route, distinct from risk and flood colours |
| `selected` | `#0B1F33` | Selected-zone outline (thick) |
| `demo` | `#B26A00` on `#FFF3D6` | DEMO MODE badge |

Check text contrast against its background (aim for WCAG AA, 4.5:1 for body text). Risk colours on white are used for outlines and badges with dark or white text chosen for contrast.

### Typography

| Role | Spec |
|---|---|
| Font | System UI stack (`ui-sans-serif, system-ui, Segoe UI, Roboto, sans-serif`) |
| App title | 18 px, semibold, wide letter-spacing |
| Section heading | 16 px, semibold |
| Stat value | 28 px, bold |
| Body | 14 px |
| Caption and legends | 12 px |

### Spacing, radius, elevation
- Spacing scale: 4, 8, 12, 16, 24, 32 px
- Card radius: 8 px; badge radius: 999 px
- Cards use a 1 px border and a subtle shadow; no heavy drop shadows

## 3. Layout

### Desktop (1024 px and up)

```
┌──────────────────────────────────────────────────────────────┐
│ HIGHWATER  Study area   [DEMO MODE]   Updated 10:00   Refresh │
├──────────────────────────────────────────────────────────────┤
│ [Flooded area] [High-priority zones] [Exposed bldgs] [Blocked]│
├───────────────────────────────────────────┬──────────────────┤
│                                           │ Layer controls   │
│              FLOOD MAP                    │ Zone details     │
│                                           │                  │
├───────────────────────────────┬───────────┴──────────────────┤
│ Priority zone list + filters  │  Charts (risk, impact)       │
└───────────────────────────────┴──────────────────────────────┘
```

### Tablet (640 to 1023 px)
- Two stat cards per row
- Map full width; side panel moves beneath the map or becomes collapsible
- Touch targets at least 44 px

### Mobile (below 640 px)
- One or two stat cards per row
- Full-width map with a usable minimum height (about 50 vh)
- Filters and zone details open in a bottom drawer
- No horizontal page overflow

## 4. Components

### Header
Compact (about 56 px). Left: logo and name. Centre or right: study area, data timestamp, source status, **DEMO MODE** badge, refresh button. Refresh shows a spinner while loading and is disabled during an in-flight request.

### Stat card
Value, label, optional one-line note. A demo-derived value carries an "Illustrative" caption. Missing data shows "Not available", not 0.

### Map
- Base tiles with attribution
- Layer control panel (compact), reset-extent button, legend
- Selected zone: thick `selected` outline plus raised fill opacity
- Zone popup: name, risk label, one key figure
- Offline fallback: neutral background with a "Map tiles unavailable" notice; overlays still render

| Data | Style |
|---|---|
| Flood extent | `flood` fill 0.35, 1.5 px darker outline |
| HIGH / MEDIUM / LOW zone | Risk outline 2 px, fill opacity 0.25 |
| UNKNOWN zone | Grey outline, diagonal hatch fill or 0.15 grey fill, dashed outline |
| Blocked road | `risk-high` dashed line, 4 px |
| Route | `route` solid line, 5 px, white casing |
| Facility | Icon by type: hospital, shelter, depot |

### Legend
Shows only enabled overlays. Each entry has a swatch plus text. Also lists the provenance badge meanings when present.

### Layer controls
Five switches with labels and a count ("Enabled overlays: 4 of 5"). Each has a visible focus state and a text label.

### Risk badge
Pill with icon and text (`HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`). Never a bare colour dot.

### Provenance badge (when supplied)
| Value | Label | Style |
|---|---|---|
| `observed` | Observed | Solid navy pill |
| `derived` | Derived | Outlined navy pill |
| `simulated` | Simulated | Dashed amber pill |

### Zone list
Row: rank, name, risk badge, score (or "Not available"), exposed buildings. Selected row is highlighted and scrolled into view. Controls above: search field, risk-level filter, sort selector. Rows without geometry show a small "No map shape" note.

### Zone details panel
Header with zone name and risk badge, then: flood coverage, exposed buildings, accessibility, score, reasons list, last-updated. Empty state when nothing is selected: "Select a zone on the map or in the list."

### Charts
- **Risk distribution:** bar chart, four bars in risk colours with text labels on each
- **Impact:** horizontal bars for exposed buildings by zone, top N zones
- Both: title, axis labels, tooltip, and a "No data" placeholder

### State screens
| State | Content |
|---|---|
| Loading | Skeletons for cards, map area and list, plus "Loading data…" |
| Empty | "No zones available" with explanation; no map overlays implying safety |
| Error | Plain-language message, retry button, rest of shell visible |
| Stale | Amber banner: "Data last updated HH:MM. This may be out of date." |
| Layer failure | Inline small warning on that layer; the rest keeps working |

## 5. Copy guidelines

- Use plain, operational language: "Restricted access", not "Accessibility impaired".
- Reasons are short phrases from the data, not generated text.
- Demo labels: "DEMO MODE" in the header; "Illustrative data" on affected stats.
- Never say "live" or "real-time" unless the payload says so.

## 6. Accessibility

| Requirement | Approach |
|---|---|
| Keyboard | Tab order follows visual order; list rows and layer toggles reachable and operable |
| Focus | Visible 2 px focus ring on all interactive elements |
| Colour independence | Risk badges carry text and icons; UNKNOWN zones use pattern or dashed outline |
| Contrast | AA for text and for UI component boundaries |
| Screen readers | Labels on toggles and buttons; `aria-live="polite"` on the details panel and status messages |
| Motion | No essential information conveyed by animation |

## 7. Responsive checklist

- [ ] 360 px: no horizontal scroll, drawer works
- [ ] 768 px: two-column stat cards, map prominent
- [ ] 1280 px: full desktop layout
- [ ] Map resizes correctly when the drawer or panel opens and closes
