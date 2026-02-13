# Codex Instructions for VoiceTree

## Before You Start — Read These Files

1. **`TODO.md`** — Full phased roadmap, all pending issues, and priorities. Every task should be understood in the context of this roadmap.
2. **`COMPETITIVE-LANDSCAPE.md`** — Market research and reusable ideas from competitors.
3. **`CLAUDE.md`** (repo root) — Repository overview, architecture, known gaps.
4. **`webapp/CLAUDE.md`** — Coding rules, dev commands, design philosophy. Mandatory before writing code.

## Project Overview

VoiceTree is an Electron app that converts voice/text input into structured markdown nodes linked via `[[wikilinks]]`, rendered as an interactive Cytoscape.js graph. Also serves as a multi-agent control plane — AI agents connect via MCP (StreamableHTTP on port 3001+) to spawn sub-agents, create graph nodes, and coordinate work.

## Code Rules

- **Functional design, NOT OOP.** Everything modeled as functions. Push impurity to edge/shell.
- **Deep functions.** Minimal public API, hide internal complexity.
- **Never use `any` type.** All code is typechecked.
- **Never run destructive git commands.**
- **Never remove human-written comments** (tagged `//human`).
- **Markdown files are the source of truth.**

## Architecture

```
webapp/src/pure/    — Pure functions (no side effects)
webapp/src/shell/   — Impure edge/shell (I/O, state, side effects)
  edge/main/        — Electron main process (MCP, terminals, graph, state)
  edge/UI-edge/     — Renderer-side edge code (IPC, SSE)
  UI/               — React components, Cytoscape rendering
```

Three ingestion pathways: Voice→Python→Markdown, File edits→Chokidar→Graph, Agent MCP→Markdown.

## Known Architectural Gaps

1. No graph database — markdown files only, ChromaDB is search cache
2. 300-node hard cap, no virtualization
3. Backend lacks crash recovery and graceful shutdown
4. No WYSIWYG editing

## Key Competitors and Ideas to Reuse

| Competitor | Reusable Idea |
|-----------|---------------|
| Heptabase | Canvas interaction model (drag, resize, inline edit) |
| Tana | Supertags (typed node schemas), voice→structured pipeline |
| Sigma.js | WebGL graph rendering for 10k+ nodes |
| Kuzu | Embeddable graph DB (SQLite for graphs) |
| ScreenPipe | Ambient capture integration (localhost:3030 REST API) |
| InfraNodus | Graph analytics (betweenness centrality, gap detection) |

## Development

- `cd webapp && npm run electron` — Dev mode (use short timeout)
- `cd webapp && npm run test` — Unit tests
- `cd webapp && npx vitest run <file>` — Specific test

## Git Remotes

- `origin` = `Coldaine/voicetree` (personal fork)
- `upstream` = `voicetreelab/voicetree`

## Issues: https://github.com/Coldaine/voicetree/issues (#4-#12)
