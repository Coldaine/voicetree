# Phase 4 — Scale, Polish, and Production Readiness

> **Duration**: Weeks 17–20  
> **Effort**: ~140 hours  
> **Depends on**: All previous phases  
> **Enables**: Public release

---

## Goals

1. **Performance optimization** — 10,000+ node graphs render at 60fps; query latency < 100ms (p95)
2. **Temporal graph features** — version history, time-sliced views, change diffs
3. **Enhanced visualization** — semantic zoom (LOD), clustering, minimap, visual legend
4. **Testing + CI/CD** — automated test suite, cross-platform builds, release pipeline
5. **Documentation** — user docs, developer docs, MCP tool reference

---

## Prerequisites

- Phases 0–3 complete: FalkorDB + ingestion + query + UI + ambient capture all functional
- Real-world data in the system from daily use during Phases 1–3

---

## Task Breakdown

### 4.1 — Performance Profiling and Optimization (Days 1–7)

**Goal**: Identify and fix performance bottlenecks. Define and enforce SLOs.

#### Performance SLOs

| Metric | Target (p50) | Target (p95) | Measure |
|--------|-------------|-------------|---------|
| Graph render (1k nodes) | < 16ms | < 50ms | Sigma.js render cycle |
| Graph render (10k nodes) | < 32ms | < 100ms | Sigma.js render cycle |
| Ingestion latency | < 200ms | < 500ms | Event received → committed to FalkorDB |
| Search latency (blended) | < 50ms | < 150ms | Query → ranked results returned |
| Vector search | < 20ms | < 50ms | Embedding → top-K results |
| Full-text search | < 10ms | < 30ms | Query → BM25 results |
| App cold start | < 5s | < 10s | Launch → MCP server ready |
| App warm start | < 2s | < 4s | Resume from tray → UI responsive |

#### Profiling Approach

```typescript
// src/shell/edge/main/perf/profiler.ts

interface PerfSample {
  readonly operation: string;
  readonly durationMs: number;
  readonly timestamp: number;
  readonly metadata?: Record<string, unknown>;
}

const samples: PerfSample[] = [];
const MAX_SAMPLES = 10_000;

export function recordPerf(operation: string, durationMs: number, metadata?: Record<string, unknown>): void {
  samples.push({ operation, durationMs, timestamp: Date.now(), metadata });
  if (samples.length > MAX_SAMPLES) {
    samples.splice(0, samples.length - MAX_SAMPLES);
  }
}

export function getPerfStats(operation: string): {
  count: number;
  p50: number;
  p95: number;
  p99: number;
  mean: number;
} {
  const relevant = samples
    .filter(s => s.operation === operation)
    .map(s => s.durationMs)
    .sort((a, b) => a - b);

  if (relevant.length === 0) return { count: 0, p50: 0, p95: 0, p99: 0, mean: 0 };

  return {
    count: relevant.length,
    p50: relevant[Math.floor(relevant.length * 0.5)]!,
    p95: relevant[Math.floor(relevant.length * 0.95)]!,
    p99: relevant[Math.floor(relevant.length * 0.99)]!,
    mean: relevant.reduce((a, b) => a + b, 0) / relevant.length,
  };
}

/** Wrap an async function with performance recording */
export function withPerf<T>(operation: string, fn: () => Promise<T>): Promise<T> {
  const start = performance.now();
  return fn().then(
    (result) => {
      recordPerf(operation, performance.now() - start);
      return result;
    },
    (err) => {
      recordPerf(operation, performance.now() - start, { error: true });
      throw err;
    }
  );
}
```

#### Optimization Strategies

1. **FalkorDB query optimization**
   - Use `PROFILE` on slow queries to identify bottlenecks
   - Add composite indexes for frequent filter combinations
   - Use `OPTIONAL MATCH` sparingly — each adds a scan
   - Batch writes: group multiple node creates into a single `UNWIND` query

```cypher
-- Batch node creation (much faster than individual CREATEs)
UNWIND $nodes AS nodeData
CREATE (n:Node {
  id: nodeData.id,
  title: nodeData.title,
  content: nodeData.content,
  vault_id: nodeData.vaultId,
  created_at: nodeData.createdAt,
  embedding: vecf32(nodeData.embedding)
})
```

2. **Sigma.js rendering optimization**
   - Enable Barnes-Hut approximation for ForceAtlas2 at > 1,000 nodes
   - Reduce label density as graph grows
   - Use node/edge programs for GPU-accelerated rendering
   - Implement viewport culling (only render visible nodes)

3. **IPC data transfer optimization**
   - Stream graph data in chunks rather than one large payload
   - Use `SharedArrayBuffer` for embedding data transfer
   - Compress large payloads with LZ4

4. **Embedding computation optimization**
   - Cache embeddings — don't recompute for unchanged content
   - Batch embeddings (process 10 texts at once instead of 1)
   - Use quantized model (int8) for faster inference

**Effort**: 5 days  
**Test**: Synthetic benchmark with 1k, 5k, 10k nodes — measure all SLO metrics

---

### 4.2 — Temporal Graph Features (Days 6–12)

**Goal**: Version history, time-sliced queries, change diffs, session replay.

#### Temporal Query API

```typescript
// src/shell/edge/main/temporal/temporal-queries.ts

import type { Graph } from '@falkordb/falkordb';

export interface TimeSlice {
  readonly start: string;   // ISO 8601
  readonly end: string;     // ISO 8601
}

export interface ChangeRecord {
  readonly nodeId: string;
  readonly title: string;
  readonly changeType: 'created' | 'modified' | 'appended';
  readonly timestamp: string;
  readonly agentSessionId?: string;
  readonly contentPreview: string;
}

/**
 * Get the graph state at a specific point in time.
 * Returns all nodes that existed at the given timestamp.
 */
export async function getGraphAtTimestamp(
  graph: Graph,
  vaultId: string,
  timestamp: string,
): Promise<Array<{ id: string; title: string; createdAt: string }>> {
  const result = await graph.query(`
    MATCH (n:Node {vault_id: $vaultId})
    WHERE n.created_at <= $timestamp
    RETURN n.id AS id, n.title AS title, n.created_at AS createdAt
    ORDER BY n.created_at DESC
  `, { params: { vaultId, timestamp } });

  return (result.data ?? []).map((row: Record<string, unknown>) => ({
    id: row['id'] as string,
    title: row['title'] as string,
    createdAt: row['createdAt'] as string,
  }));
}

/**
 * Get all changes within a time range.
 */
export async function getChangesSince(
  graph: Graph,
  vaultId: string,
  since: string,
  until?: string,
): Promise<ChangeRecord[]> {
  const untilClause = until ? 'AND v.timestamp <= $until' : '';
  
  const result = await graph.query(`
    MATCH (v:NodeVersion)
    WHERE v.timestamp >= $since ${untilClause}
    MATCH (n:Node {id: v.node_id, vault_id: $vaultId})
    RETURN v.node_id AS nodeId, n.title AS title,
           v.change_type AS changeType, v.timestamp AS timestamp,
           v.agent_session_id AS agentSessionId,
           left(v.content_snapshot, 200) AS contentPreview
    ORDER BY v.timestamp DESC
  `, { params: { vaultId, since, ...(until ? { until } : {}) } });

  return (result.data ?? []).map((row: Record<string, unknown>) => ({
    nodeId: row['nodeId'] as string,
    title: row['title'] as string,
    changeType: row['changeType'] as ChangeRecord['changeType'],
    timestamp: row['timestamp'] as string,
    agentSessionId: row['agentSessionId'] as string | undefined,
    contentPreview: row['contentPreview'] as string,
  }));
}

/**
 * Get version history for a specific node.
 */
export async function getNodeHistory(
  graph: Graph,
  nodeId: string,
): Promise<Array<{
  versionId: string;
  changeType: string;
  timestamp: string;
  contentSnapshot: string;
}>> {
  const result = await graph.query(`
    MATCH (v:NodeVersion {node_id: $nodeId})
    RETURN v.id AS versionId, v.change_type AS changeType,
           v.timestamp AS timestamp, v.content_snapshot AS contentSnapshot
    ORDER BY v.timestamp DESC
  `, { params: { nodeId } });

  return (result.data ?? []).map((row: Record<string, unknown>) => ({
    versionId: row['versionId'] as string,
    changeType: row['changeType'] as string,
    timestamp: row['timestamp'] as string,
    contentSnapshot: row['contentSnapshot'] as string,
  }));
}

/**
 * Get git-correlated changes.
 * Links graph changes to git commits for project evolution tracking.
 */
export async function getGitCorrelatedChanges(
  graph: Graph,
  vaultId: string,
  gitCommit: string,
): Promise<ChangeRecord[]> {
  const result = await graph.query(`
    MATCH (v:NodeVersion {git_commit: $gitCommit})
    MATCH (n:Node {id: v.node_id, vault_id: $vaultId})
    RETURN v.node_id AS nodeId, n.title AS title,
           v.change_type AS changeType, v.timestamp AS timestamp,
           left(v.content_snapshot, 200) AS contentPreview
    ORDER BY v.timestamp ASC
  `, { params: { vaultId, gitCommit } });

  return (result.data ?? []).map((row: Record<string, unknown>) => ({
    nodeId: row['nodeId'] as string,
    title: row['title'] as string,
    changeType: row['changeType'] as ChangeRecord['changeType'],
    timestamp: row['timestamp'] as string,
    contentPreview: row['contentPreview'] as string,
  }));
}
```

#### Timeline UI Component

```typescript
// src/shell/UI/temporal/Timeline.tsx

import React, { useMemo } from 'react';
import type { ChangeRecord } from '../../../shell/edge/main/temporal/temporal-queries';

interface TimelineProps {
  changes: readonly ChangeRecord[];
  onChangeSelect: (nodeId: string) => void;
}

export function Timeline({ changes, onChangeSelect }: TimelineProps): React.ReactElement {
  const groupedByDay = useMemo(() => {
    const groups = new Map<string, ChangeRecord[]>();
    for (const change of changes) {
      const day = new Date(change.timestamp).toLocaleDateString();
      const existing = groups.get(day) ?? [];
      existing.push(change);
      groups.set(day, existing);
    }
    return groups;
  }, [changes]);

  return (
    <div className="timeline p-4 overflow-y-auto">
      {[...groupedByDay.entries()].map(([day, dayChanges]) => (
        <div key={day} className="mb-6">
          <h3 className="text-sm font-semibold text-gray-500 mb-2 sticky top-0 bg-white py-1">
            {day}
          </h3>
          <div className="relative pl-6 border-l-2 border-gray-200">
            {dayChanges.map((change, idx) => (
              <div key={`${change.nodeId}-${idx}`} className="mb-3 relative">
                {/* Timeline dot */}
                <div className={`absolute -left-[29px] w-3 h-3 rounded-full border-2 border-white ${
                  getChangeColor(change.changeType)
                }`} />
                
                <button
                  className="w-full text-left p-2 rounded hover:bg-gray-50"
                  onClick={() => onChangeSelect(change.nodeId)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">
                      {new Date(change.timestamp).toLocaleTimeString()}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${getChangeBadge(change.changeType)}`}>
                      {change.changeType}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-gray-900 mt-1">{change.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5 truncate">{change.contentPreview}</p>
                  {change.agentSessionId && (
                    <span className="text-xs text-blue-500 mt-1 inline-block">
                      Agent: {change.agentSessionId.slice(0, 8)}
                    </span>
                  )}
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function getChangeColor(type: string): string {
  switch (type) {
    case 'created': return 'bg-green-500';
    case 'modified': return 'bg-blue-500';
    case 'appended': return 'bg-yellow-500';
    default: return 'bg-gray-400';
  }
}

function getChangeBadge(type: string): string {
  switch (type) {
    case 'created': return 'bg-green-100 text-green-700';
    case 'modified': return 'bg-blue-100 text-blue-700';
    case 'appended': return 'bg-yellow-100 text-yellow-700';
    default: return 'bg-gray-100 text-gray-700';
  }
}
```

**Effort**: 5 days  
**Test**: Create 50 versions over multiple days → timeline groups correctly. Time-sliced query returns correct graph state.

---

### 4.3 — Enhanced Visualization (Days 10–14)

**Goal**: Semantic zoom, level-of-detail, clustering, minimap, visual legend.

Key features:
1. **Semantic zoom** — zoomed out: nodes are dots with cluster labels. Zoomed in: full labels, content previews
2. **Automatic clustering** — Louvain community detection groups related nodes
3. **Minimap** — overview of full graph with viewport indicator
4. **Visual legend** — shows what colors and shapes mean

```typescript
// src/shell/UI/graph/graph-enhancements.ts

import Graph from 'graphology';
import louvain from 'graphology-communities-louvain';

/** Color palette for clusters */
const CLUSTER_COLORS = [
  '#4CAF50', '#2196F3', '#FF9800', '#9C27B0', '#F44336',
  '#00BCD4', '#795548', '#607D8B', '#E91E63', '#3F51B5',
];

/**
 * Apply Louvain community detection and assign cluster colors.
 */
export function applyClustering(graph: Graph): Map<string, number> {
  const communities = louvain(graph);
  
  // Assign colors to communities
  const communityIds = [...new Set(Object.values(communities))];
  
  graph.forEachNode((node) => {
    const communityId = communities[node] ?? 0;
    const colorIndex = communityIds.indexOf(communityId) % CLUSTER_COLORS.length;
    graph.setNodeAttribute(node, 'communityId', communityId);
    graph.setNodeAttribute(node, 'communityColor', CLUSTER_COLORS[colorIndex]);
  });

  // Return community membership
  const membership = new Map<string, number>();
  for (const [node, community] of Object.entries(communities)) {
    membership.set(node, community);
  }
  return membership;
}

/**
 * Generate cluster labels for semantic zoom.
 * When zoomed out, show top tags/titles per cluster instead of individual labels.
 */
export function getClusterLabels(
  graph: Graph,
  communities: Map<string, number>,
): Map<number, string> {
  const clusterNodes = new Map<number, string[]>();
  
  for (const [nodeId, communityId] of communities) {
    const existing = clusterNodes.get(communityId) ?? [];
    const title = graph.getNodeAttribute(nodeId, 'label') as string;
    existing.push(title);
    clusterNodes.set(communityId, existing);
  }

  const labels = new Map<number, string>();
  for (const [communityId, titles] of clusterNodes) {
    // Use most common words as cluster label
    const label = titles.length <= 3
      ? titles.join(', ')
      : `${titles[0]} +${titles.length - 1} more`;
    labels.set(communityId, label);
  }

  return labels;
}
```

**Effort**: 3 days  
**Test**: Graph with 5 clusters colors them distinctly. Zoom out → cluster labels visible. Zoom in → individual labels.

---

### 4.4 — CI/CD Pipeline (Days 13–17)

**Goal**: Automated testing, building, and releasing for all platforms.

#### GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
          cache-dependency-path: webapp/package-lock.json

      - name: Install dependencies
        run: cd webapp && npm ci

      - name: Type check
        run: cd webapp && npx tsc --noEmit

      - name: Lint
        run: cd webapp && npx eslint src/

      - name: Unit tests
        run: cd webapp && npm run test

  integration-test:
    runs-on: ubuntu-latest
    needs: lint-and-test
    services:
      falkordb:
        image: falkordb/falkordb:latest
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: cd webapp && npm ci

      - name: Integration tests
        run: cd webapp && npm run test:integration
        env:
          FALKORDB_HOST: localhost
          FALKORDB_PORT: 6379

  build:
    needs: [lint-and-test, integration-test]
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: cd webapp && npm ci

      - name: Build
        run: cd webapp && npm run build

      - name: Package Electron
        run: cd webapp && npm run package

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: voicetree-${{ matrix.os }}
          path: webapp/dist/
```

#### Release Workflow

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            platform: linux
          - os: macos-latest
            platform: mac
          - os: windows-latest
            platform: win
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - run: cd webapp && npm ci
      - run: cd webapp && npm run build
      - run: cd webapp && npm run package -- --${{ matrix.platform }}

      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          files: webapp/dist/*
          draft: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Effort**: 3 days  
**Test**: Push to main → CI passes. Create tag → release artifacts built for all platforms.

---

### 4.5 — Documentation (Days 16–20)

**Goal**: Comprehensive docs for users, developers, and MCP tool consumers.

#### Documentation Structure

```
docs/
├── getting-started.md          # Install, first run, basic usage
├── user-guide/
│   ├── voice-capture.md        # Voice input workflow
│   ├── graph-navigation.md     # Graph view, feed view, search
│   ├── ambient-capture.md      # ScreenPipe setup, configuration
│   ├── multi-project.md        # Working with multiple projects
│   └── settings.md             # All configuration options
├── developer-guide/
│   ├── architecture.md         # System architecture overview
│   ├── falkordb-schema.md      # Graph schema, Cypher queries
│   ├── ingestion-pipeline.md   # How data flows in
│   ├── query-engine.md         # How search and retrieval work
│   └── contributing.md         # Dev setup, PR process
├── mcp-tools/
│   ├── overview.md             # What MCP tools are available
│   ├── create_graph.md         # Detailed usage + examples
│   ├── search_nodes.md         # Detailed usage + examples
│   ├── get_graph.md            # Detailed usage + examples
│   └── setup.md                # How to configure MCP clients
└── faq.md                      # Common questions
```

#### MCP Tool Reference Example

```markdown
# create_graph

Create one or more nodes in the VoiceTree knowledge graph, optionally with typed edges between them.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project | string | Yes | Project path for vault routing |
| nodes | array | Yes | Array of node specifications |
| nodes[].title | string | Yes | Node title |
| nodes[].content | string | Yes | Node content (markdown) |
| nodes[].tags | string[] | No | Tags to apply |
| nodes[].nodeType | enum | No | voice, agent, manual, ambient |
| nodes[].parentId | string | No | ID of parent node |
| edges | array | No | Array of edge specifications |
| edges[].from | string | Yes | Title or ID of source node |
| edges[].to | string | Yes | Title or ID of target node |
| edges[].relationType | enum | Yes | references, depends_on, extends, contradicts, example_of, child_of |

## Example

```json
{
  "project": "/home/user/my-project",
  "nodes": [
    {
      "title": "Authentication Flow",
      "content": "The app uses OAuth2 with PKCE for secure authentication.\n\n## Steps\n1. Redirect to provider\n2. Exchange code for token\n3. Store token securely",
      "tags": ["auth", "security", "oauth"]
    },
    {
      "title": "Token Storage",
      "content": "Tokens are stored in the system keychain. Never in localStorage.",
      "tags": ["auth", "storage"]
    }
  ],
  "edges": [
    {
      "from": "Authentication Flow",
      "to": "Token Storage",
      "relationType": "depends_on"
    }
  ]
}
```

## Response

```json
{
  "nodesCreated": 2,
  "nodeIds": [
    { "title": "Authentication Flow", "id": "a1b2c3d4-..." },
    { "title": "Token Storage", "id": "e5f6g7h8-..." }
  ]
}
```
```

**Effort**: 4 days  

---

### 4.6 — Markdown Export (Days 18–20)

**Goal**: On-demand export of any vault to human-readable markdown files with frontmatter.

```typescript
// src/shell/edge/main/export/markdown-export.ts

import type { Graph } from '@falkordb/falkordb';
import fs from 'fs/promises';
import path from 'path';

interface ExportResult {
  filesWritten: number;
  exportPath: string;
  durationMs: number;
}

export async function exportVaultToMarkdown(
  graph: Graph,
  vaultId: string,
  outputDir: string,
): Promise<ExportResult> {
  const start = Date.now();
  await fs.mkdir(outputDir, { recursive: true });

  // Fetch all nodes with their tags and edges
  const result = await graph.query(`
    MATCH (n:Node {vault_id: $vaultId})
    OPTIONAL MATCH (n)-[:TAGGED_WITH]->(t:Tag)
    OPTIONAL MATCH (n)-[e:RELATES_TO]->(target:Node)
    RETURN n.id AS id, n.title AS title, n.content AS content,
           n.node_type AS nodeType, n.source_type AS sourceType,
           n.created_at AS createdAt, n.modified_at AS modifiedAt,
           collect(DISTINCT t.name) AS tags,
           collect(DISTINCT {title: target.title, type: e.relation_type}) AS relations
    ORDER BY n.created_at ASC
  `, { params: { vaultId } });

  let filesWritten = 0;

  for (const row of result.data ?? []) {
    const title = row['title'] as string;
    const content = row['content'] as string;
    const tags = row['tags'] as string[];
    const relations = row['relations'] as Array<{ title: string; type: string }>;
    const safeTitle = title.replace(/[<>:"/\\|?*]/g, '_');

    // Build frontmatter
    const frontmatter = [
      '---',
      `title: "${title}"`,
      `id: ${row['id']}`,
      `type: ${row['nodeType']}`,
      `source: ${row['sourceType']}`,
      `created: ${row['createdAt']}`,
      `modified: ${row['modifiedAt']}`,
    ];

    if (tags.length > 0) {
      frontmatter.push(`tags: [${tags.map(t => `"${t}"`).join(', ')}]`);
    }

    frontmatter.push('---', '');

    // Add wikilinks for relations
    let body = content;
    if (relations.length > 0) {
      body += '\n\n## Related\n\n';
      for (const rel of relations) {
        if (rel.title) {
          body += `- ${rel.type}: [[${rel.title}]]\n`;
        }
      }
    }

    const fileContent = frontmatter.join('\n') + body;
    await fs.writeFile(path.join(outputDir, `${safeTitle}.md`), fileContent, 'utf-8');
    filesWritten++;
  }

  return {
    filesWritten,
    exportPath: outputDir,
    durationMs: Date.now() - start,
  };
}
```

**Effort**: 2 days  
**Test**: Export vault with 100 nodes → all .md files created with correct frontmatter. Re-import → identical graph.

---

## Testing Strategy

| Test Type | Scope | Tool |
|-----------|-------|------|
| Performance benchmarks | Render time, query latency, ingestion throughput | Custom benchmark suite |
| Temporal queries | Time-sliced views, change history, version diffs | Vitest + FalkorDB |
| CI pipeline | Lint, type-check, unit test, integration test, build | GitHub Actions |
| Cross-platform build | Windows + macOS + Linux packaging | GitHub Actions matrix |
| Export/import round-trip | Export → re-import → verify identical graph | Vitest |
| Visual regression | Clustering colors, zoom levels, minimap | Playwright screenshots |

---

## Definition of Done

- [ ] All performance SLOs met (see table above)
- [ ] 10,000-node synthetic benchmark passes all latency targets
- [ ] Temporal queries work: `getGraphAtTimestamp`, `getChangesSince`, `getNodeHistory`
- [ ] Timeline UI renders grouped changes with correct colors
- [ ] Louvain clustering assigns distinct colors to communities
- [ ] Semantic zoom: labels fade at zoom-out, cluster labels appear
- [ ] Minimap shows full graph with viewport indicator
- [ ] CI/CD pipeline: push → test → build for all platforms
- [ ] Release workflow: tag → draft release with artifacts
- [ ] Markdown export creates valid .md files with frontmatter + wikilinks
- [ ] User documentation covers: getting started, voice capture, graph navigation, search, ambient capture, MCP tools
- [ ] Developer documentation covers: architecture, schema, pipeline, query engine, contributing

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 10k-node performance target not hit | Core selling point fails | Sigma.js handles this natively. Profile and optimize iteratively. Viewport culling is the fallback |
| Temporal query performance at scale | Slow history views | Index `NodeVersion.timestamp` and `NodeVersion.node_id`. Partition old versions to archive |
| Cross-platform build differences | Platform-specific bugs | CI tests on all three platforms. Manual QA for platform-specific UI (tray, auto-start) |
| Documentation becomes stale | Developer friction | Use doc generation from TypeScript types where possible. Mark docs with "last verified" dates |
| Docker requirement for CI | Can't test FalkorDB without Docker | Use GitHub Actions services (Docker-in-Docker). Local: require Docker for integration tests |
