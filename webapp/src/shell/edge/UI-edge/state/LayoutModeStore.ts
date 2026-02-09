/**
 * LayoutModeStore - Manages graph layout mode state
 *
 * Tracks the current layout mode (force-directed vs hierarchical)
 * and provides position save/restore for smooth toggling between modes.
 *
 * When switching to a hierarchical mode, the current (manually-arranged)
 * positions are saved. When switching back to force-directed, they are restored
 * so users don't lose their spatial arrangement.
 */

export type LayoutMode = 'force-directed' | 'hierarchical-TB' | 'hierarchical-LR';

interface SavedPosition {
    readonly x: number;
    readonly y: number;
}

/** Ordered list of modes for cycling */
const MODE_CYCLE: readonly LayoutMode[] = ['force-directed', 'hierarchical-TB', 'hierarchical-LR'] as const;

/** Human-readable labels for each mode */
export const LAYOUT_MODE_LABELS: Record<LayoutMode, string> = {
    'force-directed': 'Force-Directed',
    'hierarchical-TB': 'Hierarchical (Top-Down)',
    'hierarchical-LR': 'Hierarchical (Left-Right)',
};

// --- Module state ---
let currentMode: LayoutMode = 'force-directed';
let savedPositions: Map<string, SavedPosition> = new Map();
const listeners: Set<(mode: LayoutMode) => void> = new Set();

// --- Public API ---

export function getLayoutMode(): LayoutMode {
    return currentMode;
}

/**
 * Cycle to the next layout mode: force-directed → TB → LR → force-directed
 * Returns the new mode.
 */
export function cycleLayoutMode(): LayoutMode {
    const currentIndex = MODE_CYCLE.indexOf(currentMode);
    const nextIndex = (currentIndex + 1) % MODE_CYCLE.length;
    setLayoutMode(MODE_CYCLE[nextIndex]);
    return currentMode;
}

export function setLayoutMode(mode: LayoutMode): void {
    if (mode === currentMode) return;
    currentMode = mode;
    notifyListeners();
}

/**
 * Subscribe to layout mode changes.
 * Returns an unsubscribe function.
 */
export function onLayoutModeChange(callback: (mode: LayoutMode) => void): () => void {
    listeners.add(callback);
    return () => { listeners.delete(callback); };
}

/**
 * Save current node positions from Cytoscape (call before switching to hierarchical).
 * Only saves if we don't already have saved positions (i.e., we're coming from force-directed).
 */
export function savePositionsFromCy(cy: { nodes: () => Array<{ id: () => string; position: () => { x: number; y: number } }> }): void {
    if (savedPositions.size > 0) return; // Already saved
    savedPositions = new Map();
    for (const node of cy.nodes()) {
        const pos = node.position();
        savedPositions.set(node.id(), { x: pos.x, y: pos.y });
    }
}

/**
 * Restore previously saved positions to Cytoscape nodes (call when switching back to force-directed).
 * Clears saved positions after restoring.
 */
export function restorePositionsToCy(cy: { getElementById: (id: string) => { position: (pos: { x: number; y: number }) => void; length: number } }): void {
    for (const [id, pos] of savedPositions.entries()) {
        const node = cy.getElementById(id);
        if (node.length > 0) {
            node.position({ x: pos.x, y: pos.y });
        }
    }
    savedPositions = new Map();
}

export function hasSavedPositions(): boolean {
    return savedPositions.size > 0;
}

/** Reset all state to defaults. For testing only. */
export function _resetForTesting(): void {
    currentMode = 'force-directed';
    savedPositions = new Map();
    listeners.clear();
}

function notifyListeners(): void {
    for (const listener of listeners) {
        listener(currentMode);
    }
}
