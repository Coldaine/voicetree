# Phase 3 — Daemon & Background Services

> **Duration**: Weeks 13–16  
> **Effort**: ~100 hours (reduced scope — no ScreenPipe in v2)  
> **Depends on**: Phase 1 (ingestion pipeline), Phase 2 (UI)  
> **Enables**: Phase 4 (performance optimization), v3.0+ (full ambient capture)

---

## Goals

1. **System tray / daemon mode** — VoiceTree runs in the background without a visible window
2. **Auto-start on login** — VoiceTree starts when the user logs in
3. **Background ingestion infrastructure** — ingestion pipeline runs without blocking the UI
4. **Context-aware routing** — automatically associate ingested nodes with the correct project
5. **Lightweight active-window detection (Windows)** — capture focused window name at ingestion time (optional, Phase 4 stretch goal)

**EXPLICITLY NOT IN v2**: Full ScreenPipe integration (OCR, screen recording, audio context) is **v3.0 product territory**. It requires extensive calibration and is conceptual at this stage. Phase 3 builds the *infrastructure* for ambient ingestion (daemon, background processing) but does NOT actively capture screen state.

---

## Prerequisites

- Phase 1 complete: ingestion pipeline processes events into FalkorDB
- Phase 2 complete: UI can display and filter nodes
- **ScreenPipe is NOT a prerequisite** — it's not integrated in v2

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

### 3.3 — ScreenPipe / Full Ambient Capture → v3.0 Product (NOT Phase 3)

**Why this section was removed**: Full ScreenPipe integration (OCR, screen recording, audio context, browser tab tracking) is **v3.0 product territory**, not v2. The user clarified that active screen capture "is going to require so much calibration that it will take a while to build in." Phase 3 builds the *infrastructure* for background ingestion (daemon mode, background processing), but VoiceTree v2 does **NOT** actively capture screen state.

**What v3.0 might look like**: ScreenPipe (or equivalent) as an optional external provider feeding events into the ingestion pipeline. The architecture is ready for this — the pipeline is provider-agnostic — but the capture side requires its own roadmap.

**Lightweight alternative for v2 (optional stretch goal in Phase 4)**: Capture the currently focused window name via Windows API at ingestion time. This is a cheap, zero-dependency signal that adds useful context without the complexity of full screen capture. See Phase 4 docs for implementation.

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
