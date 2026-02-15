# VoiceTree v2 — Architecture Review

> **Reviewer**: Architecture Review (Critical Assessment)  
> **Date**: 2026-02-14  
> **Documents Reviewed**: NORTH-STAR.md, ARCHITECTURE.md, v2-plan/README.md, all Phase docs, TDD-PLAN.md, COMPETITIVE-LANDSCAPE.md  
> **Status**: Pre-implementation review

---

## Section 1: Dependency Validation

### 1.1 FalkorDB (Graph + Vector + Full-Text)

| Attribute | Detail |
|-----------|--------|
| Latest version | v4.x (Docker image `falkordb/falkordb:latest`) |
| GitHub stars | ~5,500 (FalkorDB/FalkorDB) |
| License | **Server Side Public License v1 (SSPLv1)** |
| Protocols | RESP (Redis) + Bolt |
| Features | OpenCypher, Full-Text (BM25), Vector Similarity (cosine/euclidean), Range indexing |
| Backing store | Redis (in-memory with persistence) |

**Maturity**: Production-ready for graph workloads, but with caveats. Forked from RedisGraph (which Redis Labs discontinued in 2023). The FalkorDB team picked it up and has been actively developing it since. Vector search was added relatively recently compared to Neo4j or dedicated vector stores.

**Known Issues / Gotchas**:
1. **SSPLv1 license** — This is NOT an OSI-approved open-source license. It restricts offering FalkorDB as a service. For a local desktop app this is fine, but it's worth documenting. If VoiceTree were ever offered as a hosted service, SSPLv1 would be a legal problem.
2. **Cypher compatibility** — FalkorDB supports OpenCypher but NOT the full Neo4j Cypher spec. Notably: `UNIQUE` constraints behave differently, `OPTIONAL MATCH` has performance footguns, `MERGE` semantics have subtle differences. The plan's Cypher queries should be validated against FalkorDB's actual dialect, not assumed to work from Neo4j docs.
3. **Vector search maturity** — Vector indexing exists and works for basic use cases. However, it lacks features like ANN index tuning (HNSW parameters), filter-before-search (post-filtering only), and multi-vector per node. For 384-dim embeddings with <100K vectors this should be fine; for larger scale it's unproven.
4. **Memory consumption** — Redis-backed means all data lives in memory by default. For a desktop knowledge graph that could grow to 100K+ nodes with embeddings (384 floats × 4 bytes × 100K = ~150MB just for vectors), memory usage needs monitoring.
5. **Single-threaded** — Redis is fundamentally single-threaded. Complex Cypher queries can block the event loop. This matters for concurrent MCP requests + UI queries.
6. **Backup/restore** — Relies on Redis RDB/AOF persistence. No built-in snapshot export — if the Docker volume gets corrupted, data is gone. The plan mentions no backup strategy.

**Alternatives not fully considered**:
- **Kuzu** — The plan dismisses Kuzu for lacking vector search, but Kuzu v0.4+ added buffer manager improvements and the community is exploring vector extensions. Kuzu is truly embeddable (no Docker), which is a massive advantage for a desktop app.
- **Neo4j Community Edition** — Heavier, but extremely mature Cypher + vector support since v5.11. GPLv3 license.

**Verdict: CAUTION**

FalkorDB is a reasonable choice for the feature set, but the small community (relative to Neo4j/Postgres), SSPLv1 license, Docker requirement, and memory model create real risk. The plan should include a fallback strategy and explicit memory budgeting.

---

### 1.2 FalkorDB TypeScript Client

| Attribute | Detail |
|-----------|--------|
| NPM package | **`falkordb`** (NOT `@falkordb/falkordb` as stated in the plan) |
| Latest version | 6.6.0 (released ~Jan 2026) |
| GitHub | FalkorDB/falkordb-ts — 38 stars, 15 contributors |
| License | MIT |
| Dependencies | Built on `node-redis` v5.10 |

**CRITICAL ISSUE**: The plan consistently refers to `@falkordb/falkordb` as the npm package name. This is **wrong**. The actual npm package is simply `falkordb`. All import statements like `import { FalkorDB, Graph } from '@falkordb/falkordb'` in the plan documents will fail. This must be corrected to `import { FalkorDB } from 'falkordb'`.

**Maturity**: Very young. 38 GitHub stars, 15 contributors (several are bots). The client is a thin wrapper around `node-redis` with graph-specific commands. The API surface is small:
- `FalkorDB.connect()` — connect to server
- `db.selectGraph(name)` — get a graph handle
- `graph.query(cypher, opts)` — run Cypher queries
- `graph.delete()` — delete graph
- `db.list()` / `db.info()` — metadata

**Known Issues**:
1. No connection pooling (relies on node-redis's single connection by default)
2. No query builder — all queries are raw Cypher strings (SQL injection risk if params aren't properly used)
3. Error messages from Cypher parsing failures are often unhelpful
4. The `vecf32()` function for vector literals is FalkorDB-specific — no TypeScript types for it
5. Limited TypeScript typing — `query()` returns loosely typed results requiring manual casting

**Verdict: CAUTION**

Functional but fragile. The small community means bugs may not get fixed quickly. Build a thin abstraction layer on top (which the plan already does) so the client can be swapped if needed. **Fix the package name immediately.**

---

### 1.3 Sigma.js + Graphology (Graph Rendering)

| Attribute | Detail |
|-----------|--------|
| Sigma.js version | v3.x (latest stable) |
| GitHub stars | ~11,000 (jacomyal/sigma.js) |
| Graphology stars | ~1,000 (graphology/graphology) |
| License | MIT (both) |
| Rendering | WebGL |
| Last release | Active development, regular releases |

**Maturity**: Production-ready. Sigma.js v3 is a mature WebGL graph renderer used in production by multiple companies and research groups. The graphology library provides an excellent in-memory graph data model with algorithms (ForceAtlas2, Louvain communities, centrality metrics, etc.).

**Proven capabilities**:
- 10,000+ nodes at 60fps — confirmed by benchmarks and real-world usage
- Semantic zoom (level-of-detail) built in
- Custom node/edge rendering programs for GPU acceleration
- Barnes-Hut optimization for force-directed layouts at scale

**Known Issues**:
1. **Learning curve** — Sigma.js v3 API is significantly different from v2 and from Cytoscape.js. Budget extra time.
2. **React integration** — Sigma.js is imperative (create renderer, attach to DOM). The `@react-sigma/core` package exists but has its own quirks. The plan's React component approach is correct but may need refinement.
3. **Label rendering** — Text rendering on WebGL is inherently harder than Canvas. Label collision avoidance is basic.
4. **Edge rendering** — Curved edges and edge labels are less mature than in Cytoscape.js.
5. **No built-in node editing** — Sigma renders graphs; it doesn't provide WYSIWYG editing on nodes. That's a separate UI concern.

**Verdict: APPROVED**

Sigma.js + graphology is the right choice for large-scale graph visualization. The migration from Cytoscape.js is justified by the 30x+ performance improvement at scale. Budget 2 extra days for the learning curve as the plan suggests.

---

### 1.4 @xenova/transformers (Local Embeddings)

| Attribute | Detail |
|-----------|--------|
| NPM package | `@xenova/transformers` |
| Latest version | **2.17.2** |
| Last published | **~2 years ago (early 2024)** |
| Weekly downloads | ~255,000 (legacy usage) |
| Status | **DEPRECATED — superseded by `@huggingface/transformers`** |

**CRITICAL ISSUE**: The plan references `@xenova/transformers` which is **frozen at v2.17.2 and has not been updated in over 2 years**. The project has been officially absorbed into Hugging Face and rebranded as `@huggingface/transformers`. The current version is **v3.8.1** (stable, released Dec 2025) with **v4.0.0-next.3** in development.

**What changed**:
- Package name: `@xenova/transformers` → `@huggingface/transformers`
- API is largely compatible but with improvements
- v3.x added WebGPU support, better ONNX runtime integration, quantized model support (int8, q4)
- v4.x restructures to pnpm workspaces

**Impact on VoiceTree**:
- All imports in the plan (`from '@xenova/transformers'`) must be changed to `from '@huggingface/transformers'`
- The `pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2')` call may need model path updates
- The v3 API is mostly backward compatible but should be verified
- v3 supports ONNX Runtime for Node.js natively, which is ideal for Electron

**Correct code**:
```typescript
import { pipeline } from '@huggingface/transformers';
const model = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
```

**Verdict: REJECTED (as specified) — use `@huggingface/transformers` v3.x instead**

This is a straightforward fix. The `@huggingface/transformers` package is actively maintained (69 contributors, 6k dependents, 11k+ stars), supports all the same models, and adds WebGPU acceleration. The plan must be updated to reference the correct package.

---

### 1.5 Docker (FalkorDB Deployment)

| Attribute | Detail |
|-----------|--------|
| Docker Desktop | Required for Windows/macOS; Docker Engine for Linux |
| Image | `falkordb/falkordb:latest` |
| Size | ~150-200MB compressed image |
| Cold start | 3-10 seconds (container + Redis + module load) |

**Maturity**: Docker itself is extremely mature. The concern is not Docker's quality but whether requiring Docker for a desktop app is reasonable.

**Analysis**:

Developer Docker adoption estimates (2025-2026):
- **Professional developers**: ~60-70% have Docker installed (Stack Overflow surveys consistently show this)
- **Hobbyist/student developers**: ~30-40%
- **Non-developer power users**: ~5%

For a "developer-first" tool, 60-70% base coverage is okay but not great. **30-40% of your developer target audience would need to install Docker** before they can use VoiceTree. Docker Desktop on Windows/macOS also requires:
- Hyper-V or WSL2 (Windows)
- ~2GB RAM overhead
- Periodic license key issues (Docker Desktop is free for personal use but commercial use requires a subscription for companies >250 employees)

**Alternatives to Docker**:
1. **FalkorDB as a sidecar binary** — FalkorDB doesn't distribute standalone binaries. It's a Redis module, so you need Redis + the module loaded. This could be packaged with the app but would require building/bundling Redis + FalkorDB module for each platform (Linux x64, macOS arm64, macOS x64, Windows x64). Non-trivial but possible.
2. **Redis with FalkorDB module installed locally** — Requires Redis installation + module loading. More complex than Docker.
3. **Switch to an embeddable DB** — See Section 4.

**Verdict: CAUTION**

Docker works but limits your addressable audience. The plan should have a **Phase 0 spike** that validates the Docker UX on all three platforms (Windows, macOS, Linux) before committing. Consider providing a fallback embedded option for users without Docker (see Section 4).

---

### 1.6 Electron (Runtime)

| Attribute | Detail |
|-----------|--------|
| Version | 28+ (plan spec) |
| Current stable | Electron 34.x (Feb 2026) |
| License | MIT |
| Maturity | Very mature, widely used |

**Assessment**: The plan's decision to stay with Electron over Tauri is pragmatic and well-reasoned. The team knows Electron, the bottleneck is the data layer not the runtime, and Tauri would add 2-3 months of learning.

**Concerns**:
1. **Memory** — Electron + FalkorDB (Docker) + Sigma.js (WebGL) + local embedding model (~100MB loaded) could easily consume 500MB-1GB RAM. Document minimum system requirements.
2. **Electron version** — The plan says "Electron 28+" but current stable is 34.x. Pin to a specific major version.
3. **System tray on Linux** — Electron's `Tray` API works differently across Linux desktop environments (GNOME, KDE, etc.). Test on at least Ubuntu and Fedora.

**Verdict: APPROVED**

Correct decision for the team's current situation. Revisit if/when memory becomes a user complaint.

---

### 1.7 React + Tailwind (Frontend)

| Attribute | Detail |
|-----------|--------|
| React | 18.x or 19.x |
| Tailwind CSS | 4.x |
| Maturity | Both extremely mature |

**Verdict: APPROVED**

No concerns. Standard, well-supported choices.

---

### 1.8 Vitest (Testing)

| Attribute | Detail |
|-----------|--------|
| Version | 2.x (current stable) |
| Maturity | Production-ready, widely adopted |
| Compatibility | Vite-native, excellent TypeScript support |

**Assessment**: Good choice. The TDD plan is thorough with proper test pyramid (unit/integration/E2E), Docker test containers, and realistic fixtures. Coverage thresholds (80% lines/functions) are reasonable.

**Verdict: APPROVED**

---

### 1.9 Playwright (E2E)

| Attribute | Detail |
|-----------|--------|
| Version | 1.x (current stable) |
| Maturity | Production-ready, industry standard |
| Electron support | Via `electron` fixture (official) |

**Verdict: APPROVED**

---

### 1.10 Express (MCP Server)

| Attribute | Detail |
|-----------|--------|
| Version | 4.x or 5.x |
| Maturity | The most mature Node.js HTTP framework |

**Assessment**: Fine for the MCP server. StreamableHTTP transport over Express is straightforward. The fixed port approach is correct.

**Minor concern**: Express 4 is in maintenance mode. Express 5 has been in beta for years. Consider Fastify for better TypeScript support and performance, but Express is perfectly adequate for this use case.

**Verdict: APPROVED**

---

## Section 2: Architecture Risk Analysis

### 2.1 FalkorDB as Single Data Store

**Risk Level: MEDIUM-HIGH**

Putting all data (graph, vectors, full-text) in one store is architecturally elegant but creates a single point of failure:

1. **Data loss scenario**: If the Docker volume is corrupted or accidentally deleted, ALL data is gone — graph structure, node content, embeddings, version history, everything. There is no secondary copy.
2. **No export-on-write**: Unlike v1 where markdown files were the source of truth (and thus always on disk in a human-readable format), v2 stores everything in FalkorDB's binary format. The plan mentions "markdown export" as on-demand but not continuous.
3. **Backup strategy is missing**: The plan has no backup section. At minimum:
   - Automatic RDB snapshots to a separate directory (not just the Docker volume)
   - Periodic markdown export as a human-readable backup
   - Export-to-JSON for machine-readable backup
4. **FalkorDB bug impact**: If a FalkorDB bug corrupts the graph, everything is affected simultaneously. With separate stores (e.g., markdown + ChromaDB), a bug in one doesn't destroy the other.

**Recommendation**: Add a backup module to Phase 0 that:
- Takes RDB snapshots every N minutes to a user-accessible directory
- Exports graph to JSON periodically
- Provides a `voicetree backup` CLI command
- Provides a `voicetree restore` CLI command

### 2.2 Docker Dependency for Desktop App

**Risk Level: HIGH**

This is the single most likely deal-breaker for user adoption.

**Problems**:
1. **Installation friction**: "Install Docker, then install VoiceTree" doubles the onboarding friction
2. **Docker Desktop licensing**: Free for personal use and small companies, but paid for enterprises >250 employees. This could block enterprise developer adoption.
3. **Resource overhead**: Docker Desktop on macOS consumes ~1-2GB RAM just running. Combined with Electron + FalkorDB: ~2-3GB total.
4. **Docker startup time**: Cold-starting Docker Desktop + pulling the FalkorDB image + starting the container = 30-60 seconds on first run, 5-15 seconds on subsequent runs.
5. **Docker not available in all environments**: Some corporate environments block Docker installation. WSL2 requirement on Windows can conflict with other hypervisors.

**Recommendation**: Phase 0 should include a **Docker UX spike** (2 days) that:
- Tests cold start on Windows (WSL2), macOS (arm64), and Linux
- Measures total memory consumption
- Tests the "Docker not installed" error path
- Evaluates bundling Redis + FalkorDB module as native binaries as a Docker-free fallback
- Documents minimum system requirements

### 2.3 Electron + FalkorDB (Docker) + Sigma.js Performance

**Risk Level: MEDIUM**

The combined stack is heavy:
- Electron: ~150-300MB RAM
- Docker Desktop: ~1-2GB RAM (macOS/Windows)
- FalkorDB container: ~100-300MB RAM (depends on data size)
- Local embedding model: ~100MB in memory
- Sigma.js WebGL context: ~50-200MB VRAM

**Total estimated: 1.5-3GB RAM** for a knowledge management tool. This is comparable to VS Code + Docker Desktop, which developers tolerate, but it's a lot for a "note-taking" app.

**Recommendation**: Define minimum system requirements early (8GB RAM minimum, 16GB recommended). Profile actual memory usage during Phase 0.

### 2.4 Pure/Shell Architecture

**Risk Level: LOW**

The pure/shell split is sound and well-applied in the plan:
- Pure functions (`src/pure/`) for types, parsing, normalization — no I/O, easily testable
- Shell functions (`src/shell/`) for FalkorDB queries, Docker management, IPC — tested with Docker containers

This is a good architectural pattern for this codebase. The TDD plan correctly maps unit tests to pure functions and integration tests to shell functions.

**One concern**: The plan mixes some pure logic into shell files (e.g., `extractTags()` and `inferRelations()` in the ingestion pipeline are pure but live in `src/shell/`). Ensure pure functions are always in `src/pure/` and called from shell orchestrators.

**Verdict: APPROVED (minor refactoring needed)**

### 2.5 MCP Fixed Port (3100)

**Risk Level: LOW**

Port 3100 is a reasonable default. It's not commonly used by well-known services: 
- Grafana uses 3000
- Express dev servers commonly use 3000-3001
- React dev server uses 3000
- 3100 is used by Grafana Loki, but unlikely to conflict on a developer's desktop

The `VOICETREE_MCP_PORT` env var override is correct.

**Minor concerns**:
1. **Firewall**: Some corporate firewalls block non-standard ports. Since this is localhost-only, it should be fine.
2. **Port conflict detection**: The plan should include a port-in-use check on startup with clear error messaging.

**Verdict: APPROVED**

---

## Section 3: Gaps and Missing Pieces

### 3.1 Backup and Disaster Recovery
**Severity: HIGH**

No backup strategy is defined anywhere in the plan. For a tool that becomes the "single source of truth" for a user's knowledge graph, data loss is catastrophic. See Section 2.1 for recommendations.

### 3.2 Offline / Docker-Down Behavior
**Severity: HIGH**

What happens when Docker isn't running? The plan doesn't define degraded-mode behavior:
- Can the UI show cached data?
- Can MCP tools queue requests for later?
- What error does the user see?

### 3.3 Data Migration Rollback
**Severity: MEDIUM**

The plan includes a markdown → FalkorDB migration tool but no rollback path. If migration fails partway through, or if users want to go back to v1, there's no plan.

### 3.4 Security Model
**Severity: MEDIUM**

- FalkorDB is accessed over localhost:6379 with **no authentication** by default in the Docker config. Any local process can read/write the graph.
- The MCP server on port 3100 has **no authentication**. Any local process can create/delete graph nodes.
- For a local-first app this is mostly acceptable, but it should be documented as a known limitation.

### 3.5 Embedding Model Versioning
**Severity: MEDIUM**

If the user switches embedding models (MiniLM-L6-v2 → OpenAI), existing embeddings become incompatible (384 vs 1536 dimensions). The plan doesn't address:
- Re-embedding existing nodes
- Supporting multiple embedding dimensions simultaneously
- Vector index migration

### 3.6 Error Handling Patterns
**Severity: MEDIUM**

The plan shows mostly happy-path code. Critical error scenarios not addressed:
- FalkorDB connection lost mid-query
- Docker container crashes during operation
- Disk full (RDB persistence fails)
- Embedding model download interrupted

### 3.7 Monitoring and Observability
**Severity: LOW**

Phase 4 has a profiler but no structured logging or health monitoring. For a daemon-mode app, users need to be able to diagnose problems without developer tools.

### 3.8 Update / Migration Path
**Severity: MEDIUM**

No plan for schema migrations when FalkorDB schema evolves between VoiceTree versions. What happens when v2.1 adds a new property to nodes? The `deploySchema()` function is marked "idempotent" but only handles index creation, not data migration.

---

## Section 4: Alternative Architecture Considerations

### 4.1 SurrealDB (Multi-Model, Embeddable)

| Attribute | Detail |
|-----------|--------|
| Version | 2.x (stable) |
| Features | Graph, document, vector, full-text, ACID, embeddable mode |
| License | BSL 1.1 (converts to Apache 2.0 after 4 years) |
| Embedding | Yes — can run in-process, no Docker needed |
| Language | Rust |

**Pros**:
- **No Docker required** — can embed directly in the Electron app
- Multi-model: graph + document + vector + time-series in one
- SurrealQL is expressive (though not Cypher)
- Active development, growing community

**Cons**:
- Not Cypher — would need to learn SurrealQL (graph queries use `RELATE`, `->`, `<-` syntax)
- Younger than FalkorDB for graph-specific workloads
- Vector search is newer, less battle-tested
- BSL license (not OSI open source, but more permissive than SSPLv1 for end users)

**Assessment**: SurrealDB should have been more seriously considered. The "embeddable mode" eliminates Docker entirely, which is a massive UX win. The trade-off is learning SurrealQL instead of Cypher. The plan dismissed it as "ambitious multi-model scope raises maturity concerns" — this was a fair concern in 2024, but as of 2026 SurrealDB v2 is significantly more mature.

**Recommendation**: Run a 2-day spike comparing SurrealDB embedded vs FalkorDB Docker for the VoiceTree use case. If SurrealDB's graph traversal and vector search meet needs, it eliminates the Docker dependency entirely.

### 4.2 PostgreSQL + pgvector + Apache AGE

| Attribute | Detail |
|-----------|--------|
| PostgreSQL | 16.x (extremely mature) |
| pgvector | 0.8.x (production-ready vector extension) |
| Apache AGE | 1.5.x (graph extension, OpenCypher on Postgres) |
| License | PostgreSQL (permissive), pgvector (PostgreSQL), AGE (Apache 2.0) |

**Pros**:
- Postgres is the most mature database in existence. Zero risk of project abandonment.
- pgvector is production-proven at scale (used by major companies for RAG)
- Apache AGE provides OpenCypher on Postgres — similar query language to FalkorDB
- ACID transactions, proper backup/restore, pg_dump, point-in-time recovery
- Can be embedded via `embedded-postgres` npm package (downloads and runs a Postgres binary)

**Cons**:
- Heavier than FalkorDB for a desktop app (~50-100MB binary)
- Apache AGE's Cypher support is partial (no full-text index integration, separate from pgvector)
- Three extensions to coordinate (AGE + pgvector + pg_trgm for full-text)
- More operational complexity than a single-binary solution

**Assessment**: This is the "nuclear option" — maximum maturity and capability, but significant complexity and weight. Not recommended as the primary approach, but worth knowing about as a fallback if FalkorDB proves insufficient.

### 4.3 SQLite + sqlite-vss (or sqlite-vec)

| Attribute | Detail |
|-----------|--------|
| SQLite | 3.x (zero-dependency, embedded) |
| sqlite-vec | 0.x (Alex Garcia's vector extension) |
| License | Public domain (SQLite), MIT (sqlite-vec) |

**Pros**:
- Zero external dependencies — single file database
- `better-sqlite3` npm package is excellent for Node.js/Electron
- sqlite-vec provides vector similarity search
- Extremely fast for read-heavy workloads
- No Docker, no containers, no services
- Backup = copy the .db file

**Cons**:
- **No native graph capabilities** — graph traversal would require recursive CTEs (possible but verbose and less performant than a real graph DB)
- Full-text search via FTS5 is good but not as flexible as FalkorDB's Cypher-integrated full-text
- Graph algorithms (shortest path, PageRank, etc.) would need to be implemented manually
- More code to write for graph operations

**Assessment**: This is the lightweight extreme. For a knowledge graph where relationships and traversals are core features, the lack of native graph support is a real limitation. However, for MVP/Phase 0, a SQLite-based prototype could validate the architecture without the Docker dependency, then migrate to FalkorDB (or SurrealDB) once the data model is proven.

### 4.4 Kuzu (Embeddable Graph DB) + ChromaDB/LanceDB (Vectors)

| Attribute | Detail |
|-----------|--------|
| Kuzu | 0.8.x (embeddable graph database) |
| ChromaDB | 0.5.x (vector database, Python) |
| LanceDB | 0.15.x (embeddable vector DB, Rust-based, Node.js bindings) |

**Pros**:
- Kuzu is truly embeddable — runs in-process via Node.js bindings
- Full Cypher support for graph operations
- LanceDB is also embeddable (no Python sidecar like ChromaDB)
- No Docker needed for either
- Kuzu is specifically designed for desktop/embedded use cases

**Cons**:
- Two databases instead of one (Kuzu + LanceDB)
- Kuzu is still young (v0.x)
- Integration between graph queries and vector search requires application-level joining

**Assessment**: This was the original v2 plan candidate that was dismissed because "we're already running Docker." But if Docker is the #1 risk, this combination eliminates it while providing real graph capabilities. LanceDB is a better fit than ChromaDB for Node.js (no Python required).

---

## Section 5: Recommendations

### Priority 1: CRITICAL (must fix before starting Phase 0)

1. **Fix the npm package name**: Change all references from `@falkordb/falkordb` to `falkordb` throughout the plan documents and all code samples. This is a factual error that will cause immediate build failures.

2. **Replace `@xenova/transformers` with `@huggingface/transformers`**: The `@xenova/transformers` package is deprecated and frozen at v2.17.2 (2+ years old). The correct package is `@huggingface/transformers` v3.8.1+. Update all imports and verify API compatibility.

3. **Add a backup strategy to Phase 0**: Define automated RDB snapshot rotation, periodic JSON export, and CLI backup/restore commands. This is non-negotiable for a "single source of truth" data store.

### Priority 2: HIGH (should address before Phase 0 begins)

4. **Run a Docker UX spike (2 days)**: Test Docker cold start, memory consumption, and error handling on Windows (WSL2), macOS (arm64), and Linux. Define minimum system requirements. Document the "Docker not installed" user experience.

5. **Run a SurrealDB embedded spike (2 days)**: Evaluate SurrealDB embedded mode as a Docker-free alternative. Test graph traversal, vector search, and full-text search against the VoiceTree data model. If it works, it eliminates the #1 risk.

6. **Design the degraded-mode behavior**: What happens when Docker/FalkorDB is unavailable? Queue? Cache? Error? This must be defined before building.

7. **Add FalkorDB authentication**: Set a password on the Redis instance even for localhost. Prevents other local processes from reading/modifying the knowledge graph.

### Priority 3: MEDIUM (address during Phase 0)

8. **Define schema migration strategy**: How does the FalkorDB schema evolve between VoiceTree versions? Write a versioned migration runner.

9. **Define embedding model migration strategy**: What happens when users switch embedding models? Re-embed? Maintain multiple vector indexes?

10. **Document memory budget**: Electron + Docker + FalkorDB + embedding model = how much RAM? Set a ceiling and enforce it.

11. **Profile FalkorDB vector search at target scale**: Test vector search with 10K, 50K, 100K nodes to validate the "architecturally capable of 100K+" claim.

### Priority 4: NICE TO HAVE

12. **Consider Fastify over Express**: Better TypeScript support, faster performance, built-in validation. Low effort to switch.

13. **Consider LanceDB as a vector fallback**: If FalkorDB vector search proves insufficient, LanceDB is embeddable (no Python) and high-performance. Can coexist alongside FalkorDB for graph-only duties.

14. **Add structured logging from day 1**: Not just `console.log`. Use `pino` or similar for JSON-structured logs. Critical for daemon mode debugging.

---

## Section 6: Final Verdict

### Overall Assessment

The v2 plan is **thorough, well-structured, and architecturally sound in its broad strokes**. The phased approach is correct, the pure/shell split is well-applied, the TDD plan is comprehensive, and the feature priorities are right (data layer → services → UI → ambient → scale).

However, there are **two critical errors** (wrong package names for FalkorDB client and transformers.js) and **one high-risk architectural decision** (Docker dependency) that need resolution before starting.

### What Should Be Validated BEFORE Writing Production Code

1. **Fix the two wrong package names** — 1 hour
2. **Docker UX spike on all 3 platforms** — 2 days
3. **SurrealDB embedded spike** — 2 days (could eliminate Docker entirely)
4. **FalkorDB vector search validation at 10K+ nodes** — 1 day
5. **Memory profiling (Electron + Docker + FalkorDB + embedding model)** — 1 day

**Total pre-commit validation: ~1 week**

### Confidence Level for Major Decisions

| Decision | Confidence (1–10) | Notes |
|----------|-------------------|-------|
| Sigma.js + graphology for rendering | **9/10** | Excellent choice, well-proven |
| React + Tailwind for UI | **9/10** | Standard, no risk |
| Vitest + Playwright for testing | **9/10** | Industry standard |
| Pure/shell architecture split | **8/10** | Good pattern, minor boundary issues |
| Electron over Tauri | **8/10** | Pragmatic, correct for now |
| Fixed-port MCP on 3100 | **8/10** | Simple and correct |
| Express for MCP server | **7/10** | Fine, Fastify slightly better |
| FalkorDB for graph + vector + FT | **6/10** | Capable but small community, SSPLv1 |
| `falkordb` TypeScript client | **5/10** | Very small community, 38 stars |
| Docker for FalkorDB deployment | **4/10** | Biggest adoption risk |
| `@huggingface/transformers` for embeddings | **8/10** | Correct once package name is fixed |

### Is the plan sound enough to start Phase 0?

**Yes, with conditions.** Spend 1 week on the pre-commit validation above. If the Docker spike reveals serious UX problems, pivot to SurrealDB embedded or Kuzu + LanceDB before writing production code. If Docker UX is acceptable, proceed with FalkorDB as planned.

The plan's biggest strength is that it's **phase-gated** — Phase 0+1 is a minimum viable v2, and each subsequent phase is independently shippable. This gives natural decision points to re-evaluate.

---

## Summary: Top 3 Risks, Hard Stops, and Spikes

### Top 3 Risks That Could Derail the Project

1. **Docker dependency kills adoption** — 30-40% of developer target audience doesn't have Docker. Installation friction, memory overhead, and licensing concerns compound this.
2. **FalkorDB TS client is too immature** — 38 GitHub stars, 15 contributors. A critical bug or missing feature could block development with no community to fall back on.
3. **Data loss with no backup** — Single data store, no backup strategy, Docker volume as sole persistence. One `docker volume rm` command deletes everything.

### Hard Stops (Must Resolve Before Starting)

1. Fix npm package name (`falkordb`, not `@falkordb/falkordb`)
2. Fix embedding package (`@huggingface/transformers`, not `@xenova/transformers`)
3. Add backup strategy to Phase 0 scope

### Recommended Proof-of-Concept Spikes

| Spike | Duration | Purpose |
|-------|----------|---------|
| Docker UX validation | 2 days | Test install → first run on Win/Mac/Linux |
| SurrealDB embedded evaluation | 2 days | Validate as Docker-free alternative |
| FalkorDB vector search at scale | 1 day | Test 10K-100K vectors with cosine search |
| Memory profiling | 1 day | Measure full stack RAM consumption |
| FalkorDB Cypher dialect validation | 1 day | Run all plan's Cypher queries against real FalkorDB |
