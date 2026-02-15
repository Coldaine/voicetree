# VoiceTree v2 — TDD Implementation Plan

> **Status**: Planning
> **Testing Framework**: Vitest (unit + integration) + Playwright (E2E)
> **Principle**: Red-Green-Refactor — write failing tests FIRST, then implement to satisfy them
> **Architecture**: Pure functions get unit tests; shell/edge code gets integration tests with Docker containers

---

## Table of Contents

1. [Testing Philosophy](#1-testing-philosophy)
2. [Testing Infrastructure Setup](#2-testing-infrastructure-setup)
3. [Phase-by-Phase TDD Breakdown](#3-phase-by-phase-tdd-breakdown)
4. [Example Tests (Actual Code)](#4-example-tests-actual-code)
5. [CI Integration](#5-ci-integration)
6. [Test Data Strategy](#6-test-data-strategy)

---

## 1. Testing Philosophy

### Red-Green-Refactor Cycle

Every feature follows this strict cycle:

1. **RED**: Write a failing test that describes the desired behavior
2. **GREEN**: Write the minimum code to make the test pass
3. **REFACTOR**: Clean up the code while keeping tests green

### Test Pyramid

```
         ╱╲
        ╱E2E╲           ~15 tests  — Playwright (critical user flows only)
       ╱──────╲
      ╱Contract╲         ~20 tests  — MCP tool API contracts
     ╱──────────╲
    ╱Integration ╲       ~60 tests  — FalkorDB + Docker + lifecycle
   ╱──────────────╲
  ╱   Unit Tests   ╲    ~150 tests  — Pure functions, no I/O
 ╱──────────────────╲
```

### Rules

| Rule | Rationale |
|------|-----------|
| Pure functions (`src/pure/`) get unit tests FIRST | Zero I/O = fast, deterministic, no setup |
| Shell/edge code (`src/shell/`) gets integration tests | Requires Docker FalkorDB container |
| Every public function has at least one test | Untested code is broken code you haven't found yet |
| Tests use realistic VoiceTree data | "Hello World" tests catch nothing real |
| No `any` types in test code | Tests are production code — same standards apply |
| Tests run in < 30s (unit), < 120s (integration), < 300s (E2E) | Slow tests don't get run |
| Snapshot tests require manual approval on first change | Prevent snapshot rot |

### What Gets Tested Where

| Layer | Test Type | Runner | Docker Required |
|-------|-----------|--------|-----------------|
| `src/pure/types/` | Type compilation | `tsc --noEmit` | No |
| `src/pure/` functions | Unit tests | Vitest | No |
| `src/shell/edge/main/falkordb/` | Integration | Vitest + Docker | Yes |
| `src/shell/edge/main/mcp-server/` | Contract + integration | Vitest + supertest | Yes |
| `src/shell/edge/main/ingestion/` | Integration | Vitest + Docker | Yes |
| `src/shell/edge/main/query/` | Integration | Vitest + Docker | Yes |
| `src/shell/UI/` | Component tests | Vitest + jsdom | No |
| `src/shell/UI/graph/` | Visual regression | Playwright | No |
| Full app | E2E | Playwright + Electron | Yes |

---

## 2. Testing Infrastructure Setup

### 2.1 Vitest Configuration

```typescript
// webapp/vitest.config.ts

import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    // Separate test pools for unit vs integration
    include: ['src/**/*.test.ts', 'src/**/*.spec.ts'],
    exclude: ['**/e2e/**', '**/node_modules/**'],
    environment: 'node',
    globals: true,
    testTimeout: 10_000,
    hookTimeout: 30_000,

    // Coverage
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      include: ['src/pure/**', 'src/shell/**'],
      exclude: [
        'src/**/*.test.ts',
        'src/**/*.spec.ts',
        'src/**/types/**',
        'src/**/*.d.ts',
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80,
      },
    },

    // Workspace-level project configuration
    projects: [
      {
        // Unit tests — no Docker, fast
        test: {
          name: 'unit',
          include: ['src/pure/**/*.test.ts', 'src/shell/UI/**/*.test.ts'],
          environment: 'node',
          testTimeout: 5_000,
        },
      },
      {
        // Integration tests — Docker FalkorDB required
        test: {
          name: 'integration',
          include: ['src/shell/edge/**/*.integration.test.ts'],
          environment: 'node',
          testTimeout: 30_000,
          hookTimeout: 60_000,
          // setupFiles run FalkorDB container
          setupFiles: ['./tests/setup/falkordb-container.ts'],
        },
      },
    ],
  },
  resolve: {
    alias: {
      '@pure': path.resolve(__dirname, 'src/pure'),
      '@shell': path.resolve(__dirname, 'src/shell'),
    },
  },
});
```

### 2.2 Docker Test Container for FalkorDB

```typescript
// webapp/tests/setup/falkordb-container.ts

import { execFileSync, execFile } from 'child_process';
import { promisify } from 'util';
import { FalkorDB, type Graph } from '@falkordb/falkordb';

const exec = promisify(execFile);

const TEST_CONTAINER_NAME = 'voicetree-falkordb-test';
const TEST_PORT = 6380; // Different from prod (6379)
const TEST_GRAPH_NAME = 'voicetree_test';

let testDb: FalkorDB | null = null;
let testGraph: Graph | null = null;

/**
 * Spin up a fresh FalkorDB container for integration tests.
 * Called once before the entire test suite via Vitest setupFiles.
 */
export async function setup(): Promise<void> {
  // Kill any leftover test container
  try {
    execFileSync('docker', ['rm', '-f', TEST_CONTAINER_NAME], { stdio: 'ignore' });
  } catch { /* container didn't exist */ }

  // Start fresh container
  execFileSync('docker', [
    'run', '-d',
    '--name', TEST_CONTAINER_NAME,
    '-p', `${TEST_PORT}:6379`,
    '--health-cmd', 'redis-cli ping',
    '--health-interval', '2s',
    '--health-timeout', '2s',
    '--health-retries', '10',
    'falkordb/falkordb:latest',
    'redis-server',
    '--loadmodule', '/usr/lib/redis/modules/falkordb.so',
  ]);

  // Wait for healthy
  const start = Date.now();
  while (Date.now() - start < 30_000) {
    try {
      const { stdout } = await exec('docker', [
        'inspect', '--format', '{{.State.Health.Status}}', TEST_CONTAINER_NAME,
      ]);
      if (stdout.trim() === 'healthy') break;
    } catch { /* not ready yet */ }
    await new Promise(r => setTimeout(r, 500));
  }

  // Connect client
  testDb = await FalkorDB.connect({
    socket: { host: '127.0.0.1', port: TEST_PORT },
  });
  testGraph = testDb.selectGraph(TEST_GRAPH_NAME);

  // Expose to tests via global
  (globalThis as Record<string, unknown>).__TEST_GRAPH__ = testGraph;
  (globalThis as Record<string, unknown>).__TEST_DB__ = testDb;
  (globalThis as Record<string, unknown>).__TEST_PORT__ = TEST_PORT;
  (globalThis as Record<string, unknown>).__TEST_GRAPH_NAME__ = TEST_GRAPH_NAME;
}

/**
 * Tear down the test container after all tests complete.
 */
export async function teardown(): Promise<void> {
  if (testDb) {
    await testDb.close();
    testDb = null;
    testGraph = null;
  }

  try {
    execFileSync('docker', ['rm', '-f', TEST_CONTAINER_NAME], { stdio: 'ignore' });
  } catch { /* best effort */ }
}
```

### 2.3 Test Helpers & Utilities

```typescript
// webapp/tests/helpers/test-graph.ts

import type { Graph } from '@falkordb/falkordb';

/**
 * Get the test graph instance. Throws if integration test setup hasn't run.
 */
export function getTestGraph(): Graph {
  const graph = (globalThis as Record<string, unknown>).__TEST_GRAPH__ as Graph | undefined;
  if (!graph) throw new Error('Test graph not initialized. Are you in an integration test?');
  return graph;
}

/**
 * Wipe all data from the test graph between tests.
 */
export async function resetTestGraph(): Promise<void> {
  const graph = getTestGraph();
  await graph.query('MATCH (n) DETACH DELETE n');
}
```

### 2.4 Test Fixtures

```typescript
// webapp/tests/fixtures/nodes.ts

import type { GraphNode, GraphEdge } from '@pure/types/graph';
import type { IngestionEvent } from '@pure/types/ingestion';

/** A realistic voice-captured planning node */
export const VOICE_PLANNING_NODE: GraphNode = {
  id: 'node-voice-001',
  title: 'Sprint 12 Planning',
  content: 'We need to prioritize the authentication refactor. The current OAuth flow has a token refresh bug that affects 15% of users. Also discussed migrating to PKCE for mobile clients.',
  summary: 'Sprint 12 priorities: auth refactor, OAuth token refresh bug, PKCE migration.',
  nodeType: 'voice',
  sourceType: 'whisper',
  sourceRef: 'session-2026-02-14',
  vaultId: 'vault-test-001',
  createdAt: '2026-02-14T09:00:00Z',
  modifiedAt: '2026-02-14T09:00:00Z',
  tags: ['sprint-planning', 'auth', 'oauth'],
  metadata: {},
};

/** An agent-created architecture node */
export const AGENT_ARCHITECTURE_NODE: GraphNode = {
  id: 'node-agent-001',
  title: 'Auth Service Architecture',
  content: 'The auth service uses OAuth2 with PKCE flow. Token storage uses the OS keychain via `keytar`. Refresh tokens are rotated on each use with a 7-day absolute expiry. See [[Sprint 12 Planning]] for context.',
  summary: 'Auth service architecture with PKCE, keychain storage, and rotating refresh tokens.',
  nodeType: 'agent',
  sourceType: 'mcp',
  sourceRef: 'claude-session-abc123',
  vaultId: 'vault-test-001',
  createdAt: '2026-02-14T10:30:00Z',
  modifiedAt: '2026-02-14T10:30:00Z',
  tags: ['architecture', 'auth', 'security'],
  metadata: {},
};

/** A manually created documentation node */
export const MANUAL_DOC_NODE: GraphNode = {
  id: 'node-manual-001',
  title: 'API Rate Limiting',
  content: 'All API endpoints enforce rate limiting via a token bucket algorithm. Default: 100 requests/minute per API key. Burst: 20 requests. Rate limit headers: X-RateLimit-Remaining, X-RateLimit-Reset.',
  summary: 'API rate limiting with token bucket: 100 req/min, burst 20.',
  nodeType: 'manual',
  sourceType: 'editor',
  sourceRef: '',
  vaultId: 'vault-test-001',
  createdAt: '2026-02-13T15:00:00Z',
  modifiedAt: '2026-02-14T08:00:00Z',
  tags: ['api', 'rate-limiting', 'infrastructure'],
  metadata: {},
};

/** An ambient capture node from ScreenPipe */
export const AMBIENT_CAPTURE_NODE: GraphNode = {
  id: 'node-ambient-001',
  title: 'VS Code: auth-service/token-handler.ts',
  content: 'Active editing in auth-service/token-handler.ts. Functions visible: refreshAccessToken(), validateTokenExpiry(), rotateRefreshToken(). Using keytar for secure storage.',
  summary: 'Editing token handler with refresh, validation, and rotation functions.',
  nodeType: 'ambient',
  sourceType: 'screenpipe',
  sourceRef: 'screenpipe-frame-9821',
  vaultId: 'vault-test-001',
  createdAt: '2026-02-14T10:35:00Z',
  modifiedAt: '2026-02-14T10:35:00Z',
  tags: ['coding', 'auth', 'token-handler'],
  metadata: { appName: 'VS Code', windowName: 'token-handler.ts' },
};

/** Sample edges connecting the fixture nodes */
export const FIXTURE_EDGES: readonly GraphEdge[] = [
  {
    id: 'edge-001',
    fromNodeId: 'node-agent-001',
    toNodeId: 'node-voice-001',
    relationType: 'references',
    weight: 1.0,
    createdAt: '2026-02-14T10:30:00Z',
    createdBy: 'ingestion',
  },
  {
    id: 'edge-002',
    fromNodeId: 'node-agent-001',
    toNodeId: 'node-manual-001',
    relationType: 'depends_on',
    weight: 0.8,
    createdAt: '2026-02-14T10:30:00Z',
    createdBy: 'claude-session-abc123',
  },
  {
    id: 'edge-003',
    fromNodeId: 'node-ambient-001',
    toNodeId: 'node-agent-001',
    relationType: 'related_to',
    weight: 0.6,
    createdAt: '2026-02-14T10:35:00Z',
    createdBy: 'screenpipe-correlator',
  },
];

/** Raw ingestion events for pipeline testing */
export const VOICE_INGESTION_EVENT: IngestionEvent = {
  source: 'whisper',
  sourceRef: 'session-2026-02-14',
  content: 'We need to prioritize the authentication refactor. The current OAuth flow has a token refresh bug that affects 15% of users.',
  title: 'Sprint 12 Planning',
  timestamp: '2026-02-14T09:00:00Z',
  projectPath: '/projects/voicetree',
  tags: ['sprint-planning'],
};

export const AGENT_INGESTION_EVENT: IngestionEvent = {
  source: 'mcp',
  sourceRef: 'claude-session-abc123',
  content: 'The auth service uses OAuth2 with PKCE flow. Token storage uses the OS keychain via `keytar`. See [[Sprint 12 Planning]] for context.',
  title: 'Auth Service Architecture',
  timestamp: '2026-02-14T10:30:00Z',
  projectPath: '/projects/voicetree',
  tags: ['architecture'],
};

export const DUPLICATE_INGESTION_EVENT: IngestionEvent = {
  ...VOICE_INGESTION_EVENT,
  timestamp: '2026-02-14T09:00:15Z', // 15 seconds later — within 30s dedupe window
};

export const SCREENPIPE_INGESTION_EVENT: IngestionEvent = {
  source: 'screenpipe',
  sourceRef: 'screenpipe-frame-9821',
  content: 'Active editing in auth-service/token-handler.ts. Functions visible: refreshAccessToken(), validateTokenExpiry().',
  timestamp: '2026-02-14T10:35:00Z',
  projectPath: '/projects/voicetree',
  metadata: { appName: 'VS Code', windowName: 'token-handler.ts' },
};
```

```typescript
// webapp/tests/fixtures/vaults.ts

import type { Vault, VaultSettings } from '@pure/types/graph';

export const TEST_VAULT: Vault = {
  id: 'vault-test-001',
  name: 'voicetree',
  projectPath: '/projects/voicetree',
  createdAt: '2026-02-01T00:00:00Z',
  settings: {
    embeddingModel: 'all-MiniLM-L6-v2',
    embeddingDimensions: 384,
    autoTag: true,
    autoRelation: true,
  },
};

export const TEST_VAULT_B: Vault = {
  id: 'vault-test-002',
  name: 'other-project',
  projectPath: '/projects/other-project',
  createdAt: '2026-02-10T00:00:00Z',
  settings: {
    embeddingModel: 'all-MiniLM-L6-v2',
    embeddingDimensions: 384,
    autoTag: true,
    autoRelation: true,
  },
};
```

```typescript
// webapp/tests/fixtures/embeddings.ts

/**
 * Pre-computed 384-dim embeddings for test content.
 * Generated from MiniLM-L6-v2 for the fixture node contents.
 * Using deterministic truncated fixtures to avoid model dependency in unit tests.
 */
export function makeFakeEmbedding(seed: number = 0): number[] {
  // Deterministic pseudo-random 384-dim vector for testing
  const embedding: number[] = [];
  let state = seed + 1;
  for (let i = 0; i < 384; i++) {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    embedding.push((state / 0x7fffffff) * 2 - 1); // range [-1, 1]
  }
  // L2-normalize
  const norm = Math.sqrt(embedding.reduce((sum, v) => sum + v * v, 0));
  return embedding.map(v => v / norm);
}

/** Embedding provider mock that returns deterministic fake embeddings */
export function createMockEmbeddingProvider() {
  let callCount = 0;
  return {
    name: 'mock-embedding' as const,
    dimensions: 384,
    async embed(text: string): Promise<number[]> {
      // Use text hashcode as seed for deterministic but text-dependent embeddings
      const seed = text.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
      callCount++;
      return makeFakeEmbedding(seed);
    },
    async embedBatch(texts: string[]): Promise<number[][]> {
      return Promise.all(texts.map(t => this.embed(t)));
    },
    getCallCount: () => callCount,
  };
}
```

### 2.5 Mock Factories for FalkorDB Responses

```typescript
// webapp/tests/mocks/falkordb-mock.ts

import type { Graph } from '@falkordb/falkordb';

interface MockQueryResult {
  data: Array<Record<string, unknown>>;
}

/**
 * Create a mock FalkorDB Graph object for unit testing.
 * Does NOT require Docker — stores data in-memory.
 */
export function createMockGraph(): Graph & { _queries: string[] } {
  const queries: string[] = [];
  const storedNodes = new Map<string, Record<string, unknown>>();

  const mockGraph = {
    _queries: queries,

    async query(
      cypher: string,
      options?: { params?: Record<string, unknown> }
    ): Promise<MockQueryResult> {
      queries.push(cypher);

      // Simulate basic CRUD responses
      if (cypher.includes('CREATE')) {
        const id = options?.params?.['id'] as string ?? 'mock-id';
        storedNodes.set(id, options?.params ?? {});
        return { data: [] };
      }

      if (cypher.includes('MATCH') && cypher.includes('RETURN')) {
        return { data: [...storedNodes.values()] };
      }

      return { data: [] };
    },

    async delete(): Promise<void> {
      storedNodes.clear();
    },
  } as unknown as Graph & { _queries: string[] };

  return mockGraph;
}
```

### 2.6 Playwright Configuration

```typescript
// webapp/playwright.config.ts

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false, // E2E tests share state
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 2 : 0,
  workers: 1,
  reporter: [
    ['html', { open: 'never' }],
    ['json', { outputFile: 'test-results/e2e-results.json' }],
  ],
  timeout: 60_000,

  use: {
    baseURL: 'http://localhost:3100',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'electron',
      testDir: './tests/e2e/electron',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
    {
      name: 'visual-regression',
      testDir: './tests/e2e/visual',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1920, height: 1080 },
      },
    },
  ],

  // Start FalkorDB + MCP server before E2E tests
  webServer: {
    command: 'npm run start:test',
    url: 'http://127.0.0.1:3100/health',
    timeout: 30_000,
    reuseExistingServer: !process.env['CI'],
  },
});
```

---

## 3. Phase-by-Phase TDD Breakdown

---

### Phase 0 — Foundation (Weeks 1–4)

**Coverage target: 90% for pure functions, 80% for shell code**

#### Unit Tests (no Docker)

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/pure/types/graph.test.ts` | Type compilation — all types compile with `tsc` | 1 |
| `src/shell/edge/main/falkordb/schema.test.ts` | `ignoreExistingIndex()` edge cases | 3 |
| `src/shell/edge/main/mcp-server/server.test.ts` | `getConfiguredPort()` env var parsing | 4 |
| `src/shell/edge/main/cli/setup.test.ts` | Client detection logic (pure path resolution) | 5 |
| `src/shell/edge/main/migration/markdown-to-falkordb.test.ts` | `extractWikilinks()`, `extractTags()`, `findMarkdownFiles()` | 6 |

##### `src/pure/types/graph.test.ts`

```
describe('GraphNode type', () => {
  it('should compile a valid GraphNode with all required fields')
  it('should enforce readonly on all properties')
})
```
**Implementation**: The types themselves in `src/pure/types/graph.ts`. Test passes if `tsc --noEmit` succeeds.

##### `src/shell/edge/main/falkordb/schema.test.ts`

```
describe('ignoreExistingIndex', () => {
  it('should swallow errors containing "already indexed"')
  it('should swallow errors containing "Index already exists"')
  it('should rethrow errors with unrecognized messages')
})
```
**Implementation**: The `ignoreExistingIndex()` function in `schema.ts`.

##### `src/shell/edge/main/mcp-server/server.test.ts`

```
describe('getConfiguredPort', () => {
  it('should return 3100 when VOICETREE_MCP_PORT is not set')
  it('should return parsed port when VOICETREE_MCP_PORT is a valid number')
  it('should return 3100 when VOICETREE_MCP_PORT is not a number')
  it('should return 3100 when VOICETREE_MCP_PORT is out of range (0 or 65536+)')
})
```
**Implementation**: `getConfiguredPort()` in `server.ts`.

##### `src/shell/edge/main/migration/markdown-to-falkordb.test.ts`

```
describe('extractWikilinks', () => {
  it('should extract single wikilink from content')
  it('should extract multiple wikilinks from content')
  it('should return empty array when no wikilinks present')
  it('should handle nested brackets correctly')
})

describe('extractTags', () => {
  it('should extract array-format tags from frontmatter')
  it('should extract comma-separated string tags from frontmatter')
})
```
**Implementation**: Pure functions `extractWikilinks()` and `extractTags()` in `markdown-to-falkordb.ts`.

#### Integration Tests (Docker FalkorDB required)

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/falkordb/container-manager.integration.test.ts` | Docker container lifecycle | 5 |
| `src/shell/edge/main/falkordb/client.integration.test.ts` | FalkorDB connection/disconnection | 4 |
| `src/shell/edge/main/falkordb/schema.integration.test.ts` | Schema deployment (idempotent) | 4 |
| `src/shell/edge/main/falkordb/crud.integration.test.ts` | CRUD on nodes, edges, tags | 10 |
| `src/shell/edge/main/falkordb/vector-search.integration.test.ts` | Vector index + similarity search | 5 |
| `src/shell/edge/main/falkordb/fulltext-search.integration.test.ts` | Full-text index + BM25 search | 4 |
| `src/shell/edge/main/migration/markdown-to-falkordb.integration.test.ts` | Full vault migration | 5 |
| `src/shell/edge/main/mcp-server/server.integration.test.ts` | MCP server start/stop/health | 5 |
| `src/shell/edge/main/lifecycle.integration.test.ts` | Startup → healthy → shutdown → clean | 4 |

##### `src/shell/edge/main/falkordb/container-manager.integration.test.ts`

```
describe('FalkorDB Container Manager', () => {
  it('should start a FalkorDB Docker container when none exists')
  it('should reuse existing running container without error')
  it('should restart a stopped container')
  it('should report accurate container status')
  it('should stop a running container within 10 seconds')
})
```
**Implementation**: `startFalkorDB()`, `stopFalkorDB()`, `getContainerStatus()` in `container-manager.ts`. Tests verify actual Docker container state using `docker inspect`.

##### `src/shell/edge/main/falkordb/client.integration.test.ts`

```
describe('FalkorDB Client', () => {
  it('should connect to FalkorDB and execute RETURN 1')
  it('should throw when connecting to wrong port')
  it('should disconnect cleanly without errors')
  it('should throw when calling getGraph() before connect')
})
```
**Implementation**: `connectFalkorDB()`, `disconnectFalkorDB()`, `getGraph()` in `client.ts`.

##### `src/shell/edge/main/falkordb/schema.integration.test.ts`

```
describe('Schema Deployment', () => {
  it('should create all indexes on fresh database')
  it('should complete without error when run twice (idempotent)')
  it('should create full-text index on Node label')
  it('should create vector index with 384 dimensions and cosine metric')
})
```
**Implementation**: `deploySchema()` in `schema.ts`. Verify indexes exist via `CALL db.indexes()`.

##### `src/shell/edge/main/falkordb/crud.integration.test.ts`

```
describe('Node CRUD', () => {
  it('should create a node and return its ID')
  it('should read a node by ID with all properties')
  it('should update a node title and modified_at timestamp')
  it('should delete a node and its edges')
  it('should create a node with embedding vector')
})

describe('Edge CRUD', () => {
  it('should create an edge between two existing nodes')
  it('should create an edge with relation_type and weight')
  it('should fail silently when creating edge to non-existent node')
})

describe('Tag CRUD', () => {
  it('should create a tag and link it to a node via TAGGED_WITH')
  it('should merge duplicate tag names (MERGE semantics)')
})
```
**Implementation**: `createNode()`, `createEdge()` and supporting functions in Phase 0 CRUD code.

##### `src/shell/edge/main/falkordb/vector-search.integration.test.ts`

```
describe('Vector Search', () => {
  it('should return top-K nodes ranked by cosine similarity')
  it('should return empty array when no nodes have embeddings')
  it('should filter results by vault_id')
  it('should return score between 0 and 1')
  it('should rank semantically similar content higher than unrelated content')
})
```
**Implementation**: `vectorSearch()` function. Tests insert nodes with known embeddings (using `makeFakeEmbedding()`) and verify ranking.

##### `src/shell/edge/main/falkordb/fulltext-search.integration.test.ts`

```
describe('Full-Text Search (BM25)', () => {
  it('should return nodes matching keyword query')
  it('should rank exact title matches higher than content-only matches')
  it('should return empty array for non-matching queries')
  it('should respect the limit parameter')
})
```
**Implementation**: `fullTextSearch()` function.

##### `src/shell/edge/main/migration/markdown-to-falkordb.integration.test.ts`

```
describe('Markdown to FalkorDB Migration', () => {
  it('should import all .md files from a vault directory')
  it('should create edges from [[wikilinks]] between nodes')
  it('should extract and create tags from frontmatter')
  it('should report correct node, edge, and tag counts')
  it('should handle vault with no markdown files gracefully')
})
```
**Implementation**: `migrateVault()` function. Use a temp directory with sample `.md` files created by the test.

##### `src/shell/edge/main/mcp-server/server.integration.test.ts`

```
describe('MCP Server', () => {
  it('should start on configured port and respond to /health')
  it('should reject startup when port is already in use')
  it('should stop cleanly and free the port')
  it('should return 200 with version info on /health')
  it('should handle /mcp POST endpoint')
})
```
**Implementation**: `startMCPServer()`, `stopMCPServer()` in `server.ts`. Use `supertest` or direct `fetch` to hit endpoints.

##### `src/shell/edge/main/lifecycle.integration.test.ts`

```
describe('App Lifecycle', () => {
  it('should complete startup sequence: FalkorDB → schema → MCP')
  it('should complete shutdown sequence in reverse order')
  it('should not leak ports after shutdown')
  it('should handle double-shutdown gracefully')
})
```
**Implementation**: `startup()`, `shutdown()` in `lifecycle.ts`.

#### Phase 0 Test Count: **~60 tests** (19 unit + 46 integration)

---

### Phase 1 — Core Services (Weeks 5–8)

**Coverage target: 95% for pure ingestion/query functions, 85% for shell code**

#### Unit Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/ingestion/pipeline.test.ts` | Pure pipeline functions | 16 |
| `src/pure/types/query.test.ts` | DEFAULT_WEIGHTS constants, BlendWeights validation | 2 |
| `src/shell/edge/main/query/engine.test.ts` | `blendScore()` pure function | 5 |
| `src/shell/edge/main/routing/project-router.test.ts` | Route cache behavior | 3 |

##### `src/shell/edge/main/ingestion/pipeline.test.ts`

```
describe('normalize', () => {
  it('should trim whitespace and collapse multiple spaces')
  it('should generate title from first 80 chars when title is missing')
  it('should preserve existing title when provided')
})

describe('contentHash', () => {
  it('should return a 16-char hex string')
  it('should return same hash for identical content')
  it('should return different hashes for different content')
})

describe('isDuplicate', () => {
  it('should return true when hash was seen within window')
  it('should return false when hash was seen outside window')
  it('should return false when hash has never been seen')
})

describe('classifyNodeType', () => {
  it('should return "voice" for whisper source')
  it('should return "ambient" for screenpipe source')
  it('should return "agent" for mcp source')
  it('should return "manual" for editor source')
})

describe('extractTags', () => {
  it('should extract #hashtag-style tags from content')
  it('should merge extracted tags with existing tags without duplicates')
  it('should return existing tags when no hashtags in content')
  it('should handle tags with hyphens and underscores')
})

describe('inferRelations', () => {
  it('should extract [[wikilink]] as a references relation with confidence 1.0')
  it('should extract multiple wikilinks from content')
  it('should return empty array when no wikilinks present')
})

describe('generateSummary', () => {
  it('should return first sentence when under 200 chars')
  it('should truncate to 200 chars with ellipsis for long content')
})
```
**Implementation**: All pure functions in `pipeline.ts`. These tests are written BEFORE the implementation — the TDD red phase.

##### `src/shell/edge/main/query/engine.test.ts`

```
describe('blendScore', () => {
  it('should weight vector score highest with default weights')
  it('should return 0 when all component scores are 0')
  it('should return 1.0 when all component scores are 1.0')
  it('should apply custom weights correctly')
  it('should handle partial scores (some 0, some non-zero)')
})
```
**Implementation**: `blendScore()` pure function in `engine.ts`.

#### Integration Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/ingestion/pipeline.integration.test.ts` | Full ingestion pipeline → FalkorDB | 10 |
| `src/shell/edge/main/query/engine.integration.test.ts` | Blended query E2E | 8 |
| `src/shell/edge/main/routing/project-router.integration.test.ts` | Multi-vault routing | 5 |
| `src/shell/edge/main/embedding/local-provider.integration.test.ts` | Local MiniLM embedding | 4 |
| `src/shell/edge/main/mcp-server/tools.integration.test.ts` | MCP tool handlers | 8 |

##### `src/shell/edge/main/ingestion/pipeline.integration.test.ts`

```
describe('Ingestion Pipeline (integration)', () => {
  it('should ingest a voice event and create a node in FalkorDB')
  it('should ingest an agent event with wikilinks and create edges')
  it('should deduplicate identical content within 30s window')
  it('should allow same content after dedupe window expires')
  it('should auto-extract hashtags as tags linked to the node')
  it('should generate and store embedding vector on the node')
  it('should create a NodeVersion snapshot on first ingestion')
  it('should link node to parent when parentNodeId is provided')
  it('should link node to vault via CONTAINS edge')
  it('should return IngestionResult with correct metadata')
})
```
**Implementation**: `ingest()` orchestrator function. Tests use mock embedding provider + real FalkorDB.

##### `src/shell/edge/main/query/engine.integration.test.ts`

```
describe('Blended Query Engine (integration)', () => {
  it('should return vector-similar nodes when query matches content semantically')
  it('should return BM25-matching nodes when query matches keywords')
  it('should rank nodes with multiple signal matches higher')
  it('should filter results by node type')
  it('should filter results by tag')
  it('should filter results by time range (since/until)')
  it('should boost graph-proximate nodes when anchorNodeId is provided')
  it('should return empty array for queries with no matches')
})
```
**Implementation**: `blendedSearch()` function in `engine.ts`.

##### `src/shell/edge/main/routing/project-router.integration.test.ts`

```
describe('Project Router (integration)', () => {
  it('should create a new vault on first resolve for unknown project')
  it('should return cached vault ID on subsequent resolves')
  it('should isolate nodes between different vaults')
  it('should list all vaults with correct metadata')
  it('should return accurate node/edge/tag counts per vault')
})
```
**Implementation**: `resolveVault()`, `listVaults()`, `getVaultStats()` in `project-router.ts`.

##### `src/shell/edge/main/embedding/local-provider.integration.test.ts`

```
describe('Local Embedding Provider', () => {
  it('should return a 384-dimensional vector for any text input')
  it('should return similar vectors for semantically similar texts')
  it('should return dissimilar vectors for unrelated texts')
  it('should batch-embed multiple texts efficiently')
})
```
**Implementation**: `createLocalEmbeddingProvider()`. Requires model download — mark with `@slow` tag.

#### MCP Contract Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/mcp-server/tools.contract.test.ts` | MCP tool input/output contracts | 6 |

##### `src/shell/edge/main/mcp-server/tools.contract.test.ts`

```
describe('MCP Tool Contracts', () => {
  describe('create_graph', () => {
    it('should accept valid input with project, nodes, and optional edges')
    it('should return nodesCreated count and nodeIds array')
    it('should reject input missing required project field')
  })

  describe('search_nodes', () => {
    it('should accept valid input with project and query')
    it('should return results array with id, title, summary, score')
    it('should reject input missing required query field')
  })
})
```
**Implementation**: Tool definitions and handlers in `tools.ts`. Tests verify JSON schema compliance and response shape.

#### Phase 1 Test Count: **~67 tests** (26 unit + 35 integration + 6 contract)

---

### Phase 2 — UI Overhaul (Weeks 9–12)

**Coverage target: 85% for adapters and data logic, visual regression for rendering**

#### Unit Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/UI/graph/graph-adapter.test.ts` | FalkorDB → graphology conversion | 8 |
| `src/shell/UI/feed/feed-sort.test.ts` | Feed sorting logic | 5 |
| `src/shell/UI/search/search-utils.test.ts` | Search result formatting and ranking | 4 |
| `src/shell/UI/filters/filter-logic.test.ts` | Filter application pure functions | 6 |

##### `src/shell/UI/graph/graph-adapter.test.ts`

```
describe('buildGraphologyGraph', () => {
  it('should create a graphology Graph with correct node count')
  it('should create a graphology Graph with correct edge count')
  it('should assign label attribute from node title')
  it('should assign color based on node type (voice=green, agent=blue)')
  it('should assign size based on node type')
  it('should skip edges where source or target node is missing')
  it('should set edge color based on relation type')
  it('should handle empty input (zero nodes, zero edges)')
})
```
**Implementation**: `buildGraphologyGraph()`, `getNodeColor()`, `getNodeSize()`, `getEdgeColor()` in `graph-adapter.ts`.

##### `src/shell/UI/feed/feed-sort.test.ts`

```
describe('Feed sorting', () => {
  it('should sort nodes by created_at descending for "recent" sort')
  it('should sort nodes by modified_at descending for "updated" sort')
  it('should sort nodes by relevance score descending for "relevance" sort')
  it('should handle nodes with identical timestamps stably')
  it('should return empty array for empty input')
})
```
**Implementation**: Pure sort functions extracted from `FeedView.tsx`.

##### `src/shell/UI/filters/filter-logic.test.ts`

```
describe('Filter Logic', () => {
  it('should filter nodes by single node type')
  it('should filter nodes by multiple tags (AND logic)')
  it('should filter nodes by time range')
  it('should filter nodes by source type')
  it('should combine multiple filters with AND semantics')
  it('should return all nodes when no filters applied')
})
```
**Implementation**: Pure filter functions in `filter-logic.ts`.

#### Component Tests (jsdom)

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/UI/feed/FeedView.test.tsx` | Feed renders node cards | 4 |
| `src/shell/UI/search/SearchBar.test.tsx` | Search input and result display | 3 |
| `src/shell/UI/filters/FilterPanel.test.tsx` | Filter toggles and state | 3 |

##### `src/shell/UI/feed/FeedView.test.tsx`

```
describe('FeedView', () => {
  it('should render a card for each node in the feed')
  it('should call onNodeSelect when a card is clicked')
  it('should highlight the selected node card')
  it('should show sort controls for recent/relevance/updated')
})
```

#### Visual Regression Tests (Playwright)

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `tests/e2e/visual/graph-rendering.spec.ts` | Graph renders correctly in viewport | 3 |
| `tests/e2e/visual/feed-view.spec.ts` | Feed view layout and cards | 2 |

##### `tests/e2e/visual/graph-rendering.spec.ts`

```
describe('Graph Rendering (visual)', () => {
  it('should render a graph with 100 nodes without visual artifacts')
  it('should dim non-connected nodes when a node is selected')
  it('should show labels only at sufficient zoom level')
})
```
**Implementation**: Screenshots compared against baseline snapshots. Updated manually when UI changes intentionally.

#### Phase 2 Test Count: **~38 tests** (23 unit + 10 component + 5 visual)

---

### Phase 3 — Ambient Capture (Weeks 13–16)

**Coverage target: 80% for adapters and routing, integration tests for ScreenPipe**

#### Unit Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/pure/types/screenpipe.test.ts` | ScreenPipe type compilation | 1 |
| `src/shell/edge/main/ambient/screenpipe-adapter.test.ts` | Event normalization, app filtering | 6 |
| `src/shell/edge/main/ambient/context-router.test.ts` | Project inference from window context | 4 |
| `src/shell/edge/main/autostart/autostart.test.ts` | Auto-start config logic | 2 |

##### `src/shell/edge/main/ambient/screenpipe-adapter.test.ts`

```
describe('ScreenPipe Adapter', () => {
  it('should normalize OCR content into an AmbientCaptureEvent')
  it('should normalize audio transcription into an AmbientCaptureEvent')
  it('should filter out events from excluded apps')
  it('should skip events with content shorter than minContentLength')
  it('should deduplicate identical content within dedupWindowMs')
  it('should infer project path from VS Code window title')
})
```
**Implementation**: Normalization functions in `screenpipe-adapter.ts`.

##### `src/shell/edge/main/ambient/context-router.test.ts`

```
describe('Context Router', () => {
  it('should map VS Code window title to project path')
  it('should map terminal CWD to project path')
  it('should return null for unknown app contexts')
  it('should handle windows with no project-identifiable info')
})
```
**Implementation**: Pure function that maps app name + window title to project path.

#### Integration Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/tray/system-tray.integration.test.ts` | Tray lifecycle (Electron mocked) | 4 |
| `src/shell/edge/main/ambient/screenpipe-adapter.integration.test.ts` | ScreenPipe polling with MSW mock | 5 |
| `src/shell/edge/main/ambient/background-ingestion.integration.test.ts` | Background processing without UI blocking | 3 |

##### `src/shell/edge/main/tray/system-tray.integration.test.ts`

```
describe('System Tray', () => {
  it('should create tray icon and context menu')
  it('should toggle main window visibility on click')
  it('should prevent window close and hide to tray instead')
  it('should quit app when "Quit VoiceTree" is selected')
})
```
**Implementation**: `createSystemTray()` function. Tests use mocked Electron `Tray`, `Menu`, `BrowserWindow` objects.

##### `src/shell/edge/main/ambient/screenpipe-adapter.integration.test.ts`

```
describe('ScreenPipe Integration', () => {
  it('should poll ScreenPipe REST API and receive OCR events')
  it('should convert ScreenPipe events to IngestionEvents')
  it('should feed converted events into the ingestion pipeline')
  it('should handle ScreenPipe being unavailable gracefully')
  it('should respect polling interval configuration')
})
```
**Implementation**: ScreenPipe adapter with MSW (Mock Service Worker) intercepting `localhost:3030`.

#### Phase 3 Test Count: **~25 tests** (13 unit + 12 integration)

---

### Phase 4 — Scale & Polish (Weeks 17–20)

**Coverage target: Performance benchmarks have fixed SLO thresholds, not coverage %**

#### Performance Benchmark Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `tests/benchmarks/graph-rendering.bench.ts` | Sigma.js render latency at scale | 3 |
| `tests/benchmarks/query-latency.bench.ts` | FalkorDB query latency at scale | 5 |
| `tests/benchmarks/ingestion-throughput.bench.ts` | Events/second ingestion rate | 3 |

##### `tests/benchmarks/query-latency.bench.ts`

```
describe('Query Latency Benchmarks', () => {
  it('should complete vector search in < 50ms (p95) with 10k nodes')
  it('should complete full-text search in < 30ms (p95) with 10k nodes')
  it('should complete blended search in < 150ms (p95) with 10k nodes')
  it('should complete graph traversal (2-hop) in < 100ms (p95) with 10k nodes')
  it('should complete cold start (connect + schema) in < 10s')
})
```
**Implementation**: Uses `performance.now()` and runs each query 100 times, calculates p95. Asserts against SLO thresholds from Phase 4 doc.

##### `tests/benchmarks/ingestion-throughput.bench.ts`

```
describe('Ingestion Throughput Benchmarks', () => {
  it('should ingest a single event in < 500ms (p95)')
  it('should sustain 10 events/second ingestion rate')
  it('should batch-ingest 100 events in < 30 seconds')
})
```

#### Temporal Query Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `src/shell/edge/main/temporal/temporal-queries.integration.test.ts` | Temporal query correctness | 6 |

##### `src/shell/edge/main/temporal/temporal-queries.integration.test.ts`

```
describe('Temporal Queries', () => {
  it('should return only nodes that existed at a given timestamp')
  it('should return all changes since a given timestamp')
  it('should return changes within a time range (since + until)')
  it('should return version history for a specific node in chronological order')
  it('should correlate changes with git commit SHAs')
  it('should return empty results for timestamps before any data')
})
```
**Implementation**: `getGraphAtTimestamp()`, `getChangesSince()`, `getNodeHistory()`, `getGitCorrelatedChanges()` in `temporal-queries.ts`.

#### E2E Smoke Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `tests/e2e/electron/smoke.spec.ts` | App launches, graph loads, search works | 3 |
| `tests/e2e/electron/mcp-roundtrip.spec.ts` | Create graph via MCP → see in UI | 2 |

##### `tests/e2e/electron/smoke.spec.ts`

```
describe('VoiceTree v2 Smoke Tests', () => {
  it('should launch Electron app and show main window')
  it('should display graph view with nodes from FalkorDB')
  it('should return search results when query is entered')
})
```

##### `tests/e2e/electron/mcp-roundtrip.spec.ts`

```
describe('MCP Round-Trip', () => {
  it('should create nodes via MCP create_graph and see them in the graph view')
  it('should search nodes via MCP search_nodes and verify ranked results')
})
```

#### Cross-Platform Build Smoke Tests

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `tests/e2e/electron/build-smoke.spec.ts` | Built app launches on target platform | 2 |

```
describe('Build Smoke Tests', () => {
  it('should launch the packaged app without errors')
  it('should respond to /health on MCP port after launch')
})
```

#### Phase 4 Test Count: **~24 tests** (11 benchmark + 6 temporal + 5 E2E + 2 build)

---

## 4. Example Tests (Actual Code)

### 4.1 Unit Tests — Pure Functions

```typescript
// webapp/src/shell/edge/main/ingestion/pipeline.test.ts

import { describe, it, expect } from 'vitest';
import {
  normalize,
  contentHash,
  isDuplicate,
  classifyNodeType,
  extractTags,
  inferRelations,
  generateSummary,
} from './pipeline';
import type { IngestionEvent, DedupeWindow } from '@pure/types/ingestion';

// ── TEST 1: normalize ──

describe('normalize', () => {
  it('should trim whitespace and collapse multiple spaces', () => {
    const event: IngestionEvent = {
      source: 'whisper',
      sourceRef: 'session-1',
      content: '  Hello   world   this is   a test  ',
      timestamp: '2026-02-14T09:00:00Z',
    };

    const result = normalize(event);

    expect(result.content).toBe('Hello world this is a test');
  });

  it('should generate title from first 80 chars when title is missing', () => {
    const event: IngestionEvent = {
      source: 'mcp',
      sourceRef: 'agent-1',
      content: 'The authentication service uses OAuth2 with PKCE flow for secure token exchange across all client apps',
      timestamp: '2026-02-14T10:00:00Z',
    };

    const result = normalize(event);

    expect(result.title).toBeDefined();
    expect(result.title!.length).toBeLessThanOrEqual(80);
    expect(result.title).not.toContain('[');
    expect(result.title).not.toContain(']');
  });
});

// ── TEST 2: contentHash ──

describe('contentHash', () => {
  it('should return same hash for identical content', () => {
    const hash1 = contentHash('OAuth2 with PKCE flow');
    const hash2 = contentHash('OAuth2 with PKCE flow');
    expect(hash1).toBe(hash2);
    expect(hash1).toHaveLength(16);
  });

  it('should return different hashes for different content', () => {
    const hash1 = contentHash('OAuth2 with PKCE flow');
    const hash2 = contentHash('Token bucket rate limiting');
    expect(hash1).not.toBe(hash2);
  });
});

// ── TEST 3: classifyNodeType ──

describe('classifyNodeType', () => {
  it('should return "voice" for whisper source', () => {
    const event: IngestionEvent = {
      source: 'whisper',
      sourceRef: 'session-1',
      content: 'Sprint planning discussion',
      timestamp: '2026-02-14T09:00:00Z',
    };
    expect(classifyNodeType(event)).toBe('voice');
  });

  it('should return "agent" for mcp source', () => {
    const event: IngestionEvent = {
      source: 'mcp',
      sourceRef: 'claude-abc',
      content: 'Architecture analysis result',
      timestamp: '2026-02-14T10:00:00Z',
    };
    expect(classifyNodeType(event)).toBe('agent');
  });
});

// ── TEST 4: extractTags ──

describe('extractTags', () => {
  it('should extract #hashtag-style tags from content', () => {
    const content = 'Discussing #authentication and #security concerns for the API';
    const tags = extractTags(content);

    expect(tags).toContain('authentication');
    expect(tags).toContain('security');
    expect(tags).toHaveLength(2);
  });

  it('should merge extracted tags with existing tags without duplicates', () => {
    const content = 'Working on #auth improvements and #testing';
    const existing = ['auth', 'sprint-12'];

    const tags = extractTags(content, existing);

    expect(tags).toContain('auth');
    expect(tags).toContain('testing');
    expect(tags).toContain('sprint-12');
    // 'auth' should appear only once
    expect(tags.filter(t => t === 'auth')).toHaveLength(1);
  });
});

// ── TEST 5: inferRelations ──

describe('inferRelations', () => {
  it('should extract [[wikilink]] as a references relation with confidence 1.0', () => {
    const content = 'The auth service depends on [[Token Storage]] for secure keychain access.';
    const relations = inferRelations(content);

    expect(relations).toHaveLength(1);
    expect(relations[0]!.targetTitle).toBe('Token Storage');
    expect(relations[0]!.relationType).toBe('references');
    expect(relations[0]!.confidence).toBe(1.0);
  });

  it('should extract multiple wikilinks from content', () => {
    const content = 'See [[Auth Flow]] and [[API Rate Limiting]] for related policies.';
    const relations = inferRelations(content);

    expect(relations).toHaveLength(2);
    expect(relations.map(r => r.targetTitle)).toContain('Auth Flow');
    expect(relations.map(r => r.targetTitle)).toContain('API Rate Limiting');
  });
});
```

### 4.2 Integration Tests — FalkorDB Operations

```typescript
// webapp/src/shell/edge/main/falkordb/crud.integration.test.ts

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import type { Graph } from '@falkordb/falkordb';
import { getTestGraph, resetTestGraph } from '../../../../../tests/helpers/test-graph';
import { deploySchema } from './schema';
import { createNode, createEdge, vectorSearch } from './crud';
import { makeFakeEmbedding } from '../../../../../tests/fixtures/embeddings';

let graph: Graph;

beforeAll(async () => {
  graph = getTestGraph();
  await deploySchema(graph);
});

afterEach(async () => {
  await resetTestGraph();
});

// ── INTEGRATION TEST 1: Node creation round-trip ──

describe('Node CRUD (integration)', () => {
  it('should create a node and read it back with all properties', async () => {
    const nodeId = await createNode(graph, {
      title: 'Sprint 12 Planning',
      content: 'Prioritize auth refactor. OAuth token refresh bug affects 15% of users.',
      nodeType: 'voice',
      sourceType: 'whisper',
      sourceRef: 'session-2026-02-14',
      vaultId: 'vault-test-001',
      tags: ['sprint-planning', 'auth'],
      embedding: makeFakeEmbedding(42),
    });

    expect(nodeId).toBeDefined();
    expect(typeof nodeId).toBe('string');

    // Read it back
    const result = await graph.query(`
      MATCH (n:Node {id: $id})
      RETURN n.title AS title, n.node_type AS nodeType,
             n.vault_id AS vaultId
    `, { params: { id: nodeId } });

    expect(result.data).toHaveLength(1);
    expect(result.data![0]!['title']).toBe('Sprint 12 Planning');
    expect(result.data![0]!['nodeType']).toBe('voice');
    expect(result.data![0]!['vaultId']).toBe('vault-test-001');
  });

  it('should create tags and link them to nodes via TAGGED_WITH', async () => {
    const nodeId = await createNode(graph, {
      title: 'Auth Architecture',
      content: 'OAuth2 with PKCE flow.',
      nodeType: 'agent',
      sourceType: 'mcp',
      vaultId: 'vault-test-001',
      tags: ['architecture', 'auth', 'security'],
    });

    const result = await graph.query(`
      MATCH (n:Node {id: $id})-[:TAGGED_WITH]->(t:Tag)
      RETURN t.name AS tagName
      ORDER BY t.name
    `, { params: { id: nodeId } });

    const tagNames = result.data!.map(
      (row: Record<string, unknown>) => row['tagName']
    );
    expect(tagNames).toEqual(['architecture', 'auth', 'security']);
  });
});

// ── INTEGRATION TEST 2: Edge creation ──

describe('Edge CRUD (integration)', () => {
  it('should create an edge between two nodes with relation type', async () => {
    const nodeA = await createNode(graph, {
      title: 'Auth Flow',
      content: 'OAuth2 with PKCE.',
      nodeType: 'agent',
      sourceType: 'mcp',
      vaultId: 'vault-test-001',
    });

    const nodeB = await createNode(graph, {
      title: 'Token Storage',
      content: 'Keychain-based token storage.',
      nodeType: 'agent',
      sourceType: 'mcp',
      vaultId: 'vault-test-001',
    });

    await createEdge(graph, nodeA, nodeB, 'depends_on', 'claude-agent', 0.9);

    const result = await graph.query(`
      MATCH (a:Node {id: $fromId})-[e:RELATES_TO]->(b:Node {id: $toId})
      RETURN e.relation_type AS relType, e.weight AS weight
    `, { params: { fromId: nodeA, toId: nodeB } });

    expect(result.data).toHaveLength(1);
    expect(result.data![0]!['relType']).toBe('depends_on');
    expect(result.data![0]!['weight']).toBeCloseTo(0.9);
  });
});

// ── INTEGRATION TEST 3: Vector search ──

describe('Vector Search (integration)', () => {
  it('should return nodes ranked by cosine similarity', async () => {
    // Create nodes with known embeddings
    const authEmbedding = makeFakeEmbedding(100);
    const rateEmbedding = makeFakeEmbedding(200);

    await createNode(graph, {
      title: 'Auth System',
      content: 'Authentication and authorization.',
      nodeType: 'agent',
      sourceType: 'mcp',
      vaultId: 'vault-test-001',
      embedding: authEmbedding,
    });

    await createNode(graph, {
      title: 'Rate Limiter',
      content: 'Token bucket rate limiting algorithm.',
      nodeType: 'manual',
      sourceType: 'editor',
      vaultId: 'vault-test-001',
      embedding: rateEmbedding,
    });

    // Search with embedding similar to auth content
    const results = await vectorSearch(graph, authEmbedding, 10, 'vault-test-001');

    expect(results.length).toBeGreaterThan(0);
    expect(results[0]!.title).toBe('Auth System');
    expect(results[0]!.score).toBeGreaterThan(0);
    // Auth node should rank higher than rate limiter when querying with auth embedding
    if (results.length > 1) {
      expect(results[0]!.score).toBeGreaterThanOrEqual(results[1]!.score);
    }
  });
});
```

### 4.3 E2E Test Skeletons — Playwright

```typescript
// webapp/tests/e2e/electron/smoke.spec.ts

import { test, expect, type ElectronApplication, type Page } from '@playwright/test';
import { _electron as electron } from 'playwright';
import path from 'path';

let app: ElectronApplication;
let page: Page;

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.join(__dirname, '../../../dist/main/index.js')],
    env: {
      ...process.env,
      NODE_ENV: 'test',
      VOICETREE_MCP_PORT: '3101',      // Avoid port conflict with dev
      VOICETREE_FALKORDB_PORT: '6381',  // Test-specific port
    },
  });

  page = await app.firstWindow();
  // Wait for app to fully initialize
  await page.waitForSelector('[data-testid="app-ready"]', { timeout: 30_000 });
});

test.afterAll(async () => {
  await app.close();
});

// ── E2E TEST 1: App launches ──

test('should launch Electron app and show main window', async () => {
  const title = await page.title();
  expect(title).toContain('VoiceTree');

  const isVisible = await page.isVisible('[data-testid="main-layout"]');
  expect(isVisible).toBe(true);
});

// ── E2E TEST 2: Graph view renders ──

test('should display graph view with nodes', async () => {
  // Navigate to graph view
  await page.click('[data-testid="nav-graph"]');
  await page.waitForSelector('.sigma-container', { timeout: 10_000 });

  // Verify the sigma canvas is present
  const canvas = page.locator('.sigma-container canvas');
  await expect(canvas).toBeVisible();
});
```

```typescript
// webapp/tests/e2e/electron/mcp-roundtrip.spec.ts

import { test, expect, type ElectronApplication, type Page } from '@playwright/test';
import { _electron as electron } from 'playwright';
import path from 'path';

let app: ElectronApplication;
let page: Page;
const MCP_PORT = 3101;

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.join(__dirname, '../../../dist/main/index.js')],
    env: {
      ...process.env,
      NODE_ENV: 'test',
      VOICETREE_MCP_PORT: String(MCP_PORT),
      VOICETREE_FALKORDB_PORT: '6381',
    },
  });

  page = await app.firstWindow();
  await page.waitForSelector('[data-testid="app-ready"]', { timeout: 30_000 });
});

test.afterAll(async () => {
  await app.close();
});

// ── E2E TEST 3: MCP create_graph round-trip ──

test('should create nodes via MCP and see them in the graph view', async () => {
  // Call create_graph via HTTP
  const response = await fetch(`http://127.0.0.1:${MCP_PORT}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'create_graph',
        arguments: {
          project: '/test/e2e-project',
          nodes: [
            {
              title: 'E2E Test Node',
              content: 'This node was created by an E2E test via MCP.',
              tags: ['e2e-test'],
            },
          ],
        },
      },
    }),
  });

  const result = await response.json();
  expect(result.result.nodesCreated).toBe(1);

  // Verify node appears in graph view
  await page.click('[data-testid="nav-graph"]');
  await page.waitForTimeout(2000); // Wait for graph to refresh

  // Search for the created node
  await page.fill('[data-testid="search-input"]', 'E2E Test Node');
  await page.waitForSelector('[data-testid="search-result"]', { timeout: 5000 });

  const resultText = await page.textContent('[data-testid="search-result"]');
  expect(resultText).toContain('E2E Test Node');
});

// ── E2E TEST 4: MCP search_nodes ──

test('should search nodes via MCP and get ranked results', async () => {
  const response = await fetch(`http://127.0.0.1:${MCP_PORT}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: {
        name: 'search_nodes',
        arguments: {
          project: '/test/e2e-project',
          query: 'E2E test MCP',
          limit: 5,
        },
      },
    }),
  });

  const result = await response.json();
  expect(result.result.results).toBeDefined();
  expect(result.result.results.length).toBeGreaterThan(0);
  expect(result.result.results[0].title).toBe('E2E Test Node');
  expect(result.result.results[0].score).toBeGreaterThan(0);
});
```

### 4.4 MCP Contract Test

```typescript
// webapp/src/shell/edge/main/mcp-server/tools.contract.test.ts

import { describe, it, expect, beforeAll } from 'vitest';
import { createToolRegistry } from './tools';
import { createMockGraph } from '../../../../../tests/mocks/falkordb-mock';
import { createMockEmbeddingProvider } from '../../../../../tests/fixtures/embeddings';

describe('MCP Tool Contracts', () => {
  const mockGraph = createMockGraph();
  const mockEmbedding = createMockEmbeddingProvider();
  const tools = createToolRegistry(mockGraph, mockEmbedding);

  describe('Tool registration', () => {
    it('should register create_graph, search_nodes, get_graph, and list_vaults tools', () => {
      const names = tools.map(t => t.name);
      expect(names).toContain('create_graph');
      expect(names).toContain('search_nodes');
      expect(names).toContain('get_graph');
      expect(names).toContain('list_vaults');
    });
  });

  describe('create_graph contract', () => {
    it('should have inputSchema requiring project and nodes fields', () => {
      const tool = tools.find(t => t.name === 'create_graph')!;
      const schema = tool.inputSchema as {
        required: string[];
        properties: Record<string, unknown>;
      };

      expect(schema.required).toContain('project');
      expect(schema.required).toContain('nodes');
      expect(schema.properties).toHaveProperty('project');
      expect(schema.properties).toHaveProperty('nodes');
      expect(schema.properties).toHaveProperty('edges');
    });

    it('should accept valid input and return nodesCreated count', async () => {
      const tool = tools.find(t => t.name === 'create_graph')!;

      const result = await tool.handler({
        project: '/test/contract',
        nodes: [
          { title: 'Contract Test Node', content: 'Testing the MCP contract.' },
        ],
      }) as { nodesCreated: number; nodeIds: Array<{ title: string; id: string }> };

      expect(result).toHaveProperty('nodesCreated');
      expect(typeof result.nodesCreated).toBe('number');
      expect(result).toHaveProperty('nodeIds');
      expect(Array.isArray(result.nodeIds)).toBe(true);
    });
  });

  describe('search_nodes contract', () => {
    it('should have inputSchema requiring project and query fields', () => {
      const tool = tools.find(t => t.name === 'search_nodes')!;
      const schema = tool.inputSchema as {
        required: string[];
        properties: Record<string, unknown>;
      };

      expect(schema.required).toContain('project');
      expect(schema.required).toContain('query');
    });

    it('should return results array with score field', async () => {
      const tool = tools.find(t => t.name === 'search_nodes')!;

      const result = await tool.handler({
        project: '/test/contract',
        query: 'authentication',
        limit: 5,
      }) as { results: Array<{ score: number }> };

      expect(result).toHaveProperty('results');
      expect(Array.isArray(result.results)).toBe(true);
    });
  });
});
```

---

## 5. CI Integration

### 5.1 GitHub Actions Workflow

```yaml
# .github/workflows/test.yml

name: VoiceTree v2 Tests

on:
  push:
    branches: [main, v2-dev]
  pull_request:
    branches: [main, v2-dev]

env:
  NODE_VERSION: '20'
  FALKORDB_TEST_PORT: 6380

jobs:
  # ── Stage 1: Unit Tests (fast, no Docker) ──
  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
          cache-dependency-path: webapp/package-lock.json

      - name: Install dependencies
        working-directory: webapp
        run: npm ci

      - name: Type check
        working-directory: webapp
        run: npx tsc --noEmit

      - name: Run unit tests
        working-directory: webapp
        run: npx vitest run --project unit --coverage

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: unit-coverage
          path: webapp/coverage/

  # ── Stage 2: Integration Tests (requires Docker) ──
  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: unit-tests

    services:
      falkordb:
        image: falkordb/falkordb:latest
        ports:
          - 6380:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
          cache-dependency-path: webapp/package-lock.json

      - name: Install dependencies
        working-directory: webapp
        run: npm ci

      - name: Wait for FalkorDB
        run: |
          for i in $(seq 1 30); do
            redis-cli -p ${{ env.FALKORDB_TEST_PORT }} ping && break
            sleep 1
          done

      - name: Run integration tests
        working-directory: webapp
        run: npx vitest run --project integration
        env:
          VOICETREE_FALKORDB_PORT: ${{ env.FALKORDB_TEST_PORT }}
          VOICETREE_MCP_PORT: 3101

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: integration-coverage
          path: webapp/coverage/

  # ── Stage 3: E2E Tests (Electron + Docker) ──
  e2e-tests:
    name: E2E Tests
    runs-on: ubuntu-latest
    timeout-minutes: 30
    needs: integration-tests

    services:
      falkordb:
        image: falkordb/falkordb:latest
        ports:
          - 6381:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
          cache-dependency-path: webapp/package-lock.json

      - name: Install dependencies
        working-directory: webapp
        run: npm ci

      - name: Install Playwright browsers
        working-directory: webapp
        run: npx playwright install --with-deps chromium

      - name: Build app
        working-directory: webapp
        run: npx electron-vite build

      - name: Run E2E tests
        working-directory: webapp
        run: npx playwright test
        env:
          VOICETREE_FALKORDB_PORT: 6381
          VOICETREE_MCP_PORT: 3101
          DISPLAY: ':99'

      - name: Upload E2E results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-results
          path: |
            webapp/test-results/
            webapp/playwright-report/

  # ── Stage 4: Benchmark Tests (on-demand) ──
  benchmarks:
    name: Performance Benchmarks
    runs-on: ubuntu-latest
    timeout-minutes: 30
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: integration-tests

    services:
      falkordb:
        image: falkordb/falkordb:latest
        ports:
          - 6382:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
          cache-dependency-path: webapp/package-lock.json

      - name: Install dependencies
        working-directory: webapp
        run: npm ci

      - name: Run benchmarks
        working-directory: webapp
        run: npx vitest run tests/benchmarks/
        env:
          VOICETREE_FALKORDB_PORT: 6382

      - name: Upload benchmark results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: webapp/test-results/
```

### 5.2 Coverage Reporting

```yaml
# Appended to the unit-tests job

      - name: Coverage summary
        working-directory: webapp
        run: |
          echo "## Coverage Report" >> $GITHUB_STEP_SUMMARY
          cat coverage/coverage-summary.json | \
            jq -r '"| Category | Lines | Functions | Branches |",
                   "|----------|-------|-----------|----------|",
                   "| Total | \(.total.lines.pct)% | \(.total.functions.pct)% | \(.total.branches.pct)% |"' \
            >> $GITHUB_STEP_SUMMARY
```

### 5.3 Test Scripts (package.json)

```json
{
  "scripts": {
    "test": "vitest run",
    "test:unit": "vitest run --project unit",
    "test:integration": "vitest run --project integration",
    "test:e2e": "playwright test",
    "test:bench": "vitest run tests/benchmarks/",
    "test:watch": "vitest --project unit",
    "test:coverage": "vitest run --coverage",
    "start:test": "cross-env NODE_ENV=test electron-vite preview"
  }
}
```

---

## 6. Test Data Strategy

### 6.1 Fixture Design for Reproducible Tests

All test fixtures live in `webapp/tests/fixtures/`:

| File | Contents |
|------|----------|
| `nodes.ts` | 4 realistic `GraphNode` objects (voice, agent, manual, ambient) |
| `edges.ts` | 3 realistic `GraphEdge` objects connecting fixture nodes |
| `vaults.ts` | 2 `Vault` objects for multi-project testing |
| `embeddings.ts` | `makeFakeEmbedding(seed)` deterministic generator + mock provider |
| `ingestion-events.ts` | Raw `IngestionEvent` objects for pipeline testing |
| `markdown-vault/` | Directory with 10 sample `.md` files for migration testing |

**Sample markdown vault fixture:**

```
webapp/tests/fixtures/markdown-vault/
├── Sprint 12 Planning.md
├── Auth Flow.md
├── Token Storage.md
├── API Rate Limiting.md
├── Database Schema.md
├── Error Handling.md
├── Deployment Pipeline.md
├── Monitoring Setup.md
├── User Stories.md
└── Retrospective Notes.md
```

Each file has frontmatter with `title`, `tags`, and `created` fields, plus `[[wikilinks]]` in the content body for edge testing.

### 6.2 Seed Data for FalkorDB Test Instances

```typescript
// webapp/tests/helpers/seed-data.ts

import type { Graph } from '@falkordb/falkordb';
import { createNode, createEdge } from '../../src/shell/edge/main/falkordb/crud';
import { deploySchema } from '../../src/shell/edge/main/falkordb/schema';
import { makeFakeEmbedding } from '../fixtures/embeddings';

/**
 * Seed a test graph with a realistic small dataset.
 * 10 nodes, 8 edges, 6 tags — enough for meaningful query testing.
 */
export async function seedTestData(graph: Graph, vaultId: string): Promise<{
  nodeIds: string[];
  edgeCount: number;
}> {
  await deploySchema(graph);

  // Create vault
  await graph.query(`
    CREATE (v:Vault {
      id: $id, name: 'test-vault', project_path: '/test/project',
      created_at: $now
    })
  `, { params: { id: vaultId, now: new Date().toISOString() } });

  const nodes = [
    { title: 'Sprint 12 Planning', content: 'Auth refactor priority. OAuth bug affecting 15% users.', type: 'voice' as const, tags: ['sprint', 'auth'] },
    { title: 'Auth Service Architecture', content: 'OAuth2 with PKCE. Keychain storage via keytar.', type: 'agent' as const, tags: ['architecture', 'auth'] },
    { title: 'Token Storage', content: 'Secure token storage using OS keychain. Refresh rotation with 7-day expiry.', type: 'agent' as const, tags: ['auth', 'security'] },
    { title: 'API Rate Limiting', content: 'Token bucket: 100 req/min. Burst 20. Headers: X-RateLimit-Remaining.', type: 'manual' as const, tags: ['api', 'infrastructure'] },
    { title: 'Database Schema', content: 'PostgreSQL with UUID primary keys. Migration via Prisma.', type: 'manual' as const, tags: ['database', 'infrastructure'] },
    { title: 'Error Handling', content: 'Centralized error handler. Sentry integration. Custom error codes.', type: 'agent' as const, tags: ['reliability', 'infrastructure'] },
    { title: 'Deployment Pipeline', content: 'GitHub Actions CI/CD. Docker builds. Blue-green deployment.', type: 'manual' as const, tags: ['devops', 'infrastructure'] },
    { title: 'Monitoring Setup', content: 'Prometheus metrics. Grafana dashboards. PagerDuty alerts.', type: 'manual' as const, tags: ['observability', 'infrastructure'] },
    { title: 'User Authentication Flow', content: 'Login → OAuth consent → Token exchange → Redirect. See [[Auth Service Architecture]].', type: 'voice' as const, tags: ['auth', 'ux'] },
    { title: 'Security Audit Results', content: 'No critical vulnerabilities. 3 medium severity. Recommendations: rate limiting, CORS.', type: 'agent' as const, tags: ['security', 'audit'] },
  ];

  const nodeIds: string[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]!;
    const id = await createNode(graph, {
      title: node.title,
      content: node.content,
      nodeType: node.type,
      sourceType: node.type === 'voice' ? 'whisper' : node.type === 'agent' ? 'mcp' : 'editor',
      vaultId,
      tags: node.tags,
      embedding: makeFakeEmbedding(i),
    });
    nodeIds.push(id);
  }

  // Create meaningful edges
  const edges: Array<[number, number, string]> = [
    [1, 0, 'references'],       // Auth Architecture → Sprint Planning
    [2, 1, 'depends_on'],       // Token Storage → Auth Architecture
    [3, 1, 'related_to'],       // Rate Limiting → Auth Architecture
    [5, 3, 'extends'],          // Error Handling → Rate Limiting
    [6, 4, 'depends_on'],       // Deployment → Database
    [7, 6, 'depends_on'],       // Monitoring → Deployment
    [8, 1, 'references'],       // User Auth Flow → Auth Architecture
    [9, 2, 'related_to'],       // Security Audit → Token Storage
  ];

  for (const [fromIdx, toIdx, relType] of edges) {
    await createEdge(graph, nodeIds[fromIdx]!, nodeIds[toIdx]!, relType, 'seed-data');
  }

  return { nodeIds, edgeCount: edges.length };
}

/**
 * Seed a large dataset for benchmark testing.
 */
export async function seedBenchmarkData(
  graph: Graph,
  vaultId: string,
  nodeCount: number = 10_000,
): Promise<void> {
  await deploySchema(graph);

  // Batch create for performance
  const batchSize = 100;
  for (let batch = 0; batch < nodeCount; batch += batchSize) {
    const nodes = [];
    for (let i = batch; i < Math.min(batch + batchSize, nodeCount); i++) {
      nodes.push({
        id: `bench-node-${i}`,
        title: `Benchmark Node ${i}`,
        content: `Content for benchmark node ${i}. Contains keywords: auth, api, database, testing, deployment.`,
        vaultId,
        createdAt: new Date(Date.now() - (nodeCount - i) * 60_000).toISOString(),
        embedding: makeFakeEmbedding(i),
      });
    }

    await graph.query(`
      UNWIND $nodes AS nodeData
      CREATE (n:Node {
        id: nodeData.id,
        title: nodeData.title,
        content: nodeData.content,
        node_type: 'manual',
        source_type: 'editor',
        vault_id: nodeData.vaultId,
        created_at: nodeData.createdAt,
        modified_at: nodeData.createdAt,
        embedding: vecf32(nodeData.embedding)
      })
    `, { params: { nodes } });
  }
}
```

### 6.3 Snapshot Testing Strategy

Snapshots are used sparingly and only for:

| What | Why | Update Policy |
|------|-----|---------------|
| Cypher query shapes | Detect unintentional query changes | Manual review on every update |
| MCP tool input schemas | Contract stability | Must be reviewed — breaking change if schema changes |
| Graph layout data | Detect position regression for deterministic inputs | Auto-update allowed with visual inspection |

```typescript
// Example: Snapshot test for MCP tool schema stability

describe('MCP Tool Schema Snapshots', () => {
  it('should match the create_graph input schema snapshot', () => {
    const tool = tools.find(t => t.name === 'create_graph')!;
    expect(tool.inputSchema).toMatchSnapshot();
  });

  it('should match the search_nodes input schema snapshot', () => {
    const tool = tools.find(t => t.name === 'search_nodes')!;
    expect(tool.inputSchema).toMatchSnapshot();
  });
});
```

**Snapshot files** are committed to git and reviewed in PRs. The CI fails if snapshots change without explicit update.

---

## Test File Directory Structure

```
webapp/
├── src/
│   ├── pure/
│   │   └── types/
│   │       ├── graph.test.ts              ← Type compilation
│   │       └── query.test.ts              ← Constants validation
│   └── shell/
│       ├── edge/
│       │   └── main/
│       │       ├── falkordb/
│       │       │   ├── schema.test.ts                      ← Unit
│       │       │   ├── container-manager.integration.test.ts    ← Integration
│       │       │   ├── client.integration.test.ts               ← Integration
│       │       │   ├── schema.integration.test.ts               ← Integration
│       │       │   ├── crud.integration.test.ts                 ← Integration
│       │       │   ├── vector-search.integration.test.ts        ← Integration
│       │       │   └── fulltext-search.integration.test.ts      ← Integration
│       │       ├── ingestion/
│       │       │   ├── pipeline.test.ts                    ← Unit (pure functions)
│       │       │   └── pipeline.integration.test.ts        ← Integration
│       │       ├── query/
│       │       │   ├── engine.test.ts                      ← Unit (blendScore)
│       │       │   └── engine.integration.test.ts          ← Integration
│       │       ├── routing/
│       │       │   ├── project-router.test.ts              ← Unit
│       │       │   └── project-router.integration.test.ts  ← Integration
│       │       ├── embedding/
│       │       │   └── local-provider.integration.test.ts  ← Integration
│       │       ├── mcp-server/
│       │       │   ├── server.test.ts                      ← Unit
│       │       │   ├── server.integration.test.ts          ← Integration
│       │       │   ├── tools.integration.test.ts           ← Integration
│       │       │   └── tools.contract.test.ts              ← Contract
│       │       ├── migration/
│       │       │   ├── markdown-to-falkordb.test.ts        ← Unit
│       │       │   └── markdown-to-falkordb.integration.test.ts ← Integration
│       │       ├── lifecycle.integration.test.ts           ← Integration
│       │       ├── temporal/
│       │       │   └── temporal-queries.integration.test.ts ← Integration
│       │       ├── tray/
│       │       │   └── system-tray.integration.test.ts     ← Integration
│       │       ├── ambient/
│       │       │   ├── screenpipe-adapter.test.ts          ← Unit
│       │       │   ├── context-router.test.ts              ← Unit
│       │       │   ├── screenpipe-adapter.integration.test.ts ← Integration
│       │       │   └── background-ingestion.integration.test.ts ← Integration
│       │       └── autostart/
│       │           └── autostart.test.ts                   ← Unit
│       └── UI/
│           ├── graph/
│           │   └── graph-adapter.test.ts                   ← Unit
│           ├── feed/
│           │   ├── feed-sort.test.ts                       ← Unit
│           │   └── FeedView.test.tsx                        ← Component
│           ├── search/
│           │   ├── search-utils.test.ts                    ← Unit
│           │   └── SearchBar.test.tsx                       ← Component
│           └── filters/
│               ├── filter-logic.test.ts                    ← Unit
│               └── FilterPanel.test.tsx                     ← Component
├── tests/
│   ├── setup/
│   │   └── falkordb-container.ts                           ← Test infra
│   ├── helpers/
│   │   ├── test-graph.ts                                   ← Test utilities
│   │   └── seed-data.ts                                    ← Data seeding
│   ├── mocks/
│   │   └── falkordb-mock.ts                                ← Mock factory
│   ├── fixtures/
│   │   ├── nodes.ts                                        ← Node fixtures
│   │   ├── vaults.ts                                       ← Vault fixtures
│   │   ├── embeddings.ts                                   ← Embedding fixtures
│   │   └── markdown-vault/                                 ← Sample vault dir
│   │       ├── Sprint 12 Planning.md
│   │       ├── Auth Flow.md
│   │       └── ... (10 files)
│   ├── benchmarks/
│   │   ├── graph-rendering.bench.ts                        ← Perf benchmark
│   │   ├── query-latency.bench.ts                          ← Perf benchmark
│   │   └── ingestion-throughput.bench.ts                   ← Perf benchmark
│   └── e2e/
│       ├── electron/
│       │   ├── smoke.spec.ts                               ← E2E
│       │   ├── mcp-roundtrip.spec.ts                       ← E2E
│       │   └── build-smoke.spec.ts                         ← E2E
│       └── visual/
│           ├── graph-rendering.spec.ts                     ← Visual regression
│           └── feed-view.spec.ts                           ← Visual regression
```

---

## Summary: Test Count by Phase

| Phase | Unit | Integration | Contract | E2E/Visual | Benchmark | Total |
|-------|------|-------------|----------|------------|-----------|-------|
| 0 — Foundation | 19 | 46 | — | — | — | **65** |
| 1 — Core Services | 26 | 35 | 6 | — | — | **67** |
| 2 — UI Overhaul | 23 | — | — | 5 | — | **38** † |
| 3 — Ambient Capture | 13 | 12 | — | — | — | **25** |
| 4 — Scale & Polish | — | 6 | — | 7 | 11 | **24** |
| **TOTAL** | **81** | **99** | **6** | **12** | **11** | **~219** |

† Phase 2 also has 10 component tests included in the unit count.

---

## Key Risks and Gaps

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Docker not available in some CI environments** | Integration tests fail | GitHub Actions `services` block handles this. Local devs need Docker Desktop. |
| **FalkorDB vector search API instability** | Tests break on FalkorDB upgrade | Pin Docker image version. Run integration tests against pinned image. |
| **Embedding model download in CI** | Slow/flaky integration tests | Cache model in GitHub Actions artifact. Use mock embeddings for non-embedding tests. |
| **Electron E2E flakiness** | False failures | Retry 2x in CI. Use explicit waits, not timeouts. Disable animation for tests. |
| **Visual regression baseline drift** | Constant snapshot updates | Only use for critical layout tests (3-5 screenshots). Require manual approval. |
| **Benchmark SLO targets are aspirational** | Early failures in CI | Mark benchmark tests as soft-fail (warning, not error) until Phase 4 optimization. |
| **ScreenPipe integration testability** | Can't run ScreenPipe in CI | Use MSW to mock ScreenPipe REST API. Real ScreenPipe integration tested manually. |
| **Cross-platform test coverage** | Windows/macOS-specific bugs missed | Run unit + integration on all 3 OS in matrix. E2E on Linux only (pragmatic). |
| **Test data doesn't represent real-world scale** | Benchmark results misleading | Use `seedBenchmarkData()` for 10k+ nodes. Run separate perf CI job. |
