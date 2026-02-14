# Copilot Instructions for VoiceTree

## Before You Start

**Read these files at the repo root before doing any work:**

1. **`TODO.md`** — Full phased roadmap with all pending issues, implementation checklists, and priorities. Every task should be understood in the context of this roadmap.
2. **`COMPETITIVE-LANDSCAPE.md`** — Market research showing closest competitors and reusable ideas. Consult this when making design or architecture decisions.
3. **`CLAUDE.md`** (repo root) — Repository overview, architecture, known gaps, and competitive learnings.
4. **`webapp/CLAUDE.md`** — Coding rules, dev commands, and design philosophy. **This is mandatory before writing any code.**

## Project Overview

VoiceTree is an Electron app: voice/text input creates structured markdown nodes linked via `[[wikilinks]]`, rendered as a Cytoscape.js graph. It also serves as a multi-agent control plane via MCP (Model Context Protocol).

## Code Rules (from webapp/CLAUDE.md)

- **Functional design, NOT OOP.** Model everything as functions. Push impurity to edge/shell.
- **Deep functions.** Minimal public API, hide internal complexity. Deep and narrow.
- **Never use `any` type.** All code is typechecked.
- **Never run destructive git commands.**
- **Never remove human-written comments** (tagged `//human`).
- **Markdown files are the source of truth.** Frontmatter + wikilinks define the graph.

## Architecture

```
[MCP Clients] --HTTP--> [Electron Main] --IPC--> [React Renderer] --SSE--> [Python Backend]
```

- **Pure code**: `webapp/src/pure/` — No side effects, no I/O
- **Shell/edge code**: `webapp/src/shell/` — I/O, state, side effects
- **MCP server**: `webapp/src/shell/edge/main/mcp-server/`
- **Graph state**: `webapp/src/shell/edge/main/state/`
- **UI**: `webapp/src/shell/UI/`

## Known Gaps (Be Aware)

1. No graph database — markdown files only, ChromaDB is just a search cache
2. 300-node hard cap with no virtualization — performance is poor at scale
3. Backend is happy-path code — no crash recovery, no graceful shutdown
4. No WYSIWYG editing — floating markdown editors only

## Closest Competitors to Learn From

- **Heptabase**: Best canvas UX — study their spatial card interactions
- **Tana**: Voice + AI + supertags — their structured voice pipeline is strong
- **Sigma.js**: Renders 10k+ graph nodes at 60fps — candidate for Issue #9
- **Kuzu**: Embeddable graph DB (SQLite for graphs) — candidate for data layer
- **ScreenPipe**: Open-source ambient capture — integration target for Issue #7

## GitHub Issues

Live issues: https://github.com/voicetreelab/voicetree/issues

> **Note:** Numbers below (#4-#12) are internal roadmap IDs from `TODO.md`, not live GitHub issue numbers.

Priority order: Stability (#4-6) > Always-On (#7-8) > Scale (#9-10) > Visual (#11-12)
