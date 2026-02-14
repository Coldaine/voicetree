# GitHub Issues: Backend Infrastructure Robustness

Generated from architectural audit of VoiceTree's WebSocket/server management infrastructure.

> **Numbering note:** Issue numbers in this document (#1-#17) are internal to this
> audit report. They do NOT match live GitHub issue numbers or other roadmap IDs.
> See https://github.com/voicetreelab/voicetree/issues for canonical tracking.

---

## Critical Priority Issues

### Issue #1: MCP Server has no graceful shutdown (port leak)

**Labels**: `bug`, `critical`, `server-lifecycle`

**Description**:
The MCP Express server is never gracefully shut down when the app quits, causing port leaks.

**Current Behavior**:
- `startMcpServer()` called at `main.ts:76` with `void` (fire-and-forget)
- `app.listen()` returns `http.Server` but reference is never stored
- On `before-quit` event, MCP server is not stopped
- Port remains bound until OS cleans it up, preventing rapid restart

**Expected Behavior**:
- Store server reference from `app.listen()`
- Call `server.close()` in `before-quit` handler
- Await `startMcpServer()` to catch startup errors

**Files Affected**:
- `src/shell/edge/main/mcp-server/mcp-server.ts:242-267`
- `src/shell/edge/main/electron/main.ts:76`

**Implementation**:
```typescript
// mcp-server.ts
let mcpServerInstance: http.Server | null = null;

export async function startMcpServer(): Promise<void> {
  // ... existing code ...

  mcpServerInstance = app.listen(mcpPort, '127.0.0.1', async () => {
    const projectPath = getProjectRootWatchedDirectory();
    await writeMcpPortFile(mcpPort, projectPath);
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

// main.ts
await startMcpServer(); // Remove void, await it

app.on('before-quit', async () => {
  // ... existing cleanup ...
  await stopMcpServer(); // Add this
});
```

---

### Issue #2: No global unhandled rejection handler (silent crashes)

**Labels**: `bug`, `critical`, `error-handling`

**Description**:
Unhandled promise rejections in the main process can crash Electron silently with no error logging or user notification.

**Current Behavior**:
- No `process.on('unhandledRejection')` handler anywhere
- Extensive use of `void` fire-and-forget async calls: `void startMcpServer()`, `void broadcastVaultState()`, `void cleanupOrphanedContextNodes()`
- If any of these throw, the app crashes with no diagnostic info

**Expected Behavior**:
- Log unhandled rejections to electron-log
- Surface critical errors to users via dialog
- Attempt graceful recovery where possible

**Files Affected**:
- `src/shell/edge/main/electron/main.ts`

**Implementation**:
```typescript
// Add to main.ts startup
process.on('unhandledRejection', (reason, promise) => {
  log.error('[Unhandled Rejection]', reason);
  log.error('Promise:', promise);

  // For critical infrastructure failures, notify user
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
  // Potentially more severe - consider exiting gracefully
});
```

---

### Issue #3: MCP server has no error middleware (crash on malformed requests)

**Labels**: `bug`, `critical`, `server-lifecycle`

**Description**:
The MCP Express server has no error-handling middleware. Malformed JSON or exceptions in request handlers can crash the server.

**Current Behavior**:
- No `app.use((err, req, res, next) => ...)` error handler
- No request body size limit on `express.json()`
- `mcpServer.connect(transport)` is not wrapped in try/catch (line 258)
- Exception in StreamableHTTPServerTransport could crash the process

**Expected Behavior**:
- Graceful error handling with 500 responses
- Request size limits to prevent memory attacks
- Catch and log transport errors

**Files Affected**:
- `src/shell/edge/main/mcp-server/mcp-server.ts:245-266`

**Implementation**:
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

  // Add error middleware (must be last)
  app.use((err: Error, req: express.Request, res: express.Response, next: express.NextFunction) => {
    log.error('[MCP] Express error:', err);
    res.status(500).json({ error: 'Internal server error' });
  });

  // ... rest of startup ...
}
```

---

## High Priority Issues

### Issue #4: TextToTree server SIGTERM/SIGKILL race (data corruption risk)

**Labels**: `bug`, `high`, `server-lifecycle`

**Description**:
TextToTree server sends SIGTERM immediately followed by SIGKILL, giving the Python process zero time for graceful shutdown.

**Current Behavior**:
```typescript
this.serverProcess.kill('SIGTERM');
this.serverProcess.kill('SIGKILL'); // Sent immediately, no delay
```

**Impact**: Python server cannot flush buffers, close DB connections, or save state. Risk of data corruption.

**Expected Behavior**:
- Send SIGTERM
- Wait 5 seconds for graceful shutdown
- If still alive, send SIGKILL

**Files Affected**:
- `src/shell/edge/main/electron/server/RealTextToTreeServerManager.ts:134-135`

**Implementation**:
```typescript
public stop(): void {
  if (!this.serverProcess) return;

  this.serverProcess.kill('SIGTERM');

  // Give it 5 seconds to exit gracefully
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

---

### Issue #5: No TextToTree server crash recovery (silent feature loss)

**Labels**: `bug`, `high`, `server-lifecycle`, `user-experience`

**Description**:
If the TextToTree Python server crashes mid-session, search/ask/transcription features silently stop working with no automatic recovery.

**Current Behavior**:
- `exit` event handler (line 239-244) sets `this.serverProcess = null` and logs
- No restart attempt
- SSE consumer and backend API have no reconnection logic
- User must manually restart entire Electron app

**Expected Behavior**:
- Automatic restart with exponential backoff (max 3 attempts)
- Update `backendPort` after successful restart
- Notify renderer of port change for SSE reconnection
- Show user notification if restart fails

**Files Affected**:
- `src/shell/edge/main/electron/server/RealTextToTreeServerManager.ts:239-244`
- `src/shell/edge/UI-edge/text_to_tree_server_communication/sse-consumer.ts`

**Implementation**: See attached recovery pattern with retry logic and port update notification.

---

### Issue #6: SSE Consumer has no reconnection logic (permanent connection loss)

**Labels**: `bug`, `high`, `frontend`, `connectivity`

**Description**:
The SSE EventSource consumer does not reconnect on error. If TextToTree server restarts on a different port, the SSE consumer connects to stale port indefinitely.

**Current Behavior**:
- `EventSource.onerror` only emits status event, no reconnection
- Native EventSource auto-reconnect doesn't handle port changes
- After server restart on new port, SSE consumer is permanently disconnected

**Expected Behavior**:
- Reconnect with exponential backoff on error
- Re-query `getBackendPort()` before each reconnection attempt
- Update EventSource URL if port has changed

**Files Affected**:
- `src/shell/edge/UI-edge/text_to_tree_server_communication/sse-consumer.ts`
- `src/shell/edge/UI-edge/text_to_tree_server_communication/use-sse-consumer.ts`

**Implementation**: Adapt `reconnectionManager.ts` pattern used for speech client.

---

### Issue #7: Terminal sender references become stale after renderer restart

**Labels**: `bug`, `high`, `terminal-management`

**Description**:
Terminal `sender.send()` calls can throw if the renderer is destroyed. Sender references are captured at spawn time and never updated when windows are recreated (macOS activate).

**Current Behavior**:
- `sender` reference captured in `spawnTerminal()` at line 111
- If window closes and new one opens, sender ref is stale
- `sender.send('terminal:data')` throws, caught in try/catch (good), but output is lost
- `terminalToWindow` cleanup only on window close, not sender destruction

**Expected Behavior**:
- Update sender references when main window changes
- Queue terminal output when sender is unavailable
- Replay queued output when sender becomes available

**Files Affected**:
- `src/shell/edge/main/terminals/terminal-manager.ts:115-130`
- `src/shell/edge/main/state/app-electron-state.ts`

---

### Issue #8: Preload async init race (API undefined during early render)

**Labels**: `bug`, `high`, `electron`, `initialization`

**Description**:
`exposeElectronAPI()` is async and may not complete before renderer starts executing, leaving `window.electronAPI` undefined.

**Current Behavior**:
- `preload.ts:25-158` calls `ipcRenderer.invoke('rpc:getApiKeys')` before exposing API
- Early IPC messages can be lost (documented in `ui-rpc-handler.test.ts:118-139`)
- No queue/buffer for messages sent before API is ready

**Expected Behavior**:
- Synchronous API exposure with lazy loading of API keys
- Queue early IPC messages until API is ready
- Or: Block renderer start until preload completes

**Files Affected**:
- `src/shell/edge/main/electron/preload.ts:25-158`
- `src/shell/edge/UI-edge/ui-rpc-handler.test.ts:118-139`

---

## Medium Priority Issues

### Issue #9: Graph state sync is fire-and-forget (delta loss risk)

**Labels**: `enhancement`, `medium`, `state-management`

**Description**:
Graph delta broadcasts from main to renderer have no acknowledgment, ordering guarantees, or loss detection.

**Current Behavior**:
- `mainWindow.webContents.send('graph:stateChanged', delta)` at line 52
- No sequence numbers, delta IDs, or missed-delta detection
- If renderer is busy, Electron's IPC buffer could drop deltas
- No full-state resync mechanism

**Expected Behavior**:
- Add monotonic sequence numbers to deltas
- Renderer detects gaps and requests full resync
- Optional: Renderer ACKs each delta

**Files Affected**:
- `src/shell/edge/main/graph/markdownHandleUpdateFromStateLayerPaths/applyGraphDeltaToDBThroughMemAndUI.ts:52`

---

### Issue #10: uiAPI proxy silently drops calls when window unavailable

**Labels**: `bug`, `medium`, `state-management`

**Description**:
When `mainWindow` is null or destroyed, `uiAPI` calls are silently dropped with only a console.log.

**Current Behavior**:
```typescript
if (!mainWindow || mainWindow.isDestroyed()) {
  console.log(`UI API call to ${funcName} ignored: no window available`);
  return;
}
```

**Impact**: `syncTerminals()`, `updateInjectBadge()`, `createEditorForExternalNode()` silently fail.

**Expected Behavior**:
- Queue calls when window unavailable
- Replay queue when window becomes available
- Or: Return error to caller

**Files Affected**:
- `src/shell/edge/main/ui-api-proxy.ts:22-26`

---

### Issue #11: Multiple servers compete for ports with no coordination

**Labels**: `enhancement`, `medium`, `server-lifecycle`

**Description**:
TextToTree (8001+), MCP (3001+), and OTLP (4318+) all use `findAvailablePort()` independently. Multiple app instances can't coordinate.

**Current Behavior**:
- Each server finds its own port with no global coordination
- If all ports shift, agents can't discover them
- No lock file or registry for multi-instance scenarios

**Expected Behavior**:
- Centralized port registry (e.g., `server-ports.json`)
- All servers register their ports
- Port discovery file tracks all instances

**Related**: Port discovery implementation (MCP-PORT-DISCOVERY-IMPLEMENTATION.md) partially solves this for MCP.

---

### Issue #12: No request timeout on MCP Express endpoints

**Labels**: `enhancement`, `medium`, `server-lifecycle`

**Description**:
MCP `/mcp` endpoint has no timeout. Slow tools (e.g., `create_graph` with many nodes) can hold connections indefinitely.

**Current Behavior**:
- No timeout middleware
- No backpressure for concurrent requests
- A single slow tool call can block the server

**Expected Behavior**:
- Add request timeout middleware (e.g., 60 seconds)
- Consider concurrent request limit

**Files Affected**:
- `src/shell/edge/main/mcp-server/mcp-server.ts`

---

### Issue #13: onBackendLog API leaks listeners (memory leak)

**Labels**: `bug`, `medium`, `memory-leak`

**Description**:
`onBackendLog` in preload.ts registers IPC listeners but doesn't return an unsubscribe function. Calling it multiple times adds duplicate listeners.

**Current Behavior**:
```typescript
onBackendLog: (callback: (message: string) => void) => {
  ipcRenderer.on('backend-log', (_event, message: string) => {
    callback(message);
  });
}
```

**Expected Behavior**:
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

**Files Affected**:
- `src/shell/edge/main/electron/preload.ts:76-78`

---

### Issue #14: File watcher error handler just logs (no recovery)

**Labels**: `bug`, `medium`, `file-watching`

**Description**:
Chokidar file watcher error handler logs but doesn't recover. Fatal errors (EMFILE) silently stop watching.

**Current Behavior**:
```typescript
currentWatcher.on('error', (error) =>
  console.error('File watcher error:', error)
);
```

**Expected Behavior**:
- Attempt watcher restart with backoff
- Notify user of watching failure
- Surface EMFILE errors with actionable guidance

**Files Affected**:
- `src/shell/edge/main/graph/watch_folder/file-watcher-setup.ts:153-155`

---

## Low Priority Issues

### Issue #15: Duplicate allowlist declarations in preload.ts (DRY violation)

**Labels**: `refactor`, `low`, `code-quality`

**Description**:
Three separate `ALLOWED_*_CHANNELS` arrays must be manually synchronized when adding IPC channels.

**Files Affected**:
- `src/shell/edge/main/electron/preload.ts:101-147`

**Recommendation**: Single source of truth for allowed channels.

---

### Issue #16: No rate limiting on MCP server (DoS risk)

**Labels**: `enhancement`, `low`, `security`

**Description**:
MCP server bound to `127.0.0.1` (good) but has no rate limiting. Runaway agent could flood requests.

**Recommendation**: Add rate limiting middleware (e.g., express-rate-limit).

---

### Issue #17: Terminal spawn returns success:true on error (broken contract)

**Labels**: `bug`, `low`, `api-contract`

**Description**:
Terminal spawn catch block returns `{ success: true, terminalId }` even on failure, making it impossible for caller to detect errors.

**Files Affected**:
- `src/shell/edge/main/terminals/terminal-manager.ts:158`

**Fix**: Return `{ success: false, error: ... }` on actual failures.

---

## Epic: Add React ErrorBoundary

**Labels**: `enhancement`, `medium`, `frontend`

**Description**:
Neither frontend nor backend have error boundaries. Adding React ErrorBoundary would catch render errors and prevent white screens.

**Recommendation**: Wrap main app components with ErrorBoundary that shows fallback UI and logs to electron-log.

---

## Summary Statistics

- **Critical**: 3 issues
- **High**: 5 issues
- **Medium**: 6 issues
- **Low**: 3 issues
- **Epic**: 1 issue

**Total**: 18 issues identified

**Estimated effort**:
- Tier 1 (Critical + High 1-4): 2-3 days
- Tier 2 (High 5-8): 3-4 days
- Tier 3 (Medium): 2-3 days
- Tier 4 (Low): 1 day

**Total**: ~10-15 days of focused work

---

## Implementation Priority

Recommended order:
1. Issue #2 (unhandled rejection handler) - 30 minutes, prevents silent crashes
2. Issue #1 (MCP shutdown) - 1 hour, prevents port leaks
3. Issue #3 (MCP error middleware) - 1 hour, prevents server crashes
4. Issue #4 (SIGTERM/SIGKILL race) - 1 hour, prevents data corruption
5. Issue #13 (onBackendLog leak) - 30 minutes, prevents memory leaks
6. Issues #5-8 (crash recovery, reconnection) - 1-2 days each

**Quick wins**: Issues #1, #2, #3, #4, #13 can be done in a single 4-hour session and eliminate most crash risks.
