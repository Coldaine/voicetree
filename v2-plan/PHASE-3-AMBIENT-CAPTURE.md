# Phase 3 — Ambient Capture: Daemon Mode + ScreenPipe Integration

> **Duration**: Weeks 13–16  
> **Effort**: ~140 hours  
> **Depends on**: Phase 1 (ingestion pipeline), Phase 2 (UI for reviewing captures)  
> **Enables**: Phase 4 (performance optimization for high-throughput ambient data)

---

## Goals

1. **System tray / daemon mode** — VoiceTree runs in the background without a visible window
2. **Auto-start on login** — VoiceTree starts when the user logs in
3. **ScreenPipe integration** — ingest OCR, active window, audio context via ScreenPipe REST API
4. **Background ingestion** — ambient events flow into FalkorDB without blocking the UI
5. **Context-aware routing** — automatically associate captures with the correct project based on active window/path

---

## Prerequisites

- Phase 1 complete: ingestion pipeline processes events into FalkorDB
- Phase 2 complete: UI can display and filter ambient nodes
- ScreenPipe installed (optional — VoiceTree works without it)

---

## Task Breakdown

### 3.1 — System Tray + Daemon Mode (Days 1–5)

**Goal**: VoiceTree runs as a system tray application. Main window opens/closes on demand.

```typescript
// src/shell/edge/main/tray/system-tray.ts

import { Tray, Menu, nativeImage, BrowserWindow, app } from 'electron';
import path from 'path';

let tray: Tray | null = null;
let mainWindow: BrowserWindow | null = null;

interface TrayState {
  isCapturing: boolean;
  nodeCount: number;
  lastCaptureTime: string | null;
}

const state: TrayState = {
  isCapturing: false,
  nodeCount: 0,
  lastCaptureTime: null,
};

export function createSystemTray(window: BrowserWindow): Tray {
  mainWindow = window;

  const iconPath = path.join(__dirname, '../assets/tray-icon.png');
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  tray = new Tray(icon);

  tray.setToolTip('VoiceTree');
  updateTrayMenu();

  // Click to show/hide window
  tray.on('click', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow?.show();
      mainWindow?.focus();
    }
  });

  // Hide window instead of closing (stay in tray)
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  return tray;
}

function updateTrayMenu(): void {
  if (!tray) return;

  const contextMenu = Menu.buildFromTemplate([
    {
      label: `VoiceTree — ${state.nodeCount} nodes`,
      enabled: false,
    },
    { type: 'separator' },
    {
      label: state.isCapturing ? '⏸ Pause Capture' : '▶ Resume Capture',
      click: () => {
        state.isCapturing = !state.isCapturing;
        updateTrayMenu();
        // Emit event to toggle ScreenPipe polling
      },
    },
    {
      label: 'Show Window',
      click: () => {
        mainWindow?.show();
        mainWindow?.focus();
      },
    },
    {
      label: 'Quick Capture...',
      accelerator: 'CmdOrCtrl+Shift+V',
      click: () => {
        // Open mini capture window
        openQuickCapture();
      },
    },
    { type: 'separator' },
    {
      label: 'Settings',
      click: () => {
        mainWindow?.show();
        mainWindow?.webContents.send('navigate', '/settings');
      },
    },
    {
      label: 'Quit VoiceTree',
      click: () => {
        (app as { isQuitting?: boolean }).isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
}

export function updateTrayState(updates: Partial<TrayState>): void {
  Object.assign(state, updates);
  updateTrayMenu();
}

function openQuickCapture(): void {
  const quickWindow = new BrowserWindow({
    width: 400,
    height: 200,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, '../preload.js'),
    },
  });
  
  quickWindow.loadURL('app://./quick-capture.html');
}
```

**Effort**: 3 days  
**Risk**: Platform differences (Windows tray vs macOS menu bar) → test on both  
**Test**: App minimizes to tray. Right-click shows menu. Click toggles window. Quit actually quits.

---

### 3.2 — Auto-Start on Login (Days 4–6)

**Goal**: VoiceTree starts automatically when the user logs in.

```typescript
// src/shell/edge/main/autostart/autostart.ts

import { app } from 'electron';

interface AutoStartConfig {
  enabled: boolean;
  hidden: boolean;  // Start minimized to tray
}

export function configureAutoStart(config: AutoStartConfig): void {
  app.setLoginItemSettings({
    openAtLogin: config.enabled,
    openAsHidden: config.hidden,
    args: config.hidden ? ['--hidden'] : [],
  });
}

export function getAutoStartStatus(): AutoStartConfig {
  const settings = app.getLoginItemSettings();
  return {
    enabled: settings.openAtLogin,
    hidden: settings.openAsHidden ?? false,
  };
}

// In main.ts startup:
export function handleAutoStartLaunch(): boolean {
  const isHidden = process.argv.includes('--hidden');
  return isHidden; // Caller decides whether to show window
}
```

**Effort**: 1 day  
**Risk**: macOS requires special permissions for login items → document in README  
**Test**: Enable auto-start → restart → VoiceTree appears in tray

---

### 3.3 — ScreenPipe Integration (Days 5–14)

**Goal**: Poll ScreenPipe REST API for ambient context events and ingest them into FalkorDB.

#### ScreenPipe Data Types

```typescript
// src/pure/types/screenpipe.ts

/** ScreenPipe REST API response types */
export interface ScreenPipeSearchResponse {
  readonly data: readonly ScreenPipeContentItem[];
  readonly pagination: {
    readonly limit: number;
    readonly offset: number;
    readonly total: number;
  };
}

export interface ScreenPipeContentItem {
  readonly type: 'OCR' | 'Audio' | 'UI';
  readonly content: ScreenPipeOCRContent | ScreenPipeAudioContent;
}

export interface ScreenPipeOCRContent {
  readonly frame_id: number;
  readonly text: string;
  readonly timestamp: string;
  readonly file_path: string;
  readonly offset_index: number;
  readonly app_name: string;
  readonly window_name: string;
  readonly tags: readonly string[];
  readonly frame: string | null;  // base64 screenshot
}

export interface ScreenPipeAudioContent {
  readonly chunk_id: number;
  readonly transcription: string;
  readonly timestamp: string;
  readonly file_path: string;
  readonly offset_index: number;
  readonly tags: readonly string[];
  readonly device_name: string;
  readonly device_type: string;
}

/** Normalized ambient capture event */
export interface AmbientCaptureEvent {
  readonly source: 'screenpipe';
  readonly captureType: 'ocr' | 'audio' | 'ui';
  readonly content: string;
  readonly appName: string;
  readonly windowName: string;
  readonly timestamp: string;
  readonly projectPath: string | null;  // Inferred from window context
}
```

#### ScreenPipe Adapter

```typescript
// src/shell/edge/main/ambient/screenpipe-adapter.ts

import type {
  ScreenPipeSearchResponse,
  ScreenPipeContentItem,
  AmbientCaptureEvent,
  ScreenPipeOCRContent,
  ScreenPipeAudioContent,
} from '../../pure/types/screenpipe';

const SCREENPIPE_BASE_URL = 'http://localhost:3030';

interface ScreenPipePollerConfig {
  pollIntervalMs: number;       // Default: 10000 (10s)
  ocrEnabled: boolean;
  audioEnabled: boolean;
  minContentLength: number;     // Skip very short captures
  dedupWindowMs: number;        // Dedup within this time window
  excludeApps: readonly string[];  // Apps to ignore
}

const DEFAULT_CONFIG: ScreenPipePollerConfig = {
  pollIntervalMs: 10_000,
  ocrEnabled: true,
  audioEnabled: true,
  minContentLength: 20,
  dedupWindowMs: 30_000,
  excludeApps: ['Task Manager', 'Activity Monitor', 'System Preferences'],
};

let pollingInterval: ReturnType<typeof setInterval> | null = null;
let lastPollTimestamp: string = new Date().toISOString();

export async function checkScreenPipeAvailable(): Promise<boolean> {
  try {
    const response = await fetch(`${SCREENPIPE_BASE_URL}/health`, {
      signal: AbortSignal.timeout(3000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export function startPolling(
  onCapture: (event: AmbientCaptureEvent) => Promise<void>,
  config: Partial<ScreenPipePollerConfig> = {},
): void {
  if (pollingInterval) return; // Already polling

  const resolved = { ...DEFAULT_CONFIG, ...config };

  pollingInterval = setInterval(async () => {
    try {
      const events = await pollScreenPipe(resolved);
      for (const event of events) {
        await onCapture(event);
      }
    } catch (err) {
      console.error('[screenpipe] Poll error:', err);
      // Don't stop polling on transient errors
    }
  }, resolved.pollIntervalMs);
}

export function stopPolling(): void {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
  }
}

async function pollScreenPipe(
  config: ScreenPipePollerConfig,
): Promise<AmbientCaptureEvent[]> {
  const events: AmbientCaptureEvent[] = [];

  // Query OCR captures since last poll
  if (config.ocrEnabled) {
    const ocrResponse = await fetchScreenPipe('/search', {
      content_type: 'ocr',
      start_time: lastPollTimestamp,
      limit: 50,
    });
    
    for (const item of ocrResponse?.data ?? []) {
      const event = normalizeCapture(item, config);
      if (event) events.push(event);
    }
  }

  // Query audio captures since last poll
  if (config.audioEnabled) {
    const audioResponse = await fetchScreenPipe('/search', {
      content_type: 'audio',
      start_time: lastPollTimestamp,
      limit: 50,
    });

    for (const item of audioResponse?.data ?? []) {
      const event = normalizeCapture(item, config);
      if (event) events.push(event);
    }
  }

  lastPollTimestamp = new Date().toISOString();
  return events;
}

async function fetchScreenPipe(
  endpoint: string,
  params: Record<string, string | number>,
): Promise<ScreenPipeSearchResponse | null> {
  const url = new URL(`${SCREENPIPE_BASE_URL}${endpoint}`);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, String(value));
  }

  try {
    const response = await fetch(url.toString(), {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return await response.json() as ScreenPipeSearchResponse;
  } catch {
    return null;
  }
}

function normalizeCapture(
  item: ScreenPipeContentItem,
  config: ScreenPipePollerConfig,
): AmbientCaptureEvent | null {
  if (item.type === 'OCR') {
    const ocr = item.content as ScreenPipeOCRContent;
    
    // Skip excluded apps
    if (config.excludeApps.includes(ocr.app_name)) return null;
    
    // Skip short content
    if (ocr.text.length < config.minContentLength) return null;

    return {
      source: 'screenpipe',
      captureType: 'ocr',
      content: ocr.text,
      appName: ocr.app_name,
      windowName: ocr.window_name,
      timestamp: ocr.timestamp,
      projectPath: inferProjectPath(ocr.app_name, ocr.window_name),
    };
  }

  if (item.type === 'Audio') {
    const audio = item.content as ScreenPipeAudioContent;
    
    if (audio.transcription.length < config.minContentLength) return null;

    return {
      source: 'screenpipe',
      captureType: 'audio',
      content: audio.transcription,
      appName: 'audio',
      windowName: audio.device_name,
      timestamp: audio.timestamp,
      projectPath: null,  // Can't infer project from audio
    };
  }

  return null;
}

/**
 * Infer project path from active window context.
 * IDE title bars typically include the project directory.
 */
function inferProjectPath(appName: string, windowName: string): string | null {
  // VS Code: "filename — ProjectName — Visual Studio Code"
  // Cursor: similar pattern
  const idePattern = /—\s*(.+?)\s*—\s*(Visual Studio Code|Cursor|Code)/;
  const match = windowName.match(idePattern);
  if (match && match[1]) return match[1];

  // Terminal: look for path-like strings
  const pathPattern = /([A-Z]:\\[^\s]+|\/[^\s]+)/;
  const pathMatch = windowName.match(pathPattern);
  if (pathMatch && pathMatch[1]) return pathMatch[1];

  return null;
}
```

#### Connecting ScreenPipe to Ingestion Pipeline

```typescript
// src/shell/edge/main/ambient/ambient-ingestion.ts

import type { Graph } from '@falkordb/falkordb';
import type { EmbeddingProvider } from '../../pure/types/embedding';
import type { AmbientCaptureEvent } from '../../pure/types/screenpipe';
import { ingest } from '../ingestion/pipeline';
import { resolveVault } from '../routing/project-router';
import { checkScreenPipeAvailable, startPolling, stopPolling } from './screenpipe-adapter';

interface AmbientIngestionConfig {
  enabled: boolean;
  batchIntervalMs: number;   // Batch captures before ingesting (default: 30s)
  maxBatchSize: number;
}

const DEFAULT_AMBIENT_CONFIG: AmbientIngestionConfig = {
  enabled: true,
  batchIntervalMs: 30_000,
  maxBatchSize: 10,
};

let eventBuffer: AmbientCaptureEvent[] = [];
let batchTimer: ReturnType<typeof setInterval> | null = null;

export async function startAmbientIngestion(
  graph: Graph,
  embedding: EmbeddingProvider,
  config: Partial<AmbientIngestionConfig> = {},
): Promise<boolean> {
  const resolved = { ...DEFAULT_AMBIENT_CONFIG, ...config };
  
  if (!resolved.enabled) return false;

  // Check if ScreenPipe is running
  const available = await checkScreenPipeAvailable();
  if (!available) {
    console.log('[ambient] ScreenPipe not available — ambient capture disabled');
    return false;
  }

  console.log('[ambient] ScreenPipe detected — starting ambient capture');

  // Start polling ScreenPipe
  startPolling(async (event) => {
    eventBuffer.push(event);
    
    // Flush if buffer is full
    if (eventBuffer.length >= resolved.maxBatchSize) {
      await flushBuffer(graph, embedding);
    }
  });

  // Periodic flush
  batchTimer = setInterval(async () => {
    await flushBuffer(graph, embedding);
  }, resolved.batchIntervalMs);

  return true;
}

export function stopAmbientIngestion(): void {
  stopPolling();
  if (batchTimer) {
    clearInterval(batchTimer);
    batchTimer = null;
  }
  eventBuffer = [];
}

async function flushBuffer(
  graph: Graph,
  embedding: EmbeddingProvider,
): Promise<void> {
  if (eventBuffer.length === 0) return;

  const batch = [...eventBuffer];
  eventBuffer = [];

  // Merge OCR captures from the same app/window within the batch
  const merged = mergeRelatedCaptures(batch);

  for (const event of merged) {
    try {
      await ingest(
        graph,
        {
          source: 'screenpipe',
          sourceRef: `${event.captureType}:${event.appName}`,
          content: event.content,
          title: `[${event.captureType.toUpperCase()}] ${event.appName} — ${event.windowName}`,
          timestamp: event.timestamp,
          projectPath: event.projectPath ?? 'ambient',
          tags: ['ambient', event.captureType, event.appName.toLowerCase()],
        },
        embedding,
        (projectPath) => resolveVault(graph, projectPath),
      );
    } catch (err) {
      console.error('[ambient] Ingestion error:', err);
    }
  }
}

/**
 * Merge captures from the same app+window within a batch.
 * Prevents creating 10 separate nodes for continuous typing in the same editor.
 */
function mergeRelatedCaptures(events: AmbientCaptureEvent[]): AmbientCaptureEvent[] {
  const grouped = new Map<string, AmbientCaptureEvent[]>();

  for (const event of events) {
    const key = `${event.appName}::${event.windowName}::${event.captureType}`;
    const existing = grouped.get(key) ?? [];
    existing.push(event);
    grouped.set(key, existing);
  }

  const merged: AmbientCaptureEvent[] = [];
  for (const [, group] of grouped) {
    if (group.length === 1) {
      merged.push(group[0]!);
      continue;
    }

    // Merge: concatenate content, use latest timestamp
    const content = group.map(e => e.content).join('\n\n---\n\n');
    const latest = group.reduce((a, b) =>
      new Date(a.timestamp) > new Date(b.timestamp) ? a : b
    );

    merged.push({
      ...latest,
      content,
    });
  }

  return merged;
}
```

**Effort**: 7 days  
**Risk**: ScreenPipe API changes → pin to tested version, abstract behind adapter  
**Risk**: OCR noise creates too many low-quality nodes → aggressive dedup + min content length filter  
**Test**: Mock ScreenPipe API → verify captures flow through pipeline → appear in FalkorDB

---

### 3.4 — Background Ingestion Performance (Days 12–16)

**Goal**: Ambient capture doesn't degrade UI performance.

Key strategies:
1. **Worker thread for embedding** — compute embeddings off the main thread
2. **Batch writes to FalkorDB** — group multiple nodes into a single transaction
3. **Rate limiting** — cap ambient ingestion at N nodes per minute
4. **Priority queue** — agent and voice captures take priority over ambient

```typescript
// src/shell/edge/main/ingestion/worker-pool.ts

import { Worker } from 'worker_threads';
import path from 'path';

interface EmbeddingJob {
  id: string;
  text: string;
  resolve: (embedding: number[]) => void;
  reject: (error: Error) => void;
}

const POOL_SIZE = 2;  // Number of parallel embedding workers
const workers: Worker[] = [];
const queue: EmbeddingJob[] = [];
const activeJobs = new Map<string, EmbeddingJob>();

export function initEmbeddingPool(): void {
  for (let i = 0; i < POOL_SIZE; i++) {
    const worker = new Worker(path.join(__dirname, 'embedding-worker.js'));
    
    worker.on('message', (msg: { id: string; embedding: number[] }) => {
      const job = activeJobs.get(msg.id);
      if (job) {
        activeJobs.delete(msg.id);
        job.resolve(msg.embedding);
        processQueue(worker);
      }
    });

    worker.on('error', (err) => {
      // Reject all active jobs for this worker
      for (const [id, job] of activeJobs) {
        job.reject(err);
        activeJobs.delete(id);
      }
    });

    workers.push(worker);
  }
}

export function embedAsync(text: string): Promise<number[]> {
  return new Promise((resolve, reject) => {
    const id = Math.random().toString(36).slice(2);
    const job: EmbeddingJob = { id, text, resolve, reject };
    queue.push(job);
    
    // Try to assign to an idle worker
    for (const worker of workers) {
      processQueue(worker);
    }
  });
}

function processQueue(worker: Worker): void {
  const job = queue.shift();
  if (!job) return;
  
  activeJobs.set(job.id, job);
  worker.postMessage({ id: job.id, text: job.text });
}

export function shutdownPool(): void {
  for (const worker of workers) {
    worker.terminate();
  }
  workers.length = 0;
}
```

```typescript
// src/shell/edge/main/ingestion/rate-limiter.ts

interface RateLimiterConfig {
  maxPerMinute: number;
  priorityBoost: Map<string, number>;  // source → priority multiplier
}

const DEFAULT_RATE_CONFIG: RateLimiterConfig = {
  maxPerMinute: 30,
  priorityBoost: new Map([
    ['mcp', 10],      // Agent captures: highest priority
    ['whisper', 5],   // Voice: high priority
    ['editor', 3],    // Manual: medium priority
    ['screenpipe', 1], // Ambient: lowest priority
  ]),
};

interface RateLimiterState {
  timestamps: number[];
  windowMs: number;
}

const state: RateLimiterState = {
  timestamps: [],
  windowMs: 60_000,
};

export function canIngest(source: string, config = DEFAULT_RATE_CONFIG): boolean {
  const now = Date.now();
  
  // Clean old timestamps
  state.timestamps = state.timestamps.filter(t => now - t < state.windowMs);

  // Priority sources always pass
  const priority = config.priorityBoost.get(source) ?? 1;
  if (priority >= 5) return true;

  // Check rate limit
  return state.timestamps.length < config.maxPerMinute;
}

export function recordIngestion(): void {
  state.timestamps.push(Date.now());
}
```

**Effort**: 3 days  
**Test**: Ingest 100 ambient events → UI remains responsive (< 16ms frame time). Rate limiter caps at configured max.

---

### 3.5 — Context-Aware Routing (Days 14–18)

**Goal**: Automatically associate ambient captures with the correct project vault.

Strategy:
1. Parse active window title for IDE project names
2. Parse file paths from terminal windows
3. Fall back to a "default/ambient" vault for unresolvable context
4. Allow manual re-routing in the UI

```typescript
// src/pure/context/project-inferrer.ts

interface ProjectInference {
  readonly projectPath: string | null;
  readonly confidence: number;    // 0–1
  readonly method: 'ide-title' | 'terminal-path' | 'browser-url' | 'manual' | 'none';
}

/** Infer project from window context — pure function */
export function inferProject(
  appName: string,
  windowTitle: string,
  knownProjects: readonly string[],
): ProjectInference {
  // 1. IDE title bar: "file.ts — MyProject — Visual Studio Code"
  const idePatterns = [
    /—\s*(.+?)\s*—\s*(?:Visual Studio Code|VS Code|Cursor|Code - OSS)/,
    /\[(.+?)\]\s*-\s*(?:IntelliJ|WebStorm|PyCharm)/,
  ];

  for (const pattern of idePatterns) {
    const match = windowTitle.match(pattern);
    if (match?.[1]) {
      const projectName = match[1].trim();
      const fullPath = findKnownProject(projectName, knownProjects);
      if (fullPath) return { projectPath: fullPath, confidence: 0.9, method: 'ide-title' };
      return { projectPath: projectName, confidence: 0.6, method: 'ide-title' };
    }
  }

  // 2. Terminal: look for path in title
  if (['Terminal', 'iTerm', 'Windows Terminal', 'PowerShell', 'cmd'].some(t =>
    appName.toLowerCase().includes(t.toLowerCase())
  )) {
    const pathMatch = windowTitle.match(/([A-Z]:\\[\w\\.-]+|\/(?:home|Users)\/[\w/.-]+)/);
    if (pathMatch?.[1]) {
      const fullPath = findKnownProject(pathMatch[1], knownProjects);
      if (fullPath) return { projectPath: fullPath, confidence: 0.8, method: 'terminal-path' };
    }
  }

  // 3. Browser: could extract repo from GitHub URL
  if (['Chrome', 'Firefox', 'Edge', 'Safari', 'Arc'].some(b =>
    appName.toLowerCase().includes(b.toLowerCase())
  )) {
    const githubMatch = windowTitle.match(/github\.com\/[\w-]+\/([\w-]+)/);
    if (githubMatch?.[1]) {
      const projectName = githubMatch[1];
      const fullPath = findKnownProject(projectName, knownProjects);
      if (fullPath) return { projectPath: fullPath, confidence: 0.7, method: 'browser-url' };
    }
  }

  return { projectPath: null, confidence: 0, method: 'none' };
}

function findKnownProject(query: string, projects: readonly string[]): string | null {
  const lower = query.toLowerCase();
  return projects.find(p => {
    const name = p.split(/[/\\]/).pop()?.toLowerCase() ?? '';
    return name === lower || p.toLowerCase().includes(lower);
  }) ?? null;
}
```

**Effort**: 3 days  
**Test**: VS Code window with "myproject" → routes to myproject vault. Unknown app → routes to ambient vault.

---

## Testing Strategy

| Test Type | Scope | Tool |
|-----------|-------|------|
| Unit tests | `inferProject()`, `mergeRelatedCaptures()`, rate limiter | Vitest |
| Integration tests | ScreenPipe mock → ingestion pipeline → FalkorDB | Vitest + nock |
| E2E (manual) | Enable ambient capture → use IDE → verify nodes appear | Manual checklist |
| Performance | 100 ambient events/min → UI frame time < 16ms | Custom benchmark |
| Platform | System tray works on Windows + macOS + Linux | Manual per-platform |

### ScreenPipe Mock Server

```typescript
// tests/mocks/screenpipe-mock.ts

import express from 'express';

export function createScreenPipeMock(port = 3030): express.Application {
  const app = express();

  app.get('/health', (_req, res) => res.json({ status: 'ok' }));

  app.get('/search', (req, res) => {
    const contentType = req.query.content_type;

    if (contentType === 'ocr') {
      res.json({
        data: [
          {
            type: 'OCR',
            content: {
              frame_id: 1,
              text: 'function authenticateUser(token: string) { ... }',
              timestamp: new Date().toISOString(),
              file_path: '/tmp/screen.png',
              offset_index: 0,
              app_name: 'Visual Studio Code',
              window_name: 'auth.ts — MyProject — Visual Studio Code',
              tags: [],
              frame: null,
            },
          },
        ],
        pagination: { limit: 50, offset: 0, total: 1 },
      });
    } else {
      res.json({ data: [], pagination: { limit: 50, offset: 0, total: 0 } });
    }
  });

  return app;
}
```

---

## Definition of Done

- [ ] System tray icon appears on launch
- [ ] Clicking tray icon toggles main window
- [ ] Right-click menu shows capture status, node count, controls
- [ ] "Pause Capture" stops ScreenPipe polling
- [ ] Auto-start on login configurable via settings
- [ ] ScreenPipe adapter polls for OCR and audio captures
- [ ] Ambient captures flow through ingestion pipeline into FalkorDB
- [ ] Captures are tagged with source app, window, and capture type
- [ ] Related captures from the same window are merged (not 10 separate nodes)
- [ ] Rate limiter prevents ambient flood (max 30/min default)
- [ ] Agent and voice captures take priority over ambient
- [ ] Context-aware routing assigns captures to correct project vault
- [ ] UI frame time stays < 16ms during background ingestion
- [ ] VoiceTree works fine when ScreenPipe is not installed

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| ScreenPipe not installed | No ambient capture | Graceful fallback — all other features work. Show "Install ScreenPipe" prompt in settings |
| OCR noise creating low-quality nodes | Graph pollution | Min content length (20 chars), dedupe window (30s), app exclusion list |
| High CPU from continuous embedding | Poor UX | Worker threads for embedding. Rate limiting. User-configurable poll interval |
| Privacy concerns (capturing screen content) | User trust issues | Clear opt-in flow. Pause/resume controls. App exclusion list. Local-only processing |
| Project inference wrong | Nodes in wrong vault | Low-confidence inferences go to "ambient" vault. Manual re-routing in UI |
| ScreenPipe API changes | Adapter breaks | Pin tested version. Abstract behind interface. E2E tests with mock server |
