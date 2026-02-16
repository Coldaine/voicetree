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
- **Accept contextual metadata on ingestion** — the ingestion pipeline should accept optional context (active window name, source app, editor file path) attached to any input, but VoiceTree does not actively capture screen state in v2
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

These are things VoiceTree v2 is **not** trying to be. Each has a brief rationale.

1. **General-purpose note-taking app** — We are not competing with Notion, Obsidian, or Roam for their core daily-driver UX. VoiceTree is a knowledge *graph service*, not a writing environment.
2. **Code editor or IDE plugin** — AI agents *use* VoiceTree as a coordination layer. VoiceTree does not replace VS Code, Cursor, or any editor. No syntax highlighting, no LSP, no inline code actions.
3. **Project management tool** — No kanban boards, no sprints, no issue tracking, no Gantt charts. Agents report progress to the graph; humans use their own PM tools.
4. **LLM / AI model provider** — VoiceTree orchestrates agents and stores their output. It does not host, fine-tune, or serve language models.
5. **Real-time audio/video conferencing tool** — VoiceTree consumes transcription streams; it does not capture audio, run a microphone, or handle video calls.
6. **Mobile app** — No iOS/Android client in v2. The architecture doesn't preclude it later (the core service has an HTTP API), but it's not a target.
7. **Multi-user real-time collaboration** — No simultaneous editing by multiple humans. Single-user (with many agents) is the model for v2.
8. **Obsidian-format compatibility** — We export markdown, but we do not constrain our schema, frontmatter, or linking conventions to match Obsidian's format. Interop is nice-to-have, not a design constraint.
9. **Full ambient screen capture (v2)** — Active screen recording, OCR of arbitrary windows, and ScreenPipe-level ambient capture are v3+ territory. The ingestion pipeline *accepts* context metadata, but v2 does not actively capture screen state.
10. **Offline-only / anti-cloud stance** — Local-first is a *default*, not a dogma. Cloud sync, remote backends, and hosted deployment are all legitimate future directions. We do not artificially constrain to local-only.

---

## Decisions

What stack did we choose and why?

### Runtime: Electron (default) vs Tauri (candidate) — decision gated by spike

The original justification for Electron ("team learning curve") is weak if most code is AI-authored. The real decision drivers are: **(1) Dockerless data layer feasibility**, **(2) memory baseline**, **(3) background/tray + auto-start behavior**, **(4) WebGL graph performance (Sigma.js)**, and **(5) packaging reliability across Win/Mac/Linux**.

- **Default (until proven otherwise): Electron**
  - Matches the existing v1 codebase and developer tooling (DevTools, embedded terminal workflows)
  - Minimizes rewrite risk while we validate the data layer
- **Candidate: Tauri**
  - Potentially much lower idle memory footprint (Rust + system WebView)
  - Native daemon/tray ergonomics are strong if we also move the core service to Rust
- **Architecture constraint (either way)**: keep the **core service behind a stable local API boundary** (HTTP on `localhost` + internal IPC), so the UI shell can be swapped without rewriting the ingestion/query/data model.

**Spike (3-4 days)**: build a minimal Electron shell and a minimal Tauri shell that both:
1. Render a Sigma.js graph view (5k+ nodes synthetic) and measure FPS + memory
2. Expose a trivial MCP tool and validate the bridge + throughput
3. Run a background/tray mode with auto-start (Win/Mac/Linux)
4. Package and run on all 3 platforms (CI artifacts are enough)

### Graph Database: FalkorDB (Redis-backed, graph + vector unified)

FalkorDB is the primary data store, handling **both graph queries and vector similarity search** in a single system. This eliminates ChromaDB entirely.

**Why FalkorDB over Kuzu:**
- **Graph + Vector in one** — FalkorDB supports native vector indexes with cosine/euclidean similarity search. Kuzu does not have vector support yet. This eliminates the need for a separate vector store (ChromaDB, LanceDB).
- **Cypher query language** — full Cypher support, same query language as Neo4j
- **Redis-backed performance** — sub-millisecond reads for hot data, excellent throughput
- **Full-text search** — built-in full-text indexing (BM25) — eliminates another dependency
- **Production-proven** — used by major companies, active development, good TypeScript client (`falkordb`)
- **Docker-friendly** — runs as a single container with persistent volumes (fallback deployment mode).

**Why not Kuzu:**
- No vector search support (would still need ChromaDB or LanceDB as sidecar)
- Younger ecosystem with fewer client libraries
- The "embeddable" advantage matters less when we're already running Docker for ambient capture tools

**Why not SurrealDB:**
- Ambitious multi-model scope raises maturity concerns
- Smaller community, less battle-tested for graph workloads specifically

**Trade-off**: FalkorDB requires Redis. **We should not make Docker Desktop a hard requirement**: preferred deployment is a Dockerless local sidecar (bundled Redis + FalkorDB module where feasible), with Docker as a fallback.

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

### Ambient Capture: Future (v3+), with lightweight near-term option

Full ambient capture (ScreenPipe integration, continuous OCR, browser tab tracking, editor state streaming) is **v3+ conceptual work** — not part of the v2 plan. The calibration, privacy controls, noise filtering, and UX required to make ambient capture useful (rather than overwhelming) will take significant iteration.

**What v2 does:**
- The ingestion pipeline **accepts optional context metadata** on every input (e.g., `{ source: "vscode", activeFile: "src/index.ts", windowTitle: "..." }`). Any caller — agent, voice service, or future ambient provider — can attach this.
- **Lightweight active-window detection (Windows):** If feasible, capture the currently focused window name via Windows API at ingestion time. This is a cheap, zero-dependency signal that adds useful context without the complexity of full screen capture.

**What v2 does NOT do:**
- No ScreenPipe integration, no continuous screen recording, no OCR pipeline
- No browser tab tracking, no editor state streaming
- No always-on background capture daemon

**Future (v3+):** ScreenPipe or equivalent as an optional external provider, feeding events into the same ingestion pipeline. The architecture is ready for this — the ingestion pipeline is provider-agnostic — but the capture side requires its own roadmap.

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

### Decided

- **ScreenPipe / ambient capture**: Hard dependency or optional? → **Decided: Not in v2.** Full ambient capture is v3+. The ingestion pipeline accepts context metadata, but VoiceTree does not actively capture screen state. Lightweight active-window name capture (Windows API) is a reasonable near-term addition if cheap to implement.
- **Embedding model**: Bundle locally (all-MiniLM-L6-v2, 384 dims) or use API (OpenAI, 1536 dims)? → **Decided: Local default, API fallback.** Bundle a local model for zero-config startup. If standing up local inference is painful on a given platform, an OpenAI-served embedding endpoint is an acceptable fallback. The vector dimensions will differ (384 vs 1536), so the schema must handle both.

### Leaning (direction chosen, details still open)

- **Docker**: Docker must not be a hard requirement for local usage — performance overhead and install friction are real. However, Docker as an *optional deployment mode* for the backend is interesting: it cleanly enables future remote deployment (run VoiceTree's backend on a home server, NAS, or cloud VM while the UI runs locally). **Architecture implication:** the client/backend boundary must be a clean HTTP API so Docker can wrap the backend without changing the client. Leaning toward: Dockerless local default, Docker as a supported-but-optional backend deployment.
- **Voice transcription provider**: Whisper (local) vs Soniox (cloud) vs other. Leaning toward pluggable provider interface with Whisper as default. The real question is latency: local Whisper on CPU is slow (~2-5x realtime); GPU Whisper is fast but requires CUDA. Soniox is fast but cloud-dependent. Needs benchmarking.

### Genuinely Open

- **License**: MIT? AGPL? Apache 2.0? This affects whether companies can embed VoiceTree in proprietary products. AGPL protects the project but limits adoption. MIT maximizes adoption but offers no protection. No decision yet — needs a conversation about the project's long-term model.
- **Deployment model (local vs remote vs hybrid)**: The current assumption is local-only, but that's a leftover from v1, not a deliberate v2 decision. Real possibilities:
  - **Local**: Electron app + local FalkorDB. Simplest, most private, but limited by the user's hardware.
  - **Remote backend**: FalkorDB + ingestion pipeline run on a home server or cloud VM. UI connects over the network. Enables multi-device access and heavier workloads.
  - **Hybrid**: Local UI with remote data layer (e.g., hosted FalkorDB). Best of both worlds but adds network dependency.
  - Cloud sync is NOT off the table. The question is when and how, not whether.
- **Data portability / export format**: Markdown is the current export format, but what's the canonical export? JSON-LD? RDF? A FalkorDB dump? If users want to leave VoiceTree, what do they take with them? This matters for trust and adoption.
- **Graph schema evolution**: How do we handle schema migrations as the graph model evolves? FalkorDB doesn't enforce a schema, but our application layer does. When we add new node types, edge types, or properties, how do we migrate existing graphs? Do we version the schema? Run migrations on startup?
- **Multi-user potential (future)**: v2 is explicitly single-user with many agents. But what about v3+? If two humans want to share a graph (e.g., a team knowledge base), what changes? This affects data model decisions now (e.g., do nodes have an `owner` field?).
- **API surface for third-party extensions**: Beyond MCP tools, should VoiceTree expose a plugin API? What can third parties extend — custom node types, custom visualizations, custom ingestion providers, custom query operators? How much of the internals do we expose?
- **Monetization model**: Is VoiceTree a free open-source tool forever? Freemium with a hosted backend? Paid desktop app? This isn't urgent, but it shapes decisions about cloud features, licensing, and what we optimize for.
- **FalkorDB without Docker on Windows**: FalkorDB is Redis-backed, and Redis doesn't officially support Windows. The plan says "Dockerless default," but how? Options: (a) bundle Redis via WSL2 auto-setup, (b) use Memurai (Windows Redis alternative), (c) bundle a pre-compiled Redis fork, (d) accept Docker as the Windows default. This is a real implementation risk that needs a spike.
- **Electron vs Tauri**: The spike is defined but not yet run. The answer affects memory footprint, packaging, and background-service ergonomics. Until the spike is done, Electron is the default, but this is still an open question.
- **Graph size tiers and performance targets**: "10k+ nodes" is the stated goal, but what's the actual performance budget? 60fps at 10k nodes? What about 50k? 100k? At what point do we need server-side rendering or level-of-detail streaming? Sigma.js helps, but the query layer also needs to scale.

---

## Implementation Plan

The v2 rewrite is phased over 20 weeks. See `v2-plan/README.md` for the full plan.

| Phase | Duration | Focus |
|-------|----------|-------|
| 0 — Foundation | Weeks 1–4 | FalkorDB setup, schema, MCP server, lifecycle, migration |
| 1 — Core Services | Weeks 5–8 | Ingestion pipeline, query engine, project router, MCP tools |
| 2 — UI Overhaul | Weeks 9–12 | Sigma.js, feed view, search, filters |
| 3 — Daemon & Background | Weeks 13–16 | System tray, auto-start, background ingestion (NO ScreenPipe — that's v3.0 product) |
| 4 — Scale & Polish | Weeks 17–20 | Performance, temporal graph, CI/CD, docs, lightweight context capture (active window) |

---

## Reference

- `ARCHITECTURE.md` — Detailed diagrams, data models, FalkorDB schema, lifecycle, MCP discovery
- `COMPETITIVE-LANDSCAPE.md` — Market research and competitor analysis
- `v2-plan/README.md` — Full phased implementation plan with task breakdowns
- `TODO.md` — v1 roadmap (superseded by v2-plan)
