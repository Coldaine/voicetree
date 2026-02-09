import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
    getLayoutMode,
    setLayoutMode,
    cycleLayoutMode,
    onLayoutModeChange,
    savePositionsFromCy,
    restorePositionsToCy,
    hasSavedPositions,
    LAYOUT_MODE_LABELS,
    _resetForTesting
} from './LayoutModeStore';

describe('LayoutModeStore', () => {
    beforeEach(() => {
        _resetForTesting();
    });

    describe('getLayoutMode / setLayoutMode', () => {
        it('defaults to force-directed', () => {
            expect(getLayoutMode()).toBe('force-directed');
        });

        it('sets mode', () => {
            setLayoutMode('hierarchical-TB');
            expect(getLayoutMode()).toBe('hierarchical-TB');
        });

        it('no-ops when setting same mode', () => {
            const listener = vi.fn();
            onLayoutModeChange(listener);

            setLayoutMode('force-directed'); // same as default
            expect(listener).not.toHaveBeenCalled();
        });
    });

    describe('cycleLayoutMode', () => {
        it('cycles force-directed → TB → LR → force-directed', () => {
            expect(getLayoutMode()).toBe('force-directed');

            const result1 = cycleLayoutMode();
            expect(result1).toBe('hierarchical-TB');
            expect(getLayoutMode()).toBe('hierarchical-TB');

            const result2 = cycleLayoutMode();
            expect(result2).toBe('hierarchical-LR');
            expect(getLayoutMode()).toBe('hierarchical-LR');

            const result3 = cycleLayoutMode();
            expect(result3).toBe('force-directed');
            expect(getLayoutMode()).toBe('force-directed');
        });
    });

    describe('onLayoutModeChange', () => {
        it('notifies listeners on mode change', () => {
            const listener = vi.fn();
            onLayoutModeChange(listener);

            setLayoutMode('hierarchical-LR');
            expect(listener).toHaveBeenCalledWith('hierarchical-LR');
            expect(listener).toHaveBeenCalledTimes(1);
        });

        it('unsubscribes correctly', () => {
            const listener = vi.fn();
            const unsubscribe = onLayoutModeChange(listener);

            unsubscribe();
            setLayoutMode('hierarchical-TB');
            expect(listener).not.toHaveBeenCalled();
        });

        it('supports multiple listeners', () => {
            const listener1 = vi.fn();
            const listener2 = vi.fn();
            onLayoutModeChange(listener1);
            onLayoutModeChange(listener2);

            setLayoutMode('hierarchical-TB');
            expect(listener1).toHaveBeenCalledWith('hierarchical-TB');
            expect(listener2).toHaveBeenCalledWith('hierarchical-TB');
        });
    });

    describe('position save/restore', () => {
        function createMockCy(nodes: Array<{ id: string; x: number; y: number }>) {
            const nodeMap = new Map(nodes.map(n => [n.id, { x: n.x, y: n.y }]));
            return {
                nodes: () => nodes.map(n => ({
                    id: () => n.id,
                    position: () => ({ x: n.x, y: n.y }),
                })),
                getElementById: (id: string) => {
                    const pos = nodeMap.get(id);
                    return {
                        length: pos ? 1 : 0,
                        position: (newPos: { x: number; y: number }) => {
                            if (pos) {
                                nodeMap.set(id, newPos);
                            }
                        },
                    };
                },
                getPositions: () => Object.fromEntries(nodeMap),
            };
        }

        it('starts with no saved positions', () => {
            expect(hasSavedPositions()).toBe(false);
        });

        it('saves and restores positions', () => {
            const cy = createMockCy([
                { id: 'a', x: 100, y: 200 },
                { id: 'b', x: 300, y: 400 },
            ]);

            savePositionsFromCy(cy);
            expect(hasSavedPositions()).toBe(true);

            // Simulate positions changed by hierarchical layout
            restorePositionsToCy(cy);
            expect(hasSavedPositions()).toBe(false);

            // Verify positions were restored to the getElementById mock
            const posA = cy.getPositions();
            expect(posA.a).toEqual({ x: 100, y: 200 });
            expect(posA.b).toEqual({ x: 300, y: 400 });
        });

        it('does not overwrite saved positions if already saved', () => {
            const cy1 = createMockCy([{ id: 'a', x: 10, y: 20 }]);
            const cy2 = createMockCy([{ id: 'a', x: 999, y: 999 }]);

            savePositionsFromCy(cy1);
            savePositionsFromCy(cy2); // should be ignored

            const restoreCy = createMockCy([{ id: 'a', x: 0, y: 0 }]);
            restorePositionsToCy(restoreCy);

            const positions = restoreCy.getPositions();
            expect(positions.a).toEqual({ x: 10, y: 20 }); // original, not overwritten
        });

        it('handles missing nodes gracefully during restore', () => {
            const saveCy = createMockCy([
                { id: 'a', x: 100, y: 200 },
                { id: 'b', x: 300, y: 400 },
            ]);
            savePositionsFromCy(saveCy);

            // Restore to a cy that only has node 'a' (node 'b' was removed)
            const restoreCy = createMockCy([{ id: 'a', x: 0, y: 0 }]);
            restorePositionsToCy(restoreCy); // should not throw

            const positions = restoreCy.getPositions();
            expect(positions.a).toEqual({ x: 100, y: 200 });
        });
    });

    describe('LAYOUT_MODE_LABELS', () => {
        it('has labels for all modes', () => {
            expect(LAYOUT_MODE_LABELS['force-directed']).toBe('Force-Directed');
            expect(LAYOUT_MODE_LABELS['hierarchical-TB']).toBe('Hierarchical (Top-Down)');
            expect(LAYOUT_MODE_LABELS['hierarchical-LR']).toBe('Hierarchical (Left-Right)');
        });
    });
});
