# VoiceTree v2 — North Star

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
- **Be discoverable by any MCP client** without per-project config file injection

> **TODO**: These requirements are a mix of confirmed user goals and inferred architectural needs. Needs review to separate "must have" from "should have."

---

## Goals

What are we optimizing for?

- **Ambient, effortless capture** — like Granola for meetings, but for all knowledge work
- **Graph-native data model** — typed edges, tags, temporal history, graph algorithms as first-class features
- **Scale** — comfortable at 1,000 nodes, usable at 10,000+, architecturally capable of 100,000+
- **Developer-first** — agents are the primary users, humans navigate via feed/search/graph
- **Pluggable inputs** — voice, ambient capture, and agent tools are separate concerns that plug into a common ingestion pipeline

> **TODO**: Goals section needs owner input. Some of these are inferred, not stated.

---

## Non-Goals (Explicitly Out of Scope)

- Mobile app
- Real-time collaboration between multiple humans

> **TODO**: Needs review. Is cloud sync a non-goal? Is Obsidian compatibility a non-goal?

---

## Decisions

What stack did we choose and why?

### Runtime: Tauri (Rust + WebView) over Electron

- Rust backend eliminates Python subprocess and Node.js main process
- Native system tray / daemon mode for always-on operation
- Lower memory footprint
- **Trade-off:** Steeper learning curve, smaller ecosystem

### Graph Database: Kuzu (embedded) as primary store

- Embeddable — runs in-process like SQLite, no server to manage
- Cypher query language — industry standard for graph queries
- Typed edges, node properties, indexes — all native
- **Trade-off:** Younger project, smaller community
- **Open question:** SurrealDB offers graph + document + vector in one DB — worth the maturity risk? Would eliminate the need for a separate vector store

### Vector Search: Needs resolution

- Kuzu doesn't have native vector indexes yet
- ChromaDB is Python-based — would be a sidecar process, contradicting the embedded approach
- **Options:** LanceDB (embeddable, Rust bindings), SurrealDB (built-in vectors), or wait for Kuzu vector support
- **Open question:** Unresolved. See `ARCHITECTURE.md` for analysis.

### Graph Rendering: Sigma.js (WebGL)

- Purpose-built for large graph visualization — 10k+ nodes at 60fps
- Semantic zoom, level-of-detail built in
- **Trade-off:** Less flexible than Cytoscape.js for custom shapes

### Voice Transcription: Pluggable (separate concern)

- Voice transcription is its own service, not part of VoiceTree core
- Provider interface: Whisper (local), Soniox (cloud), or any future provider
- VoiceTree consumes a text stream — doesn't care about the source

### Ambient Capture: Pluggable (separate concern)

- ScreenPipe is the primary integration target (open source, REST API at localhost:3030)
- But it's an optional external dependency, not built into VoiceTree
- VoiceTree's ingestion pipeline accepts events from any context provider

### MCP Transport: StreamableHTTP on fixed port

- Fixed port (default 3100, configurable via `VOICETREE_PORT`) — no random port hunting
- One-time `voicetree setup` configures all detected MCP clients
- No per-project config file injection

### Frontend: React + Tailwind

- React is fine. The UI is not the hard part.

---

## How It Hangs Together

```mermaid
architecture-beta
    group external(internet)[External Clients]
    group core(server)[VoiceTree Core Service]
    group ingest(server)[Ingestion] in core
    group querygrp(server)[Query] in core
    group data(database)[Data Layer]

    service agents(internet)[MCP Clients] in external
    service screenpipe(internet)[ScreenPipe] in external
    service voicerec(internet)[Voice Service] in external

    service mcp(server)[MCP Server :3100] in core
    service router(server)[Project Router] in core
    service pipeline(server)[Ingestion Pipeline] in ingest
    service engine(server)[Query Engine] in querygrp
    service blender(server)[Blended Ranker] in querygrp

    service graphdb(database)[Graph DB] in data
    service vectordb(database)[Vector Search] in data

    service webview(server)[WebView UI]

    agents:B --> T:mcp
    screenpipe:B --> T:pipeline
    voicerec:B --> T:pipeline
    mcp:B --> T:router
    router:L --> R:pipeline
    router:R --> L:engine
    pipeline:B --> T:graphdb
    pipeline:B --> T:vectordb
    engine:B --> T:blender
    blender:B --> T:graphdb
    blender:B --> T:vectordb
    webview:B --> T:engine
```

Three independent input sources (voice, ambient capture, agent MCP tools) feed into a common ingestion pipeline. The pipeline writes to a graph DB + vector store. A query engine blends graph traversal with vector search. The UI and MCP responses both consume the query engine.

**Detailed diagrams, data models, sequence diagrams, and component breakdowns are in `ARCHITECTURE.md`.**

---

## What We Take From VoiceTree v1

Ideas and patterns worth preserving:

- **MCP tool API design** — `create_graph`, `spawn_agent`, `wait_for_agents` are well-designed tools
- **Voice → structured nodes pipeline** — the concept works, even if the implementation needs replacing
- **Progress graph for agents** — unique paradigm, keep it
- **Pure/shell architecture split** — good principle, apply it in Rust
- **Auto-positioning algorithms** — graph layout heuristics from `createGraphTool.ts`
- **Worktree management** — git worktree isolation for agent work

What we explicitly leave behind:

- Markdown files as runtime source of truth
- Per-project config file injection (`mcp-client-config.ts`)
- Random port binding
- Python subprocess for backend
- Chokidar file watching as primary ingestion
- 300-node hard cap
- Canvas-based Cytoscape rendering
- Fire-and-forget async patterns (`void startMcpServer()`)

---

## Open Questions

- **Kuzu vs SurrealDB**: One DB for everything (graph + vector) vs two embedded DBs?
- **Tauri vs Electron**: Is the team comfortable with Rust?
- **Vector store**: LanceDB, SurrealDB built-in, or wait for Kuzu vector support?
- **ScreenPipe**: Hard dependency or optional? What if it's not running?
- **Obsidian compatibility**: Should markdown export match Obsidian format?
- **License**: MIT? AGPL?
- **Local-first**: Is this a hard constraint or a preference?

---

## Reference

- `ARCHITECTURE.md` — Detailed diagrams, data models, ingestion pipeline, lifecycle, MCP discovery
- `COMPETITIVE-LANDSCAPE.md` — Market research and competitor analysis
- `TODO.md` — Current roadmap for VoiceTree v1 improvements
