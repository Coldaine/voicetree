# Consolidated GitHub Issues

> **Numbering note:** The issue numbers in this document (#1-#9) are internal to this
> specification file. They pre-date the Phase 0 restructuring of `TODO.md` and correspond
> to an older roadmap numbering. They do NOT match live GitHub issue numbers.
> See https://github.com/voicetreelab/voicetree/issues for canonical issue tracking.

## Issue #1: Implement MCP Port Discovery for External Clients

**Labels**: `enhancement`, `mcp`, `external-clients`

### Problem
External MCP clients (Gemini CLI, custom tools) can't discover VoiceTree's MCP server port when it drifts from the default 3001. VoiceTree currently writes `.mcp.json` for Claude Code/Codex in the watched directory, but external tools running outside that directory have no discovery mechanism.

**Current behavior:**
- MCP server uses `findAvailablePort(3001)` and can land on 3001-3100
- `.mcp.json` written to watched directory only (Claude Code discovers this)
- External clients with static config pointing to 3001 break when port drifts

**Impact:** Gemini CLI and other external MCP clients fail to connect.

### Solution
Write a cross-platform port discovery file to `app.getPath('userData')/mcp-server.json` that any external tool can read.

**Port file format (multi-instance support):**
```json
{
  "instances": [
    {
      "pid": 12345,
      "port": 3001,
      "url": "http://127.0.0.1:3001/mcp",
      "projectPath": "E:/voicetree",
      "startedAt": "2026-02-13T10:30:00.000Z"
    }
  ]
}
```

**Cross-platform paths:**
- Windows: `%APPDATA%/VoiceTree/mcp-server.json`
- macOS: `~/Library/Application Support/VoiceTree/mcp-server.json`
- Linux: `~/.config/VoiceTree/mcp-server.json`

### Implementation Checklist

**Phase 1: Port Discovery File**
- [ ] Create `src/shell/edge/main/mcp-server/mcp-port-file.ts` with:
  - `writeMcpPortFile(port, projectPath)` - writes/updates port file
  - `cleanupMcpPortFile()` - removes entry on shutdown
  - `isPidAlive(pid)` - checks if PID is still running (using `process.kill(pid, 0)`)
- [ ] Update `mcp-server.ts`:
  - Call `writeMcpPortFile()` after successful `app.listen()`
  - Store `http.Server` reference for later cleanup
- [ ] Update `main.ts`:
  - Await `startMcpServer()` instead of `void`
  - Call `cleanupMcpPortFile()` in `before-quit` handler
- [ ] Add unit tests in `mcp-port-file.test.ts`:
  - Test single instance write
  - Test multi-instance merge
  - Test stale PID cleanup
  - Test graceful shutdown cleanup

**Phase 2: Environment Variable Override (Optional)**
- [ ] Add `VOICETREE_MCP_PORT` env var support in `mcp-server.ts`
- [ ] Hard-fail with clear error if pinned port is occupied
- [ ] Log whether using pinned or auto-discovered port

**Phase 3: Documentation**
- [ ] Document external client discovery pattern in README
- [ ] Provide example discovery code for external tools
- [ ] Update Gemini CLI config instructions

### Files to Create/Modify
- **New**: `src/shell/edge/main/mcp-server/mcp-port-file.ts` (~100 lines)
- **New**: `src/shell/edge/main/mcp-server/mcp-port-file.test.ts` (~80 lines)
- **Modify**: `src/shell/edge/main/mcp-server/mcp-server.ts` (~10 lines)
- **Modify**: `src/shell/edge/main/electron/main.ts` (~5 lines)

### Testing
- Unit tests for port file write/cleanup/stale detection
- Manual test: Launch two VoiceTree instances, verify both in port file
- Manual test: Kill one instance, verify stale entry cleaned by other
- Manual test: Set `VOICETREE_MCP_PORT=3050`, verify it uses that port
- Manual test: External Gemini CLI reads port file and connects successfully

### Reference Documents
- Full implementation plan: `MCP-PORT-DISCOVERY-IMPLEMENTATION.md`
- Investigation analysis: `MCP-PORT-INVESTIGATION.md`

### Estimated Effort
**4-6 hours** (including tests and documentation)

---

## Issue #2: Critical Backend Infrastructure Fixes

**Labels**: `bug`, `critical`, `server-lifecycle`

### Problem
VoiceTree's backend server management has several critical gaps that cause port leaks, silent crashes, and permanent service failures under error conditions.

### Critical Fixes (Must Fix)

#### Fix 1: MCP Server Graceful Shutdown
**Problem**: MCP server never closes on app quit, leaking port until OS cleanup.

**Current code** (`mcp-server.ts:264`):
```typescript
app.listen(mcpPort, '127.0.0.1', () => {
  //console.log(`[MCP] Voicetree MCP Server running...`)
})
// http.Server reference is lost immediately
```

**Fix**:
```typescript
let mcpServerInstance: http.Server | null = null;

export async function startMcpServer(): Promise<void> {
  // ... existing code ...

  mcpServerInstance = app.listen(mcpPort, '127.0.0.1', () => {
    log.info(`[MCP] Server started on port ${mcpPort}`);
  });
}

export async function stopMcpServer(): Promise<void> {
  return new Promise((resolve) => {
    if (!mcpServerInstance) {
      resolve();
      return;
    }
    mcpServerInstance.close(() => {
      mcpServerInstance = null;
      resolve();
    });
  });
}
```

**Update `main.ts:76`**:
```typescript
await startMcpServer(); // Remove void, await it

app.on('before-quit', async () => {
  // ... existing cleanup ...
  await stopMcpServer(); // Add this
});
```

**Impact**: Prevents port exhaustion, allows rapid restart.

---

#### Fix 2: Global Unhandled Rejection Handler
**Problem**: No handler for unhandled promise rejections. Extensive use of `void` async calls throughout the codebase means crashes happen silently.

**Examples of fire-and-forget calls**:
- `void broadcastVaultState()`
- `void cleanupOrphanedContextNodes()`
- Previously `void startMcpServer()`

**Fix** (add to `main.ts` startup):
```typescript
process.on('unhandledRejection', (reason, promise) => {
  log.error('[Unhandled Rejection]', reason);
  log.error('Promise:', promise);

  // Show user dialog for critical failures
  const mainWindow = BrowserWindow.getAllWindows()[0];
  if (mainWindow && !mainWindow.isDestroyed()) {
    void dialog.showMessageBox(mainWindow, {
      type: 'error',
      title: 'Application Error',
      message: 'An unexpected error occurred. Some features may not work correctly.',
      detail: reason instanceof Error ? reason.message : String(reason)
    });
  }
});

process.on('uncaughtException', (error) => {
  log.error('[Uncaught Exception]', error);
  // Consider graceful exit for truly fatal errors
});
```

**Impact**: Prevents silent crashes, surfaces errors to users and logs.

---

#### Fix 3: MCP Server Error Middleware
**Problem**: No error handling in Express middleware. Malformed JSON or exceptions crash the server.

**Fix** (add to `mcp-server.ts`):
```typescript
export async function startMcpServer(): Promise<void> {
  const mcpServer: McpServer = createMcpServer();
  const app: Express = express();

  // Add body size limit
  app.use(express.json({ limit: '1mb' }));

  app.post('/mcp', async (req, res) => {
    try {
      const transport: StreamableHTTPServerTransport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true
      });

      res.on('close', () => {
        void transport.close();
      });

      await mcpServer.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      log.error('[MCP] Request handler error:', error);
      if (!res.headersSent) {
        res.status(500).json({
          error: 'Internal server error',
          message: error instanceof Error ? error.message : 'Unknown error'
        });
      }
    }
  });

  // Error middleware (must be last)
  app.use((err: Error, req: express.Request, res: express.Response, next: express.NextFunction) => {
    log.error('[MCP] Express error:', err);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // ... rest of startup ...
}
```

**Impact**: Graceful error responses instead of crashes.

---

#### Fix 4: TextToTree SIGTERM/SIGKILL Race
**Problem**: Python backend gets 0ms to shutdown gracefully, risks data corruption.

**Current code** (`RealTextToTreeServerManager.ts:134-135`):
```typescript
this.serverProcess.kill('SIGTERM');
this.serverProcess.kill('SIGKILL'); // Immediate!
```

**Fix**:
```typescript
public stop(): void {
  if (!this.serverProcess) return;

  this.serverProcess.kill('SIGTERM');

  // Give it 5 seconds for graceful shutdown
  const killTimeout = setTimeout(() => {
    if (this.serverProcess) {
      log.warn('[TextToTreeServer] Process did not exit gracefully, sending SIGKILL');
      this.serverProcess.kill('SIGKILL');
    }
  }, 5000);

  // Clear timeout if process exits naturally
  this.serverProcess.once('exit', () => {
    clearTimeout(killTimeout);
  });
}
```

**Impact**: Prevents data corruption in Python backend.

---

#### Fix 5: onBackendLog Memory Leak
**Problem**: `onBackendLog` in preload adds duplicate IPC listeners on every call.

**Current code** (`preload.ts:76-78`):
```typescript
onBackendLog: (callback: (message: string) => void) => {
  ipcRenderer.on('backend-log', (_event, message: string) => {
    callback(message);
  });
}
```

**Fix**:
```typescript
onBackendLog: (callback: (message: string) => void) => {
  const handler = (_event: IpcRendererEvent, message: string) => {
    callback(message);
  };
  ipcRenderer.on('backend-log', handler);

  // Return cleanup function
  return () => ipcRenderer.off('backend-log', handler);
}
```

**Impact**: Prevents memory leak in long-running sessions.

---

### Implementation Checklist

**Critical Fixes (1-2 hours total)**
- [ ] Fix 1: MCP server shutdown (30 min)
- [ ] Fix 2: Unhandled rejection handler (15 min)
- [ ] Fix 3: MCP error middleware (30 min)
- [ ] Fix 4: SIGTERM/SIGKILL race (15 min)
- [ ] Fix 5: onBackendLog leak (10 min)

**Testing**
- [ ] Manual: Quit app, verify MCP port is freed immediately
- [ ] Manual: Trigger unhandled rejection, verify dialog shown
- [ ] Manual: Send malformed JSON to MCP, verify 500 response
- [ ] Manual: Stop TextToTree, verify 5s delay before SIGKILL
- [ ] Manual: Call onBackendLog multiple times, verify no listener leak

### Files to Modify
- `src/shell/edge/main/mcp-server/mcp-server.ts` (~30 lines)
- `src/shell/edge/main/electron/main.ts` (~20 lines)
- `src/shell/edge/main/electron/server/RealTextToTreeServerManager.ts` (~15 lines)
- `src/shell/edge/main/electron/preload.ts` (~5 lines)

### Reference Documents
- Full architectural audit: `GITHUB-ISSUES-BACKEND-ROBUSTNESS.md`
- See "Medium Priority Issues" section for additional improvements

### Estimated Effort
**2-3 hours** (including manual testing)

---

## Issue #3: Backend Crash Recovery and Reconnection

**Labels**: `enhancement`, `high`, `resilience`

### Problem
When backend servers crash mid-session, features silently stop working with no automatic recovery. Users must restart the entire app.

**Affected servers:**
- **TextToTree Python backend**: Search, ask mode, transcription all fail permanently after crash
- **SSE Consumer**: Connects to stale port after backend restart, never reconnects

### Solution Overview
Add automatic crash recovery with exponential backoff and port re-discovery.

### Implementation

#### Part 1: TextToTree Auto-Restart
**Add to `RealTextToTreeServerManager.ts`:**

```typescript
private restartAttempts: number = 0;
private readonly MAX_RESTART_ATTEMPTS = 3;

private async attemptRestart(debugLog: (msg: string) => void): Promise<void> {
  if (this.restartAttempts >= this.MAX_RESTART_ATTEMPTS) {
    log.error('[TextToTreeServer] Max restart attempts reached');

    // Notify user
    const mainWindow = BrowserWindow.getAllWindows()[0];
    if (mainWindow && !mainWindow.isDestroyed()) {
      void dialog.showMessageBox(mainWindow, {
        type: 'error',
        title: 'Backend Server Failed',
        message: 'The text-to-tree server has crashed and could not be restarted.',
        detail: 'Please restart VoiceTree to restore functionality.'
      });
    }
    return;
  }

  this.restartAttempts++;
  const delay = Math.pow(2, this.restartAttempts) * 1000; // 2s, 4s, 8s

  debugLog(`[TextToTreeServer] Restarting after ${delay}ms (attempt ${this.restartAttempts}/${this.MAX_RESTART_ATTEMPTS})`);

  await new Promise(resolve => setTimeout(resolve, delay));

  try {
    await this.start(pythonCommand, cwd, vaultPath, serverEnv, debugLog);

    // Success! Reset attempts and update backend port
    this.restartAttempts = 0;
    const newPort = this.getPort();
    setBackendPort(newPort);

    // Notify renderer of port change
    const mainWindow = getMainWindow();
    if (mainWindow) {
      mainWindow.webContents.send('backend:port-changed', newPort);
    }

    debugLog('[TextToTreeServer] Successfully restarted');
  } catch (error) {
    debugLog(`[TextToTreeServer] Restart failed: ${error}`);
    await this.attemptRestart(debugLog); // Recursive retry
  }
}
```

**Update exit handler** (line 239):
```typescript
this.serverProcess.on('exit', (code: number | null, signal: string | null) => {
  debugLog(`[TextToTreeServer] Process exited with code ${code}, signal ${signal}`);
  this.serverProcess = null;

  // Auto-restart if unexpected exit
  if (code !== 0) {
    void this.attemptRestart(debugLog);
  }
});
```

---

#### Part 2: SSE Consumer Reconnection
**Add to `sse-consumer.ts`:**

```typescript
private reconnectAttempts = 0;
private readonly MAX_RECONNECT_ATTEMPTS = 10;

private async reconnect(): Promise<void> {
  if (this.reconnectAttempts >= this.MAX_RECONNECT_ATTEMPTS) {
    this.emitStatus('max_reconnect_attempts');
    return;
  }

  this.reconnectAttempts++;
  const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);

  await new Promise(resolve => setTimeout(resolve, delay));

  // Re-query backend port (may have changed after restart)
  const newPort = await window.electronAPI.getBackendPort();
  if (newPort) {
    this.connect(newPort);
  } else {
    await this.reconnect(); // Recursive retry
  }
}
```

**Update error handler**:
```typescript
this.eventSource.onerror = () => {
  this.emitStatus('connection_error');
  this.eventSource = null;
  void this.reconnect();
};
```

**Listen for port changes** (new):
```typescript
// In use-sse-consumer.ts or similar
useEffect(() => {
  const handlePortChange = (_event: any, newPort: number) => {
    // Reconnect to new port
    sseConsumer.connect(newPort);
  };

  window.electronAPI.onBackendPortChange?.(handlePortChange);

  return () => {
    // Cleanup if API provides unsubscribe
  };
}, []);
```

---

### Implementation Checklist

**Phase 1: Auto-Restart (2-3 hours)**
- [ ] Add restart logic to `RealTextToTreeServerManager.ts`
- [ ] Add `backend:port-changed` IPC event
- [ ] Add user notification on max attempts
- [ ] Test: Kill Python process, verify auto-restart
- [ ] Test: Verify port update propagates to renderer

**Phase 2: SSE Reconnection (1-2 hours)**
- [ ] Add reconnection logic to `sse-consumer.ts`
- [ ] Add `onBackendPortChange` to preload API
- [ ] Test: Restart backend, verify SSE reconnects
- [ ] Test: Verify reconnection stops at max attempts

**Phase 3: Integration (1 hour)**
- [ ] End-to-end test: Kill backend during search, verify recovery
- [ ] Test multi-crash scenario (3+ crashes)
- [ ] Verify no memory leaks from reconnection loops

### Files to Create/Modify
- **Modify**: `src/shell/edge/main/electron/server/RealTextToTreeServerManager.ts` (~60 lines)
- **Modify**: `src/shell/edge/UI-edge/text_to_tree_server_communication/sse-consumer.ts` (~40 lines)
- **Modify**: `src/shell/edge/main/electron/preload.ts` (~10 lines)

### Testing Strategy
- Simulate backend crash by killing Python process
- Verify auto-restart with port change
- Verify SSE consumer reconnects to new port
- Verify user gets notification after max restart attempts
- Load test: Does it recover from 10+ rapid crashes?

### Reference Documents
- Full architectural audit: `GITHUB-ISSUES-BACKEND-ROBUSTNESS.md` (Issues #5, #6)
- Reconnection pattern: `src/shell/UI/views/hooks/reconnectionManager.ts` (existing reference)

### Estimated Effort
**4-6 hours** (including testing and edge cases)

---

## Summary

**3 Issues Total:**
1. **MCP Port Discovery** (4-6 hours) - Solves external client connectivity
2. **Critical Backend Fixes** (2-3 hours) - Fixes port leaks, crashes, memory leaks
3. **Crash Recovery** (4-6 hours) - Auto-restart servers, reconnect SSE

**Total Estimated Effort**: 10-15 hours

**Quick Wins**: Issue #2 can be done in one sitting and eliminates most crash risks immediately.

---

## New Product Direction Issues (Always-On Workflow)

### Issue #4: Always-On Context-Aware Ingestion Pipeline

**Labels**: `enhancement`, `ingestion`, `context-awareness`, `product-core`

### Problem
VoiceTree currently behaves like a scoped/project-oriented tool. The target workflow is the opposite: always running, context-aware, and adapting to the user’s active work surface without manual project switching.

### Goal
Ingest context continuously from active user surfaces (focused app/window/tab), then route ingestion into VoiceTree automatically with source attribution and confidence.

### Scope
- Add an ingestion adapter interface for external context providers (ScreenPipe-first, extensible to browser and editor telemetry)
- Capture active-focus metadata: app, window title, URL (when available), timestamp, confidence
- Add dedupe window + rate limiting for noisy events
- Emit normalized ingestion events to backend pipeline

### Implementation Checklist
- [ ] Create `backend/context_retrieval/context_providers/base_provider.py` (provider interface)
- [ ] Create `backend/context_retrieval/context_providers/screenpipe_provider.py` (initial adapter)
- [ ] Create `backend/text_to_graph_pipeline/ingestion/ingestion_event_schema.py` (normalized event model)
- [ ] Add active-context event queue and backpressure control
- [ ] Add source attribution fields to node metadata (`source_type`, `source_ref`, `active_context_score`)
- [ ] Add feature flag: `always_on_context_ingestion`
- [ ] Add telemetry counters: event rate, dropped events, dedupe hit rate

### Acceptance Criteria
- VoiceTree can run continuously and ingest active-context events without manual project switching
- Ingestion remains stable under high-frequency focus changes
- Every ingested node has auditable source attribution

### Estimated Effort
**1-2 weeks** (including adapter hardening)

---

### Issue #5: Introduce Tag-First Knowledge Model with Multi-Relational Edges

**Labels**: `enhancement`, `data-model`, `tagging`, `graph`

### Problem
Graph relationships alone are not enough for retrieval and navigation. Users need explicit tagging and richer edge semantics to avoid brittle or sparse cross-node relationships.

### Goal
Move from graph-only linking to a hybrid model: tags + typed relationships + graph traversal.

### Scope
- Add first-class tags to node schema
- Add typed edge taxonomy (`references`, `depends_on`, `contradicts`, `extends`, `example_of`, `related_to`)
- Add auto-tag extraction from content and source context
- Update retrieval to blend tag overlap, semantic similarity, and graph proximity

### Implementation Checklist
- [ ] Extend node schema to include `tags: string[]`
- [ ] Extend edge schema to include `relation_type`
- [ ] Implement tag extraction stage in ingestion pipeline
- [ ] Add tag index for fast lookup
- [ ] Add retrieval scoring blend with configurable weights
- [ ] Add migration script for existing nodes/edges
- [ ] Add tests for tag extraction and relation coverage

### Acceptance Criteria
- Nodes can be queried by tags independent of graph shape
- Multiple typed relationships per node are supported and persisted
- Retrieval quality improves on multi-topic context stitching

### Estimated Effort
**1-2 weeks**

---

### Issue #6: Performance Overhaul for Large Graphs and Continuous Ingestion

**Labels**: `performance`, `scalability`, `high-priority`, `overhaul`

### Problem
Performance degrades significantly as node/edge count grows. Current responsiveness is insufficient for always-on usage.

### Goal
Make ingestion, retrieval, and graph interactions performant at larger scale.

### Scope
- Profile end-to-end latency (ingest -> index -> retrieval -> UI render)
- Add bounded queues and batching for ingestion/index writes
- Add incremental indexing and cache invalidation strategy
- Optimize graph query patterns and avoid full scans
- Introduce UI virtualization/level-of-detail for dense graph rendering

### Implementation Checklist
- [ ] Add benchmark suite in `backend/benchmarker/` for ingest/retrieval/render proxies
- [ ] Define SLOs: p50/p95 ingest latency and retrieval latency
- [ ] Add hot-path profiling and trace logging
- [ ] Implement batched writes + index update coalescing
- [ ] Add cache for repeated retrieval subqueries
- [ ] Add guardrails for worst-case graph traversal depth/breadth
- [ ] Add regression CI check for performance deltas

### Acceptance Criteria
- Meets target SLOs on representative large datasets
- No UI lockups on dense graphs under normal interaction
- Continuous ingestion does not starve retrieval queries

### Estimated Effort
**2-3 weeks**

---

### Issue #7: Graph UX Redesign + Non-Graph Primary Navigation

**Labels**: `ux`, `graph`, `high-priority`, `product`

### Problem
Current graph visualization is hard to interpret and does not expose cross-relationships clearly. For many workflows, graph-first interaction is not the most useful surface.

### Goal
Keep graph as a secondary exploratory tool while making primary navigation list/query/tag-driven and context-centric.

### Scope
- Add primary "Context Feed" and "Related Context" panels (non-graph)
- Add relationship inspector for a selected node (all typed edges + tags)
- Add graph controls for density, relation filters, and neighborhood depth
- Improve edge visibility and prevent single-link visual bias

### Implementation Checklist
- [ ] Define UX flows in `meta/ui_plan.md` for feed-first navigation
- [ ] Add node detail pane showing tags + all relation groups
- [ ] Add filter controls by relation type and tag
- [ ] Add neighborhood expansion controls (1-hop/2-hop/3-hop)
- [ ] Add empty/error states for overloaded graph views
- [ ] Run usability test pass against current graph-first baseline

### Acceptance Criteria
- Users can complete core retrieval workflows without opening graph view
- Graph view clearly shows multi-relationship structure when needed
- Navigation remains understandable under dense relationship sets

### Estimated Effort
**1-2 weeks**

---

### Issue #8: Temporal Graph and Project History Visualization (Vibe-Viz Integration)

**Labels**: `temporal`, `graph`, `visualization`, `history`, `enhancement`

### Problem
VoiceTree has no temporal awareness or historical tracking beyond basic timestamps (`created_at`, `modified_at`). Users cannot:
- See how the graph evolved over time
- Track which nodes were added/modified/deleted when
- Understand the timeline of project development
- Replay agent sessions or decision sequences
- Query by time ("what was I working on yesterday?")

There's no connection between the git commit history and the knowledge graph, making it hard to understand the "story" of how a project developed.

### Goal
Add temporal graph capabilities to track and visualize knowledge graph evolution over time, with integration to git history for project timeline visualization.

### Inspiration: Vibe-Viz/Viz-Vibe
A tool that creates visual timelines of GitHub projects by connecting commits with visual nodes, showing project evolution and activity patterns. This concept should be adapted to VoiceTree's knowledge graph context.

### Scope
- Add temporal node metadata (version history, change diffs)
- Build temporal index for time-based queries
- Create timeline view showing graph evolution
- Add git integration to correlate commits with graph changes
- Add session replay (watch how agents built subgraphs)
- Add "what changed recently" view with time filters
- Add temporal context retrieval ("what was context around this node yesterday?")

### Implementation Checklist
- [ ] Extend node schema with version history (`node_history: list[NodeVersion]`)
- [ ] Add temporal index structure for time-sliced queries
- [ ] Create `TemporalGraphManager` service in backend
- [ ] Add git commit correlation (commit hash ↔ graph state snapshot)
- [ ] Build timeline UI component (horizontal timeline with node events)
- [ ] Add temporal query API (`get_graph_at_timestamp`, `get_changes_since`)
- [ ] Add session replay feature (reconstruct agent work sequence)
- [ ] Add "Recent Changes" panel with time filters (last hour, day, week)
- [ ] Add temporal context retrieval mode (distance + time constraints)
- [ ] Add migration script for existing graphs (backfill from git history)

### Data Model Extensions
```python
class NodeVersion:
    timestamp: datetime
    content: str
    summary: str
    change_type: Literal["created", "modified", "appended", "deleted"]
    git_commit: Optional[str]  # SHA of related commit
    agent_session_id: Optional[str]  # Which agent made this change

class Node:
    # ... existing fields ...
    version_history: list[NodeVersion]
    
class TemporalSnapshot:
    timestamp: datetime
    graph_state: dict[int, Node]  # Full graph state at this time
    git_commit: Optional[str]
```

### UI Components
- **Timeline View**: Horizontal timeline with node creation/modification events
- **Git Integration Panel**: Show commits alongside graph changes
- **Session Replay**: Play back agent work sequences step-by-step
- **Time Travel**: View graph state at any past timestamp
- **Recent Activity Feed**: Live feed of recent changes with filters

### Acceptance Criteria
- Users can see full history of any node (all versions, diffs)
- Timeline view shows when nodes were created/modified
- Git commits are correlated with graph state changes
- Session replay reconstructs agent work with visual progression
- Time-based queries work efficiently (indexed, not full scan)
- Historical graph states can be viewed and explored

### Estimated Effort
**2-3 weeks**

---

### Issue #9: Enhanced Graph Visualization (Node Shapes, Filters, Visual Controls)

**Labels**: `visualization`, `ux`, `graph`, `enhancement`

### Problem
Current graph visualization is limited and hard to navigate:
- **Only 2-3 node shapes** (ellipse, rectangle for context/terminal nodes)
- **No visual filters** for node types, tags, or relationships
- **No shape customization** for different node categories
- **Hard to distinguish** node types at a glance
- **No legend** explaining visual encodings
- **No density controls** for crowded graphs
- **Edge labels barely visible** in dense graphs

### Goal
Make the graph visualization more expressive, filterable, and easier to navigate with rich visual encodings and interactive controls.

### Scope
- Add more node shapes (triangle, diamond, hexagon, star, custom)
- Add shape-based categorization (tasks, concepts, code, data, agents)
- Add visual filters by: node type, tag, relationship type, time range, agent
- Add edge styling (line thickness, color, pattern) based on relationship type
- Add graph density controls (collapse/expand clusters)
- Add legend panel showing current visual encodings
- Add filter panel with multi-select checkboxes
- Add minimap with semantic zoom levels

### Implementation Checklist

#### Node Shapes & Styling
- [ ] Extend node schema with `shape` field in frontmatter
- [ ] Add shape picker to node editor UI
- [ ] Implement custom Cytoscape shape renderers (triangle, diamond, hexagon, star)
- [ ] Add shape presets for common node types (task, concept, code, data, agent, person)
- [ ] Add visual legend showing shape meanings (collapsible panel)

#### Graph Filters
- [ ] Create filter panel component (slide-in from left/right)
- [ ] Add filter by node type checkboxes (regular, context, terminal)
- [ ] Add filter by tag multi-select (auto-populated from graph)
- [ ] Add filter by relationship type (references, depends_on, etc.)
- [ ] Add filter by time range (created/modified in last X days)
- [ ] Add filter by agent (which agent created/modified)
- [ ] Add "show only connected to selected" filter
- [ ] Persist filter state in localStorage

#### Edge Enhancements
- [ ] Add edge styling based on relationship type (color, thickness, pattern)
- [ ] Add edge label visibility toggle (show/hide/auto)
- [ ] Add edge bundling for dense graphs (reduce edge crossings)
- [ ] Add curved edges option (bezier vs straight)

#### Graph Controls
- [ ] Add density slider (controls visible edge/node thresholds)
- [ ] Add cluster collapse/expand (group related nodes)
- [ ] Add semantic zoom (different detail levels at different zoom)
- [ ] Add "focus mode" (dim everything except selected + neighbors)
- [ ] Add minimap with viewport indicator (collapsible corner widget)

#### Visual Encodings
- [ ] Node size by degree (importance)
- [ ] Node border thickness by num_appends (activity)
- [ ] Node opacity by last_modified (fade old nodes)
- [ ] Edge thickness by relationship strength (if weighted)

### UI Mock Flow
```
[Graph View]
├── Left Panel: Filters
│   ├── Node Type: [✓ Regular] [✓ Context] [✓ Terminal]
│   ├── Tags: [✓ architecture] [✓ backend] [ ] testing
│   ├── Relations: [✓ references] [ ] depends_on
│   ├── Time: [Last 7 days ▼]
│   └── Agent: [All agents ▼]
├── Bottom Bar: Legend
│   ├── Shapes: ⬢=Concept, ▲=Task, ⬟=Code, ★=Important
│   ├── Colors: Purple=Backend, Blue=Frontend, Green=Done
│   └── Edges: Solid=references, Dashed=depends_on
└── Top Right: Controls
    ├── Minimap [toggle]
    ├── Density [slider]
    └── Focus Mode [toggle]
```

### Acceptance Criteria
- Users can distinguish node types by shape at a glance
- Filter panel works without lag on 300+ node graphs
- Legend accurately reflects current visual encodings
- Minimap provides spatial context for large graphs
- Edge labels remain readable in dense graphs
- Filter state persists across sessions

### Estimated Effort
**2-3 weeks**

---

## Updated Summary (Including Temporal and Visual Enhancements)

**9 Issues Total:**
1. MCP Port Discovery
2. Critical Backend Fixes
3. Crash Recovery
4. Always-On Context-Aware Ingestion
5. Tag-First + Multi-Relational Data Model
6. Performance Overhaul
7. Graph UX Redesign + Non-Graph Navigation
8. Temporal Graph and Project History Visualization
9. Enhanced Graph Visualization (Shapes, Filters, Visual Controls)

**Recommended Sequencing**:
- Phase A (stability foundation): Issues #1-3
- Phase B (always-on intelligence core): Issues #4-5
- Phase C (scale and usability): Issues #6-7
- Phase D (temporal and visual): Issues #8-9
