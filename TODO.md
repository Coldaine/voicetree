# VoiceTree - Next Steps & TODO

> Note: Issue numbers in this file are internal roadmap IDs used for planning. They do not map 1:1 to the current live GitHub issue numbers.

## Phase 0: Architectural Foundation

These two issues are prerequisites that shape everything else. The current architecture — an Electron app that watches one folder, injects config files into project directories, and stores everything as flat markdown — doesn't support the vision of an always-on, multi-project, multi-agent knowledge platform.

### Issue #13: Service Architecture — From Folder Watcher to Persistent Service
**Effort**: 2-3 weeks
**GitHub**: [voicetreelab/voicetree#13](https://github.com/voicetreelab/voicetree/issues/13) *(this roadmap ID intentionally matches the GitHub issue number)*

**The Problem**: VoiceTree is currently an "Electron app that watches one folder." This forces:
- Per-project config file injection (`.mcp.json`, `.codex/config.toml`) into directories VoiceTree doesn't own
- Random port binding (3001-3100) with no stable discovery
- Single-project, single-instance limitation
- Dirty git state every launch (port rewritten in tracked `.mcp.json`)
- Only 2 of 7+ MCP clients supported (Claude Code, Codex)
- No cleanup on exit (stale ports in config files)

**The Fix**: VoiceTree becomes a persistent service with an Electron UI frontend.

- [ ] **Fixed port** with `VOICETREE_MCP_PORT` env var, hard-fail if occupied
- [ ] **Global port discovery file** at `app.getPath('userData')/mcp-server.json` (interim)
- [ ] **Stop injecting files into project directories** — remove `mcp-client-config.ts` file-writing behavior
- [ ] **`voicetree setup` CLI** that writes global config for all detected MCP clients (Claude Code, VS Code, Cursor, Gemini CLI, Windsurf, Cline, Codex)
- [ ] **Server-side project routing** — agents send project path via MCP tool, VoiceTree routes to the right vault
- [ ] **Multi-project support** — multiple vaults active simultaneously
- [ ] **Graceful lifecycle** — proper startup, shutdown, port cleanup (subsumes Issues #5, #6)

**MCP client config locations** (what `voicetree setup` would write):
| Client | Config Path | Format |
|--------|------------|--------|
| Claude Code | `.mcp.json` or `~/.claude.json` | `{"mcpServers": {"voicetree": {"type": "http", "url": "..."}}}` |
| VS Code Copilot | `.vscode/mcp.json` | Same mcpServers format |
| Cursor | `.cursor/mcp.json` | Same mcpServers format |
| Gemini CLI | `~/.gemini/settings.json` | `{"mcpServers": {"voicetree": {"httpUrl": "..."}}}` |
| Codex | `.codex/config.toml` | `[mcp_servers.voicetree] url = "..."` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | Same mcpServers format |
| Cline | `.cline/mcp_settings.json` | Same mcpServers format |

**Reference**: `MCP-PORT-INVESTIGATION.md`, `MCP-PORT-DISCOVERY-IMPLEMENTATION.md`

---

### Issue #14: Data Layer — Add Graph Database Under Markdown
**Effort**: 2-3 weeks

**The Problem**: Markdown files are the sole source of truth. There is no graph database. ChromaDB is only a vector search cache. BM25 is recomputed fresh every query. Wikilinks are the only relationship mechanism — untyped, no graph queries, no ACID, no traversal algorithms.

This means:
- No way to query "all nodes that depend on X" (no typed edges)
- No graph algorithms (shortest path, clustering, centrality)
- No transactional consistency (two agents writing simultaneously = race condition)
- Performance ceiling — every query scans files or rebuilds indexes
- The "graph" in VoiceTree is really just a visualization of file links, not a queryable data structure

**The Fix**: Add an embeddable graph database as the authoritative data layer. Markdown files become a serialization format (import/export), not the runtime store.

**Candidates** (from competitive landscape research):
| DB | Why It Fits | Concern |
|----|------------|---------|
| **Kuzu** | Embeddable (like SQLite for graphs), Cypher support, perfect for desktop apps | Young project |
| **FalkorDB** | Redis-backed, extremely fast, Cypher-compatible | Requires Redis runtime |
| **SurrealDB** | Multi-model (graph + document + vector), embeddable mode | Ambitious scope, maturity |

- [ ] Evaluate Kuzu vs FalkorDB vs SurrealDB for embeddable desktop use
- [ ] Design schema: nodes, typed edges, tags, temporal metadata
- [ ] Implement graph DB layer with Markdown import/export
- [ ] Migrate ChromaDB vector search into graph DB (if it supports vectors) or keep as sidecar
- [ ] Add typed edge support (`references`, `depends_on`, `contradicts`, `extends`, etc.)
- [ ] Add graph query API (traversals, shortest path, neighborhood, centrality)
- [ ] Migration tool for existing markdown vaults
- [ ] Markdown files remain human-readable exports, not the runtime store

**Relationship to other issues**: This subsumes much of Issue #8 (tags + typed edges) and unblocks Issue #9 (performance at scale). It also makes Issue #11 (temporal queries) feasible — a proper DB can index timestamps efficiently.

---

## Phase A: Stability Foundation

### Issue #5: Critical Backend Infrastructure Fixes
**Effort**: 2-3 hours (quick wins)

Five critical fixes for port leaks, silent crashes, and memory leaks. These are worth doing immediately even before the Phase 0 architecture work.

- [ ] **MCP graceful shutdown**: Store `http.Server` ref, call `.close()` in `before-quit`
- [ ] **Unhandled rejection handler**: Add `process.on('unhandledRejection')` to `main.ts`
- [ ] **MCP error middleware**: Add try/catch + error middleware to Express
- [ ] **SIGTERM/SIGKILL race**: Add 5s delay between SIGTERM and SIGKILL for Python backend
- [ ] **onBackendLog leak**: Return cleanup function from IPC listener

**Reference**: `GITHUB-ISSUES-BACKEND-ROBUSTNESS.md`

---

### Issue #6: Backend Crash Recovery and Reconnection
**Effort**: 4-6 hours

Auto-restart TextToTree server on crash and reconnect SSE consumer:

- [ ] TextToTree auto-restart with exponential backoff (max 3 attempts)
- [ ] Update `backendPort` after restart, notify renderer
- [ ] SSE consumer reconnection with port re-discovery
- [ ] User notification on max restart failures

---

## Phase B: Always-On Intelligence Core

### Issue #7: Always-On Context-Aware Ingestion Pipeline
**Effort**: 1-2 weeks
**Depends on**: Phase 0 (service architecture enables always-on; graph DB enables efficient ingestion)

VoiceTree should run continuously without manual project scoping. Integrate ambient context capture (ScreenPipe-first) to understand the user's active work surface.

**The Vision**: Instead of scoping to a watched directory, VoiceTree adapts to what you're actively working on. Context signals include:
- Active window/tab/URL
- OCR'd screen content
- Agent-analyzed screenshots
- Browser tabs
- Editor context

**Implementation**:
- [ ] Create provider interface for external context sources
- [ ] Create ScreenPipe adapter (REST API at `localhost:3030`)
- [ ] Normalize ingestion events with source attribution
- [ ] Add dedupe window + rate limiting for noisy focus changes
- [ ] Add source metadata to nodes (`source_type`, `source_ref`, `active_context_score`)
- [ ] Feature flag: `always_on_context_ingestion`

**Key Architecture Decisions**:
- ScreenPipe provides OCR, active windows, audio transcription, and screenshots
- VoiceTree's ingestion pipeline tags and routes events by context
- Nodes must be auditable (where did this come from?)

---

### Issue #8: Tag-First Knowledge Model with Multi-Relational Edges
**Effort**: 1-2 weeks
**Depends on**: Issue #14 (graph DB provides typed edges natively; without it, tags/edges are hacked into frontmatter)

Graph relationships alone aren't enough. Need explicit tagging and richer edge semantics.

**Current State**: Nodes link via `[[wikilinks]]` only. No tags. All edges are untyped.

**Target State**: Hybrid model - tags + typed relationships + graph traversal.

- [ ] Extend node schema with `tags: string[]` in frontmatter
- [ ] Extend edge schema with `relation_type` (`references`, `depends_on`, `contradicts`, `extends`, `example_of`, `related_to`)
- [ ] Auto-tag extraction from content and source context
- [ ] Tag index for fast lookup
- [ ] Retrieval scoring blend (tag overlap + semantic similarity + graph proximity)
- [ ] Migration script for existing nodes/edges

---

## Phase C: Scale and Usability

### Issue #9: Performance Overhaul for Large Graphs
**Effort**: 2-3 weeks
**Depends on**: Issue #14 (graph DB eliminates file-scanning bottleneck; proper indexes replace full scans)

Performance degrades significantly as node count grows. Current hard cap is 300 nodes. Always-on usage requires much higher scale.

**Current State**:
- 300 file hard cap per vault (`fileLimitEnforce.ts`)
- Canvas-based Cytoscape rendering
- All nodes rendered (no virtualization)
- Already laggy at moderate node counts

**Performance Targets**:
- Comfortable at 1,000+ nodes
- Usable at 10,000+ nodes (Super Memory handles tens of thousands)

**Options Explored**:
| Library | Tech | 10k Nodes |
|---------|------|-----------|
| Cytoscape.js + WebGL | Canvas/WebGL | 100+ FPS (with WebGL enabled since v3.31) |
| Sigma.js | WebGL | Nearly instant, 60 FPS (purpose-built for large graphs) |
| deck.gl | WebGL2/WebGPU | Millions of points (overkill but powerful) |

- [ ] Profile end-to-end latency (ingest → index → retrieval → UI render)
- [ ] Enable Cytoscape WebGL renderer as first step
- [ ] Add viewport culling / virtualization
- [ ] Add level-of-detail (hide labels when zoomed out)
- [ ] Add clustering for dense areas
- [ ] Evaluate Sigma.js migration if Cytoscape hits limits
- [ ] Define and enforce SLOs (p50/p95 ingest and retrieval latency)

---

### Issue #10: Graph UX Redesign + Non-Graph Primary Navigation
**Effort**: 1-2 weeks

Graph-first interaction isn't always the most useful surface. Need feed-first / query-first navigation.

- [ ] Add primary "Context Feed" and "Related Context" panels (non-graph)
- [ ] Add relationship inspector for selected nodes (all typed edges + tags)
- [ ] Add graph controls for density, relation filters, neighborhood depth
- [ ] Add filter controls by relation type and tag
- [ ] Add neighborhood expansion (1-hop/2-hop/3-hop)

---

## Phase D: Temporal and Visual Enhancements

### Issue #11: Temporal Graph and Project History Visualization
**Effort**: 2-3 weeks
**Depends on**: Issue #14 (temporal queries need indexed timestamps and version history — can't do this over flat files)

VoiceTree lacks temporal awareness - no version history, no "what changed when", no way to understand project evolution over time.

**Current State**:
- Only basic timestamps (`created_at`, `modified_at`)
- No version history or diffs
- No temporal queries
- No git integration
- No session replay

**Vibe-Viz Inspiration**: Create visual timelines of projects by connecting git commits with knowledge graph changes, showing how the project evolved.

- [ ] Extend node schema with `version_history: list[NodeVersion]`
- [ ] Add temporal index for time-sliced queries
- [ ] Create `TemporalGraphManager` service
- [ ] Add git commit correlation (commit ↔ graph state)
- [ ] Build timeline UI (horizontal timeline with node events)
- [ ] Add temporal query API (`get_graph_at_timestamp`, `get_changes_since`)
- [ ] Add session replay (reconstruct agent work sequence)
- [ ] Add "Recent Changes" panel with time filters
- [ ] Add temporal context retrieval (distance + time constraints)

---

### Issue #12: Enhanced Graph Visualization (Shapes, Filters, Visual Controls)
**Effort**: 2-3 weeks

Current graph visualization is limited - only 2-3 shapes, no filters, hard to distinguish node types.

**Current Limitations**:
- Only 2-3 node shapes (ellipse, rectangle)
- No visual filters for node types or tags
- No shape customization
- No legend explaining visual encodings
- Edge labels barely visible in dense graphs

**Target Features**:
- Multiple node shapes (triangle, diamond, hexagon, star, custom)
- Visual filters by: type, tag, relation, time, agent
- Edge styling by relationship type
- Graph density controls
- Minimap with semantic zoom

- [ ] Add shape picker to node editor
- [ ] Implement custom Cytoscape shapes (triangle, diamond, hexagon, star)
- [ ] Create filter panel component (node type, tag, relationship, time, agent)
- [ ] Add visual legend showing shape/color meanings
- [ ] Add edge styling based on relationship type
- [ ] Add density slider and cluster controls
- [ ] Add minimap with viewport indicator
- [ ] Add focus mode (dim unrelated nodes)

---

## Current Ingestion Architecture (Reference)

Three pathways into the graph today:

1. **Voice/Text → TextToTree Server → Markdown Files → Graph**
   - Soniox speech-to-text → token streaming → Python backend buffers & creates .md files
   - Chokidar watches .md files → parses frontmatter + wikilinks → graph delta → Cytoscape

2. **File System Changes → Graph**
   - Direct markdown edits detected by Chokidar watcher
   - Parsed to GraphNode via `parse-markdown-to-node.ts`

3. **Agent-Created Nodes (MCP `create_graph` tool)**
   - Batch node creation with DAG support
   - Auto-positioning, frontmatter generation, context node linking

**Key Files**:
- Voice input: `voicetree-transcribe.tsx`, `useTranscriptionSender.ts`
- File watching: `file-watcher-setup.ts`, `watchFolder.ts`
- Markdown parsing: `parse-markdown-to-node.ts`
- Agent creation: `createGraphTool.ts`
- Graph state: `graph-store.ts`, `applyGraphDeltaToDBThroughMemAndUI.ts`
- MCP server: `mcp-server.ts`, `mcp-client-config.ts`

---

## Reference Documents

| Document | Location | Purpose |
|----------|----------|---------|
| MCP Port Investigation | `MCP-PORT-INVESTIGATION.md` | Analysis of Gemini agent findings |
| MCP Port Discovery Plan | `MCP-PORT-DISCOVERY-IMPLEMENTATION.md` | Detailed implementation plan |
| Backend Robustness Audit | `GITHUB-ISSUES-BACKEND-ROBUSTNESS.md` | Full 18-issue architectural audit |
| Consolidated Issues | `CONSOLIDATED-GITHUB-ISSUES.md` | All GitHub issues in one place |
| Competitive Landscape | `COMPETITIVE-LANDSCAPE.md` | Market research and competitor analysis |

## GitHub Issues

Live tracker: https://github.com/voicetreelab/voicetree/issues

Current repository issues:
- [#1 MacOS Dev Setup](https://github.com/voicetreelab/voicetree/issues/1)
- [#3 Graph logo for VoiceTree in Ubuntu renders weirdly](https://github.com/voicetreelab/voicetree/issues/3)
- [#4 Security: Critical XSS to RCE vulnerability via malicious markdown files](https://github.com/voicetreelab/voicetree/issues/4)
- [#6 How to update project overview after substantial changes in codebase?](https://github.com/voicetreelab/voicetree/issues/6)
- [#7 macOS: Drag & drop files onto terminal windows to expand to filepath](https://github.com/voicetreelab/voicetree/issues/7)
- [#8 Better automatic worktree management](https://github.com/voicetreelab/voicetree/issues/8)
- [#9 Expandable Folder Nodes](https://github.com/voicetreelab/voicetree/issues/9)
- [#11 Won't open up folder with > 300 files](https://github.com/voicetreelab/voicetree/issues/11)

Roadmap IDs in this document (`Issue #5` ... `Issue #14`) are planning labels, not GitHub issue numbers.
