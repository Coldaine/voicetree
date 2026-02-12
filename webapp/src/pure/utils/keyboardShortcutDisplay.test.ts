import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { isMacPlatform, getModifierSymbol, formatShortcut, getSpecialKeySymbol } from './keyboardShortcutDisplay';

describe('keyboardShortcutDisplay', () => {
    // Store original values to restore after tests
    let originalNavigator: Navigator | undefined;
    let originalProcess: NodeJS.Process | undefined;

    beforeEach(() => {
        // Save original values
        if (typeof navigator !== 'undefined') {
            originalNavigator = navigator;
        }
        if (typeof process !== 'undefined') {
            originalProcess = process;
        }
    });

    afterEach(() => {
        // Restore original values
        if (originalNavigator !== undefined) {
            Object.defineProperty(globalThis, 'navigator', {
                value: originalNavigator,
                writable: true,
                configurable: true
            });
        }
        if (originalProcess !== undefined) {
            Object.defineProperty(globalThis, 'process', {
                value: originalProcess,
                writable: true,
                configurable: true
            });
        }
    });

    describe('isMacPlatform', () => {
        it('should detect macOS via modern userAgentData API', () => {
            // Mock navigator with userAgentData
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(true);
        });

        it('should detect non-macOS via modern userAgentData API', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(false);
        });

        it('should fall back to navigator.platform when userAgentData is not available', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    platform: 'MacIntel'
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(true);
        });

        it('should detect Windows via navigator.platform fallback', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    platform: 'Win32'
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(false);
        });

        it('should handle case-insensitive platform detection', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    platform: 'MACINTEL'
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(true);
        });

        it('should return false when navigator.platform is not a string', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    platform: null
                },
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(false);
        });

        it('should return false when navigator is undefined', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: undefined,
                writable: true,
                configurable: true
            });

            expect(isMacPlatform()).toBe(false);
        });
    });

    describe('getModifierSymbol', () => {
        it('should return ⌘ for macOS', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getModifierSymbol()).toBe('⌘');
        });

        it('should return Ctrl for Windows', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getModifierSymbol()).toBe('Ctrl');
        });

        it('should return Ctrl for Linux', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    platform: 'Linux x86_64'
                },
                writable: true,
                configurable: true
            });

            expect(getModifierSymbol()).toBe('Ctrl');
        });
    });

    describe('getSpecialKeySymbol', () => {
        it('should return macOS backspace symbol on Mac', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Backspace')).toBe('⌫');
            expect(getSpecialKeySymbol('backspace')).toBe('⌫');
        });

        it('should return Backspace text on Windows', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Backspace')).toBe('Backspace');
        });

        it('should return macOS enter symbol on Mac', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Enter')).toBe('⏎');
            expect(getSpecialKeySymbol('return')).toBe('⏎');
        });

        it('should return Enter text on Windows', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Enter')).toBe('Enter');
        });

        it('should return macOS option symbol on Mac', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Option')).toBe('⌥');
            expect(getSpecialKeySymbol('alt')).toBe('⌥');
        });

        it('should return Alt text on Windows', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('Option')).toBe('Alt');
            expect(getSpecialKeySymbol('Alt')).toBe('Alt');
        });

        it('should return the key unchanged for non-special keys', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(getSpecialKeySymbol('N')).toBe('N');
            expect(getSpecialKeySymbol('[')).toBe('[');
            expect(getSpecialKeySymbol('1')).toBe('1');
        });
    });

    describe('formatShortcut', () => {
        it('should format Mac shortcut without separator', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('N')).toBe('⌘N');
            expect(formatShortcut('[')).toBe('⌘[');
            expect(formatShortcut('1')).toBe('⌘1');
        });

        it('should format Windows shortcut with + separator', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('N')).toBe('Ctrl+N');
            expect(formatShortcut('[')).toBe('Ctrl+[');
            expect(formatShortcut('1')).toBe('Ctrl+1');
        });

        it('should format special keys on Mac', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('Backspace')).toBe('⌘⌫');
            expect(formatShortcut('Enter')).toBe('⌘⏎');
            expect(formatShortcut('Option')).toBe('⌘⌥');
        });

        it('should format special keys on Windows', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'Windows'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('Backspace')).toBe('Ctrl+Backspace');
            expect(formatShortcut('Enter')).toBe('Ctrl+Enter');
            expect(formatShortcut('Alt')).toBe('Ctrl+Alt');
        });

        it('should return only the key when modifier is false', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('N', false)).toBe('N');
            expect(formatShortcut('Backspace', false)).toBe('⌫');
        });

        it('should handle case-insensitive special keys', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('ENTER')).toBe('⌘⏎');
            expect(formatShortcut('backspace')).toBe('⌘⌫');
        });

        it('should handle return as an alias for enter', () => {
            Object.defineProperty(globalThis, 'navigator', {
                value: {
                    userAgentData: {
                        platform: 'macOS'
                    }
                },
                writable: true,
                configurable: true
            });

            expect(formatShortcut('return')).toBe('⌘⏎');
            expect(formatShortcut('Return')).toBe('⌘⏎');
        });
    });
});
