# Workflows

These pages show how the app works, as diagrams. Each one is short and covers one flow.
They describe the app as built. The [target design](../architecture/target-design.md) is still
the authority for the design and its reasons.

The diagrams are written in [Mermaid](https://mermaid.js.org/). GitHub draws them in the
browser. In VS Code, the "Markdown Preview Mermaid Support" extension does the same.

## Pages

| Page | Diagram types | Read it when |
|---|---|---|
| [User journeys](user-journeys.md) | Flowcharts | You want to know what the Analyst does, page by page. |
| [Import](import.md) | Sequence diagram, flowchart | You work on files, archives, the parser or import errors. |
| [Analysis](analysis.md) | Data-flow chart, sequence diagram | You work on `core`, findings, round stories or recompute. |
| [AI brief and export](ai-brief-and-export.md) | Sequence diagrams | You work on the brief, the payload or the HTML export. |
| [State machines](state-machines.md) | Statecharts | You need the lifecycle of a job, a version, a demo or a brief. |
| [Data model](data-model.md) | ER diagram, folder tree | You touch SQLite, the workspace folder or what may leave the PC. |
| [Runtime](runtime.md) | Flowcharts | You work on startup, the request guard or job concurrency. |
| [Development workflow](dev-workflow.md) | Flowchart, swimlane | You want to change the code and get it merged. |

## Keeping them true

- Change a diagram in the same commit as the code it describes.
- Use names from the code: function, file and error code names.
- Never put real team names, nicknames or SteamIDs in a diagram. Use `a1`–`a5` and `opp`.
- If a diagram and the code disagree, the code wins. Fix the diagram.

## Shared terms

| Term | Meaning |
|---|---|
| Analyst | The person using the app. |
| Entry (analysis) | One team on one map. It has demos, a roster and versions. |
| Extract | The Parquet tables the parser made from one demo. Cached per parser version. |
| Version | One computed result of an entry, in `entries/<id>/v<n>/`. |
| Findings Snapshot | `findings.json` in a version. The UI, the export and the AI brief all read it. |
| Round ref | `<demo label>:r<n>`, for example `3f9a1c2e:r14`. Every finding keeps its refs. |
| Job | Background work (import, recompute, add demos) with progress and cancel. |
