# Runtime

How the app starts, which requests it lets in, and how background work shares the machine.
Code: `__main__.py`, `settings.py`, `web/app.py`, `web/security.py`, `jobs/runner.py`.

## Startup

```mermaid
flowchart TD
  A["uv run cs2scout"] --> B["Settings.from_env<br/>CS2SCOUT_HOME or %LOCALAPPDATA%\CS2DemoScout<br/>CS2SCOUT_PORT, else settings.json, else 8765<br/>ANTHROPIC_API_KEY from env or .env"]
  B --> C["New session token<br/>secrets.token_urlsafe(32)"]
  C --> D["create_app"]
  D --> E["Library: open or create library.sqlite"]
  E --> F["startup_cleanup<br/>delete building versions<br/>mark queued and running jobs failed<br/>delete _partial extracts and tmp/cs2scout-*"]
  F --> G["JobRunner: 4 worker threads, 1 parse slot"]
  G --> H["New AI secret for preview tokens"]
  H --> I["Routes: /api, pages, /static<br/>LocalGuard middleware"]
  I --> J["uvicorn on 127.0.0.1 only"]
  J --> K["Browser opens the app"]
```

A restart makes every open AI preview invalid, because the AI secret is new.

## Request guard

Every HTTP request passes `LocalGuard` before it reaches a route. It stops other machines,
DNS rebinding and other web pages from driving the app.

```mermaid
flowchart TD
  A["Request"] --> B{"Host is 127.0.0.1:port<br/>or localhost:port?"}
  B -->|No| X["403 FORBIDDEN<br/>Host not allowed"]
  B -->|Yes| C{"POST, PUT, PATCH or DELETE?"}
  C -->|Yes| D{"Origin is this app?"}
  D -->|No| Y["403 FORBIDDEN<br/>Origin not allowed"]
  D -->|Yes| E
  C -->|No| E{"Path under /api/<br/>or unsafe method?"}
  E -->|No| OK["Route runs"]
  E -->|Yes| F{"Path is /api/health?"}
  F -->|Yes| OK
  F -->|No| G{"X-CS2Scout header<br/>= session token?"}
  G -->|No| Z["403 FORBIDDEN<br/>Missing or invalid session token"]
  G -->|Yes| OK
```

Pages get the token in a meta tag. htmx sends it on every request. Websockets are closed.
The OpenAPI docs are turned off.

## Concurrency

```mermaid
flowchart LR
  subgraph Server["Server process"]
    REQ["Request threads"]
    subgraph Pool["JobRunner pool: 4 threads"]
      J1["Job: entry 1"]
      J2["Job: entry 2"]
      J3["Job: import, no entry yet"]
    end
    SLOT{{"parse_slot lock<br/>one parse at a time"}}
    AIL{{"ai_lock<br/>one brief per entry"}}
  end
  CH["Parse child process<br/>spawned, killed on cancel or timeout"]

  REQ -->|"submit; refused if the entry is busy"| Pool
  J1 --> SLOT
  J2 --> SLOT
  J3 --> SLOT
  SLOT --> CH
  REQ --> AIL
```

- One job per entry at a time. A second one gets `CONFLICT_JOB_RUNNING`.
- Jobs for different entries run side by side. They wait for each other only at the parse
  slot.
- Analysis work (Polars) runs in the job thread, not in the child.
- An AI brief runs in the request thread, not as a job. `ai_busy` stops a second brief for the
  same entry.
- On shutdown the runner sets every cancel flag and waits for the threads.
