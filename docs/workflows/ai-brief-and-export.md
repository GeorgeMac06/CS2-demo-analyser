# AI brief and export

The two ways a scouting result leaves the app. Both start from the same filtered snapshot
(see [Analysis](analysis.md#filtered-views-s7)). Both block SteamIDs and file paths.

## AI brief

Code: `web/api.py` (`preview_brief`, `create_brief`), `ai/payload.py`, `ai/confirm.py`,
`ai/client.py`, `ai/grounding.py`, `ai/instructions.md`. Design: target design §6.5.

Nothing is sent before the Analyst has seen the exact payload. The confirm token is bound to
the payload's hash, so a changed filter or a new version needs a new preview.

```mermaid
sequenceDiagram
  autonumber
  actor Analyst
  participant UI as Browser
  participant API as web/api
  participant Pay as ai.payload
  participant Conf as ai.confirm
  participant Cl as ai.client
  participant Ant as Anthropic API
  participant Gr as ai.grounding
  participant Lib as store.Library

  Analyst->>UI: AI brief tab, Preview
  UI->>API: POST .../ai-brief/preview {filter}
  API->>API: API key set? else AI_DISABLED
  API->>Pay: build(filtered snapshot, entry, filter, stories)
  Pay->>Pay: check(): no SteamIDs or paths, else EXPORT_BLOCKED
  API->>Conf: make(secret, entry, payload hash) — valid 10 min
  API-->>UI: payload, instructions, token estimate, price, token
  Analyst->>UI: Send
  UI->>API: POST .../ai-brief {filter, token}
  API->>Pay: build again from current data
  API->>Conf: valid(token, entry, new hash)?
  alt hash changed or token expired
    API-->>UI: 403 FORBIDDEN, preview again
  else token already used
    API-->>UI: 403 FORBIDDEN
  else another brief for this entry is running
    API-->>UI: 409 CONFLICT_JOB_RUNNING
  else ok
    API->>Cl: write_brief(payload) — streamed, JSON schema output
    Cl->>Ant: messages.stream
    Ant-->>Cl: sections → plays → points, each citing findings or rounds
    alt SDK error, refusal or max_tokens
      Cl-->>API: Upstream
      API-->>UI: 502 AI_UPSTREAM
    else answer
      API->>Gr: ground(answer, findings, rounds)
      Gr->>Gr: drop claims with no or unknown citations
      alt more than 20% dropped
        Gr-->>API: Ungrounded
        API-->>UI: 422 AI_UNGROUNDED
      else grounded
        API->>Lib: save_brief(entry, version, model, hash, brief, usage, cost)
        API-->>UI: brief with evidence and Markdown download
      end
    end
  end
```

What the payload holds, and what it does not:

| Sent | Never sent |
|---|---|
| Findings that pass support: id, kind, title, params, k of n, outcome, recency | `round_refs`, grids, `land`/`throw`/`hit_times_s` params |
| Roster: player key and nickname | SteamIDs |
| One story per round, times on the round timer | Raw demos, file paths |
| Demo labels and dates, the active filter, the callout glossary | The API key |

## Export

Code: `web/export_view.py` (`render`), `export/inline.py`, `templates/export.html`.
Design: target design §6.4.

```mermaid
sequenceDiagram
  autonumber
  actor Analyst
  participant UI as Browser
  participant Pg as web/pages
  participant Ex as export_view.render
  participant In as export.inline

  Analyst->>UI: pick sections, maps on or off
  UI->>Pg: GET /ui/entries/{id}/export
  Pg->>Ex: render(entry, sections, filter, maps)
  Ex->>Ex: filtered snapshot, else NOT_COMPUTED
  loop each chosen section
    Ex->>Ex: skip the AI brief if missing or stale
    Ex->>Pg: same tab template, static=True
  end
  opt maps on and radar assets present
    Ex->>In: data_uri(radar PNGs)
  end
  Ex->>Ex: export.html with inline CSS, Plotly.js, export.js and a CSP meta tag
  Ex->>In: leaks(html)
  alt SteamID or Windows path found
    Ex-->>UI: EXPORT_BLOCKED, nothing written
  else clean
    Ex-->>UI: one .html file as a download
  end
```

The CSP is `default-src 'none'` with inline scripts and styles and `data:` images. The file
cannot make a network request when someone opens it.
