# MCP Port Discovery - Implementation Plan

## Overview
Add cross-platform port discovery for external MCP clients (Gemini CLI, etc.) by writing a global port file to `app.getPath('userData')`, following VoiceTree's existing infrastructure patterns.

---

## Current State Analysis

### What Works
- **VoiceTree-spawned agents** (Claude Code, Codex): Get port via `.mcp.json`/`.codex/config.toml` in watched directory
- **Port auto-discovery**: `findAvailablePort(3001)` handles collisions (up to 100 attempts)
- **Cross-platform paths**: `app.getPath('userData')` used throughout for settings, logs, etc.

### What's Broken
- **External MCP clients** (Gemini CLI): Have static configs pointing to port 3001, break when port drifts
- **Multi-instance scenarios**: No tracking of which VoiceTree instance is on which port
- **Stale port files**: No cleanup mechanism after crashes

---

## Integration with Existing Infrastructure

Based on exploration of the codebase, here's how the port discovery file integrates with existing patterns:

### 1. File Location Pattern
**Follow**: `settings.json`, `notification-state.json`, `projects.json`, `server-debug.log`
```typescript
// All use: app.getPath('userData')
const portFilePath = path.join(app.getPath('userData'), 'mcp-server.json');
```

**Cross-platform mapping**:
- Windows: `%APPDATA%/VoiceTree/mcp-server.json`
- macOS: `~/Library/Application Support/VoiceTree/mcp-server.json`
- Linux: `~/.config/VoiceTree/mcp-server.json`

### 2. File Writing Pattern
**Follow**: `settings_IO.ts:74-80` (atomic write with directory creation)
```typescript
const portFileDir = path.dirname(portFilePath);
await fs.mkdir(portFileDir, { recursive: true });
await fs.writeFile(portFilePath, JSON.stringify(data, null, 2), 'utf-8');
```

### 3. Lifecycle Integration
**Startup** (`main.ts:76`):
```typescript
await startMcpServer(); // Currently here - writes port after binding
```

**Shutdown** (`main.ts:159-179` in `before-quit` handler):
```typescript
// Add cleanup alongside existing:
textToTreeServerManager.stop()  // line 163
terminalManager.cleanup()        // line 166
// NEW: cleanupMcpPortFile()
```

### 4. State Management Pattern
**Follow**: `app-electron-state.ts` or keep in `mcp-server.ts` module
```typescript
// mcp-server.ts already has:
let mcpPort: number = MCP_BASE_PORT
export function getMcpPort(): number { return mcpPort }

// Add if needed for external access:
export function setMcpPort(port: number): void { mcpPort = port }
```

### 5. Logging Pattern
**Follow**: `main.ts` and `RealTextToTreeServerManager.ts`
```typescript
import log from 'electron-log';

log.info(`[MCP] Port file written: ${portFilePath}`);
log.warn(`[MCP] Cleaned up stale port file from PID ${pid}`);
```

### 6. Error Handling Pattern
**Follow**: `notification-scheduler.ts:30-41` (graceful fallback)
```typescript
try {
  const data = await fs.readFile(portFilePath, 'utf-8');
  const parsed = JSON.parse(data);
  return { ...DEFAULT_STATE, ...parsed };
} catch (error) {
  if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
    return DEFAULT_STATE; // File doesn't exist yet
  }
  throw error; // Real error
}
```

---

## Implementation Plan

### Phase 1: Basic Port File (Core Fix)

**File**: `webapp/src/shell/edge/main/mcp-server/mcp-port-file.ts` (NEW)

```typescript
import { promises as fs } from 'fs';
import path from 'path';
import { app } from 'electron';

interface McpPortFileEntry {
  pid: number;
  port: number;
  url: string;
  projectPath: string | null;
  startedAt: string;
}

interface McpPortFileData {
  instances: McpPortFileEntry[];
}

function getPortFilePath(): string {
  return path.join(app.getPath('userData'), 'mcp-server.json');
}

/**
 * Write MCP server port to global discovery file
 */
export async function writeMcpPortFile(
  port: number,
  projectPath: string | null
): Promise<void> {
  const portFilePath = getPortFilePath();
  const portFileDir = path.dirname(portFilePath);

  // Ensure directory exists
  await fs.mkdir(portFileDir, { recursive: true });

  // Read existing instances
  let data: McpPortFileData;
  try {
    const content = await fs.readFile(portFilePath, 'utf-8');
    data = JSON.parse(content);
  } catch (error) {
    data = { instances: [] };
  }

  // Add this instance
  const entry: McpPortFileEntry = {
    pid: process.pid,
    port,
    url: `http://127.0.0.1:${port}/mcp`,
    projectPath,
    startedAt: new Date().toISOString()
  };

  // Replace existing entry with same PID or add new
  const existingIndex = data.instances.findIndex(i => i.pid === process.pid);
  if (existingIndex >= 0) {
    data.instances[existingIndex] = entry;
  } else {
    data.instances.push(entry);
  }

  // Clean up stale entries (PID not alive)
  data.instances = data.instances.filter(instance => {
    if (instance.pid === process.pid) return true; // Keep self
    return isPidAlive(instance.pid);
  });

  // Write atomically
  await fs.writeFile(portFilePath, JSON.stringify(data, null, 2), 'utf-8');
}

/**
 * Remove this instance from port file on shutdown
 */
export async function cleanupMcpPortFile(): Promise<void> {
  const portFilePath = getPortFilePath();

  try {
    const content = await fs.readFile(portFilePath, 'utf-8');
    const data: McpPortFileData = JSON.parse(content);

    // Remove this instance
    data.instances = data.instances.filter(i => i.pid !== process.pid);

    if (data.instances.length === 0) {
      // No instances left, delete file
      await fs.unlink(portFilePath);
    } else {
      // Write updated file
      await fs.writeFile(portFilePath, JSON.stringify(data, null, 2), 'utf-8');
    }
  } catch (error) {
    // File doesn't exist or can't be read - that's fine
  }
}

/**
 * Check if a PID is still alive (cross-platform)
 */
function isPidAlive(pid: number): boolean {
  try {
    // Sending signal 0 checks if process exists without killing it
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return false;
  }
}
```

**Changes to `mcp-server.ts`**:
```typescript
import { writeMcpPortFile } from './mcp-port-file';
import { getProjectRootWatchedDirectory } from '@/shell/edge/main/state/watch-folder-store';

export async function startMcpServer(): Promise<void> {
  // ... existing code ...

  mcpPort = await findAvailablePort(MCP_BASE_PORT);

  app.listen(mcpPort, '127.0.0.1', async () => {
    // Write port file after successful bind
    const projectPath = getProjectRootWatchedDirectory();
    await writeMcpPortFile(mcpPort, projectPath);
  });
}
```

**Changes to `main.ts`**:
```typescript
import { cleanupMcpPortFile } from './mcp-server/mcp-port-file';

app.on('before-quit', async (): Promise<void> => {
  // ... existing cleanup ...

  void textToTreeServerManager.stop();
  void terminalManager.cleanup();
  void cleanupOrphanedContextNodes();
  void stopOTLPReceiver();
  void stopNotificationScheduler();
  void stopTrackpadMonitoring();

  // NEW: Clean up MCP port file
  await cleanupMcpPortFile();
});
```

### Phase 2: Environment Variable Override

**Changes to `mcp-server.ts`**:
```typescript
export async function startMcpServer(): Promise<void> {
  const mcpServer: McpServer = createMcpServer();

  const app: Express = express();
  app.use(express.json());

  // ... existing route setup ...

  // Check for pinned port via env var
  const pinnedPort = process.env.VOICETREE_MCP_PORT;
  if (pinnedPort) {
    const port = parseInt(pinnedPort, 10);
    if (isNaN(port)) {
      throw new Error(`VOICETREE_MCP_PORT must be a number, got: ${pinnedPort}`);
    }

    const isAvailable = await isPortAvailable(port);
    if (!isAvailable) {
      throw new Error(
        `VOICETREE_MCP_PORT=${port} is already in use. ` +
        `Either free the port or unset the environment variable to use auto-discovery.`
      );
    }

    mcpPort = port;
    log.info(`[MCP] Using pinned port from VOICETREE_MCP_PORT: ${mcpPort}`);
  } else {
    // Auto-discover available port
    mcpPort = await findAvailablePort(MCP_BASE_PORT);
    log.info(`[MCP] Auto-discovered port: ${mcpPort}`);
  }

  app.listen(mcpPort, '127.0.0.1', async () => {
    const projectPath = getProjectRootWatchedDirectory();
    await writeMcpPortFile(mcpPort, projectPath);
  });
}
```

---

## Port File Format

### Multi-Instance Support
```json
{
  "instances": [
    {
      "pid": 12345,
      "port": 3001,
      "url": "http://127.0.0.1:3001/mcp",
      "projectPath": "E:/voicetree",
      "startedAt": "2026-02-13T10:30:00.000Z"
    },
    {
      "pid": 12346,
      "port": 3002,
      "url": "http://127.0.0.1:3002/mcp",
      "projectPath": "E:/other-project",
      "startedAt": "2026-02-13T11:00:00.000Z"
    }
  ]
}
```

### Single Instance (Common Case)
```json
{
  "instances": [
    {
      "pid": 12345,
      "port": 3001,
      "url": "http://127.0.0.1:3001/mcp",
      "projectPath": null,
      "startedAt": "2026-02-13T10:30:00.000Z"
    }
  ]
}
```

---

## External Client Discovery Logic

External MCP clients (Gemini CLI, custom tools) should implement this discovery pattern:

```typescript
function discoverVoiceTreeMcpPort(cwd?: string): number | null {
  const portFilePath = getPortFilePath(); // OS-specific

  try {
    const data = JSON.parse(fs.readFileSync(portFilePath, 'utf-8'));
    const instances = data.instances.filter(i => isPidAlive(i.pid));

    if (instances.length === 0) return null;

    // If in a project directory, match by path prefix
    if (cwd) {
      const match = instances.find(i =>
        i.projectPath && cwd.startsWith(i.projectPath)
      );
      if (match) return match.port;
    }

    // Otherwise, use first alive instance
    return instances[0].port;
  } catch (error) {
    return null; // File doesn't exist or can't be read
  }
}

// Cross-platform path resolution
function getPortFilePath(): string {
  if (process.platform === 'win32') {
    return path.join(process.env.APPDATA!, 'VoiceTree', 'mcp-server.json');
  } else if (process.platform === 'darwin') {
    return path.join(
      process.env.HOME!,
      'Library',
      'Application Support',
      'VoiceTree',
      'mcp-server.json'
    );
  } else {
    // Linux
    const configHome = process.env.XDG_CONFIG_HOME ||
      path.join(process.env.HOME!, '.config');
    return path.join(configHome, 'VoiceTree', 'mcp-server.json');
  }
}
```

---

## Testing Strategy

### Unit Tests
**File**: `webapp/src/shell/edge/main/mcp-server/mcp-port-file.test.ts` (NEW)

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { writeMcpPortFile, cleanupMcpPortFile } from './mcp-port-file';
import { promises as fs } from 'fs';
import path from 'path';
import { app } from 'electron';

describe('MCP Port File', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = path.join(__dirname, 'test-mcp-port-files');
    await fs.mkdir(testDir, { recursive: true });
    vi.mocked(app.getPath).mockReturnValue(testDir);
  });

  afterEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
  });

  it('writes port file with current instance', async () => {
    await writeMcpPortFile(3001, '/test/project');

    const content = await fs.readFile(
      path.join(testDir, 'mcp-server.json'),
      'utf-8'
    );
    const data = JSON.parse(content);

    expect(data.instances).toHaveLength(1);
    expect(data.instances[0].port).toBe(3001);
    expect(data.instances[0].pid).toBe(process.pid);
    expect(data.instances[0].projectPath).toBe('/test/project');
  });

  it('merges with existing instances', async () => {
    // Write first instance
    await writeMcpPortFile(3001, '/project1');

    // Simulate second instance (different PID)
    const originalPid = process.pid;
    Object.defineProperty(process, 'pid', { value: 99999, writable: true });
    await writeMcpPortFile(3002, '/project2');
    Object.defineProperty(process, 'pid', { value: originalPid, writable: true });

    const content = await fs.readFile(
      path.join(testDir, 'mcp-server.json'),
      'utf-8'
    );
    const data = JSON.parse(content);

    expect(data.instances).toHaveLength(2);
  });

  it('cleans up on shutdown', async () => {
    await writeMcpPortFile(3001, '/test/project');
    await cleanupMcpPortFile();

    // File should be deleted (no instances left)
    await expect(
      fs.access(path.join(testDir, 'mcp-server.json'))
    ).rejects.toThrow();
  });
});
```

### Integration Test
**File**: `webapp/tests/e2e/mcp-port-discovery.spec.ts` (NEW)

Test that:
1. Port file is created on VoiceTree startup
2. Port file contains correct port and PID
3. Port file is deleted on graceful shutdown
4. Multiple instances create separate entries
5. Stale entries are cleaned up

---

## Migration & Compatibility

### Backward Compatibility
- **Existing `.mcp.json` mechanism**: Unchanged, continues to work for Claude Code
- **Existing `.codex/config.toml`**: Unchanged, continues to work for Codex
- **New global port file**: Additive, doesn't break anything

### User-Facing Changes
- **None** for users who spawn agents from VoiceTree
- **Improved** for users running external MCP clients (Gemini CLI)
- **New feature**: `VOICETREE_MCP_PORT` env var for power users

---

## Documentation Updates

### User Documentation
Update VoiceTree docs to explain:
1. External MCP clients can read port from `app.getPath('userData')/mcp-server.json`
2. Environment variable `VOICETREE_MCP_PORT` pins the port (optional)
3. Multi-instance support via `projectPath` matching

### Developer Documentation
Document in `CONTRIBUTING.md` or similar:
1. Port file format and schema
2. Discovery logic for external tools
3. Testing multi-instance scenarios

---

## Rollout Plan

### Step 1: Implement Phase 1 (Port File)
- Add `mcp-port-file.ts`
- Integrate with `mcp-server.ts` and `main.ts`
- Add unit tests
- Verify cross-platform behavior

### Step 2: Add Phase 2 (Env Var)
- Add `VOICETREE_MCP_PORT` support
- Add validation and error messages
- Test pinned port scenarios

### Step 3: Integration Testing
- Test multiple VoiceTree instances
- Test stale file cleanup
- Test graceful/ungraceful shutdown

### Step 4: External Client Integration
- Update Gemini CLI config (or document manual setup)
- Create helper script for external clients
- Publish discovery logic as reference implementation

---

## Alternative Considered: HTTP Discovery Endpoint

**Approach**: Bind lightweight redirect at fixed port 3001
```typescript
// Redirect server at 3001
const redirectApp = express();
redirectApp.get('/.well-known/mcp-port', (req, res) => {
  res.json({ port: mcpPort, version: '1.0.0' });
});
redirectApp.listen(3001);

// Actual MCP server at dynamic port
app.listen(mcpPort, '127.0.0.1');
```

**Pros**:
- HTTP-native (no filesystem access needed)
- Future-proof for web clients
- Aligns with `.well-known` standard (SEP-1649)

**Cons**:
- Requires port 3001 to be free (chicken-and-egg)
- Two HTTP servers running (overhead)
- Doesn't solve multi-instance problem (which gets 3001?)

**Verdict**: Implement as Phase 3 (future enhancement), port file solves 90% of cases.

---

## Summary

This implementation:
- ✅ Follows VoiceTree's existing patterns (file locations, lifecycle, error handling)
- ✅ Cross-platform by default (Electron's `app.getPath('userData')`)
- ✅ Supports multi-instance scenarios
- ✅ Handles stale files gracefully
- ✅ Backward compatible with existing agents
- ✅ Testable with unit and integration tests
- ✅ ~100 lines of code total

The port file is written to a well-known location after the MCP server successfully binds, and cleaned up on shutdown. External clients read this file to discover the runtime port.
