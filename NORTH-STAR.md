# VoiceTree v2 — North Star Architecture

> A from-scratch reimagining of VoiceTree as a persistent, always-on knowledge service
> with a proper graph database, daemon architecture, and universal MCP discovery.

---

## Requirements

What must this system do?

- **Capture voice and text input** and convert it into structured, linked knowledge nodes in real time
- **Visualize knowledge as an interactive graph** that remains performant at 10,000+ nodes
- **Serve as a multi-agent control plane** — any AI coding agent (Claude, Copilot, Cursor, Gemini, Codex, Windsurf, Cline) can connect via MCP and create/query/traverse the graph
- **Run always-on** as a background service — no manual project scoping, no "open a folder" step
- **Ingest ambient context** — active window, screen content (OCR), browser tabs, editor state — and route it into the graph with source attribution
- **Support multiple projects simultaneously** — agents working in different repos all connect to the same service, each routed to the right vault/context
- **Store knowledge in a real graph database** with typed edges, ACID transactions, graph traversal algorithms, and indexed queries
- **Export to human-readable markdown** — the graph DB is the runtime store, markdown is the export format
- **Be discoverable by any MCP client** without per-project config file injection
- **Be open source and local-first** — all data stays on the user's machine

---

## Goals

What are we optimizing for?

- **Zero-config agent integration** — any MCP client finds VoiceTree automatically
- **Ambient, effortless capture** — like Granola for meetings, but for all knowledge work
- **Graph-native data model** — typed edges, tags, temporal history, graph algorithms as first-class features
- **Scale** — comfortable at 1,000 nodes, usable at 10,000+, architecturally capable of 100,000+
- **Developer-first** — agents are the primary users, humans navigate via feed/search/graph
- **Single binary / single service** — no Python subprocess, no Redis dependency, no Docker

---

## Non-Goals (Explicitly Out of Scope)

- Cloud sync or collaboration (local-first only, for now)
- Mobile app
- Full Obsidian plugin compatibility
- Real-time collaboration between multiple humans

---

## Decisions

### Runtime: Tauri (Rust + WebView) over Electron

**Why:**
- Single binary distribution (~10MB vs ~150MB Electron)
- Rust backend = no Python subprocess, no Node.js main process
- Native system tray / daemon mode built-in
- IPC is faster (Rust ↔ WebView vs Node ↔ Chromium)
- Lower memory footprint for always-on service

**Trade-off:** Smaller ecosystem than Electron, steeper learning curve for Rust

### Graph Database: Kuzu (embedded) as primary store

**Why:**
- Embeddable — runs in-process like SQLite, no server to manage
- Cypher query language — industry standard for graph queries
- Designed for analytical graph workloads (traversals, aggregations)
- Typed edges, node properties, indexes — all native
- Perfect weight class for a desktop app

**Trade-off:** Younger project than Neo4j, smaller community. But we don't need enterprise features.

### Vector Search: Keep ChromaDB as sidecar (or evaluate Kuzu's future vector support)

**Why:**
- ChromaDB is proven for embedding-based semantic search
- Kuzu doesn't have native vector indexes yet
- Keep them as separate concerns: graph DB for structure, vector DB for semantics
- Evaluate SurrealDB later if we want to collapse both into one

### Graph Rendering: Sigma.js (WebGL)

**Why:**
- Purpose-built for large graph visualization
- WebGL rendering — 10,000+ nodes at 60fps
- Semantic zoom, level-of-detail built in
- Active development, good API

**Trade-off:** Less flexible than Cytoscape.js for custom shapes, but vastly better at scale

### Voice Transcription: Soniox (keep existing) or Whisper (local)

**Why Soniox:** Real-time streaming, good accuracy, already integrated in VoiceTree v1
**Why Whisper:** Local-first, no API dependency, good enough for most use cases
**Decision:** Support both via provider interface. Default to Whisper for local-first, Soniox as opt-in for quality.

### Ambient Capture: ScreenPipe integration

**Why:**
- Open source, already has OCR, active window tracking, audio transcription
- REST API at localhost:3030
- Handles the hard part (screen capture, OCR) so we don't have to
- Active community

### MCP Transport: StreamableHTTP on fixed port

**Why:**
- StreamableHTTP is the current MCP standard (v2025-03-26)
- Fixed port (default 3100, configurable via `VOICETREE_PORT`) — no random port hunting
- Global discovery via well-known file at OS config dir
- One-time `voicetree setup` configures all detected MCP clients

### Frontend Framework: React (keep) with Tailwind

**Why:** React is fine. The UI is not the hard part. Keep what works.

---

## Architecture Overview

```mermaid
architecture-beta
    group external(internet)[External Clients]
    group core(server)[VoiceTree Core Service]
    group ingest(server)[Ingestion] in core
    group querygrp(server)[Query] in core
    group data(database)[Data Layer]

    service agents(internet)[MCP Clients] in external
    service screenpipe(internet)[ScreenPipe] in external

    service mcp(server)[MCP Server :3100] in core
    service router(server)[Project Router] in core
    service voice(server)[Voice Transcriber] in ingest
    service pipeline(server)[Ingestion Pipeline] in ingest
    service engine(server)[Query Engine] in querygrp
    service blender(server)[Blended Ranker] in querygrp

    service kuzu(database)[Kuzu Graph DB] in data
    service chroma(database)[ChromaDB Vectors] in data
    service mdexport(disk)[Markdown Export] in data

    service webview(server)[WebView UI]

    agents:B --> T:mcp
    screenpipe:B --> T:pipeline
    mcp:B --> T:router
    router:L --> R:pipeline
    router:R --> L:engine
    voice:R --> L:pipeline
    pipeline:B --> T:kuzu
    pipeline:B --> T:chroma
    engine:B --> T:blender
    blender:B --> T:kuzu
    blender:B --> T:chroma
    kuzu:R --> L:mdexport
    webview:B --> T:engine
```

---

## Data Flow — Capture to Output

```mermaid
flowchart TB
    subgraph Capture["fa:fa-microphone Capture Layer"]
        direction LR
        voice["fa:fa-microphone Voice Input\n Whisper / Soniox"]
        screenpipe["fa:fa-desktop ScreenPipe\n OCR, windows, audio"]
        agents["fa:fa-robot Agent MCP Tools\n create_graph, etc."]
        manual["fa:fa-edit Manual Edits\n UI editor"]
    end

    subgraph Ingestion["fa:fa-filter Ingestion Pipeline"]
        normalize["Normalize\n& Deduplicate"]
        tag["Auto-Tag\n& Classify"]
        link["Extract Relations\n& Type Edges"]
        embed["Generate\nEmbeddings"]
    end

    subgraph Store["fa:fa-database Data Layer"]
        kuzu[("fa:fa-project-diagram Kuzu Graph DB\n Nodes + Typed Edges\n + Temporal History")]
        chroma[("fa:fa-search ChromaDB\n Vector Embeddings")]
    end

    subgraph Query["fa:fa-cogs Query Engine"]
        graph_q["Cypher\nGraph Traversal"]
        vector_q["Semantic\nVector Search"]
        bm25["BM25\nKeyword Search"]
        blend["Blended Ranking\n graph + vector + BM25\n + tags + recency"]
    end

    subgraph Output["fa:fa-share-alt Output Layer"]
        direction LR
        ui["fa:fa-window-maximize WebView UI\n Sigma.js + Feed"]
        mcp_out["fa:fa-plug MCP Responses\n Tool results"]
        md_export["fa:fa-file-alt Markdown\n Export"]
    end

    voice --> normalize
    screenpipe --> normalize
    agents --> normalize
    manual --> normalize

    normalize --> tag
    tag --> link
    link --> kuzu
    link --> embed
    embed --> chroma

    kuzu --> graph_q
    chroma --> vector_q
    kuzu --> bm25
    graph_q --> blend
    vector_q --> blend
    bm25 --> blend

    blend --> ui
    blend --> mcp_out
    kuzu -.->|"on demand"| md_export

    style Capture fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style Ingestion fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style Store fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style Query fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style Output fill:#fce4ec,stroke:#b71c1c,stroke-width:2px
```

---

## MCP Discovery — One-Time Setup

```mermaid
flowchart LR
    subgraph setup["One-Time Setup"]
        cli["fa:fa-terminal voicetree setup"]
    end

    subgraph configs["Client Configs Written Once"]
        claude["Claude Code\n .mcp.json"]
        vscode["VS Code Copilot\n .vscode/mcp.json"]
        cursor["Cursor\n .cursor/mcp.json"]
        gemini["Gemini CLI\n settings.json"]
        codex["Codex\n config.toml"]
        windsurf["Windsurf\n mcp_config.json"]
    end

    subgraph service["VoiceTree Service"]
        server["fa:fa-server MCP Server\n localhost:3100"]
        portfile["Discovery File\n mcp-server.json"]
    end

    subgraph runtime["Runtime"]
        agent["fa:fa-robot Any MCP Client"]
    end

    cli -->|"detect & write"| claude
    cli -->|"detect & write"| vscode
    cli -->|"detect & write"| cursor
    cli -->|"detect & write"| gemini
    cli -->|"detect & write"| codex
    cli -->|"detect & write"| windsurf
    cli -->|"write"| portfile

    agent -->|"HTTP POST /mcp"| server
    agent -.->|"fallback: read port"| portfile

    style setup fill:#e8eaf6,stroke:#283593,stroke-width:2px
    style configs fill:#f5f5f5,stroke:#616161,stroke-width:1px
    style service fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style runtime fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

**Key point:** VoiceTree writes to client configs **once** during setup, not on every launch. The port is fixed. No file injection into project directories. Any MCP client anywhere on the machine can connect. The discovery file is a fallback for clients that aren't pre-configured.

---

## Multi-Project Routing

```mermaid
sequenceDiagram
    actor AgentA as Agent A (project-a)
    participant MCP as VoiceTree MCP :3100
    participant Router as Project Router
    participant VA as Vault A (Kuzu)
    participant VB as Vault B (Kuzu)
    actor AgentB as Agent B (project-b)

    Note over MCP,Router: All agents connect to same endpoint

    AgentA->>+MCP: create_graph(project=/project-a, nodes=[...])
    MCP->>Router: resolve vault for /project-a
    Router->>+VA: write nodes + typed edges
    VA-->>-Router: committed
    Router-->>MCP: success
    MCP-->>-AgentA: tool result (node IDs)

    AgentB->>+MCP: search_nodes(project=/project-b, query="auth flow")
    MCP->>Router: resolve vault for /project-b
    Router->>+VB: Cypher + vector search
    VB-->>-Router: ranked results
    Router-->>MCP: results
    MCP-->>-AgentB: search results

    Note over VA,VB: Vaults are independent Kuzu databases

    AgentA->>+MCP: search_nodes(project=/project-a, query="related to auth")
    MCP->>Router: resolve vault for /project-a
    Router->>+VA: Cypher + vector search
    VA-->>-Router: results
    MCP-->>-AgentA: search results
```

**Key point:** Agents declare which project they're working in. VoiceTree routes to the right vault. Multiple projects are active simultaneously as independent Kuzu database instances. No folder watching. No config injection.

---

## Ingestion Pipeline Detail

```mermaid
flowchart LR
    subgraph Input["Inbound Events"]
        voice_evt["Voice transcript"]
        screen_evt["ScreenPipe event"]
        mcp_evt["Agent MCP call"]
        edit_evt["UI edit"]
    end

    subgraph Dedupe["Deduplicate"]
        window["Sliding window\n 30s dedupe"]
        hash["Content hash\n exact-match filter"]
    end

    subgraph Enrich["Enrich"]
        classify["Classify source\n voice/ambient/agent/manual"]
        autotag["Auto-extract tags\n from content + context"]
        relations["Infer relations\n parent, references, extends"]
        context["Attach active context\n project, window, URL"]
    end

    subgraph Write["Commit"]
        graphwrite["Write node + edges\n to Kuzu (ACID)"]
        vectorwrite["Embed + write\n to ChromaDB"]
        notify["Notify UI\n via WebSocket"]
    end

    voice_evt --> window
    screen_evt --> window
    mcp_evt --> hash
    edit_evt --> hash

    window --> classify
    hash --> classify

    classify --> autotag
    autotag --> relations
    relations --> context

    context --> graphwrite
    context --> vectorwrite
    graphwrite --> notify
    vectorwrite --> notify

    style Input fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style Dedupe fill:#fce4ec,stroke:#b71c1c,stroke-width:2px
    style Enrich fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style Write fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
```

---

## Graph Data Model

```mermaid
erDiagram
    VAULT {
        uuid id PK
        string name
        string project_path
        datetime created_at
        json settings
    }

    NODE {
        uuid id PK
        uuid vault_id FK
        string title
        text content
        string summary
        string node_type "voice | agent | manual | ambient"
        string source_type "whisper | screenpipe | mcp | editor"
        string source_ref "agent_id or session_id"
        datetime created_at
        datetime modified_at
        json metadata
    }

    TAG {
        uuid id PK
        string name UK
        string category "topic | source | status | custom"
    }

    EDGE {
        uuid id PK
        uuid from_node FK
        uuid to_node FK
        string relation_type "references | depends_on | contradicts | extends | example_of | child_of"
        float weight
        datetime created_at
        string created_by "agent_id or user"
    }

    NODE_VERSION {
        uuid id PK
        uuid node_id FK
        text content_snapshot
        string change_type "created | modified | appended"
        datetime timestamp
        string git_commit "optional SHA"
        string agent_session_id "optional"
    }

    VAULT ||--o{ NODE : "contains"
    NODE ||--o{ EDGE : "outgoing edges"
    NODE }o--|| EDGE : "incoming edges"
    NODE ||--o{ NODE_VERSION : "version history"
    NODE }o--o{ TAG : "tagged with"
```

---

## Lifecycle — Startup and Shutdown

```mermaid
sequenceDiagram
    participant OS as Operating System
    participant Tray as System Tray
    participant Core as VoiceTree Core
    participant MCP as MCP Server
    participant DB as Kuzu + ChromaDB
    participant UI as WebView UI

    Note over OS,UI: Startup (auto-start or manual)

    OS->>Core: Launch VoiceTree
    activate Core
    Core->>DB: Open databases
    activate DB
    DB-->>Core: Ready
    Core->>MCP: Bind to :3100
    activate MCP
    MCP-->>Core: Listening
    Core->>Tray: Show tray icon
    activate Tray
    Core->>UI: Open WebView (if not headless)
    activate UI
    UI-->>Core: Connected

    Note over OS,UI: Running (always-on)

    Note over OS,UI: Shutdown (quit or OS signal)

    OS->>Core: SIGTERM / Quit
    Core->>UI: Close WebView
    deactivate UI
    Core->>MCP: Drain connections, close
    deactivate MCP
    Core->>DB: Flush + close
    deactivate DB
    Core->>Tray: Remove icon
    deactivate Tray
    Core-->>OS: Exit 0
    deactivate Core
```

---

## Component Responsibilities

### Core Service (Rust / Tauri backend)

- **MCP Server**: Fixed-port StreamableHTTP server exposing tools to agents
  - `create_graph` — batch node/edge creation with DAG support
  - `search_nodes` — blended retrieval (graph + vector + tags + time)
  - `spawn_agent` — terminal spawning with worktree isolation
  - `wait_for_agents` — async agent coordination
  - `get_graph` — graph state queries (neighbors, paths, subgraphs)
  - `set_project` — declare active project context
- **Ingestion Pipeline**: Normalize, deduplicate, auto-tag, extract relations, write to graph DB
- **Query Engine**: Cypher graph queries + vector search + blended ranking
- **Voice Transcriber**: Whisper (local) or Soniox (cloud) via provider interface
- **Project Router**: Map project paths to vaults, manage multi-project state
- **Lifecycle Manager**: System tray, auto-start, graceful shutdown, port management

### Data Layer

- **Kuzu Graph DB**: Authoritative store for nodes, typed edges, tags, temporal history
- **ChromaDB**: Vector embeddings for semantic search (sidecar process or embedded)
- **Markdown Export**: On-demand export of vault to human-readable `.md` files with frontmatter

### UI (React in Tauri WebView)

- **Graph View**: Sigma.js WebGL renderer with semantic zoom, filtering, focus mode
- **Feed View**: Chronological/relevance-sorted node feed (primary navigation)
- **Search**: Full-text + semantic + graph-aware search
- **Node Editor**: WYSIWYG-ish markdown editor (study Heptabase's interaction model)
- **Terminal Panel**: Embedded terminals for agent spawning
- **Filter Panel**: Filter by type, tag, relation, time, agent, project

### External Integrations

- **ScreenPipe**: Ambient capture via REST API (OCR, windows, audio)
- **MCP Clients**: Any tool that speaks MCP connects to the fixed-port server
- **Git**: Optional commit correlation for temporal graph features

---

## What We Take From VoiceTree v1

Ideas and patterns worth preserving:

- **MCP tool API design** — `create_graph`, `spawn_agent`, `wait_for_agents` are well-designed tools
- **Voice → structured nodes pipeline** — the concept works, even if the implementation needs replacing
- **Progress graph for agents** — unique paradigm, keep it
- **Pure/shell architecture split** — good principle, apply it in Rust (pure functions vs I/O boundary)
- **Auto-positioning algorithms** — graph layout heuristics from `createGraphTool.ts`
- **Worktree management** — git worktree isolation for agent work

What we explicitly leave behind:

- Markdown files as runtime source of truth
- Per-project config file injection
- Random port binding
- Python subprocess for backend
- Chokidar file watching as primary ingestion
- 300-node hard cap
- Canvas-based Cytoscape rendering
- Fire-and-forget async patterns (`void startMcpServer()`)

---

## Open Questions

- **Kuzu vs SurrealDB**: SurrealDB offers graph + document + vector in one DB. Worth the maturity risk?
- **Tauri vs Electron**: Tauri is the better architecture, but Electron has the bigger ecosystem. Is the team comfortable with Rust?
- **Whisper model size**: Which Whisper model balances accuracy vs resource usage for always-on?
- **ScreenPipe dependency**: Hard dependency or optional integration? What if ScreenPipe isn't running?
- **Obsidian compatibility**: Should markdown export be Obsidian-compatible (frontmatter + wikilinks)?
- **License**: MIT? AGPL? Affects community adoption.
