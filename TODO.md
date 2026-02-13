# VoiceTree - Next Steps & TODO

## Phase A: Stability Foundation

### Issue #4: MCP Port Discovery for External Clients
**GitHub**: https://github.com/Coldaine/voicetree/issues/4
**Effort**: 4-6 hours

External MCP clients (Gemini CLI, etc.) can't discover VoiceTree's port when it drifts from 3001. Need a cross-platform port discovery file at `app.getPath('userData')/mcp-server.json`.

- [ ] Create `mcp-port-file.ts` (write/cleanup/PID validation)
- [ ] Update `mcp-server.ts` to write port file after bind
- [ ] Update `main.ts` to await startup and cleanup on quit
- [ ] Add `VOICETREE_MCP_PORT` env var for pinning
- [ ] Unit tests

**Reference**: `MCP-PORT-DISCOVERY-IMPLEMENTATION.md`, `MCP-PORT-INVESTIGATION.md`

---

### Issue #5: Critical Backend Infrastructure Fixes
**GitHub**: https://github.com/Coldaine/voicetree/issues/5
**Effort**: 2-3 hours (quick wins)

Five critical fixes for port leaks, silent crashes, and memory leaks:

- [ ] **MCP graceful shutdown**: Store `http.Server` ref, call `.close()` in `before-quit`
- [ ] **Unhandled rejection handler**: Add `process.on('unhandledRejection')` to `main.ts`
- [ ] **MCP error middleware**: Add try/catch + error middleware to Express
- [ ] **SIGTERM/SIGKILL race**: Add 5s delay between SIGTERM and SIGKILL for Python backend
- [ ] **onBackendLog leak**: Return cleanup function from IPC listener

**Reference**: `GITHUB-ISSUES-BACKEND-ROBUSTNESS.md`

---

### Issue #6: Backend Crash Recovery and Reconnection
**GitHub**: https://github.com/Coldaine/voicetree/issues/6
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

All issues live on https://github.com/Coldaine/voicetree/issues:
- [#4 MCP Port Discovery](https://github.com/Coldaine/voicetree/issues/4)
- [#5 Critical Backend Fixes](https://github.com/Coldaine/voicetree/issues/5)
- [#6 Crash Recovery](https://github.com/Coldaine/voicetree/issues/6)
- [#7 Always-On Context-Aware Ingestion](https://github.com/Coldaine/voicetree/issues/7)
- [#8 Tag-First Knowledge Model](https://github.com/Coldaine/voicetree/issues/8)
- [#9 Performance Overhaul for Large Graphs](https://github.com/Coldaine/voicetree/issues/9)
- [#10 Graph UX Redesign](https://github.com/Coldaine/voicetree/issues/10)
- [#11 Temporal Graph and Project History](https://github.com/Coldaine/voicetree/issues/11)
- [#12 Enhanced Graph Visualization](https://github.com/Coldaine/voicetree/issues/12)
