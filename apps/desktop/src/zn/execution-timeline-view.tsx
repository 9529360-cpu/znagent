import type { TFunction } from 'i18next'
import { CheckCircle, CircleNotch, WarningCircle } from '@phosphor-icons/react'
import type { ZnExecutionAction } from './execution-timeline'

type Props = {
  actions: readonly ZnExecutionAction[]
  currentStage?: string
  locale: string
  t: TFunction
}

function actionTime(value: number | undefined, locale: string) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return {
    dateTime: date.toISOString(),
    label: new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date)
  }
}

/**
 * A read-only activity timeline, NEVER a second execution controller.
 * No synthetic retry: only the existing Resident approval/recovery path may
 * authorize actions after an error or uncertain external side effect.
 */
export function ZnExecutionTimeline({ actions, currentStage, locale, t }: Props) {
  if (actions.length === 0 && !currentStage) return null
  return (
    <div className="zn-execution-timeline" role="list" aria-label={t('trace.timelineAria')}>
      {actions.map((action, index) => {
        const time = actionTime(action.at, locale)
        return (
          <div
            className={'zn-trace-item ' + (action.success ? 'success' : 'failed')}
            role="listitem"
            key={index + '-' + action.kind + '-' + (action.at || 'unknown')}
          >
            <span className="zn-trace-icon" aria-hidden="true">
              {action.success
                ? <CheckCircle size={16} weight="fill" />
                : <WarningCircle size={16} weight="fill" />}
            </span>
            <div className="zn-trace-item-content">
              <div className="zn-trace-item-head">
                <strong>{action.kind}</strong>
                <span className="zn-trace-result">{t(action.success ? 'trace.succeeded' : 'trace.failed')}</span>
                {time ? <time dateTime={time.dateTime}>{time.label}</time> : null}
              </div>
              {action.summary ? (
                <details className="zn-trace-summary">
                  <summary>{t('trace.resultSummary')}</summary>
                  <pre>{action.summary}</pre>
                </details>
              ) : null}
            </div>
          </div>
        )
      })}
      {currentStage ? (
        <div className="zn-trace-item in-progress" role="listitem">
          <span className="zn-trace-icon" aria-hidden="true"><CircleNotch size={16} className="zn-spin" /></span>
          <div className="zn-trace-item-content">
            <div className="zn-trace-item-head">
              <strong>{currentStage}</strong>
              <span className="zn-trace-result">{t('trace.inProgress')}</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
