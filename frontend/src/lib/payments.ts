export type Simulation = 'success' | 'decline' | 'lost_response'
export type PaymentState = 'DRAFT' | 'APPROVED' | 'QUEUED' | 'SUBMITTING' | 'UNKNOWN' | 'SUCCEEDED' | 'FAILED'
export interface AuditEvent {
  id: string
  action: string
  actor_user_id: string | null
  created_at: string
  details: Record<string, unknown>
}
export interface BeneficiaryVersion {
  id: string
  version: number
  beneficiary_name: string
  sandbox_account_id: string
  created_at: string
  confirmation: { id: string; confirmed_at: string } | null
  acceptance: { id: string; accepted_at: string } | null
}
export interface SupplierView {
  id: string
  name: string
  current_beneficiary: BeneficiaryVersion | null
  allowed_actions: ('add_beneficiary' | 'confirm' | 'accept')[]
  hold_reasons: string[]
  audit_events: AuditEvent[]
}
export interface PaymentRevision {
  id: string
  version: number
  amount_minor: number
  currency: 'INR'
  beneficiary_version_id: string
  beneficiary_name: string
  sandbox_account_id: string
  simulation: Simulation
  digest: string
  created_at: string
}
export interface PaymentView {
  id: string
  supplier_id: string
  supplier_name: string
  invoice_reference: string
  state: PaymentState
  current_revision: PaymentRevision
  approval: { id: string; revision_id: string; digest: string; approved_at: string; expires_at: string } | null
  execution: { id: string; state: string; transfer_id: string | null; queued_at: string; updated_at: string } | null
  allowed_actions: ('revise' | 'approve' | 'queue')[]
  hold_reasons: string[]
  audit_events: AuditEvent[]
}

export const simulationNames: Record<Simulation, string> = {
  success: 'Successful sandbox transfer',
  decline: 'Sandbox rejection',
  lost_response: 'Lost response · independent reconciliation',
}

export function money(amount: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(amount / 100)
}

export function toMinor(value: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value.trim())) return null
  const [whole, fraction = ''] = value.trim().split('.')
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
  return Number.isSafeInteger(amount) && amount > 0 && amount <= 1_000_000_000_000 ? amount : null
}

export function displayTime(value: string) {
  return new Date(value).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
