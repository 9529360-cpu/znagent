import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ZnArtifact } from './state'

type SlideLayout = 'title' | 'title-body' | 'title-bullets' | 'architecture' | 'image-right'

type DiagramNode = {
  id: string
  label: string
}

type DiagramEdge = {
  from: string
  to: string
}

export type ZnPresentationSlide = {
  id: string
  layout: SlideLayout
  title: string
  body: string
  bullets: string[]
  imageArtifactId: string
  diagram?: {
    nodes: DiagramNode[]
    edges: DiagramEdge[]
  }
}

export type ZnPresentationSpec = {
  version: 1
  deckId: string
  title: string
  theme: 'dark-tech' | 'light-clean'
  slides: ZnPresentationSlide[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').slice(0, 8)
    : []
}

function parseDiagram(value: unknown): ZnPresentationSlide['diagram'] | undefined {
  const item = record(value)
  if (!item || !Array.isArray(item.nodes) || !Array.isArray(item.edges)) return undefined

  const nodes = item.nodes.slice(0, 6).flatMap(value => {
    const node = record(value)
    const id = String(node?.id || '').trim()
    const label = String(node?.label || '').trim()
    return id && label ? [{ id, label }] : []
  })
  const known = new Set(nodes.map(node => node.id))
  const edges = item.edges.slice(0, 8).flatMap(value => {
    const edge = record(value)
    const from = String(edge?.from || '').trim()
    const to = String(edge?.to || '').trim()
    return from && to && from !== to && known.has(from) && known.has(to)
      ? [{ from, to }]
      : []
  })
  return nodes.length >= 2 && edges.length >= 1 ? { nodes, edges } : undefined
}

export function parsePresentationArtifact(artifact: ZnArtifact | null): ZnPresentationSpec | null {
  if (!artifact || artifact.kind !== 'presentation') return null
  try {
    const raw = record(JSON.parse(artifact.content))
    if (!raw || raw.version !== 1 || !Array.isArray(raw.slides)) return null

    const deckId = String(raw.deck_id || '').trim()
    const title = String(raw.title || '').trim()
    const theme = raw.theme === 'light-clean'
      ? 'light-clean'
      : raw.theme === 'dark-tech'
        ? 'dark-tech'
        : null
    if (!deckId || !title || !theme || raw.slides.length < 1 || raw.slides.length > 20) return null

    const allowedLayouts: SlideLayout[] = [
      'title',
      'title-body',
      'title-bullets',
      'architecture',
      'image-right'
    ]
    const slides = raw.slides.flatMap((value, index) => {
      const slide = record(value)
      if (!slide) return []
      const id = String(slide.id || '').trim()
      const layout = String(slide.layout || '') as SlideLayout
      const slideTitle = String(slide.title || '').trim()
      if (
        id !== `slide-${index + 1}` ||
        !slideTitle ||
        !allowedLayouts.includes(layout)
      ) return []

      const body = String(slide.body || '').trim()
      const bullets = strings(slide.bullets)
      const imageArtifactId = String(slide.image_artifact_id || '').trim()
      const diagram = layout === 'architecture' ? parseDiagram(slide.diagram) : undefined

      if (layout === 'title' && index !== 0) return []
      if (layout === 'title-body' && !body) return []
      if (layout === 'title-bullets' && bullets.length === 0) return []
      if (layout === 'architecture' && !diagram) return []
      if (layout === 'image-right' && !imageArtifactId) return []

      return [{
        id,
        layout,
        title: slideTitle,
        body,
        bullets,
        imageArtifactId,
        ...(diagram ? { diagram } : {})
      }]
    })
    if (slides.length !== raw.slides.length) return null
    return { version: 1, deckId, title, theme, slides }
  } catch {
    return null
  }
}

type Point = { x: number; y: number }

function diagramPoints(nodes: DiagramNode[]): Map<string, Point> {
  const columns = nodes.length > 4 ? 3 : 2
  const rows = Math.ceil(nodes.length / columns)
  const result = new Map<string, Point>()
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns)
    const col = index % columns
    const itemsInRow = Math.min(columns, nodes.length - row * columns)
    const x = itemsInRow === 1 ? 50 : 20 + (60 * col / Math.max(1, itemsInRow - 1))
    const y = rows === 1 ? 52 : 32 + (40 * row / Math.max(1, rows - 1))
    result.set(node.id, { x, y })
  })
  return result
}

function ArchitectureDiagram({ slide, label }: { slide: ZnPresentationSlide; label: string }) {
  const nodes = slide.diagram?.nodes || []
  const edges = slide.diagram?.edges || []
  const points = useMemo(() => diagramPoints(nodes), [nodes])
  return (
    <div className="zn-slide-diagram" aria-label={label}>
      <svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none">
        {edges.map((edge, index) => {
          const from = points.get(edge.from)
          const to = points.get(edge.to)
          if (!from || !to) return null
          return (
            <line
              key={`${edge.from}-${edge.to}-${index}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
            />
          )
        })}
      </svg>
      {nodes.map(node => {
        const point = points.get(node.id)
        if (!point) return null
        return (
          <div
            className="zn-slide-diagram-node"
            key={node.id}
            style={{ left: `${point.x}%`, top: `${point.y}%` }}
          >
            {node.label}
          </div>
        )
      })}
    </div>
  )
}

function SlideCopy({ slide }: { slide: ZnPresentationSlide }) {
  return (
    <div className="zn-slide-copy">
      {slide.body ? <p>{slide.body}</p> : null}
      {slide.bullets.length > 0 ? (
        <ul>
          {slide.bullets.map((bullet, index) => <li key={`${bullet}-${index}`}>{bullet}</li>)}
        </ul>
      ) : null}
    </div>
  )
}

function referencedImage(artifact: ZnArtifact | undefined): string | null {
  if (!artifact) return null
  const content = artifact.content.trim()
  return content.startsWith('data:image/') ? content : null
}

function SlidePage({
  slide,
  theme,
  imageArtifact,
  imageLabel,
  unavailableImageHint,
  architectureLabel,
  thumbnail = false
}: {
  slide: ZnPresentationSlide
  theme: ZnPresentationSpec['theme']
  imageArtifact?: ZnArtifact
  imageLabel: string
  unavailableImageHint: string
  architectureLabel: string
  thumbnail?: boolean
}) {
  const imageSrc = referencedImage(imageArtifact)
  return (
    <div className={`zn-slide-page theme-${theme}${thumbnail ? ' thumbnail' : ''}`} data-slide-id={slide.id}>
      {slide.layout === 'title' ? (
        <div className="zn-slide-title-cover">
          <h1>{slide.title}</h1>
          {slide.body ? <p>{slide.body}</p> : null}
          <span className="zn-slide-accent" />
        </div>
      ) : (
        <>
          <header>
            <h2>{slide.title}</h2>
            <span />
          </header>
          {slide.layout === 'architecture' ? (
            <ArchitectureDiagram slide={slide} label={architectureLabel} />
          ) : slide.layout === 'image-right' ? (
            <div className="zn-slide-split">
              <SlideCopy slide={slide} />
              <div className="zn-slide-image-slot">
                {imageSrc ? (
                  <img src={imageSrc} alt="" />
                ) : (
                  <>
                    <span>{imageLabel}</span>
                    <strong>{imageArtifact?.name || slide.imageArtifactId}</strong>
                    <small>{unavailableImageHint}</small>
                  </>
                )}
              </div>
            </div>
          ) : (
            <SlideCopy slide={slide} />
          )}
        </>
      )}
    </div>
  )
}

export function ZnSlidesWorkstation({
  artifact,
  artifacts
}: {
  artifact: ZnArtifact
  artifacts: ZnArtifact[]
}) {
  const { t } = useTranslation()
  const spec = useMemo(() => parsePresentationArtifact(artifact), [artifact])
  const [selectedSlideId, setSelectedSlideId] = useState('')

  useEffect(() => {
    if (!spec) {
      setSelectedSlideId('')
      return
    }
    setSelectedSlideId(current =>
      spec.slides.some(slide => slide.id === current)
        ? current
        : spec.slides[0]?.id || ''
    )
  }, [spec])

  const selectedSlide = spec?.slides.find(slide => slide.id === selectedSlideId)
    || spec?.slides[0]
    || null
  const artifactById = useMemo(
    () => new Map(artifacts.map(item => [item.id, item])),
    [artifacts]
  )

  if (!spec || !selectedSlide) {
    return (
      <main className="zn-slides-workstation">
        <div className="zn-slides-invalid">
          <strong>{t('workstation.slidesUnavailable')}</strong>
          <span>{t('workstation.slidesInvalid')}</span>
        </div>
      </main>
    )
  }

  return (
    <main className="zn-slides-workstation" aria-label={t('workstation.slidesWorkspace')}>
      <aside className="zn-slides-rail" aria-label={t('workstation.slides')}>
        <div className="zn-slides-rail-title">
            <strong>{t('workstation.slides')}</strong>
          <span>{spec.slides.length}</span>
        </div>
        <div className="zn-slides-thumbnails">
          {spec.slides.map((slide, index) => (
            <button
              type="button"
              className={`zn-slide-thumbnail${slide.id === selectedSlide.id ? ' active' : ''}`}
              key={slide.id}
              onClick={() => setSelectedSlideId(slide.id)}
              aria-label={t('workstation.slideLabel', { index: index + 1, title: slide.title })}
            >
              <span className="zn-slide-number">{index + 1}</span>
              <SlidePage
                slide={slide}
                theme={spec.theme}
                imageArtifact={artifactById.get(slide.imageArtifactId)}
                imageLabel={t('workstation.currentWorkImage')}
                unavailableImageHint={t('workstation.imageUnavailable')}
                architectureLabel={t('workstation.architectureDiagram')}
                thumbnail
              />
            </button>
          ))}
        </div>
      </aside>

      <section className="zn-slides-stage">
        <div className="zn-slides-stage-head">
          <div>
            <span>{spec.theme}</span>
            <strong>{selectedSlide.title}</strong>
          </div>
          <span>{selectedSlide.id.replace('slide-', '')} / {spec.slides.length}</span>
        </div>
        <div className="zn-slides-canvas-wrap">
          <SlidePage
            slide={selectedSlide}
            theme={spec.theme}
            imageArtifact={artifactById.get(selectedSlide.imageArtifactId)}
            imageLabel={t('workstation.currentWorkImage')}
            unavailableImageHint={t('workstation.imageUnavailable')}
            architectureLabel={t('workstation.architectureDiagram')}
          />
        </div>
      </section>
    </main>
  )
}
