import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import type { Graph } from '@/pure/graph'
import type { VTSettings } from '@/pure/settings/types'
import { createStarterNode } from './create-starter-node'

vi.mock('@/shell/edge/main/settings/settings_IO', () => ({
  loadSettings: vi.fn()
}))

import { loadSettings } from '@/shell/edge/main/settings/settings_IO'

describe('createStarterNode', () => {
  let tmpDir: string

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'create-starter-node-test-'))
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-02-25T15:30:00.000Z'))
  })

  afterEach(async () => {
    vi.useRealTimers()
    vi.clearAllMocks()
    await fs.rm(tmpDir, { recursive: true, force: true })
  })

  it('returns an empty graph and does not write files when disableStarterNodes is enabled', async () => {
    vi.mocked(loadSettings).mockResolvedValue({
      disableStarterNodes: true,
      emptyFolderTemplate: '# {{DATE}}'
    } as VTSettings)

    const graph: Graph = await createStarterNode(tmpDir)

    expect(Object.keys(graph.nodes)).toHaveLength(0)
    expect(await fs.readdir(tmpDir)).toEqual([])
  })

  it('creates one starter node file when disableStarterNodes is disabled', async () => {
    vi.mocked(loadSettings).mockResolvedValue({
      disableStarterNodes: false,
      emptyFolderTemplate: '# {{DATE}}\n\nHighest priority task: '
    } as VTSettings)

    const graph: Graph = await createStarterNode(tmpDir)
    const nodeIds: string[] = Object.keys(graph.nodes)
    expect(nodeIds).toHaveLength(1)

    const nodeId: string = nodeIds[0]
    const fileContent: string = await fs.readFile(nodeId, 'utf-8')
    expect(fileContent).not.toContain('{{DATE}}')
    expect(fileContent).toContain('Highest priority task:')
    expect(graph.nodes[nodeId]?.contentWithoutYamlOrLinks).toBe(fileContent)
  })
})
