import type { SSEEvent } from '@/shell/UI/sse-status-panel/sse-status-panel';

const SSE_EVENT_TYPES: readonly string[] = [
    'phase_started', 'phase_complete',
    'action_applied', 'agent_error',
    'rate_limit_error', 'workflow_complete', 'workflow_failed'
] as const;

/**
 * Creates an SSE connection to the backend's /stream-progress endpoint.
 * Reconnects automatically with exponential backoff on connection loss.
 * Returns a disconnect function for cleanup.
 */
export function createSSEConnection(backendPort: number, onEvent: (event: SSEEvent) => void): () => void {
    const url: string = `http://localhost:${backendPort}/stream-progress`;
    let eventSource: EventSource | null = null;
    let hasConnectedOnce: boolean = false;
    let reconnectAttempts: number = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped: boolean = false;

    const MAX_RECONNECT_DELAY_MS: number = 30000;
    const BASE_RECONNECT_DELAY_MS: number = 1000;

    function connect(): void {
        if (stopped) return;

        eventSource = new EventSource(url);

        SSE_EVENT_TYPES.forEach(type => {
            eventSource!.addEventListener(type, (e: MessageEvent) => {
                const data: Record<string, unknown> = JSON.parse(e.data) as Record<string, unknown>;
                onEvent({ type, data, timestamp: Date.now() });
            });
        });

        eventSource.onerror = () => {
            const eventType: string = hasConnectedOnce ? 'connection_error' : 'connection_loading';
            onEvent({
                type: eventType,
                data: { message: hasConnectedOnce ? 'SSE connection lost' : 'Connecting to server' },
                timestamp: Date.now()
            });

            // Auto-reconnect with exponential backoff
            if (!stopped && eventSource) {
                eventSource.close();
                eventSource = null;
                const delay: number = Math.min(
                    BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts),
                    MAX_RECONNECT_DELAY_MS
                );
                reconnectAttempts++;
                reconnectTimer = setTimeout(connect, delay);
            }
        };

        eventSource.onopen = () => {
            hasConnectedOnce = true;
            reconnectAttempts = 0;
            onEvent({
                type: 'connection_open',
                data: { message: 'Connected to backend', port: backendPort },
                timestamp: Date.now()
            });
        };
    }

    connect();

    return () => {
        stopped = true;
        if (reconnectTimer !== null) {
            clearTimeout(reconnectTimer);
        }
        if (eventSource) {
            eventSource.close();
        }
    };
}
