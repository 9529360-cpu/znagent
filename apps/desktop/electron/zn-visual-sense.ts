import { createHash } from 'node:crypto'
import { desktopCapturer, screen } from 'electron'

import type { ZnResidentProcess } from './zn-resident-process'

export type ZnVisualRetinaSnapshot = {
  displayId: string
  sourceId: string
  sourceName: string
  width: number
  height: number
  frameHash: string
  capturedAt: string
}

export class ZnVisualSense {
  private timer: NodeJS.Timeout | null = null
  private running = false
  private captureInFlight = false
  private lastFrameHash: string | null = null
  private lastSnapshot: ZnVisualRetinaSnapshot | null = null

  constructor(
    private readonly resident: ZnResidentProcess,
    private readonly intervalMs = 5_000
  ) {}

  start(): void {
    if (this.running) return
    this.running = true
    void this.captureOnce()
    this.timer = setInterval(() => {
      void this.captureOnce()
    }, Math.max(2_000, this.intervalMs))
  }

  stop(): void {
    this.running = false
    if (this.timer) clearInterval(this.timer)
    this.timer = null
  }

  snapshot(): ZnVisualRetinaSnapshot | null {
    return this.lastSnapshot ? { ...this.lastSnapshot } : null
  }

  async captureOnce(): Promise<ZnVisualRetinaSnapshot | null> {
    if (!this.running || this.captureInFlight) return null
    this.captureInFlight = true
    try {
      const primary = screen.getPrimaryDisplay()
      const size = this.thumbnailSize(primary.size.width, primary.size.height)
      const sources = await desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize: size,
        fetchWindowIcons: false
      })
      const primaryId = String(primary.id)
      const source =
        sources.find(item => String(item.display_id || '') === primaryId) ||
        sources[0]
      if (!source || source.thumbnail.isEmpty()) return null

      const bitmap = source.thumbnail.toBitmap()
      const frameHash = createHash('sha256').update(bitmap).digest('hex')
      const imageSize = source.thumbnail.getSize()
      const snapshot: ZnVisualRetinaSnapshot = {
        displayId: primaryId,
        sourceId: source.id,
        sourceName: source.name,
        width: imageSize.width,
        height: imageSize.height,
        frameHash,
        capturedAt: new Date().toISOString()
      }
      this.lastSnapshot = snapshot

      const previous = this.lastFrameHash
      this.lastFrameHash = frameHash
      if (previous === frameHash || !this.running) return snapshot

      await this.resident.request(
        'perceive',
        {
          channel: 'vision',
          summary: previous
            ? `primary screen changed on display ${primaryId}`
            : `primary screen became visible on display ${primaryId}`,
          source: 'electron-retina',
          features: [
            'screen',
            previous ? 'changed' : 'initial-frame',
            `display:${primaryId}`,
            `size:${imageSize.width}x${imageSize.height}`
          ],
          salience: previous ? 0.46 : 0.34,
          valence: 0,
          arousal: previous ? 0.34 : 0.22,
          metadata: {
            frame_hash: frameHash,
            previous_frame_hash: previous,
            display_id: primaryId,
            source_id: source.id,
            source_name: source.name,
            width: imageSize.width,
            height: imageSize.height,
            captured_at: snapshot.capturedAt
          }
        },
        15_000
      )
      return snapshot
    } catch (error) {
      // Screen capture can be unavailable because of OS permission, a locked
      // session, or a headless environment. Vision failure must not stop the
      // resident's other senses or life loop.
      console.debug('[zn-vision] retina sample unavailable', error)
      return null
    } finally {
      this.captureInFlight = false
    }
  }

  private thumbnailSize(width: number, height: number): { width: number; height: number } {
    const maxWidth = 384
    const safeWidth = Math.max(1, width)
    const safeHeight = Math.max(1, height)
    if (safeWidth <= maxWidth) return { width: safeWidth, height: safeHeight }
    const ratio = maxWidth / safeWidth
    return {
      width: maxWidth,
      height: Math.max(1, Math.round(safeHeight * ratio))
    }
  }
}
