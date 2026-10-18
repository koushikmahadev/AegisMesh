# Design

## 1. UX Principles
1. **One click, one answer.** No forms, no configuration in the main flow.
2. **Numbers first, pixels second.** The big Net % is the headline; masks support it.
3. **Always responsive.** Inference runs server-side; the UI shows a skeleton while waiting and never freezes.

## 2. Layout (desktop, 16:9 for projector)
```
+--------------------------------------------------------------+
| FloodWatch                     [GPU: RTX 3050]  [Offline ●]  |
+----------------------------------------+---------------------+
|                                        |  Tile 0_39_62       |
|                                        |  ┌───────────────┐  |
|              MAP / TILE GRID           |  │  +59.5 %      │  |
|        (clickable tiles, hover         |  │  flood surge  │  |
|         highlight, selected outline)   |  └───────────────┘  |
|                                        |  Before   0.0 %     |
|                                        |  After   59.5 %     |
|                                        |  Latency  0.14 s    |
|                                        |                     |
|                                        |  [Before|After]     |
|                                        |  swipe comparison   |
|                                        |  [x] Water overlay  |
+----------------------------------------+---------------------+
```

## 3. Components
| Component | Responsibility |
|-----------|----------------|
| `MapView` | Renders tiles, handles click/hover, shows selection. |
| `ResultCard` | Headline Net %, Before/After %, latency badge. |
| `CompareSlider` | Swipe between pre and post imagery. |
| `OverlayToggle` | Show/hide water masks (blue = water). |
| `StatusBar` | GPU name, offline indicator, cache hits. |

## 4. Visual Language
- Water mask: semi-transparent cyan `rgba(0, 160, 255, 0.55)`.
- Severity colors on the Net % card:
  - < 5 %: neutral grey
  - 5–30 %: amber
  - > 30 %: red
- Font: system sans; numbers in tabular figures.
- Dark theme default (reads well on projectors).

## 5. States
- **Idle:** "Click a tile to analyze."
- **Loading:** Skeleton card plus pulsing tile outline (should rarely exceed 300 ms).
- **Success:** Card plus overlays.
- **Error (missing tile / bad data):** Inline message, map remains usable.
- **Cached:** Small "⚡ cached" badge.

## 6. Interaction Details
- Hover tile: show ID tooltip.
- Click tile: select, fire request, cancel any in-flight request for the previous tile.
- Keyboard: arrow keys move selection (nice for rapid-fire demos).

## 7. Accessibility
- Don't rely on color alone: show the numeric value and a text label ("Severe surge").
- Minimum contrast 4.5:1 for text.
