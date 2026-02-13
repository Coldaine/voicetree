# VoiceTree MCP Server: Port & Transport Investigation

## Context
A Gemini CLI agent was unable to connect to VoiceTree's MCP server. The agent identified several issues and proposed solutions. This document analyzes those proposals against the actual codebase and current MCP standards (Feb 2026).

---

## Issue Summary from Gemini Agent Session

The Gemini agent identified:
1. **Hardcoded port 3001** with auto-increment if busy
2. **Port collisions** (Vite on 3000, MCP on 3001)
3. **Transport mismatch** - suggested VoiceTree uses wrong transport
4. **No port discovery** for external clients

The Gemini agent proposed:
1. Add stdio transport support
2. Add `VOICETREE_MCP_PORT` environment variable
3. Update configuration to use stdio

---

## Findings: What the Gemini Agent Got Right

### Port Drift Is Real
- `MCP_BASE_PORT = 3001` in `mcp-server.ts:52`
- `findAvailablePort(3001)` in `port-utils.ts` scans up to 100 ports
- If another service (Vite dev, another VoiceTree instance, etc.) grabs 3001 first, the MCP server silently moves to 3002+
- Any external client with a static `http://localhost:3001/mcp` config will fail

### External Clients Have No Discovery Mechanism
- The Gemini CLI had a static config pointing to port 3001
- VoiceTree doesn't write to any location Gemini CLI would check
- No well-known file at a global path (e.g., `%APPDATA%/VoiceTree/mcp-port.json`)

---

## Findings: What the Gemini Agent Got Wrong

### Transport Is Actually Correct
- VoiceTree uses `StreamableHTTPServerTransport` - this is the **modern MCP standard** as of spec v2025-03-26
- The old SSE transport is **deprecated**. StreamableHTTP replaced it
- Both Claude Code and Gemini CLI support StreamableHTTP
- The "Cannot GET /mcp" error is expected - the endpoint only accepts POST (correct for StreamableHTTP)

### Port Discovery Already Exists for Spawned Agents
VoiceTree has a well-designed file-based discovery system in `mcp-client-config.ts`:

1. When MCP integration is enabled, VoiceTree writes `.mcp.json` to the watched directory:
   ```json
   {
     "mcpServers": {
       "voicetree": {
         "type": "http",
         "url": "http://127.0.0.1:3003/mcp"
       }
     }
   }
   ```
2. Claude Code reads `.mcp.json` from the project root automatically
3. Codex gets `.codex/config.toml` with the same port info
4. The port is the **actual runtime port**, not the hardcoded base

### Stdio Would Break the Architecture
The Gemini agent's primary recommendation (add stdio support) is architecturally wrong:
- VoiceTree's MCP server runs **in-process with Electron** to share graph state
- It accesses `getGraph()`, `getVaultPath()`, terminal registry, etc. directly
- A stdio server would be a separate process with no access to this shared state
- You'd need an IPC bridge back to Electron, adding complexity for no benefit

---

## The Actual Problem: External Client Discovery

The root cause is simple: **VoiceTree writes discovery files for Claude Code and Codex, but not for Gemini CLI or other external tools.**

### Current Discovery Matrix

| Client | Discovery Method | Status |
|--------|-----------------|--------|
| Claude Code (spawned by VoiceTree) | `.mcp.json` in watched dir | Working |
| Codex (spawned by VoiceTree) | `.codex/config.toml` | Working |
| Claude Code (external) | `.mcp.json` in project root | Working (if project root = watched dir) |
| Gemini CLI | Manual config | **Broken** - static port config |
| Any other MCP client | Manual config | **Broken** - static port config |

### Why `.mcp.json` Doesn't Help Gemini CLI
- Gemini CLI reads its MCP config from `~/.gemini/settings.json` or project-level config
- It does NOT read `.mcp.json` (that's a Claude Code convention)
- Even if it did, the Gemini CLI instance wasn't running in the watched directory

---

## Proposed Solutions (Ranked by Impact/Effort)

### Solution 1: Global Port File (Recommended - Low Effort, High Impact)

Write the MCP port to a well-known location that any client can read using Electron's cross-platform `app.getPath('userData')`:

**File paths (cross-platform)**:
- Windows: `%APPDATA%/VoiceTree/mcp-server.json`
- macOS: `~/Library/Application Support/VoiceTree/mcp-server.json`
- Linux: `~/.config/VoiceTree/mcp-server.json` (or `$XDG_CONFIG_HOME/VoiceTree/`)

**File content**:
```json
{
  "port": 3003,
  "url": "http://127.0.0.1:3003/mcp",
  "pid": 56624,
  "startedAt": "2026-02-13T10:00:00Z"
}
```

**Implementation**:
```typescript
const portFilePath = path.join(app.getPath('userData'), 'mcp-server.json');
```

**Why this is best:**
- VoiceTree already uses `app.getPath('userData')` for logs, settings, configs (see `app-electron-state.ts:22`)
- Cross-platform by default (Electron handles OS-specific paths)
- Any external tool can read from a single well-known location per OS
- No code changes needed in external clients - just point their config at this path or read it with a wrapper script
- Works with any MCP client (Gemini, Claude Code, custom tools)
- No architectural changes to VoiceTree's MCP server

**Implementation**: ~10 lines of code in `startMcpServer()`.

### Solution 2: VOICETREE_MCP_PORT Environment Variable (Complementary)

Allow users to **pin** the MCP port to avoid drift entirely:

```typescript
const MCP_BASE_PORT = parseInt(process.env.VOICETREE_MCP_PORT ?? '3001', 10)
```

**Why this helps:**
- Users running Gemini CLI can set `VOICETREE_MCP_PORT=3050` in their shell profile
- Configure Gemini CLI to point at port 3050 - no drift possible
- Simple, zero-discovery-needed solution for power users
- Also useful if user wants to avoid port range conflicts entirely

**Tradeoff**: User must ensure the port is actually free. If it's occupied, VoiceTree either fails to start or auto-increments (defeating the purpose). Should probably fail hard if a user-specified port is unavailable.

### Solution 3: Gemini CLI Config Writer (Medium Effort)

Extend `mcp-client-config.ts` to also write Gemini CLI's config format:

**File**: `~/.gemini/settings.json` or project-level equivalent

**Why this is less ideal:**
- Gemini CLI config format may change
- Writing to `~/.gemini/` feels invasive (outside VoiceTree's domain)
- Would need to track each new MCP client's config format forever
- Better to have a universal discovery mechanism (Solution 1) instead

### Solution 4: `.well-known/mcp.json` Discovery Endpoint (Future)

The MCP specification is working on standardized HTTP discovery (SEP-1649):
- Serve `/.well-known/mcp.json` on the HTTP server
- Clients auto-discover server capabilities before connecting

**Status**: Under active development, expected Q1 2026 finalization. Not yet widely adopted by clients.

**Why not yet**: Neither Claude Code nor Gemini CLI implement client-side `.well-known` discovery today.

---

## Recommended Action Plan

### Phase 1 (Quick Win): Port File + Env Override
1. Add `VOICETREE_MCP_PORT` env var support to `mcp-server.ts`
2. Write `mcp-server.json` to `%APPDATA%/VoiceTree/` on startup
3. Clean up the port file on graceful shutdown

### Phase 2 (When clients support it): `.well-known` Discovery
4. Add `GET /.well-known/mcp.json` endpoint to the Express server
5. Returns server metadata, capabilities, and connection URL

### Do NOT Do
- Add stdio transport (breaks in-process architecture)
- Write to Gemini CLI's config directory (invasive, fragile)
- Change the default port from 3001 (would break existing setups)

---

## Architecture Notes

### Why HTTP Transport Is Correct

VoiceTree's MCP server MUST run in-process with Electron because it needs:
- Direct access to the graph state (`getGraph()`)
- Direct access to the terminal registry
- Direct access to the vault path and watched directory
- Real-time state sharing without IPC overhead

StreamableHTTPServerTransport is the correct choice because:
- It's the **current MCP standard** (v2025-03-26), replacing deprecated SSE
- It supports stateless request/response (no session management needed for VoiceTree's use case)
- Both Claude Code and Gemini CLI support it natively
- `enableJsonResponse: true` + `sessionIdGenerator: undefined` = simple stateless mode

### Port Utils Are Well-Designed
- `findAvailablePort()` tries 100 consecutive ports (reasonable)
- Binds test to `127.0.0.1` only (secure)
- Has e2e tests verifying multi-server scenarios

### MCP Client Config Is Well-Designed
- Merges with existing config (doesn't clobber other MCP servers)
- Per-client format support (`.mcp.json` for Claude, `.codex/config.toml` for Codex)
- Enables/disables cleanly without leaving artifacts

---

## Second-Opinion Agent Analysis

A second agent independently reviewed the proposed solutions and confirmed the core analysis. Key additional insights:

### Stdio Assessment: Confirmed Wrong
- stdio is designed for **one client per server process** - fundamentally incompatible with VoiceTree's shared-service model
- The only valid use for stdio would be a thin **stdio-to-HTTP proxy** for legacy tools that *only* support stdio MCP. This would be a compatibility shim, not an architecture change.

### Port File Robustness: Validated with Caveats
The global port file approach is a well-established pattern (used by OPC Foundation, Docker Desktop). Key implementation details:
- **Cross-platform paths**: Use `app.getPath('userData')` - Electron handles OS-specific paths automatically
  - Windows: `%APPDATA%/VoiceTree/`
  - macOS: `~/Library/Application Support/VoiceTree/`
  - Linux: `~/.config/VoiceTree/` (respects `$XDG_CONFIG_HOME`)
- **Stale file handling**: Write PID alongside port. On startup, check if stale port file exists (PID dead + port not listening) and clean it up
- **Atomic writes**: Write to temp file, then rename (prevents partial reads)
- **Client validation**: External clients should verify both PID liveness and port availability before connecting

### Env Var Behavior: Hard Fail Recommended
If `VOICETREE_MCP_PORT` is set and the port is occupied:
- **Hard fail** with clear error message: `"VOICETREE_MCP_PORT=3050 is occupied. Either free the port or unset the env var to auto-discover."`
- Rationale: Auto-incrementing would silently defeat the purpose of pinning
- Only auto-increment when env var is NOT set (preserves current behavior)

### Alternative Solutions Explored

| Option | Feasibility | Verdict |
|--------|------------|---------|
| **HTTP redirect at fixed port** (bind tiny server at 3001 that returns actual port) | High | Elegant but still needs port 3001 free |
| **Named Pipes** (`\\.\pipe\VoiceTree-MCP`) | Medium | No port conflicts ever, but MCP SDK support unclear |
| **mDNS/Bonjour** service advertisement | Low | Overkill for localhost discovery |
| **Unix domain sockets** (Win10 1803+) | Medium | Same MCP SDK support concern as named pipes |

The **HTTP redirect at fixed port** idea is interesting as a Phase 2 addition:
```
GET http://localhost:3001/.well-known/mcp-port → { "port": 3003 }
```
But it has a chicken-and-egg problem: if 3001 is occupied by another service, the redirect server can't bind either.

### Multi-Instance Handling
The port file should support multiple concurrent VoiceTree instances:
```json
{
  "instances": [
    { "pid": 12345, "port": 3001, "projectPath": "E:/voicetree", "startedAt": "..." },
    { "pid": 12346, "port": 3002, "projectPath": "E:/other-project", "startedAt": "..." }
  ]
}
```
Client discovery logic: match by CWD prefix against `projectPath`, fall back to first alive instance.

### Real-World Precedents
- **VSCode Remote Extensions**: Uses `vscode.env.asExternalUri()` to abstract port forwarding - extensions query runtime, don't hardcode ports
- **Docker Desktop**: Publishes dynamic port mappings, clients query daemon for published ports
- **LSP**: stdio is norm for spawned-per-editor servers; socket/HTTP only for shared servers (matches VoiceTree's use case)

---

## Final Recommended Priority

### Tier 1: Implement Now
1. **Global port file** at `app.getPath('userData')/mcp-server.json` (cross-platform, with PID, multi-instance support)
2. **`VOICETREE_MCP_PORT` env var** (hard fail if occupied)

### Tier 2: Consider for v2
3. **`.well-known/mcp-port` HTTP endpoint** on the Express server
4. **Stale instance cleanup** on startup (check PIDs of registered instances)

### Tier 3: Skip
5. stdio transport (wrong architecture)
6. mDNS (overkill)
7. Named pipes / Unix sockets (SDK support unclear)
8. Writing to Gemini CLI config directory (invasive)

---

## References
- MCP Spec v2025-03-26: StreamableHTTP transport specification
- SEP-1649: `.well-known/mcp.json` discovery proposal (in progress)
- `mcp-server.ts:242-267`: Current server startup
- `mcp-client-config.ts:83-97`: Dynamic `.mcp.json` writing
- `port-utils.ts:37-50`: Port discovery implementation
- [MCP Transport Protocols comparison (MCPcat)](https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp/)
- [Dual-Transport MCP Servers (Microsoft)](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/one-mcp-server-two-transports-stdio-and-http/4443915)
- [AWS Builder: MCP Transport Mechanisms](https://builder.aws.com/content/35A0IphCeLvYzly9Sw40G1dVNzc/mcp-transport-mechanisms-stdio-vs-streamable-http)
- [VSCode Remote Extensions architecture](https://code.visualstudio.com/api/advanced-topics/remote-extensions)
- [Docker Desktop port publishing](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/)
