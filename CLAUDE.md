# VoiceTree - Repository Root CLAUDE.md

## FIRST: Read TODO.md

**Before starting any work, read `TODO.md` at the repo root.** It contains the full phased roadmap, all pending issues, and reference document pointers. Every task should be understood in the context of that roadmap.

Also read `COMPETITIVE-LANDSCAPE.md` to understand where VoiceTree sits relative to competitors and what ideas are worth borrowing.

## What Is This?

VoiceTree is an Electron app that provides a **live graph visualization of a markdown file tree**. You talk (or type), it creates structured markdown nodes linked via `[[wikilinks]]`, and renders them as an interactive Cytoscape.js graph. It also serves as a **multi-agent control plane** — AI agents (Claude Code, Codex, Gemini CLI) connect via MCP to spawn sub-agents, create graph nodes, and coordinate work visually.

## Repository Structure

```
voicetree/
├── webapp/                    # Main Electron application (this is where the code lives)
│   ├── src/
│   │   ├── pure/              # Pure functions (no side effects, no I/O)
│   │   │   └── graph/         # Graph data structures, parsing, positioning
│   │   └── shell/             # Impure edge/shell layer (I/O, state, side effects)
│   │       ├── edge/
│   │       │   ├── main/      # Electron main process
│   │       │   │   ├── electron/       # App lifecycle, preload, port-utils
│   │       │   │   ├── mcp-server/     # MCP server (Express, StreamableHTTP)
│   │       │   │   ├── terminals/      # PTY terminal spawning & management
│   │       │   │   ├── graph/          # File watching, markdown handling
│   │       │   │   └── state/          # App state (graph store, watch folder)
│   │       │   └── UI-edge/   # Renderer-side edge code (IPC handlers, SSE)
│   │       └── UI/            # React UI components, Cytoscape rendering
│   ├── webapp/CLAUDE.md       # Project-specific coding rules (READ THIS FIRST)
│   └── tests/                 # E2E tests (Playwright)
├── TODO.md                    # ** FULL ROADMAP - READ THIS FIRST **
├── COMPETITIVE-LANDSCAPE.md   # Market research, competitors, ideas to reuse
├── MCP-PORT-INVESTIGATION.md          # MCP port/transport analysis
├── MCP-PORT-DISCOVERY-IMPLEMENTATION.md  # Port discovery implementation plan
├── GITHUB-ISSUES-BACKEND-ROBUSTNESS.md   # Full backend architecture audit (18 issues)
├── CONSOLIDATED-GITHUB-ISSUES.md         # All scoped GitHub issues
└── this file (CLAUDE.md)
```

## Architecture at a Glance

**Three-layer communication:**
```
[MCP Clients: Claude Code / Gemini CLI]
     |  HTTP (StreamableHTTP, port 3001+)
[Electron Main Process]
     |  IPC (ipcMain/ipcRenderer via contextBridge)
[Electron Renderer (React + Cytoscape.js)]
     |  SSE (EventSource)
[Python TextToTree Backend (port 8001+)]
```

**Ingestion pathways:**
1. Voice/Text → TextToTree Python server → markdown files → graph
2. Direct markdown edits → Chokidar file watcher → graph
3. Agent MCP tools (`create_graph`) → markdown files → graph

**Key design principles** (from `webapp/CLAUDE.md`):
- Functional design, NOT OOP. Push impurity to edge/shell.
- Deep functions: minimal public API, hide internal complexity.
- Markdown files are the source of truth (frontmatter + wikilinks).
- Never use `any` type. All code is typechecked.
- Never run destructive git commands.

## Known Architectural Gaps

These are documented in detail in `TODO.md` and the GitHub issues. Be aware:

1. **No graph database.** Markdown files are the sole source of truth. ChromaDB is only a vector search cache. BM25 is computed fresh per query. There are no typed edges, no graph queries, no ACID transactions on the graph. Wikilinks are the only relationship mechanism.
2. **300-node hard cap.** `fileLimitEnforce.ts` caps at 300 files. Cytoscape renders all nodes with no virtualization. Performance is already poor at moderate counts.
3. **Backend is "happy path" code.** MCP server never shuts down (port leak), no unhandled rejection handler, SIGTERM/SIGKILL race in Python backend, no crash recovery. See Issues #5, #6.
4. **No WYSIWYG editing.** Markdown editing is through floating editors, not inline. Heptabase sets the bar here.

## Competitive Landscape — Key Learnings

See `COMPETITIVE-LANDSCAPE.md` for the full analysis. The closest projects and reusable ideas:

### Closest Competitors
| Project | Why It's Close | What to Borrow |
|---------|---------------|----------------|
| **Heptabase** | Best-in-class WYSIWYG canvas with spatial card layout | Their canvas interaction model — drag, resize, inline edit on cards. Gold standard for spatial UX. |
| **Tana** | Voice capture + AI + structured supertags | Supertag concept (typed nodes with schemas). Their voice → structured data pipeline. |
| **InfraNodus** | Text → knowledge graph with analytics | Gap detection in knowledge graphs. Their graph analytics (betweenness centrality, clustering). |
| **ScreenPipe** | Open-source ambient capture (OCR, audio, windows) | Direct integration target for Issue #7. REST API at localhost:3030. Already open source. |

### Reusable Ideas by Domain
- **Graph rendering**: **Sigma.js** renders 10k+ nodes at 60fps with WebGL. Purpose-built for large graphs. Evaluate for Issue #9.
- **Graph DB**: **Kuzu** is an embeddable graph DB (SQLite for graphs) — perfect weight class for a desktop app. **FalkorDB** (Redis-backed) is another option. Either could sit under the markdown layer.
- **Agent orchestration**: **LangGraph** has explicit state machines for agent workflows with checkpointing. VoiceTree's progress graph is a visual equivalent but lacks the formal state model.
- **Ambient capture**: **Granola** nails the "effortless" feel for meeting capture. **Limitless** shows what hardware-backed always-on looks like. VoiceTree should aim for Granola's UX with ScreenPipe's openness.
- **Temporal visualization**: **Vibe-Viz** connects git commits with visual timelines — direct inspiration for Issue #11.

### What VoiceTree Has That Others Don't
- Voice → graph pipeline (no competitor does this natively)
- Agent progress tracking on a live graph (unique paradigm)
- Open source + local-first + multi-agent MCP hub

### Existential Risks
- Heptabase adds AI agents + voice → covers our niche with better UX
- ScreenPipe adds its own knowledge graph → captures ambient market
- CrewAI/LangGraph add persistent visual state → captures agent orchestration

## Roadmap Summary

**See `TODO.md` for full details.** The roadmap has two foundational issues (Phase 0) that everything else depends on:

- **Phase 0 (Foundation)**: Service architecture (#13) + Graph DB data layer (#14) — these fix the root causes, not symptoms
- **Phase A (Stability)**: Issues #5-6 — Backend quick fixes and crash recovery (worth doing immediately)
- **Phase B (Always-On)**: Issues #7-8 — Context-aware ingestion, tag-first data model (depends on Phase 0)
- **Phase C (Scale)**: Issues #9-10 — Performance for 10k+ nodes, UX redesign (depends on graph DB)
- **Phase D (Temporal/Visual)**: Issues #11-12 — Temporal graph/history, enhanced visualization (depends on graph DB)

## GitHub Issues

Live issues: https://github.com/voicetreelab/voicetree/issues

> **Note:** The phase/issue numbers below are internal roadmap IDs from `TODO.md`.
> They do NOT match live GitHub issue numbers. See the link above for canonical tracking.

| Phase | Roadmap ID | Title |
|-------|------------|-------|
| 0 | #13 | Service Architecture (daemon model, MCP discovery) |
| 0 | #14 | Data Layer (graph DB under markdown) |
| A | #5 | Critical Backend Fixes |
| A | #6 | Crash Recovery |
| B | #7 | Always-On Context-Aware Ingestion |
| B | #8 | Tag-First Knowledge Model |
| C | #9 | Performance Overhaul |
| C | #10 | Graph UX Redesign |
| D | #11 | Temporal Graph & History |
| D | #12 | Enhanced Graph Visualization |

## Development

**Always read `webapp/CLAUDE.md` first** — it has the coding rules, dev commands, and philosophy.

Quick reference:
- `cd webapp && npm run electron` — Start dev mode (use short timeout, blocks otherwise)
- `cd webapp && npm run test` — Run unit tests
- `cd webapp && npx vitest run <file>` — Test specific file

## Git Remotes
- `origin` = `Coldaine/voicetree` (personal fork)
- `upstream` = `voicetreelab/voicetree` (org repo)
