# Phase 0 — Foundation: FalkorDB + Service Architecture

> **Duration**: Weeks 1–4  
> **Effort**: ~160 hours  
> **Depends on**: Nothing (first phase)  
> **Enables**: All subsequent phases

---

## Goals

1. **FalkorDB running as a Docker container**, managed by Electron's lifecycle (start on launch, stop on quit)
2. **Cypher schema deployed** with nodes, typed edges, tags, temporal versions, and vector indexes
3. **Basic CRUD operations** via TypeScript client (`@falkordb/falkordb`)
4. **Fixed-port MCP server** with `voicetree setup` CLI for one-time client configuration
5. **Graceful lifecycle management** — clean startup, shutdown, port cleanup, container cleanup
6. **Migration tool** that imports existing markdown vaults into FalkorDB

---

## Prerequisites

- Docker Desktop installed (or Docker Engine on Linux)
- Node.js 20+ / Electron 28+
- Existing v1 codebase tagged `v1.0.0-final`

---

## Task Breakdown

### 0.1 — FalkorDB Docker Setup (Days 1–3)

**Goal**: Electron spawns a FalkorDB Docker container on startup and kills it on quit.

#### Docker Configuration

```yaml
# docker-compose.falkordb.yml
version: '3.8'
services:
  falkordb:
    image: falkordb/falkordb:latest
    container_name: voicetree-falkordb
    ports:
      - "${VOICETREE_FALKORDB_PORT:-6379}:6379"
    volumes:
      - voicetree-data:/data
    environment:
      - FALKORDB_ARGS=TIMEOUT 0
    command: >
      redis-server
      --loadmodule /usr/lib/redis/modules/falkordb.so
      --save 60 1
      --appendonly yes
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  voicetree-data:
    name: voicetree-data
```

#### Electron Container Manager

```typescript
// src/shell/edge/main/falkordb/container-manager.ts

import { execFile } from 'child_process';
import { promisify } from 'util';

const exec = promisify(execFile);

interface ContainerStatus {
  running: boolean;
  containerId: string | null;
  port: number;
}

const CONTAINER_NAME = 'voicetree-falkordb';
const DEFAULT_PORT = 6379;

export async function startFalkorDB(port: number = DEFAULT_PORT): Promise<ContainerStatus> {
  // Check if container already exists
  const existing = await getContainerStatus();
  if (existing.running) return existing;

  // Check if stopped container exists — restart it
  if (existing.containerId) {
    await exec('docker', ['start', CONTAINER_NAME]);
    return waitForHealthy(port);
  }

  // Create new container
  await exec('docker', [
    'run', '-d',
    '--name', CONTAINER_NAME,
    '-p', `${port}:6379`,
    '-v', 'voicetree-data:/data',
    '--health-cmd', 'redis-cli ping',
    '--health-interval', '5s',
    '--health-timeout', '3s',
    '--health-retries', '5',
    '--restart', 'unless-stopped',
    'falkordb/falkordb:latest',
    'redis-server',
    '--loadmodule', '/usr/lib/redis/modules/falkordb.so',
    '--save', '60', '1',
    '--appendonly', 'yes',
  ]);

  return waitForHealthy(port);
}

export async function stopFalkorDB(): Promise<void> {
  try {
    await exec('docker', ['stop', CONTAINER_NAME]);
  } catch {
    // Container may not exist — that's fine
  }
}

export async function getContainerStatus(): Promise<ContainerStatus> {
  try {
    const { stdout } = await exec('docker', [
      'inspect', '--format', '{{.State.Running}} {{.Id}}', CONTAINER_NAME
    ]);
    const [running, id] = stdout.trim().split(' ');
    return { running: running === 'true', containerId: id ?? null, port: DEFAULT_PORT };
  } catch {
    return { running: false, containerId: null, port: DEFAULT_PORT };
  }
}

async function waitForHealthy(port: number, timeoutMs: number = 30_000): Promise<ContainerStatus> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const status = await getContainerStatus();
    if (status.running) return { ...status, port };
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`FalkorDB container did not become healthy within ${timeoutMs}ms`);
}
```

**Effort**: 1 day  
**Risk**: Docker not installed → show user-friendly error with install link  
**Test**: Container starts, responds to `redis-cli GRAPH.QUERY voicetree "RETURN 1"`

---

### 0.2 — FalkorDB TypeScript Client + Connection Pool (Days 2–4)

**Goal**: Establish a typed FalkorDB client wrapper with connection management.

#### Install Dependencies

```bash
npm install @falkordb/falkordb redis
```

#### Client Wrapper

```typescript
// src/shell/edge/main/falkordb/client.ts

import { FalkorDB, Graph } from '@falkordb/falkordb';

interface FalkorDBConfig {
  host: string;
  port: number;
  graphName: string;
}

const DEFAULT_CONFIG: FalkorDBConfig = {
  host: '127.0.0.1',
  port: 6379,
  graphName: 'voicetree',
};

let dbInstance: FalkorDB | null = null;
let graphInstance: Graph | null = null;

export async function connectFalkorDB(
  config: Partial<FalkorDBConfig> = {}
): Promise<Graph> {
  const resolved = { ...DEFAULT_CONFIG, ...config };

  if (graphInstance) return graphInstance;

  dbInstance = await FalkorDB.connect({
    socket: {
      host: resolved.host,
      port: resolved.port,
    },
  });

  graphInstance = dbInstance.selectGraph(resolved.graphName);
  return graphInstance;
}

export async function disconnectFalkorDB(): Promise<void> {
  if (dbInstance) {
    await dbInstance.close();
    dbInstance = null;
    graphInstance = null;
  }
}

export function getGraph(): Graph {
  if (!graphInstance) {
    throw new Error('FalkorDB not connected. Call connectFalkorDB() first.');
  }
  return graphInstance;
}
```

**Effort**: 0.5 days  
**Test**: Connect, run `RETURN 1`, disconnect cleanly

---

### 0.3 — Cypher Schema Design (Days 3–6)

**Goal**: Define the complete graph schema in Cypher, including vector indexes.

#### Schema Creation Script

```typescript
// src/shell/edge/main/falkordb/schema.ts

import { Graph } from '@falkordb/falkordb';

/**
 * Deploy the VoiceTree schema to FalkorDB.
 * Idempotent — safe to run on every startup.
 */
export async function deploySchema(graph: Graph): Promise<void> {
  // ──────────────────────────────────────
  // Node indexes
  // ──────────────────────────────────────

  // Full-text index on node content for BM25 search
  await graph.query(`
    CREATE INDEX FOR (n:Node) ON (n.id)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (n:Node) ON (n.title)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (n:Node) ON (n.node_type)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (n:Node) ON (n.created_at)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (n:Node) ON (n.vault_id)
  `).catch(ignoreExistingIndex);

  // Full-text search index
  await graph.query(`
    CALL db.idx.fulltext.createNodeIndex('Node', 'title', 'content', 'summary')
  `).catch(ignoreExistingIndex);

  // Vector index for semantic search (1536 dims for OpenAI, 384 for MiniLM)
  await graph.query(`
    CALL db.idx.vector.createNodeIndex(
      'Node',
      'embedding',
      384,
      'cosine'
    )
  `).catch(ignoreExistingIndex);

  // ──────────────────────────────────────
  // Tag indexes
  // ──────────────────────────────────────
  await graph.query(`
    CREATE INDEX FOR (t:Tag) ON (t.name)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (t:Tag) ON (t.category)
  `).catch(ignoreExistingIndex);

  // ──────────────────────────────────────
  // Vault indexes
  // ──────────────────────────────────────
  await graph.query(`
    CREATE INDEX FOR (v:Vault) ON (v.id)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (v:Vault) ON (v.project_path)
  `).catch(ignoreExistingIndex);

  // ──────────────────────────────────────
  // Version indexes
  // ──────────────────────────────────────
  await graph.query(`
    CREATE INDEX FOR (ver:NodeVersion) ON (ver.node_id)
  `).catch(ignoreExistingIndex);

  await graph.query(`
    CREATE INDEX FOR (ver:NodeVersion) ON (ver.timestamp)
  `).catch(ignoreExistingIndex);
}

function ignoreExistingIndex(err: Error): void {
  // FalkorDB throws if index already exists — that's fine
  if (err.message?.includes('already indexed') || err.message?.includes('Index already exists')) {
    return;
  }
  throw err;
}
```

#### Node Creation Example

```typescript
// Examples of CRUD operations against the schema

import { Graph } from '@falkordb/falkordb';
import { v4 as uuid } from 'uuid';

interface CreateNodeInput {
  title: string;
  content: string;
  summary?: string;
  nodeType: 'voice' | 'agent' | 'manual' | 'ambient';
  sourceType: 'whisper' | 'screenpipe' | 'mcp' | 'editor';
  sourceRef?: string;
  vaultId: string;
  tags?: string[];
  embedding?: number[];
}

export async function createNode(graph: Graph, input: CreateNodeInput): Promise<string> {
  const nodeId = uuid();
  const now = new Date().toISOString();

  // Create the node
  await graph.query(`
    CREATE (n:Node {
      id: $id,
      title: $title,
      content: $content,
      summary: $summary,
      node_type: $nodeType,
      source_type: $sourceType,
      source_ref: $sourceRef,
      vault_id: $vaultId,
      created_at: $createdAt,
      modified_at: $modifiedAt,
      embedding: vecf32($embedding)
    })
  `, {
    params: {
      id: nodeId,
      title: input.title,
      content: input.content,
      summary: input.summary ?? '',
      nodeType: input.nodeType,
      sourceType: input.sourceType,
      sourceRef: input.sourceRef ?? '',
      vaultId: input.vaultId,
      createdAt: now,
      modifiedAt: now,
      embedding: input.embedding ?? [],
    }
  });

  // Link to vault
  await graph.query(`
    MATCH (v:Vault {id: $vaultId}), (n:Node {id: $nodeId})
    CREATE (v)-[:CONTAINS]->(n)
  `, {
    params: { vaultId: input.vaultId, nodeId }
  });

  // Create tags and link them
  if (input.tags?.length) {
    for (const tagName of input.tags) {
      await graph.query(`
        MERGE (t:Tag {name: $tagName, category: 'auto'})
        WITH t
        MATCH (n:Node {id: $nodeId})
        CREATE (n)-[:TAGGED_WITH]->(t)
      `, {
        params: { tagName, nodeId }
      });
    }
  }

  return nodeId;
}

export async function createEdge(
  graph: Graph,
  fromNodeId: string,
  toNodeId: string,
  relationType: string,
  createdBy: string,
  weight: number = 1.0
): Promise<void> {
  // FalkorDB requires relationship types to be known at query time
  // We use a generic RELATES_TO with a property for the specific type
  await graph.query(`
    MATCH (a:Node {id: $fromId}), (b:Node {id: $toId})
    CREATE (a)-[:RELATES_TO {
      relation_type: $relationType,
      weight: $weight,
      created_at: $createdAt,
      created_by: $createdBy
    }]->(b)
  `, {
    params: {
      fromId: fromNodeId,
      toId: toNodeId,
      relationType,
      weight,
      createdAt: new Date().toISOString(),
      createdBy,
    }
  });
}
```

#### Query Examples

```typescript
// Vector similarity search
export async function vectorSearch(
  graph: Graph,
  queryEmbedding: number[],
  topK: number = 10,
  vaultId?: string
): Promise<Array<{ id: string; title: string; score: number }>> {
  const vaultFilter = vaultId ? 'AND n.vault_id = $vaultId' : '';
  
  const result = await graph.query(`
    CALL db.idx.vector.queryNodes(
      'Node',
      'embedding',
      $topK,
      vecf32($queryEmbedding)
    )
    YIELD node, score
    WHERE node.id IS NOT NULL ${vaultFilter}
    RETURN node.id AS id, node.title AS title, score
    ORDER BY score DESC
  `, {
    params: {
      topK,
      queryEmbedding,
      ...(vaultId ? { vaultId } : {}),
    }
  });

  return result.data?.map((row: Record<string, unknown>) => ({
    id: row['id'] as string,
    title: row['title'] as string,
    score: row['score'] as number,
  })) ?? [];
}

// Graph traversal — find all nodes within N hops
export async function getNeighborhood(
  graph: Graph,
  nodeId: string,
  maxHops: number = 2
): Promise<Array<{ id: string; title: string; depth: number }>> {
  const result = await graph.query(`
    MATCH path = (start:Node {id: $nodeId})-[*1..${maxHops}]-(neighbor:Node)
    RETURN DISTINCT neighbor.id AS id, neighbor.title AS title,
           length(path) AS depth
    ORDER BY depth ASC
  `, {
    params: { nodeId }
  });

  return result.data?.map((row: Record<string, unknown>) => ({
    id: row['id'] as string,
    title: row['title'] as string,
    depth: row['depth'] as number,
  })) ?? [];
}

// Full-text search
export async function fullTextSearch(
  graph: Graph,
  query: string,
  limit: number = 20
): Promise<Array<{ id: string; title: string }>> {
  const result = await graph.query(`
    CALL db.idx.fulltext.queryNodes('Node', $query)
    YIELD node
    RETURN node.id AS id, node.title AS title
    LIMIT $limit
  `, {
    params: { query, limit }
  });

  return result.data?.map((row: Record<string, unknown>) => ({
    id: row['id'] as string,
    title: row['title'] as string,
  })) ?? [];
}
```

**Effort**: 2 days  
**Risk**: FalkorDB Cypher dialect may differ from Neo4j in edge cases — test each query  
**Test**: Full CRUD cycle + vector search + full-text search + graph traversal

---

### 0.4 — TypeScript Interfaces (Days 4–5)

**Goal**: Define shared TypeScript types for the entire v2 codebase.

```typescript
// src/pure/types/graph.ts

/** Core node in the knowledge graph */
export interface GraphNode {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly summary: string;
  readonly nodeType: NodeType;
  readonly sourceType: SourceType;
  readonly sourceRef: string;
  readonly vaultId: string;
  readonly createdAt: string;   // ISO 8601
  readonly modifiedAt: string;  // ISO 8601
  readonly tags: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export type NodeType = 'voice' | 'agent' | 'manual' | 'ambient';
export type SourceType = 'whisper' | 'screenpipe' | 'mcp' | 'editor';

/** Typed edge between two nodes */
export interface GraphEdge {
  readonly id: string;
  readonly fromNodeId: string;
  readonly toNodeId: string;
  readonly relationType: RelationType;
  readonly weight: number;
  readonly createdAt: string;
  readonly createdBy: string;
}

export type RelationType =
  | 'references'
  | 'depends_on'
  | 'contradicts'
  | 'extends'
  | 'example_of'
  | 'child_of'
  | 'related_to';

/** Tag with category */
export interface Tag {
  readonly name: string;
  readonly category: TagCategory;
}

export type TagCategory = 'topic' | 'source' | 'status' | 'custom';

/** Vault (project container) */
export interface Vault {
  readonly id: string;
  readonly name: string;
  readonly projectPath: string;
  readonly createdAt: string;
  readonly settings: VaultSettings;
}

export interface VaultSettings {
  readonly embeddingModel: string;
  readonly embeddingDimensions: number;
  readonly autoTag: boolean;
  readonly autoRelation: boolean;
}

/** Node version for temporal history */
export interface NodeVersion {
  readonly id: string;
  readonly nodeId: string;
  readonly contentSnapshot: string;
  readonly changeType: 'created' | 'modified' | 'appended';
  readonly timestamp: string;
  readonly gitCommit?: string;
  readonly agentSessionId?: string;
}

/** Search result with blended score */
export interface SearchResult {
  readonly node: GraphNode;
  readonly score: number;
  readonly scoreBreakdown: ScoreBreakdown;
}

export interface ScoreBreakdown {
  readonly graphProximity: number;    // 0–1, from Cypher traversal
  readonly vectorSimilarity: number;  // 0–1, from vector search
  readonly bm25Score: number;         // 0–1, from full-text search
  readonly tagOverlap: number;        // 0–1, fraction of matching tags
  readonly recency: number;           // 0–1, time decay
}

/** MCP tool parameter types */
export interface CreateGraphInput {
  readonly project: string;
  readonly nodes: readonly CreateNodeSpec[];
  readonly edges?: readonly CreateEdgeSpec[];
}

export interface CreateNodeSpec {
  readonly title: string;
  readonly content: string;
  readonly tags?: readonly string[];
  readonly nodeType?: NodeType;
  readonly parentId?: string;
}

export interface CreateEdgeSpec {
  readonly from: string;  // node title or ID
  readonly to: string;    // node title or ID
  readonly relationType: RelationType;
  readonly weight?: number;
}

export interface SearchNodesInput {
  readonly project: string;
  readonly query: string;
  readonly limit?: number;
  readonly filters?: SearchFilters;
}

export interface SearchFilters {
  readonly nodeTypes?: readonly NodeType[];
  readonly tags?: readonly string[];
  readonly relationTypes?: readonly RelationType[];
  readonly since?: string;   // ISO 8601
  readonly until?: string;   // ISO 8601
  readonly sourceTypes?: readonly SourceType[];
}
```

**Effort**: 1 day  
**Test**: Type-check compiles with `tsc --noEmit`

---

### 0.5 — Fixed-Port MCP Server (Days 5–9)

**Goal**: MCP server on a fixed port (default 3100) with StreamableHTTP transport and one-time setup CLI.

#### MCP Server

```typescript
// src/shell/edge/main/mcp-server/server.ts

import express from 'express';
import http from 'http';

const DEFAULT_PORT = 3100;

interface MCPServerState {
  httpServer: http.Server | null;
  port: number;
}

const state: MCPServerState = {
  httpServer: null,
  port: DEFAULT_PORT,
};

export async function startMCPServer(
  port: number = getConfiguredPort()
): Promise<number> {
  if (state.httpServer) {
    throw new Error('MCP server already running');
  }

  const app = express();
  app.use(express.json());

  // Health check
  app.get('/health', (_req, res) => {
    res.json({ status: 'ok', version: '2.0.0', port });
  });

  // MCP StreamableHTTP endpoint
  app.post('/mcp', async (req, res) => {
    try {
      // MCP message handling (tool dispatch)
      const result = await handleMCPMessage(req.body);
      res.json(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      res.status(500).json({ error: error.message });
    }
  });

  // SSE endpoint for streaming
  app.get('/mcp/sse', (req, res) => {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });
    // SSE streaming implementation
  });

  return new Promise((resolve, reject) => {
    const server = http.createServer(app);
    
    server.on('error', (err: NodeJS.ErrnoException) => {
      if (err.code === 'EADDRINUSE') {
        reject(new Error(
          `Port ${port} is in use. Set VOICETREE_MCP_PORT env var to use a different port, ` +
          `or stop the existing VoiceTree instance.`
        ));
      } else {
        reject(err);
      }
    });

    server.listen(port, '127.0.0.1', () => {
      state.httpServer = server;
      state.port = port;
      resolve(port);
    });
  });
}

export async function stopMCPServer(): Promise<void> {
  if (!state.httpServer) return;

  return new Promise((resolve) => {
    state.httpServer!.close(() => {
      state.httpServer = null;
      resolve();
    });
    // Force close after 5 seconds
    setTimeout(() => {
      state.httpServer?.closeAllConnections();
      state.httpServer = null;
      resolve();
    }, 5000);
  });
}

function getConfiguredPort(): number {
  const envPort = process.env['VOICETREE_MCP_PORT'];
  if (envPort) {
    const parsed = parseInt(envPort, 10);
    if (!isNaN(parsed) && parsed > 0 && parsed < 65536) return parsed;
  }
  return DEFAULT_PORT;
}

async function handleMCPMessage(body: unknown): Promise<unknown> {
  // Placeholder — MCP tool dispatch implemented in Phase 1
  return { jsonrpc: '2.0', result: {} };
}
```

#### `voicetree setup` CLI

```typescript
// src/shell/edge/main/cli/setup.ts

import fs from 'fs/promises';
import path from 'path';
import os from 'os';

interface ClientConfig {
  name: string;
  configPath: string;
  format: 'json-mcpServers' | 'json-httpUrl' | 'toml';
  exists: boolean;
}

const MCP_URL = 'http://127.0.0.1:3100/mcp';

export async function setupAllClients(): Promise<void> {
  const clients = await detectClients();
  
  for (const client of clients) {
    if (client.exists) {
      await writeClientConfig(client);
      console.log(`✅ Configured ${client.name}: ${client.configPath}`);
    } else {
      console.log(`⏭️  Skipped ${client.name}: config directory not found`);
    }
  }
}

async function detectClients(): Promise<ClientConfig[]> {
  const home = os.homedir();
  
  const clients: ClientConfig[] = [
    {
      name: 'Claude Code (global)',
      configPath: path.join(home, '.claude.json'),
      format: 'json-mcpServers',
      exists: false,
    },
    {
      name: 'VS Code Copilot (global)',
      configPath: path.join(home, '.vscode', 'mcp.json'),
      format: 'json-mcpServers',
      exists: false,
    },
    {
      name: 'Cursor',
      configPath: path.join(home, '.cursor', 'mcp.json'),
      format: 'json-mcpServers',
      exists: false,
    },
    {
      name: 'Gemini CLI',
      configPath: path.join(home, '.gemini', 'settings.json'),
      format: 'json-httpUrl',
      exists: false,
    },
    {
      name: 'Windsurf',
      configPath: path.join(home, '.codeium', 'windsurf', 'mcp_config.json'),
      format: 'json-mcpServers',
      exists: false,
    },
    {
      name: 'Cline',
      configPath: path.join(home, '.cline', 'mcp_settings.json'),
      format: 'json-mcpServers',
      exists: false,
    },
  ];

  for (const client of clients) {
    const dirPath = path.dirname(client.configPath);
    try {
      await fs.access(dirPath);
      client.exists = true;
    } catch {
      // Directory doesn't exist
    }
  }

  return clients;
}

async function writeClientConfig(client: ClientConfig): Promise<void> {
  let config: Record<string, unknown> = {};
  
  // Read existing config if it exists
  try {
    const existing = await fs.readFile(client.configPath, 'utf-8');
    config = JSON.parse(existing);
  } catch {
    // File doesn't exist yet
  }

  if (client.format === 'json-mcpServers') {
    const servers = (config['mcpServers'] as Record<string, unknown>) ?? {};
    servers['voicetree'] = {
      type: 'http',
      url: MCP_URL,
    };
    config['mcpServers'] = servers;
  } else if (client.format === 'json-httpUrl') {
    const servers = (config['mcpServers'] as Record<string, unknown>) ?? {};
    servers['voicetree'] = {
      httpUrl: MCP_URL,
    };
    config['mcpServers'] = servers;
  }

  await fs.mkdir(path.dirname(client.configPath), { recursive: true });
  await fs.writeFile(client.configPath, JSON.stringify(config, null, 2), 'utf-8');
}
```

**Effort**: 3 days  
**Risk**: Port conflict with other local services → hard-fail with useful error message  
**Test**: Start server, `curl http://127.0.0.1:3100/health` returns 200

---

### 0.6 — Graceful Lifecycle Management (Days 8–12)

**Goal**: Clean startup sequence and graceful shutdown. No orphan containers, no leaked ports.

```typescript
// src/shell/edge/main/lifecycle.ts

import { app } from 'electron';
import { startFalkorDB, stopFalkorDB } from './falkordb/container-manager';
import { connectFalkorDB, disconnectFalkorDB } from './falkordb/client';
import { deploySchema } from './falkordb/schema';
import { startMCPServer, stopMCPServer } from './mcp-server/server';

interface AppState {
  falkordbReady: boolean;
  mcpReady: boolean;
  shuttingDown: boolean;
}

const appState: AppState = {
  falkordbReady: false,
  mcpReady: false,
  shuttingDown: false,
};

/**
 * Startup sequence:
 * 1. Start FalkorDB container (Docker)
 * 2. Connect TypeScript client
 * 3. Deploy schema (idempotent)
 * 4. Start MCP server on fixed port
 * 5. Open UI window
 */
export async function startup(): Promise<void> {
  console.log('[lifecycle] Starting VoiceTree v2...');

  // 1. FalkorDB
  console.log('[lifecycle] Starting FalkorDB container...');
  await startFalkorDB();
  
  // 2. Connect
  console.log('[lifecycle] Connecting to FalkorDB...');
  const graph = await connectFalkorDB();
  
  // 3. Schema
  console.log('[lifecycle] Deploying schema...');
  await deploySchema(graph);
  appState.falkordbReady = true;

  // 4. MCP
  console.log('[lifecycle] Starting MCP server...');
  const port = await startMCPServer();
  appState.mcpReady = true;
  console.log(`[lifecycle] MCP server listening on port ${port}`);

  console.log('[lifecycle] VoiceTree v2 ready.');
}

/**
 * Shutdown sequence (reverse order):
 * 1. Close UI windows
 * 2. Drain MCP connections, close server
 * 3. Disconnect FalkorDB client
 * 4. Stop FalkorDB container (optional — leave running for fast restart)
 */
export async function shutdown(): Promise<void> {
  if (appState.shuttingDown) return;
  appState.shuttingDown = true;

  console.log('[lifecycle] Shutting down VoiceTree v2...');

  // 2. MCP server
  if (appState.mcpReady) {
    console.log('[lifecycle] Stopping MCP server...');
    await stopMCPServer().catch(err => {
      console.error('[lifecycle] MCP shutdown error:', err);
    });
    appState.mcpReady = false;
  }

  // 3. FalkorDB client
  if (appState.falkordbReady) {
    console.log('[lifecycle] Disconnecting FalkorDB...');
    await disconnectFalkorDB().catch(err => {
      console.error('[lifecycle] FalkorDB disconnect error:', err);
    });
    appState.falkordbReady = false;
  }

  // 4. Container — leave running by default for fast restart
  // To force stop: await stopFalkorDB();

  console.log('[lifecycle] Shutdown complete.');
}

// Register shutdown hooks
export function registerLifecycleHooks(): void {
  app.on('before-quit', async (event) => {
    if (!appState.shuttingDown) {
      event.preventDefault();
      await shutdown();
      app.quit();
    }
  });

  // Handle SIGTERM (Unix) and SIGINT (Ctrl+C)
  process.on('SIGTERM', async () => {
    await shutdown();
    process.exit(0);
  });

  process.on('SIGINT', async () => {
    await shutdown();
    process.exit(0);
  });

  // Catch unhandled rejections
  process.on('unhandledRejection', (reason) => {
    console.error('[lifecycle] Unhandled rejection:', reason);
    // Don't crash — log and continue
  });
}
```

**Effort**: 2 days  
**Risk**: Docker container stop can hang → 10s timeout with force kill  
**Test**: Start app, verify health, quit app, verify port is freed and container is stopped

---

### 0.7 — Markdown → FalkorDB Migration Tool (Days 10–14)

**Goal**: Import an entire v1 markdown vault into FalkorDB, preserving wikilinks as typed edges.

```typescript
// src/shell/edge/main/migration/markdown-to-falkordb.ts

import fs from 'fs/promises';
import path from 'path';
import matter from 'gray-matter';
import { Graph } from '@falkordb/falkordb';
import { v4 as uuid } from 'uuid';

interface MigrationResult {
  nodesCreated: number;
  edgesCreated: number;
  tagsCreated: number;
  errors: string[];
  durationMs: number;
}

interface ParsedMarkdownNode {
  filePath: string;
  title: string;
  content: string;
  frontmatter: Record<string, unknown>;
  wikilinks: string[];
}

const WIKILINK_REGEX = /\[\[([^\]]+)\]\]/g;

export async function migrateVault(
  graph: Graph,
  vaultPath: string,
  vaultId: string
): Promise<MigrationResult> {
  const start = Date.now();
  const result: MigrationResult = {
    nodesCreated: 0,
    edgesCreated: 0,
    tagsCreated: 0,
    errors: [],
    durationMs: 0,
  };

  // Phase 1: Parse all markdown files
  const mdFiles = await findMarkdownFiles(vaultPath);
  const parsed: ParsedMarkdownNode[] = [];

  for (const filePath of mdFiles) {
    try {
      const raw = await fs.readFile(filePath, 'utf-8');
      const { data: frontmatter, content } = matter(raw);
      const title = frontmatter['title'] as string
        ?? path.basename(filePath, '.md');
      const wikilinks = extractWikilinks(content);

      parsed.push({ filePath, title, content, frontmatter, wikilinks });
    } catch (err) {
      result.errors.push(`Parse error: ${filePath}: ${err}`);
    }
  }

  // Phase 2: Create nodes in FalkorDB
  const titleToId = new Map<string, string>();

  for (const node of parsed) {
    try {
      const nodeId = uuid();
      titleToId.set(node.title.toLowerCase(), nodeId);

      const tags = extractTags(node.frontmatter);
      const createdAt = (node.frontmatter['created'] as string)
        ?? new Date().toISOString();

      await graph.query(`
        CREATE (n:Node {
          id: $id,
          title: $title,
          content: $content,
          summary: '',
          node_type: 'manual',
          source_type: 'editor',
          source_ref: $filePath,
          vault_id: $vaultId,
          created_at: $createdAt,
          modified_at: $createdAt
        })
      `, {
        params: {
          id: nodeId,
          title: node.title,
          content: node.content,
          vaultId,
          filePath: node.filePath,
          createdAt,
        }
      });

      // Create tags
      for (const tag of tags) {
        await graph.query(`
          MERGE (t:Tag {name: $tag, category: 'topic'})
          WITH t
          MATCH (n:Node {id: $nodeId})
          CREATE (n)-[:TAGGED_WITH]->(t)
        `, {
          params: { tag, nodeId }
        });
        result.tagsCreated++;
      }

      result.nodesCreated++;
    } catch (err) {
      result.errors.push(`Node creation error: ${node.title}: ${err}`);
    }
  }

  // Phase 3: Create edges from wikilinks
  for (const node of parsed) {
    const fromId = titleToId.get(node.title.toLowerCase());
    if (!fromId) continue;

    for (const link of node.wikilinks) {
      const toId = titleToId.get(link.toLowerCase());
      if (!toId) continue;

      try {
        await graph.query(`
          MATCH (a:Node {id: $fromId}), (b:Node {id: $toId})
          CREATE (a)-[:RELATES_TO {
            relation_type: 'references',
            weight: 1.0,
            created_at: $now,
            created_by: 'migration'
          }]->(b)
        `, {
          params: {
            fromId,
            toId,
            now: new Date().toISOString(),
          }
        });
        result.edgesCreated++;
      } catch (err) {
        result.errors.push(`Edge error: ${node.title} -> ${link}: ${err}`);
      }
    }
  }

  result.durationMs = Date.now() - start;
  return result;
}

function extractWikilinks(content: string): string[] {
  const links: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = WIKILINK_REGEX.exec(content)) !== null) {
    links.push(match[1]!);
  }
  return links;
}

function extractTags(frontmatter: Record<string, unknown>): string[] {
  const tags = frontmatter['tags'];
  if (Array.isArray(tags)) return tags.map(String);
  if (typeof tags === 'string') return tags.split(',').map(t => t.trim());
  return [];
}

async function findMarkdownFiles(dir: string): Promise<string[]> {
  const results: string[] = [];
  const entries = await fs.readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory() && !entry.name.startsWith('.')) {
      results.push(...await findMarkdownFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      results.push(fullPath);
    }
  }

  return results;
}
```

**Effort**: 3 days  
**Risk**: Large vaults may timeout → batch in transactions of 100 nodes  
**Test**: Migrate the default `markdownTreeVaultDefault/` folder, verify node/edge counts match

---

## Testing Strategy

| Test Type | Scope | Tool |
|-----------|-------|------|
| Unit tests | Schema deployment, CRUD functions, migration parser | Vitest |
| Integration tests | FalkorDB client ↔ Docker container | Vitest + Docker |
| E2E lifecycle | Startup → health check → shutdown → port freed | Custom script |
| Migration correctness | v1 vault → FalkorDB → verify graph structure | Vitest |

### Key Test Cases

1. **Container lifecycle**: Start container, verify healthy, stop container, verify stopped
2. **Schema idempotency**: Deploy schema twice — no errors
3. **CRUD round-trip**: Create node → read node → update node → delete node
4. **Vector search**: Create nodes with embeddings → query by vector → verify top-K results
5. **Wikilink migration**: Migrate vault with known wikilinks → verify edges exist
6. **Port conflict**: Start server on occupied port → verify useful error message
7. **Graceful shutdown**: Kill app mid-operation → verify no orphan containers or leaked ports

---

## Definition of Done

- [ ] `docker compose up` starts FalkorDB with persistent volume
- [ ] TypeScript client connects and runs Cypher queries
- [ ] Schema deployed with full-text + vector indexes
- [ ] CRUD: create/read/update/delete nodes and edges
- [ ] Vector similarity search returns ranked results
- [ ] Full-text search returns matches
- [ ] Graph traversal (N-hop neighborhood) works
- [ ] MCP server responds on port 3100
- [ ] `voicetree setup` configures at least Claude Code + VS Code Copilot
- [ ] App starts cleanly and shuts down cleanly
- [ ] No port leaks, no orphan Docker containers
- [ ] Migration tool imports v1 vault with correct node/edge/tag counts
- [ ] All tests pass in CI

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Docker not installed on user machine | Blocks all of v2 | Pre-flight check with install instructions. Long-term: evaluate Redis embedded module as alternative |
| FalkorDB vector index API changes | Breaks semantic search | Pin FalkorDB Docker image version. Monitor upstream releases |
| Cold start latency (Docker + Redis) | Slow app launch | Keep container running between sessions (`unless-stopped`). Only stop on explicit uninstall |
| Data loss on container removal | Catastrophic | Named Docker volume (`voicetree-data`) persists across container recreations. Add backup/export CLI |
| FalkorDB Cypher dialect differences from Neo4j | Query bugs | Test every query against FalkorDB specifically. Maintain a query test suite |
| Port 3100 conflict | MCP server won't start | Configurable via `VOICETREE_MCP_PORT`. Hard-fail with clear error, not silent fallback |
