import { Check, CircleAlert, Clock3, LockKeyhole } from 'lucide-react'
import { displayTime, type AuditEvent, type PaymentState } from '../lib/payments'
import { cn } from '../lib/utils'

const stateLabels: Record<PaymentState, string> = { DRAFT: 'Draft', APPROVED: 'Approved', QUEUED: 'Queued', SUBMITTING: 'Submitting', UNKNOWN: 'Outcome unknown', SUCCEEDED: 'Verified success', FAILED: 'Sandbox rejected' }

export function PaymentBadge({ state }: { state: PaymentState }) {
  return <span className={cn('payment-badge', `payment-state-${state.toLowerCase()}`)}><span />{stateLabels[state]}</span>
}

export function HoldReasons({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null
  return <div className="hold-reasons"><LockKeyhole size={15} /><div><strong>Before you can continue</strong><ul>{reasons.map(reason => <li key={reason}>{reason.replace(/_/g, ' ')}</li>)}</ul></div></div>
}

export function ActionError({ error }: { error: string | null }) {
  return error ? <div className="payment-error" role="alert"><CircleAlert size={17} /><span>{error}</span></div> : null
}

export function Checkpoint({ label, done }: { label: string; done: boolean }) {
  return <span className={cn('checkpoint', done && 'checkpoint-done')}>{done ? <Check size={13} /> : <Clock3 size={13} />}{label}</span>
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return <details className="audit-details"><summary>Audit history <span>{events.length} recorded {events.length === 1 ? 'event' : 'events'}</span></summary>{events.length ? <ol>{[...events].reverse().map(event => <li key={event.id}><span className="audit-dot" /><div><strong>{event.action.replace(/[_.]/g, ' ')}</strong><time dateTime={event.created_at}>{displayTime(event.created_at)}</time>{Object.keys(event.details).length ? <code>{JSON.stringify(event.details, null, 2)}</code> : null}<small>{event.actor_user_id ? `Authenticated actor · ${event.actor_user_id.slice(0, 8)}` : 'System worker'}</small></div></li>)}</ol> : <p>No events have been returned for this record.</p>}</details>
}
