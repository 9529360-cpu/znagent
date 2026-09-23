import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ZnArtifact } from './state'

export type ZnDocumentSection = {
  id: string
  heading: string
  paragraphs: string[]
  bullets: string[]
}

export type ZnDocumentSpec = {
  version: 1
  documentId: string
  title: string
  subtitle: string
  sections: ZnDocumentSection[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  if (value.some(item => typeof item !== 'string' || !item.trim())) return null
  return value.map(item => item.trim())
}

export function parseDocumentArtifact(artifact: ZnArtifact): ZnDocumentSpec | null {
  if (artifact.kind !== 'document' || !artifact.content) return null
  try {
    const raw = record(JSON.parse(artifact.content))
    if (!raw || raw.version !== 1) return null
    if (
      typeof raw.document_id !== 'string' ||
      typeof raw.title !== 'string' ||
      typeof raw.subtitle !== 'string' ||
      !Array.isArray(raw.sections)
    ) return null
    const sections: ZnDocumentSection[] = []
    for (let index = 0; index < raw.sections.length; index += 1) {
      const item = record(raw.sections[index])
      if (
        !item ||
        item.id !== `section-${index + 1}` ||
        typeof item.heading !== 'string'
      ) return null
      const paragraphs = stringList(item.paragraphs)
      const bullets = stringList(item.bullets)
      if (!paragraphs || !bullets || (!paragraphs.length && !bullets.length)) return null
      sections.push({
        id: item.id as string,
        heading: item.heading.trim(),
        paragraphs,
        bullets
      })
    }
    if (!sections.length || sections.length > 12) return null
    return {
      version: 1,
      documentId: raw.document_id,
      title: raw.title.trim(),
      subtitle: raw.subtitle.trim(),
      sections
    }
  } catch {
    return null
  }
}

type Props = {
  artifact: ZnArtifact
}

export function ZnDocumentWorkstation({ artifact }: Props) {
  const { t } = useTranslation()
  const spec = useMemo(() => parseDocumentArtifact(artifact), [artifact.content, artifact.id])
  const selectedFromArtifact = typeof artifact.metadata?.selected_section_id === 'string'
    ? artifact.metadata.selected_section_id
    : ''
  const [selectedSectionId, setSelectedSectionId] = useState(selectedFromArtifact)
  const paperRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!spec) return
    const next = spec.sections.some(section => section.id === selectedFromArtifact)
      ? selectedFromArtifact
      : spec.sections[0].id
    setSelectedSectionId(next)
  }, [artifact.content, selectedFromArtifact, spec])

  if (!spec) {
    return (
      <main className="zn-document-workstation zn-document-invalid">
        <strong>{t('workstation.documentUnavailable')}</strong>
        <span>{t('workstation.documentInvalid')}</span>
      </main>
    )
  }

  const selectedIndex = Math.max(
    0,
    spec.sections.findIndex(section => section.id === selectedSectionId)
  )

  const selectSection = (sectionId: string) => {
    setSelectedSectionId(sectionId)
    requestAnimationFrame(() => {
      paperRef.current
        ?.querySelector<HTMLElement>(`[data-document-section="${sectionId}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return (
    <main className="zn-document-workstation" aria-label={t('workstation.documentWorkspace')}>
      <aside className="zn-document-outline" aria-label={t('workstation.documentOutline')}>
        <div className="zn-document-outline-head">
          <span>{t('workstation.document')}</span>
          <strong title={spec.title}>{spec.title}</strong>
          <small>{t('workstation.sectionCount', { count: spec.sections.length })}</small>
        </div>
        <div className="zn-document-outline-list">
          {spec.sections.map((section, index) => (
            <button
              type="button"
              key={section.id}
              className={'zn-document-outline-item' + (section.id === selectedSectionId ? ' active' : '')}
              aria-label={t('workstation.sectionLabel', { index: index + 1, heading: section.heading })}
              onClick={() => selectSection(section.id)}
            >
              <span>{index + 1}</span>
              <strong>{section.heading}</strong>
            </button>
          ))}
        </div>
      </aside>

      <section className="zn-document-stage">
        <header className="zn-document-stage-head">
          <div>
            <span>{t('workstation.nativeDocument')}</span>
            <strong>{spec.sections[selectedIndex]?.heading || spec.title}</strong>
          </div>
          <small>{t('workstation.documentVersion')}</small>
        </header>
        <div className="zn-document-canvas-wrap">
          <article className="zn-document-paper" ref={paperRef}>
            <header className="zn-document-paper-title">
              <h1>{spec.title}</h1>
              {spec.subtitle ? <p>{spec.subtitle}</p> : null}
            </header>
            {spec.sections.map(section => (
              <section
                className={'zn-document-section' + (section.id === selectedSectionId ? ' selected' : '')}
                data-document-section={section.id}
                key={section.id}
              >
                <h2>{section.heading}</h2>
                {section.paragraphs.map((paragraph, index) => (
                  <p key={`${section.id}-p-${index}`}>{paragraph}</p>
                ))}
                {section.bullets.length ? (
                  <ul>
                    {section.bullets.map((bullet, index) => (
                      <li key={`${section.id}-b-${index}`}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </section>
            ))}
          </article>
        </div>
      </section>
    </main>
  )
}
