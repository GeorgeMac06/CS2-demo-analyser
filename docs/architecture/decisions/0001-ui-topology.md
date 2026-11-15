# ADR-001: Server-rendered UI (FastAPI + Jinja2 + htmx + Plotly), one renderer for the app and the export

| Field | Value |
|---|---|
| Status | **Accepted**, on 2026-11-15, by the owner in chat ("Accept, plan delivery") |
| Date | 2026-11-15 (proposed and accepted the same day) |
| Owner / decider | Repository owner |
| Source | [target-design.md §9](../target-design.md) (row ADR-001) |
| Affects | Requirements D1, D7, FR-EXP-1..3, J3, C-3. Baseline DRV-6, DRV-15, QS-5. |

## Context

The product is a local web app (D1). One user scouts one team on one map at a time. It must:
- show interactive radar heatmaps, charts and tables, with filters for side, round type, demos and dates (J3);
- export a **self-contained HTML file** that teammates open offline, with the same content (FR-EXP-1/2, DRV-6).

The owner's previous projects are all in Python. Node 20 is installed, but no project uses it. There is one user and no speed target (D5). All analysis logic will be Python, because the demo parser and Polars are Python (ADR-002).

The UI technology is the costliest decision to change after building starts. Every page, chart and the export depend on it.

## Decision drivers

1. **Parity between the export and the app.** The export must show the same findings and visuals as the app, with no network (DRV-6, FR-EXP-2).
2. **Interactive radar visuals and filters** (FR-PLR-3, J3).
3. **Low complexity for a solo maintainer.** One language and as few toolchains as possible.
4. **Reversibility.** Richer interaction can be added later (Q6 replay viewer) without a rewrite.
5. **Accessibility** (C-3). Every chart has a table or text equivalent.

## Considered options

| Option | Export parity | Interactivity | Complexity | Notes |
|---|---|---|---|---|
| A. Streamlit | Weak. No first-class static export, and the report must be rebuilt separately. | Good for widgets. The rerun-on-every-change model makes stable filter state and pattern labels awkward. | Lowest | Layout control is limited |
| B. Dash (Plotly) | Medium. Figures export, but the page layout must be assembled again for the export. | Good | Medium. Callback graphs grow quickly. | Python only |
| **C. FastAPI + Jinja2 + htmx + Plotly** | **Strong.** The same templates render in `static` mode, with figure specs inlined. | Good. Plotly gives hover, zoom and heatmaps over radar images. htmx gives partial updates. | **Low-medium.** Python plus two vendored JS files. No build step. | Rich client-side state is harder |
| D. FastAPI JSON API + React/TS SPA | Strong, but it needs a separate single-file build of the SPA plus data injection | Best | Highest. A second language, a Node build, and two codebases to keep in step. | Best for canvas-heavy views such as a 2D replay |

The status quo is not an option: the repository has no UI.

## Decision

The app will be built as:
- a **FastAPI** server bound to loopback, which renders **Jinja2** templates;
- **htmx** for partial page updates (filters, job progress, round lists);
- **Plotly** figures whose specs are built in Python and rendered by a vendored Plotly.js.

Export renders the **same templates** with `mode=static`:
- all scripts and images are inlined;
- a CSP blocks all network access.

Each chart is paired with a data table.

**Deliberately undecided:**
- the CSS approach (a plain stylesheet or a classless/utility CSS file, vendored);
- the exact Plotly.js bundle (full or partial);
- any future JS "island" for a replay viewer.

## Consequences

- **Positive:**
  - The export and the app cannot drift apart, because one template set and one figure builder serve both.
  - Analysis, figures and pages are all in Python.
  - There is no Node toolchain at runtime or in normal development.
  - Figure specs can be unit-tested as data.
- **Negative:**
  - Client-side interactions such as linked brushing and drag-to-select are harder than in an SPA.
  - The full Plotly.js adds about 4.6 MB to each export [E].
- **Neutral:**
  - Pages stay server-driven. Every filter change is a round trip on loopback, which is negligible for one user.
- **Accepted risk:**
  - A 2D round-replay viewer (Q6, a v2 candidate) would need a custom JS component.

## Validation

- **Before acceptance:** the owner agrees to a Python-centric stack with no SPA framework.
- **During delivery:**
  - AT-10 (in `target-design.md` §10): the export opens offline with 0 network requests, and every figure renders.
  - The size of a typical export is measured. It must stay under 15 MB [P threshold] so it is easy to share.
- **After adoption:** monitor for htmx partials growing complex, i.e. one view needing more than ~3 coordinated partial swaps or its own client state.

## Review triggers

- A 2D replay viewer is accepted (Q6), or a view needs canvas-level interaction. First add a JS island for that view. Reconsider option D only if several views need it.
- Exports grow too large to share. Then use a partial Plotly.js bundle before changing the topology.
- Teammates need to use the app live rather than read exports. That reopens the hosting and security decisions, not only this one.
