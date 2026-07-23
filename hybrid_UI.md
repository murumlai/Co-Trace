# Hybrid UI Migration Plan

## Decision

Replace the current Neumorphic visual system app-wide with the Hybrid UI direction:

- Enterprise light shell for the main application, dashboards, forms, tables, and charts.
- Embedded terminal-dark treatment for raw or redacted trace snippets.
- Preserve the existing React, Vite, Tailwind, Recharts, auth, upload, job polling, Engineer, and Manager behavior.
- Defer Golden Trace / Vector Match features until the backend exposes real data for them.

This plan supersedes the current Neumorphism direction in `designUI.md` for the UI migration branch.

## Current Repo Fit

The app already has the functional foundation needed for this design:

- `frontend/src/App.jsx` owns the authenticated shell, tab navigation, theme persistence, batch upload state, warnings, and stop-batch behavior.
- `frontend/src/components/ui.jsx` contains the shared UI primitives that should be refactored first.
- `frontend/src/pages/Home.jsx` owns upload selection, drag/drop, zip validation, progress, and batch actions.
- `frontend/src/pages/Engineer.jsx` owns unit grouping, filters, serial selection, table/card views, failure details, re-analysis, cache clearing, and redacted snippets.
- `frontend/src/pages/Manager.jsx` owns KPI cards and Recharts visualizations for summary, trend, Pareto, station/tester, and lot views.
- `backend/app/aggregator.py` already exposes Pareto `cum_pct`, so the cumulative Pareto line can be implemented without backend changes.
- `backend/app/record_views.py` confirms the Engineer view receives grouped units classified as `first_pass`, `retry_pass`, `fail`, or `unknown`.

## Visual System

### Enterprise Light Shell

Use these tokens as the new default app language:

- Page background: `#F8FAFC` or `#F1F5F9`.
- Primary surface: `#FFFFFF`.
- Secondary surface: `#F8FAFC`.
- Border: `#E2E8F0`.
- Muted border: `#CBD5E1`.
- Primary text: `#0F172A`.
- Secondary text: `#475569`.
- Muted text: `#64748B`.
- Primary action: `#2563EB`.
- Primary action hover: `#1D4ED8` or `#1E40AF`.
- Pass / high FPY: `#059669` or `#10B981`.
- Warning / marginal: `#D97706` or `#F59E0B`.
- Failure / critical: `#DC2626` or `#EF4444`.
- Shadows: subtle, low blur, low opacity, used only for panel hierarchy.
- Radii: restrained enterprise radii, generally `8px` to `12px`; reserve larger radii for large containers only if needed.

Typography should remain highly legible for dense dashboards. Keep the current `Plus Jakarta Sans` / `DM Sans` pairing unless a separate font decision is made. Add a monospace token for trace content.

### Embedded Terminal Dark

Use this only for log and trace surfaces:

- Terminal background: `#0F172A`.
- Terminal raised surface: `#1E293B`.
- Terminal border: `#334155`.
- Terminal text: `#E2E8F0`.
- Terminal muted text: `#94A3B8`.
- Warning: `#F59E0B`.
- Error: `#EF4444`.
- Success / pass: `#10B981`.
- Timestamp / syntax accent: `#06B6D4`.
- Font: `JetBrains Mono`, `Fira Code`, or `ui-monospace` fallback.

## Implementation Phases

### 1. Replace Global Tokens

Update `frontend/src/index.css` and `frontend/tailwind.config.js`.

- Replace cool-clay Neumorphic variables with enterprise light shell variables.
- Replace extruded/inset shadow tokens with subtle elevation tokens.
- Add terminal-dark variables for trace viewers.
- Keep accessible focus styling for all interactive controls.
- Keep dark-mode support only if it remains useful, but convert it to a conventional enterprise dark theme instead of Neumorphic shadows.

### 2. Refactor Shared UI Primitives

Update `frontend/src/components/ui.jsx` before page-level work.

- Refactor `Card`, `Button`, `Input`, `Badge`, and `Stat` to use border, surface, elevation, and accessible focus styles.
- Add or split primitives as needed:
  - `Panel`
  - `MetricCard`
  - `StatusBadge`
  - `SegmentedControl`
  - `ToolbarButton`
  - `TableShell`
- Keep components composable and avoid one-off visual styles inside pages where a shared primitive makes sense.

### 3. Rebuild The Authenticated Shell

Update `frontend/src/App.jsx`.

- Keep `AuthProvider`, tab state, job state, batch progress, warnings, `stopBatch`, theme persistence, and logout behavior.
- Restyle the header as an enterprise top bar.
- Keep existing tabs: Home, Engineer, Manager, About.
- Rename the visible app title if desired to `Smart Trace Log Analytics`, but keep `Co-Trace` identity where useful.
- Do not add fake station or time-range controls until real filtering exists in the API.
- A global search can be added only if wired to current job/unit data and routed into Engineer view.

### 4. Restyle App-Wide Pages

Update these pages for visual consistency:

- `frontend/src/pages/Login.jsx`
- `frontend/src/pages/Home.jsx`
- `frontend/src/pages/About.jsx`

Keep all existing behavior. Only migrate layout, spacing, color, borders, focus states, and typography.

For Home, preserve:

- Folder upload.
- File upload.
- Single zip upload.
- Drag/drop traversal.
- 1000-file validation.
- Upload summary.
- Progress bar.
- Stop-batch action.
- Error display.

### 5. Redesign Manager View

Update `frontend/src/pages/Manager.jsx` using existing API data from `api.manager(jobId)`.

Keep these data surfaces:

- FPY.
- Total runs.
- Unique units.
- Retests.
- Passed count.
- Failed count.
- Yield trend.
- Failure Pareto.
- Station/tester breakdown.
- Lot-to-lot comparison.

Enhancements that fit the current backend:

- Add a top failure category metric from `data.pareto[0]` when available.
- Add a cumulative percentage line to the Pareto chart using `cum_pct` from `backend/app/aggregator.py`.
- Use denser, scannable enterprise panels rather than large decorative cards.
- Keep chart colors semantically constrained: blue for primary series, green for pass, red for fail, amber for warning/marginal.

Do not add previous-shift trend labels unless the backend exposes previous-shift or time-window data.

### 6. Redesign Engineer View

Update `frontend/src/pages/Engineer.jsx` around the real unit group data from `api.units(jobId)`.

Keep existing behavior:

- Classification counts and filters.
- Serial filter.
- Table view.
- Optional card view if still useful on small screens.
- Failure detail expansion.
- Retry-pass explanation.
- Re-analyze action.
- Clear cached result action.
- Redacted snippet display.

Recommended table columns using available data:

1. Timestamp.
2. Board serial ID.
3. Product.
4. Test station / host.
5. Lot.
6. Status.
7. Attempts.
8. Primary failure code / message.
9. AI suggested root cause.
10. Recommended action.
11. Actions.

Do not show AI confidence, vector score, or golden-reference score until the backend provides those values.

### 7. Add `TerminalViewer`

Create `frontend/src/components/TerminalViewer.jsx` or place the component with shared UI primitives if small.

The component should accept:

- `text`: raw or redacted snippet string.
- Optional `title`.
- Optional `sourceLabel`.
- Optional `errorCode`.
- Optional `failingStep`.
- Optional `timestamp`.

Required behavior:

- Terminal-dark visual treatment.
- Monospace line rendering.
- Horizontal scrolling and readable wrapping controls where appropriate.
- Inline search or grep-style filter.
- Simple severity highlighting for `INFO`, `WARN`, `WARNING`, `ERROR`, `ERR`, `FAIL`, `FAILED`, and `CRITICAL`.
- Empty state for missing snippets.
- Keyboard-accessible controls.

First integration target:

- Replace the current light `<pre>` block in `FailureBlock` inside `frontend/src/pages/Engineer.jsx`.

Optional later enhancement:

- Convert the inline viewer into a side drawer or modal once focus management and mobile layout are designed.

## Golden Trace / Vector Match Decision Point

### What It Means

A Golden Trace is a known-good reference run or fingerprint for a specific product, station, test program, or flow. A Vector Match feature compares a failed run against stored reference traces or historical failure signatures and returns similarity evidence, such as:

- Closest known-good trace.
- Closest known-failure pattern.
- Similarity score.
- Diff summary.
- Matching log regions.
- Confidence explanation.

### Current Repo Reality

This repo does not currently expose:

- Golden reference traces.
- Trace embeddings.
- Vector similarity scores.
- AI confidence scores.
- Golden-vs-current diff payloads.
- Backend APIs for trace comparison.
- Persistent reference-trace storage.

The frontend currently has real data for:

- Redacted failure snippets.
- Error code.
- Error message.
- Failing step.
- Root cause.
- Suggested solution.
- Analysis source.
- Analysis cache key.

### Recommendation

Defer Golden Trace / Vector Match UI until the feature is backed by real backend data. Do not mock confidence scores or vector-match percentages in production UI because that could mislead engineers during failure analysis.

If approved later, implement it as a separate feature with:

- Reference-log ingestion.
- Product/station/test-program reference selection rules.
- Fingerprint or embedding generation.
- Persistent reference store.
- Comparison service.
- API fields for score, diff, and matched regions.
- Backend tests.
- Frontend tabs in `TerminalViewer` for Raw Trace, Golden Comparison, and Match Details.

## Out Of Scope For This UI Pass

- Fake AI confidence badges.
- Fake vector match percentages.
- Fake golden trace diffs.
- New backend data model for reference traces.
- New backend vector or embedding service.
- Station/time-range filters that do not affect real API data.

## Documentation Updates

After implementation, update `README.md` so it no longer says the app follows the Neumorphism/Soft UI visual system from `designUI.md`.

Recommended wording:

> The implementation uses the Hybrid UI system defined in `hybrid_UI.md`: an enterprise light shell for dashboard workflows and a terminal-dark trace viewer for log evidence.

Avoid broad documentation churn until the code migration is complete.

## Verification

Frontend verification:

```powershell
cd frontend
npm run build
```

Manual app verification:

- Login.
- Upload folder.
- Upload individual files.
- Upload single zip.
- Batch progress.
- Stop batch.
- Warning banner dismissal.
- Navigation between Home, Engineer, Manager, and About.
- Theme control if retained.
- Sign out.
- Session expiry recovery.
- Manager KPI cards and charts.
- Pareto cumulative percentage line.
- Station/tester breakdown.
- Lot comparison table.
- Engineer filters.
- Serial filter.
- Engineer table horizontal scroll.
- Failure detail expansion.
- Re-analysis action.
- Clear cached result action.
- TerminalViewer snippet search and highlighting.
- Mobile and desktop responsive layouts.

Backend verification is only required if the Golden Trace / Vector Match feature is approved and backend contracts change:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
```