# VoiceTree v2 — Architecture Detail

> Implementation-level diagrams, data models, and component specifications.
> For the high-level vision and decisions, see `NORTH-STAR.md`.

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
        graphdb[("fa:fa-project-diagram Graph DB\n Nodes + Typed Edges\n + Temporal History")]
        vectordb[("fa:fa-search Vector Store\n Embeddings")]
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
    link --> graphdb
    link --> embed
    embed --> vectordb

    graphdb --> graph_q
    vectordb --> vector_q
    graphdb --> bm25
    graph_q --> blend
    vector_q --> blend
    bm25 --> blend

    blend --> ui
    blend --> mcp_out
    graphdb -.->|"on demand"| md_export

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

VoiceTree writes to client configs **once** during setup, not on every launch. The port is fixed. No file injection into project directories. The discovery file is a fallback for clients that aren't pre-configured.

---

## Multi-Project Routing

```mermaid
sequenceDiagram
    actor AgentA as Agent A (project-a)
    participant MCP as VoiceTree MCP :3100
    participant Router as Project Router
    participant VA as Vault A
    participant VB as Vault B
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
    Router->>+VB: query graph + vectors
    VB-->>-Router: ranked results
    Router-->>MCP: results
    MCP-->>-AgentB: search results

    Note over VA,VB: Vaults are independent database instances

    AgentA->>+MCP: search_nodes(project=/project-a, query="related to auth")
    MCP->>Router: resolve vault for /project-a
    Router->>+VA: query graph + vectors
    VA-->>-Router: results
    MCP-->>-AgentA: search results
```

Agents declare which project they're working in. VoiceTree routes to the right vault. Multiple projects active simultaneously as independent database instances.

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
        graphwrite["Write node + edges\n to graph DB (ACID)"]
        vectorwrite["Embed + write\n to vector store"]
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
    participant DB as Graph DB + Vectors
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
- **Project Router**: Map project paths to vaults, manage multi-project state
- **Lifecycle Manager**: System tray, auto-start, graceful shutdown, port management

### Data Layer

- **Graph DB**: Authoritative store for nodes, typed edges, tags, temporal history
- **Vector Store**: Embeddings for semantic search (must be embeddable — no sidecar)
- **Markdown Export**: On-demand export of vault to human-readable `.md` files with frontmatter

### UI (React in Tauri WebView)

- **Graph View**: Sigma.js WebGL renderer with semantic zoom, filtering, focus mode
- **Feed View**: Chronological/relevance-sorted node feed (primary navigation)
- **Search**: Full-text + semantic + graph-aware search
- **Node Editor**: WYSIWYG-ish markdown editor (study Heptabase's interaction model)
- **Terminal Panel**: Embedded terminals for agent spawning
- **Filter Panel**: Filter by type, tag, relation, time, agent, project

### External Integrations (all optional, all pluggable)

- **Voice transcription**: Separate service, consumed via stream
- **ScreenPipe**: Ambient capture via REST API (OCR, windows, audio)
- **MCP Clients**: Any tool that speaks MCP connects to the fixed-port server
- **Git**: Optional commit correlation for temporal graph features
