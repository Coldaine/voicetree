# Phase 2 — UI Overhaul: Sigma.js, Feed View, Search, Filters

> **Duration**: Weeks 9–12  
> **Effort**: ~160 hours  
> **Depends on**: Phase 0 (FalkorDB), Phase 1 (query engine, MCP tools)  
> **Enables**: Phase 3 (ambient capture needs UI for review), Phase 4 (performance tuning)

---

## Goals

1. **Sigma.js replaces Cytoscape.js** — WebGL-rendered graph view handling 10k+ nodes at 60fps
2. **Feed view** — chronological / relevance-sorted primary navigation (not just graph)
3. **Search** — full-text + semantic + graph-aware, unified search bar
4. **Node editor** — improved markdown editor with tag management
5. **Filter panel** — filter by type, tag, relation, time range, agent, project

---

## Prerequisites

- Phase 1 complete: query engine returns blended results, FalkorDB has data
- Sigma.js familiarity — read [sigma.js docs](https://www.sigmajs.org/)
- graphology library for graph data model (required by Sigma.js)

---

## Task Breakdown

### 2.1 — Sigma.js Integration (Days 1–8)

**Goal**: Replace Cytoscape.js with Sigma.js + graphology for the main graph view.

#### Install Dependencies

```bash
npm install sigma graphology graphology-layout graphology-layout-forceatlas2 \
  graphology-communities-louvain graphology-metrics graphology-types
```

#### Graph Data Adapter

```typescript
// src/shell/UI/graph/graph-adapter.ts
// Converts FalkorDB query results → graphology graph → Sigma.js

import Graph from 'graphology';
import type { GraphNode, GraphEdge } from '../../../pure/types/graph';

export interface GraphViewData {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
}

/**
 * Build a graphology Graph from FalkorDB query results.
 * Graphology is the data layer that Sigma.js renders.
 */
export function buildGraphologyGraph(data: GraphViewData): Graph {
  const graph = new Graph({ multi: true, type: 'directed' });

  for (const node of data.nodes) {
    graph.addNode(node.id, {
      label: node.title,
      x: Math.random() * 1000,  // Initial random position, layout will fix
      y: Math.random() * 1000,
      size: getNodeSize(node),
      color: getNodeColor(node),
      nodeType: node.nodeType,
      sourceType: node.sourceType,
      tags: node.tags,
      createdAt: node.createdAt,
    });
  }

  for (const edge of data.edges) {
    if (graph.hasNode(edge.fromNodeId) && graph.hasNode(edge.toNodeId)) {
      graph.addEdge(edge.fromNodeId, edge.toNodeId, {
        label: edge.relationType,
        color: getEdgeColor(edge.relationType),
        size: edge.weight,
        relationType: edge.relationType,
      });
    }
  }

  return graph;
}

function getNodeSize(node: GraphNode): number {
  switch (node.nodeType) {
    case 'voice': return 8;
    case 'agent': return 10;
    case 'manual': return 6;
    case 'ambient': return 4;
    default: return 6;
  }
}

function getNodeColor(node: GraphNode): string {
  switch (node.nodeType) {
    case 'voice': return '#4CAF50';     // Green
    case 'agent': return '#2196F3';     // Blue
    case 'manual': return '#FF9800';    // Orange
    case 'ambient': return '#9C27B0';   // Purple
    default: return '#757575';          // Grey
  }
}

function getEdgeColor(relationType: string): string {
  switch (relationType) {
    case 'depends_on': return '#F44336';   // Red
    case 'references': return '#2196F3';   // Blue
    case 'extends': return '#4CAF50';      // Green
    case 'contradicts': return '#FF5722';  // Deep Orange
    case 'example_of': return '#00BCD4';   // Cyan
    case 'child_of': return '#795548';     // Brown
    default: return '#9E9E9E';             // Grey
  }
}
```

#### Sigma.js React Component

```typescript
// src/shell/UI/graph/SigmaGraphView.tsx

import React, { useEffect, useRef, useCallback, useState } from 'react';
import Sigma from 'sigma';
import Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import type { GraphNode } from '../../../pure/types/graph';

interface SigmaGraphViewProps {
  graph: Graph;
  onNodeClick: (nodeId: string) => void;
  onNodeHover: (nodeId: string | null) => void;
  selectedNodeId: string | null;
  highlightedNodes: Set<string>;
}

export function SigmaGraphView({
  graph,
  onNodeClick,
  onNodeHover,
  selectedNodeId,
  highlightedNodes,
}: SigmaGraphViewProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);

  // Initialize Sigma.js
  useEffect(() => {
    if (!containerRef.current || graph.order === 0) return;

    // Apply ForceAtlas2 layout
    forceAtlas2.assign(graph, {
      iterations: 100,
      settings: {
        gravity: 1,
        scalingRatio: 10,
        strongGravityMode: true,
        barnesHutOptimize: graph.order > 500,
      },
    });

    // Create Sigma instance
    const sigma = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      enableEdgeEvents: true,
      defaultEdgeType: 'arrow',
      labelRenderedSizeThreshold: 12,  // Hide labels when zoomed out (LOD)
      labelDensity: 0.07,              // Reduce label clutter
      labelGridCellSize: 200,
      minCameraRatio: 0.01,            // Max zoom in
      maxCameraRatio: 10,              // Max zoom out
      nodeProgramClasses: {},
      // Semantic zoom: reduce node size when zoomed out
      nodeReducer: (node, data) => {
        const res = { ...data };
        if (selectedNodeId && node !== selectedNodeId) {
          if (!highlightedNodes.has(node)) {
            res.color = '#e0e0e0';  // Dim non-related nodes
            res.label = '';          // Hide labels for dimmed nodes
          }
        }
        return res;
      },
      edgeReducer: (edge, data) => {
        const res = { ...data };
        if (selectedNodeId) {
          const source = graph.source(edge);
          const target = graph.target(edge);
          if (source !== selectedNodeId && target !== selectedNodeId) {
            res.color = '#f5f5f5';  // Dim non-connected edges
          }
        }
        return res;
      },
    });

    // Event handlers
    sigma.on('clickNode', ({ node }) => onNodeClick(node));
    sigma.on('enterNode', ({ node }) => onNodeHover(node));
    sigma.on('leaveNode', () => onNodeHover(null));

    sigmaRef.current = sigma;

    return () => {
      sigma.kill();
      sigmaRef.current = null;
    };
  }, [graph, selectedNodeId, highlightedNodes, onNodeClick, onNodeHover]);

  // Refresh rendering when selection changes
  useEffect(() => {
    sigmaRef.current?.refresh();
  }, [selectedNodeId, highlightedNodes]);

  return (
    <div 
      ref={containerRef}
      style={{ width: '100%', height: '100%' }}
      className="sigma-container"
    />
  );
}
```

#### Fetching Graph Data from FalkorDB

```typescript
// src/shell/UI-edge/graph/useGraphData.ts

import { useState, useEffect, useCallback } from 'react';
import Graph from 'graphology';
import { buildGraphologyGraph, type GraphViewData } from '../../UI/graph/graph-adapter';

interface UseGraphDataResult {
  graph: Graph;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useGraphData(vaultId: string | null): UseGraphDataResult {
  const [graph, setGraph] = useState<Graph>(new Graph());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    if (!vaultId) return;
    setLoading(true);
    setError(null);

    try {
      // Call main process via IPC to query FalkorDB
      const data: GraphViewData = await window.electronAPI.queryGraph(vaultId);
      const g = buildGraphologyGraph(data);
      setGraph(g);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  }, [vaultId]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  return { graph, loading, error, refetch: fetchGraph };
}
```

**Effort**: 6 days  
**Risk**: Sigma.js API differs from Cytoscape significantly → budget 2 extra days for learning curve  
**Test**: Render graph with 5,000 synthetic nodes → measure FPS (target: 60fps)

---

### 2.2 — Feed View (Days 7–12)

**Goal**: A non-graph primary navigation view showing nodes chronologically or by relevance.

```typescript
// src/shell/UI/feed/FeedView.tsx

import React, { useState, useCallback } from 'react';
import type { GraphNode } from '../../../pure/types/graph';

type FeedSort = 'recent' | 'relevance' | 'updated';

interface FeedViewProps {
  nodes: readonly GraphNode[];
  onNodeSelect: (nodeId: string) => void;
  selectedNodeId: string | null;
}

export function FeedView({ nodes, onNodeSelect, selectedNodeId }: FeedViewProps): React.ReactElement {
  const [sort, setSort] = useState<FeedSort>('recent');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const sortedNodes = useSortedNodes(nodes, sort);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="feed-view flex flex-col h-full">
      {/* Sort controls */}
      <div className="feed-header flex items-center gap-2 p-3 border-b border-gray-200">
        <span className="text-sm text-gray-500">Sort by:</span>
        {(['recent', 'relevance', 'updated'] as const).map(s => (
          <button
            key={s}
            className={`px-3 py-1 text-sm rounded-full ${
              sort === s
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
            onClick={() => setSort(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Feed items */}
      <div className="feed-items flex-1 overflow-y-auto">
        {sortedNodes.map(node => (
          <FeedItem
            key={node.id}
            node={node}
            isSelected={node.id === selectedNodeId}
            isExpanded={expandedIds.has(node.id)}
            onSelect={() => onNodeSelect(node.id)}
            onToggleExpand={() => toggleExpand(node.id)}
          />
        ))}
      </div>
    </div>
  );
}

interface FeedItemProps {
  node: GraphNode;
  isSelected: boolean;
  isExpanded: boolean;
  onSelect: () => void;
  onToggleExpand: () => void;
}

function FeedItem({ node, isSelected, isExpanded, onSelect, onToggleExpand }: FeedItemProps): React.ReactElement {
  const typeIcon = getTypeIcon(node.nodeType);

  return (
    <div
      className={`feed-item p-4 border-b border-gray-100 cursor-pointer transition-colors ${
        isSelected ? 'bg-blue-50 border-l-4 border-l-blue-500' : 'hover:bg-gray-50'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-start gap-3">
        <span className="text-lg mt-0.5">{typeIcon}</span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-gray-900 truncate">{node.title}</h3>
          <p className="text-xs text-gray-500 mt-1">
            {new Date(node.createdAt).toLocaleString()} · {node.sourceType}
          </p>
          {/* Tags */}
          {node.tags.length > 0 && (
            <div className="flex gap-1 mt-2 flex-wrap">
              {node.tags.map(tag => (
                <span
                  key={tag}
                  className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          {/* Expanded content */}
          {isExpanded && (
            <div className="mt-3 text-sm text-gray-700 whitespace-pre-wrap">
              {node.content.slice(0, 500)}
              {node.content.length > 500 && '...'}
            </div>
          )}
          <button
            className="text-xs text-blue-600 mt-2 hover:underline"
            onClick={(e) => { e.stopPropagation(); onToggleExpand(); }}
          >
            {isExpanded ? 'Collapse' : 'Expand'}
          </button>
        </div>
      </div>
    </div>
  );
}

function getTypeIcon(nodeType: string): string {
  switch (nodeType) {
    case 'voice': return '🎤';
    case 'agent': return '🤖';
    case 'manual': return '✏️';
    case 'ambient': return '🖥️';
    default: return '📄';
  }
}

function useSortedNodes(nodes: readonly GraphNode[], sort: FeedSort): GraphNode[] {
  return [...nodes].sort((a, b) => {
    switch (sort) {
      case 'recent':
        return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
      case 'updated':
        return new Date(b.modifiedAt).getTime() - new Date(a.modifiedAt).getTime();
      case 'relevance':
        // Relevance sort only applies when there's a search query
        // For now, fall back to recent
        return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    }
  });
}
```

**Effort**: 3 days  
**Test**: Feed renders 500 nodes without scroll jank. Sort toggles work. Expand/collapse works.

---

### 2.3 — Unified Search (Days 10–15)

**Goal**: A single search bar that blends full-text, semantic, and graph-aware results.

```typescript
// src/shell/UI/search/SearchBar.tsx

import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { SearchResult } from '../../../pure/types/graph';

interface SearchBarProps {
  onSearch: (query: string) => Promise<SearchResult[]>;
  onResultSelect: (nodeId: string) => void;
}

export function SearchBar({ onSearch, onResultSelect }: SearchBarProps): React.ReactElement {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.trim().length < 2) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await onSearch(value);
        setResults(res);
        setIsOpen(true);
      } finally {
        setLoading(false);
      }
    }, 300); // 300ms debounce
  }, [onSearch]);

  // Keyboard shortcut: Ctrl+K / Cmd+K to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === 'Escape') {
        setIsOpen(false);
        inputRef.current?.blur();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="search-container relative w-full max-w-xl">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          placeholder="Search nodes... (Ctrl+K)"
          className="w-full px-4 py-2 pl-10 text-sm border border-gray-300 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <svg className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        {loading && (
          <div className="absolute right-3 top-2.5">
            <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full" />
          </div>
        )}
      </div>

      {/* Results dropdown */}
      {isOpen && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-96 overflow-y-auto">
          {results.map(result => (
            <button
              key={result.node.id}
              className="w-full px-4 py-3 text-left hover:bg-gray-50 border-b border-gray-100 last:border-b-0"
              onClick={() => {
                onResultSelect(result.node.id);
                setIsOpen(false);
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900">{result.node.title}</span>
                <span className="text-xs text-gray-400">{Math.round(result.score * 100)}%</span>
              </div>
              <p className="text-xs text-gray-500 mt-1 truncate">{result.node.summary}</p>
              {result.node.tags.length > 0 && (
                <div className="flex gap-1 mt-1">
                  {result.node.tags.slice(0, 3).map(tag => (
                    <span key={tag} className="px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-600">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Effort**: 3 days  
**Test**: Type query → results appear within 500ms. Click result → node selected in graph/feed.

---

### 2.4 — Filter Panel (Days 13–18)

**Goal**: Multi-dimensional filtering: type, tag, relation, time range, source, project.

```typescript
// src/pure/types/filters.ts

export interface GraphFilters {
  readonly nodeTypes: Set<string>;
  readonly tags: Set<string>;
  readonly relationTypes: Set<string>;
  readonly sourceTypes: Set<string>;
  readonly timeRange: TimeRange | null;
  readonly projects: Set<string>;
}

export interface TimeRange {
  readonly start: string;  // ISO 8601
  readonly end: string;    // ISO 8601
}

export const EMPTY_FILTERS: GraphFilters = {
  nodeTypes: new Set(),
  tags: new Set(),
  relationTypes: new Set(),
  sourceTypes: new Set(),
  timeRange: null,
  projects: new Set(),
};

/** Apply filters to determine if a node should be visible */
export function nodePassesFilters(
  node: { nodeType: string; sourceType: string; tags: readonly string[]; createdAt: string; vaultId: string },
  filters: GraphFilters,
): boolean {
  if (filters.nodeTypes.size > 0 && !filters.nodeTypes.has(node.nodeType)) return false;
  if (filters.sourceTypes.size > 0 && !filters.sourceTypes.has(node.sourceType)) return false;
  if (filters.tags.size > 0 && !node.tags.some(t => filters.tags.has(t))) return false;
  if (filters.projects.size > 0 && !filters.projects.has(node.vaultId)) return false;
  if (filters.timeRange) {
    const nodeTime = new Date(node.createdAt).getTime();
    const start = new Date(filters.timeRange.start).getTime();
    const end = new Date(filters.timeRange.end).getTime();
    if (nodeTime < start || nodeTime > end) return false;
  }
  return true;
}
```

```typescript
// src/shell/UI/filters/FilterPanel.tsx

import React, { useCallback } from 'react';
import type { GraphFilters, TimeRange } from '../../../pure/types/filters';

interface FilterPanelProps {
  filters: GraphFilters;
  onFiltersChange: (filters: GraphFilters) => void;
  availableTags: readonly string[];
  availableProjects: readonly string[];
}

export function FilterPanel({
  filters,
  onFiltersChange,
  availableTags,
  availableProjects,
}: FilterPanelProps): React.ReactElement {
  const toggleSetItem = useCallback(
    (key: keyof GraphFilters, value: string) => {
      const current = filters[key] as Set<string>;
      const next = new Set(current);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      onFiltersChange({ ...filters, [key]: next });
    },
    [filters, onFiltersChange]
  );

  const setTimeRange = useCallback(
    (range: TimeRange | null) => {
      onFiltersChange({ ...filters, timeRange: range });
    },
    [filters, onFiltersChange]
  );

  return (
    <div className="filter-panel p-4 w-64 border-r border-gray-200 overflow-y-auto">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Filters</h3>

      {/* Node Types */}
      <FilterSection title="Node Type">
        {['voice', 'agent', 'manual', 'ambient'].map(t => (
          <FilterChip
            key={t}
            label={t}
            active={filters.nodeTypes.has(t)}
            onClick={() => toggleSetItem('nodeTypes', t)}
          />
        ))}
      </FilterSection>

      {/* Source Types */}
      <FilterSection title="Source">
        {['whisper', 'screenpipe', 'mcp', 'editor'].map(s => (
          <FilterChip
            key={s}
            label={s}
            active={filters.sourceTypes.has(s)}
            onClick={() => toggleSetItem('sourceTypes', s)}
          />
        ))}
      </FilterSection>

      {/* Tags */}
      <FilterSection title="Tags">
        {availableTags.slice(0, 20).map(tag => (
          <FilterChip
            key={tag}
            label={tag}
            active={filters.tags.has(tag)}
            onClick={() => toggleSetItem('tags', tag)}
          />
        ))}
      </FilterSection>

      {/* Relation Types */}
      <FilterSection title="Relations">
        {['references', 'depends_on', 'extends', 'contradicts', 'child_of'].map(r => (
          <FilterChip
            key={r}
            label={r.replace('_', ' ')}
            active={filters.relationTypes.has(r)}
            onClick={() => toggleSetItem('relationTypes', r)}
          />
        ))}
      </FilterSection>

      {/* Time Range */}
      <FilterSection title="Time Range">
        {[
          { label: 'Today', days: 1 },
          { label: 'This week', days: 7 },
          { label: 'This month', days: 30 },
          { label: 'All time', days: 0 },
        ].map(({ label, days }) => (
          <button
            key={label}
            className={`block w-full text-left px-2 py-1 text-sm rounded ${
              isTimeRangeActive(filters.timeRange, days) ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'
            }`}
            onClick={() => {
              if (days === 0) setTimeRange(null);
              else {
                const end = new Date().toISOString();
                const start = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
                setTimeRange({ start, end });
              }
            }}
          >
            {label}
          </button>
        ))}
      </FilterSection>

      {/* Projects */}
      {availableProjects.length > 1 && (
        <FilterSection title="Projects">
          {availableProjects.map(p => (
            <FilterChip
              key={p}
              label={p.split(/[/\\]/).pop() ?? p}
              active={filters.projects.has(p)}
              onClick={() => toggleSetItem('projects', p)}
            />
          ))}
        </FilterSection>
      )}

      {/* Clear all */}
      <button
        className="mt-4 w-full text-sm text-red-600 hover:text-red-700"
        onClick={() => onFiltersChange({
          nodeTypes: new Set(),
          tags: new Set(),
          relationTypes: new Set(),
          sourceTypes: new Set(),
          timeRange: null,
          projects: new Set(),
        })}
      >
        Clear all filters
      </button>
    </div>
  );
}

function FilterSection({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="mb-4">
      <h4 className="text-xs font-medium text-gray-400 mb-2">{title}</h4>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }): React.ReactElement {
  return (
    <button
      className={`px-2 py-1 text-xs rounded-full border transition-colors ${
        active
          ? 'bg-blue-100 text-blue-700 border-blue-300'
          : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function isTimeRangeActive(range: TimeRange | null, days: number): boolean {
  if (days === 0) return range === null;
  if (!range) return false;
  const diff = new Date(range.end).getTime() - new Date(range.start).getTime();
  const expected = days * 24 * 60 * 60 * 1000;
  return Math.abs(diff - expected) < 60000; // 1 minute tolerance
}
```

**Effort**: 4 days  
**Test**: Apply type filter → only matching nodes visible. Apply tag filter → intersects correctly. Clear → all nodes visible.

---

### 2.5 — Node Editor Improvements (Days 16–20)

**Goal**: Better markdown editing with inline tag management and relation display.

Key improvements over v1:
- Tag editor (add/remove tags inline)
- Relation inspector (show all typed edges for the selected node)
- Metadata display (source, created, modified, agent)
- Auto-save on blur
- Keyboard shortcuts (Ctrl+S save, Ctrl+B bold, etc.)

```typescript
// src/shell/UI/editor/NodeEditor.tsx

import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { GraphNode, GraphEdge } from '../../../pure/types/graph';

interface NodeEditorProps {
  node: GraphNode;
  edges: readonly GraphEdge[];
  onSave: (nodeId: string, updates: { content: string; tags: string[] }) => Promise<void>;
  onClose: () => void;
}

export function NodeEditor({ node, edges, onSave, onClose }: NodeEditorProps): React.ReactElement {
  const [content, setContent] = useState(node.content);
  const [tags, setTags] = useState<string[]>([...node.tags]);
  const [newTag, setNewTag] = useState('');
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-save on blur
  const handleBlur = useCallback(async () => {
    if (content !== node.content || JSON.stringify(tags) !== JSON.stringify(node.tags)) {
      setSaving(true);
      await onSave(node.id, { content, tags });
      setSaving(false);
    }
  }, [content, tags, node, onSave]);

  const addTag = useCallback(() => {
    const tag = newTag.trim().toLowerCase();
    if (tag && !tags.includes(tag)) {
      setTags([...tags, tag]);
      setNewTag('');
    }
  }, [newTag, tags]);

  const removeTag = useCallback((tag: string) => {
    setTags(tags.filter(t => t !== tag));
  }, [tags]);

  // Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleBlur();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleBlur]);

  const incomingEdges = edges.filter(e => e.toNodeId === node.id);
  const outgoingEdges = edges.filter(e => e.fromNodeId === node.id);

  return (
    <div className="node-editor flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">{node.title}</h2>
        <div className="flex items-center gap-2">
          {saving && <span className="text-xs text-gray-400">Saving...</span>}
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
      </div>

      {/* Metadata */}
      <div className="px-3 py-2 bg-gray-50 text-xs text-gray-500 flex gap-4">
        <span>Type: {node.nodeType}</span>
        <span>Source: {node.sourceType}</span>
        <span>Created: {new Date(node.createdAt).toLocaleDateString()}</span>
      </div>

      {/* Tags */}
      <div className="px-3 py-2 border-b border-gray-100">
        <div className="flex flex-wrap gap-1 items-center">
          {tags.map(tag => (
            <span key={tag} className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 flex items-center gap-1">
              {tag}
              <button onClick={() => removeTag(tag)} className="text-blue-400 hover:text-blue-600">×</button>
            </span>
          ))}
          <input
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addTag()}
            placeholder="Add tag..."
            className="px-2 py-0.5 text-xs border-none outline-none bg-transparent w-20"
          />
        </div>
      </div>

      {/* Content editor */}
      <textarea
        ref={textareaRef}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onBlur={handleBlur}
        className="flex-1 p-4 text-sm font-mono resize-none outline-none"
        spellCheck={false}
      />

      {/* Relations inspector */}
      {(incomingEdges.length > 0 || outgoingEdges.length > 0) && (
        <div className="border-t border-gray-200 p-3 max-h-40 overflow-y-auto">
          <h4 className="text-xs font-semibold text-gray-400 uppercase mb-2">Relations</h4>
          {outgoingEdges.map(edge => (
            <div key={edge.id} className="text-xs text-gray-600 py-0.5">
              → <span className="text-blue-600">{edge.relationType}</span> → {edge.toNodeId.slice(0, 8)}...
            </div>
          ))}
          {incomingEdges.map(edge => (
            <div key={edge.id} className="text-xs text-gray-600 py-0.5">
              ← <span className="text-green-600">{edge.relationType}</span> ← {edge.fromNodeId.slice(0, 8)}...
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Effort**: 4 days  
**Test**: Edit content → auto-saves. Add/remove tags → persisted to FalkorDB. Relations displayed correctly.

---

## Testing Strategy

| Test Type | Scope | Tool |
|-----------|-------|------|
| Unit tests | Filter logic (`nodePassesFilters`), sort logic, color/size mapping | Vitest |
| Component tests | FeedView, SearchBar, FilterPanel, NodeEditor render correctly | Vitest + @testing-library/react |
| Visual regression | Sigma.js renders expected graph shapes | Playwright screenshot comparison |
| Performance | 5,000 node graph renders at 60fps | Playwright + performance.now() measurements |
| Accessibility | Keyboard navigation, screen reader labels | axe-core |

---

## Definition of Done

- [ ] Sigma.js renders graph with correct colors, sizes, labels, and edge types
- [ ] ForceAtlas2 layout produces readable graph structure
- [ ] Semantic zoom: labels hidden when zoomed out, visible when zoomed in
- [ ] Focus mode: clicking a node dims unrelated nodes
- [ ] Feed view shows nodes in chronological order with expand/collapse
- [ ] Search returns results within 500ms with score display
- [ ] Search supports keyboard shortcut (Ctrl+K)
- [ ] Filter panel allows filtering by type, tag, relation, time, source, project
- [ ] Filters apply to both graph view and feed view
- [ ] Node editor supports content editing, tag management, and auto-save
- [ ] Relation inspector shows all typed edges for selected node
- [ ] 5,000 nodes render at 60fps in graph view
- [ ] All components have unit/component tests

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Sigma.js learning curve | Delayed delivery | Budget 2 extra days. Start with minimal config, add features incrementally |
| ForceAtlas2 layout quality for sparse graphs | Poor visual layout | Fall back to circular layout for < 20 nodes. Add manual position locking |
| Large graph data transfer (IPC) | UI freezes | Stream nodes in batches. Use Web Workers for layout computation |
| Filter combinatorics complexity | Edge case bugs | Keep filter logic pure (testable). Default to AND logic for multi-dimensional filters |
| Cytoscape → Sigma migration breaks existing features | Functionality regression | Run both renderers in parallel during Phase 2. Remove Cytoscape only after Phase 2 complete |
