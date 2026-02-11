/**
 * Auto Layout: Automatically run layout on graph changes
 *
 * Supports two layout engines:
 * - Cola (force-directed): Physics-based organic layout (default)
 * - Dagre (hierarchical): DAG/tree layout in top-down or left-right direction
 *
 * Layout mode is controlled by LayoutModeStore. When switching modes:
 * - Switching TO hierarchical: saves current positions, runs Dagre
 * - Switching BACK to force-directed: restores saved positions (no Cola re-run)
 *
 * NOTE (commit 033c57a4): We tried a two-phase layout algorithm that ran Phase 1 with only
 * constraint iterations (no unconstrained) for fast global stabilization, then Phase 2 ran
 * full iterations on just the neighborhood of most-displaced nodes. We tried this algo, and
 * that it was okay, but went on for too long since it doubled the animation period, and the
 * second phase could still be quite janky which was what we were trying to avoid.
 */

import type {Core, EdgeSingular, NodeDefinition} from 'cytoscape';
import ColaLayout from './cola';
import { DEFAULT_EDGE_LENGTH} from './cytoscape-graph-constants';
// Import to make Window.electronAPI type available
import type {} from '@/shell/electron';
import { consumePendingPan } from '@/shell/edge/UI-edge/state/PendingPanStore';
import {
  getLayoutMode,
  onLayoutModeChange,
  savePositionsFromCy,
  restorePositionsToCy,
  hasSavedPositions,
  type LayoutMode
} from '@/shell/edge/UI-edge/state/LayoutModeStore';

// Registry for layout triggers - allows external code to trigger layout via triggerLayout(cy)
const layoutTriggers: Map<Core, () => void> = new Map<Core, () => void>();

/**
 * Trigger a debounced layout run for the given cytoscape instance.
 * Use this for user-initiated resize events (expand button, CSS drag resize).
 */
export function triggerLayout(cy: Core): void {
  layoutTriggers.get(cy)?.();
}

export interface AutoLayoutOptions {
  animate?: boolean;
  maxSimulationTime?: number;
  avoidOverlap?: boolean;
  nodeSpacing?: number;
  handleDisconnected?: boolean;
  convergenceThreshold?: number;
  unconstrIter?: number;
  userConstIter?: number;
  allConstIter?: number;
  // Edge length options - different methods of specifying edge length
  edgeLength?: number | ((edge: EdgeSingular) => number);
  edgeSymDiffLength?: number | ((edge: EdgeSingular) => number);
  edgeJaccardLength?: number | ((edge: EdgeSingular) => number);
}

const DEFAULT_OPTIONS: AutoLayoutOptions = {
  animate: true,
  maxSimulationTime: 2000,
  avoidOverlap: true,
  nodeSpacing: 70,
  handleDisconnected: true, // handles disconnected components
  convergenceThreshold: 0.4,
  unconstrIter: 15, // TODO SOMETHINIG ABOUT THIS IS VERY IMPORTANT LAYOUT BREAK WITHOUT
  userConstIter: 15,
  allConstIter: 25,
  edgeLength: (_edge: EdgeSingular) => {
    return DEFAULT_EDGE_LENGTH;
  },
  // edgeSymDiffLength: undefined,
  // edgeJaccardLength: undefined
};

/**
 * Get the Cytoscape elements to lay out, excluding context nodes and their edges.
 */
function getLayoutElements(cy: Core) {
  return cy.elements().filter(ele => {
    if (ele.isNode()) return !ele.data('isContextNode');
    // Exclude edges connected to context nodes
    return !ele.source().data('isContextNode') && !ele.target().data('isContextNode');
  });
}

/**
 * Run the Cola (force-directed) layout.
 */
function runColaLayout(
  cy: Core,
  colaOptions: AutoLayoutOptions,
  onComplete: () => void
): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layout: any = new (ColaLayout as any)({
    cy: cy,
    eles: getLayoutElements(cy),
    animate: colaOptions.animate,
    randomize: false, // Don't randomize - preserve existing positions
    avoidOverlap: colaOptions.avoidOverlap,
    handleDisconnected: colaOptions.handleDisconnected,
    convergenceThreshold: colaOptions.convergenceThreshold,
    maxSimulationTime: colaOptions.maxSimulationTime,
    unconstrIter: colaOptions.unconstrIter,
    userConstIter: colaOptions.userConstIter,
    allConstIter: colaOptions.allConstIter,
    nodeSpacing: colaOptions.nodeSpacing,
    edgeLength: colaOptions.edgeLength,
    edgeSymDiffLength: colaOptions.edgeSymDiffLength,
    edgeJaccardLength: colaOptions.edgeJaccardLength,
    centerGraph: false,
    fit: false,
    nodeDimensionsIncludeLabels: true,
  });

  layout.one('layoutstop', onComplete);
  layout.run();
}

/**
 * Run the Dagre (hierarchical) layout.
 * Direction is determined by the current layout mode (TB or LR).
 */
function runDagreLayout(
  cy: Core,
  mode: LayoutMode,
  onComplete: () => void
): void {
  const rankDir = mode === 'hierarchical-LR' ? 'LR' : 'TB';

  const layout = getLayoutElements(cy).layout({
    name: 'dagre',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rankDir: rankDir as any,
    nodeSep: 80,
    rankSep: 120,
    edgeSep: 40,
    animate: true,
    animationDuration: 500,
    animationEasing: 'ease-in-out-cubic',
    fit: false,
    padding: 50,
    spacingFactor: 1.2,
    nodeDimensionsIncludeLabels: true,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);

  layout.one('layoutstop', onComplete);
  layout.run();
}

/**
 * Enable automatic layout on graph changes.
 *
 * Listens to node/edge add/remove events and triggers the appropriate layout
 * engine (Cola for force-directed, Dagre for hierarchical) based on LayoutModeStore.
 *
 * @param cy Cytoscape instance
 * @param options Layout options (currently applied to Cola only; Dagre uses its own defaults)
 * @returns Cleanup function to disable auto-layout and unsubscribe from LayoutModeStore
 */
export function enableAutoLayout(cy: Core, options: AutoLayoutOptions = {}): () => void {
  const colaOptions = { ...DEFAULT_OPTIONS, ...options };

  let layoutRunning: boolean = false;
  let layoutQueued: boolean = false;

  const onLayoutComplete: () => void = () => {
    // Only persist positions to disk in force-directed mode.
    // Hierarchical positions are algorithmic and temporary — persisting them
    // would overwrite the user's manual arrangement.
    if (getLayoutMode() === 'force-directed') {
      window.electronAPI?.main.saveNodePositions(cy.nodes().jsons() as NodeDefinition[])
        .catch((error: unknown) => {
          console.error('[AutoLayout] Failed to save node positions:', error);
        });
    }
    layoutRunning = false;

    // Execute any pending pan after layout completes (instead of arbitrary timeout)
    // This ensures viewport fits to new nodes only after their positions are finalized
    consumePendingPan(cy);

    // If another layout was queued, run it now
    if (layoutQueued) {
      layoutQueued = false;
      runLayout();
    }
  };

  const runLayout: () => void = () => {
    // If layout already running, queue another run for after it completes
    if (layoutRunning) {
      layoutQueued = true;
      return;
    }

    // Skip if no nodes
    if (cy.nodes().length === 0) {
      return;
    }

    layoutRunning = true;

    const mode = getLayoutMode();

    if (mode === 'force-directed') {
      runColaLayout(cy, colaOptions, onLayoutComplete);
    } else {
      runDagreLayout(cy, mode, onLayoutComplete);
    }
  };

  // Debounce helper to avoid rapid-fire layouts
  // Set to 300ms to prevent flickering during markdown editing (editor autosave is 100ms)
  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;
  const debouncedRunLayout: () => void = () => {
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
    debounceTimeout = setTimeout(() => {
      runLayout();
      debounceTimeout = null;
    }, 300); // 300ms debounce - prevents flickering during markdown typing
  };

  // Listen to graph modification events
  cy.on('add', 'node', debouncedRunLayout);
  cy.on('remove', 'node', debouncedRunLayout);
  cy.on('add', 'edge', debouncedRunLayout);
  cy.on('remove', 'edge', debouncedRunLayout);

  // NOTE: We intentionally do NOT listen to 'floatingwindow:resize' here.
  // That event fires on zoom-induced dimension changes (not just user resize),
  // which would cause unnecessary full layout recalculations during zoom/pan.
  // Shadow node dimensions still update correctly without triggering layout.
  // User-initiated resizes (expand button, CSS drag) call triggerLayout() directly.

  // Register trigger for external callers (user-initiated resize)
  layoutTriggers.set(cy, debouncedRunLayout);

  // Subscribe to layout mode changes from LayoutModeStore
  const unsubscribeMode = onLayoutModeChange((newMode: LayoutMode) => {
    if (newMode === 'force-directed') {
      // Switching back to force-directed: restore saved positions.
      // Do NOT re-run Cola — the restored positions are the user's manual arrangement.
      if (hasSavedPositions()) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        restorePositionsToCy(cy as any);
      }
      // No runLayout() — positions are already where the user left them
    } else {
      // Switching to hierarchical: save current positions first (only if coming from force-directed)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      savePositionsFromCy(cy as any);
      // Run Dagre immediately
      runLayout();
    }
  });

  // Return cleanup function
  return () => {
    cy.off('add', 'node', debouncedRunLayout);
    cy.off('remove', 'node', debouncedRunLayout);
    cy.off('add', 'edge', debouncedRunLayout);
    cy.off('remove', 'edge', debouncedRunLayout);
    layoutTriggers.delete(cy);
    unsubscribeMode();

    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };
}
