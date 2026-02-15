# VoiceTree v2 — North Star

> A persistent, always-on knowledge service with FalkorDB graph+vector storage,
> daemon architecture, and universal MCP discovery.

---

## Requirements

What must this system do?

- **Capture voice and text input** and convert it into structured, linked knowledge nodes in real time
- **Visualize knowledge as an interactive graph** that remains performant at 10,000+ nodes
- **Serve as a multi-agent control plane** — any AI coding agent (Claude, Copilot, Cursor, Gemini, Codex, Windsurf, Cline) can connect via MCP and create/query/traverse the graph
- **Run always-on** as a background service — no manual project scoping, no "open a folder" step
- **Ingest ambient context** — active window, screen content (OCR), browser tabs, editor state — and route it into the graph with source attribution
- **Support multiple projects simultaneously** — agents working in different repos all connect to the same service, each routed to the right vault/context
- **Store knowledge in a real graph database** with typed edges, ACID transactions, graph traversal algorithms, vector similarity search, and indexed queries
- **Be discoverable by any MCP client** without per-project config file injection

---

## Goals

What are we optimizing for?

- **Ambient, effortless capture** — like Granola for meetings, but for all knowledge work
- **Graph-native data model** — typed edges, tags, temporal history, graph algorithms as first-class features
- **Scale** — comfortable at 1,000 nodes, usable at 10,000+, architecturally capable of 100,000+
- **Developer-first** — agents are the primary users, humans navigate via feed/search/graph
- **Pluggable inputs** — voice, ambient capture, and agent tools are separate concerns that plug into a common ingestion pipeline

---

## Non-Goals (Explicitly Out of Scope)

- Mobile app
- Real-time collaboration between multiple humans
- Cloud sync (local-first is a hard constraint)
- Obsidian compatibility (we export to markdown, but don't constrain to Obsidian's format)

---

## Decisions

What stack did we choose and why?

### Runtime: Electron (with proper service architecture)

- Team knows Electron — faster iteration than learning Tauri/Rust
- The bottleneck is data layer and service architecture, not runtime overhead
- Proper lifecycle management (graceful startup/shutdown, system tray, daemon mode) addresses the real issues
- System tray + auto-start gives always-on behavior without Rust
- **Reconsidered**: Tauri was initially attractive for memory savings and native daemon support. The team decided the 2-3 month Rust learning curve isn't justified when the core problems are in the data layer and service model, not the runtime. Electron with proper architecture is the pragmatic choice.

### Graph Database: FalkorDB (Redis-backed, graph + vector unified)

FalkorDB is the primary data store, handling **both graph queries and vector similarity search** in a single system. This eliminates ChromaDB entirely.

**Why FalkorDB over Kuzu:**
- **Graph + Vector in one** — FalkorDB supports native vector indexes with cosine/euclidean similarity search. Kuzu does not have vector support yet. This eliminates the need for a separate vector store (ChromaDB, LanceDB).
- **Cypher query language** — full Cypher support, same query language as Neo4j
- **Redis-backed performance** — sub-millisecond reads for hot data, excellent throughput
- **Full-text search** — built-in full-text indexing (BM25) — eliminates another dependency
- **Production-proven** — used by major companies, active development, good TypeScript client (`@falkordb/falkordb`)
- **Docker-friendly** — runs as a single container with persistent volumes. Electron manages the container lifecycle.

**Why not Kuzu:**
- No vector search support (would still need ChromaDB or LanceDB as sidecar)
- Younger ecosystem with fewer client libraries
- The "embeddable" advantage matters less when we're already running Docker for ambient capture tools

**Why not SurrealDB:**
- Ambitious multi-model scope raises maturity concerns
- Smaller community, less battle-tested for graph workloads specifically

**Trade-off**: FalkorDB requires Redis (via Docker container). This adds a Docker dependency. For a developer-focused tool, this is acceptable — most users already have Docker.

### Vector Search: FalkorDB (unified — no separate store)

**Resolved.** FalkorDB handles vector similarity search natively via `db.idx.vector.createNodeIndex()` and `db.idx.vector.queryNodes()`. We store embeddings directly on graph nodes and run vector queries alongside Cypher traversals.

This means:
- **ChromaDB is eliminated** — no Python sidecar, no separate process
- **Vector and graph queries compose** — "find semantically similar nodes that are also within 2 hops of node X" is a single query
- **One data store** for graph, vectors, full-text indexes, and metadata

### Graph Rendering: Sigma.js (WebGL)

- Purpose-built for large graph visualization — 10k+ nodes at 60fps
- Semantic zoom, level-of-detail built in
- Uses graphology as the data model (powerful graph analysis library)
- **Trade-off:** Different API from Cytoscape.js, requires migration work

### Voice Transcription: Pluggable (separate concern)

- Voice transcription is its own service, not part of VoiceTree core
- Provider interface: Whisper (local), Soniox (cloud), or any future provider
- VoiceTree consumes a text stream — doesn't care about the source

### Ambient Capture: Pluggable (separate concern)

- ScreenPipe is the primary integration target (open source, REST API at localhost:3030)
- But it's an optional external dependency, not built into VoiceTree
- VoiceTree's ingestion pipeline accepts events from any context provider

### MCP Transport: StreamableHTTP on fixed port

- Fixed port (default 3100, configurable via `VOICETREE_MCP_PORT`) — no random port hunting
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

    service falkordb(database)[FalkorDB\nGraph + Vector + Full-Text] in data

    service webview(server)[WebView UI]

    agents:B --> T:mcp
    screenpipe:B --> T:pipeline
    voicerec:B --> T:pipeline
    mcp:B --> T:router
    router:L --> R:pipeline
    router:R --> L:engine
    pipeline:B --> T:falkordb
    engine:B --> T:blender
    blender:B --> T:falkordb
    webview:B --> T:engine
```

Three independent input sources (voice, ambient capture, agent MCP tools) feed into a common ingestion pipeline. The pipeline writes to FalkorDB (unified graph + vector + full-text store). A query engine blends graph traversal with vector search and BM25. The UI and MCP responses both consume the query engine.

**Key difference from v1**: There is one data store (FalkorDB), not two (markdown + ChromaDB). The graph, vectors, full-text indexes, and metadata all live together. Markdown files are an export format, not the source of truth.

**Detailed diagrams, data models, sequence diagrams, and component breakdowns are in `ARCHITECTURE.md`.**

---

## What We Take From VoiceTree v1

Ideas and patterns worth preserving:

- **MCP tool API design** — `create_graph`, `spawn_agent`, `wait_for_agents` are well-designed tools
- **Voice → structured nodes pipeline** — the concept works, even if the implementation needs replacing
- **Progress graph for agents** — unique paradigm, keep it
- **Pure/shell architecture split** — good principle, apply it in the new codebase
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
- ChromaDB as vector search sidecar
- Fire-and-forget async patterns (`void startMcpServer()`)

---

## Open Questions

- **ScreenPipe**: Hard dependency or optional? → **Decided: Optional.** All features work without it.
- **License**: MIT? AGPL? → Needs decision.
- **Local-first**: → **Decided: Hard constraint.** All data stays local. No cloud sync.
- **Docker requirement**: Is it acceptable to require Docker? → **Decided: Yes**, for a developer-focused tool. Provide clear install instructions and pre-flight checks.
- **Embedding model**: Bundle locally (all-MiniLM-L6-v2, 384 dims) or use API (OpenAI, 1536 dims)? → **Decided: Local default**, OpenAI optional.

---

## Implementation Plan

The v2 rewrite is phased over 20 weeks. See `v2-plan/README.md` for the full plan.

| Phase | Duration | Focus |
|-------|----------|-------|
| 0 — Foundation | Weeks 1–4 | FalkorDB setup, schema, MCP server, lifecycle, migration |
| 1 — Core Services | Weeks 5–8 | Ingestion pipeline, query engine, project router, MCP tools |
| 2 — UI Overhaul | Weeks 9–12 | Sigma.js, feed view, search, filters |
| 3 — Ambient Capture | Weeks 13–16 | System tray, ScreenPipe integration, background ingestion |
| 4 — Scale & Polish | Weeks 17–20 | Performance, temporal graph, CI/CD, docs |

---

## Reference

- `ARCHITECTURE.md` — Detailed diagrams, data models, FalkorDB schema, lifecycle, MCP discovery
- `COMPETITIVE-LANDSCAPE.md` — Market research and competitor analysis
- `v2-plan/README.md` — Full phased implementation plan with task breakdowns
- `TODO.md` — v1 roadmap (superseded by v2-plan)
