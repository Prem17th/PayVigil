import { useState } from 'react'
import { Building2, Check, FileCheck2, LoaderCircle, RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/use-api'
import { request } from '../lib/api'
import type { SupplierView } from '../lib/payments'
import { Button } from './ui/button'
import { SupplierInbox } from './delivery-panel'
import { ActionError, AuditTimeline, Checkpoint, HoldReasons } from './payment-primitives'

function ConfirmationCard({ supplier, token, refresh }: { supplier: SupplierView; token: string; refresh: () => void }) {
  const [reviewed, setReviewed] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const beneficiary = supplier.current_beneficiary
  async function confirm() {
    if (!beneficiary || !reviewed || pending) return
    setPending(true); setError(null)
    try {
      await request(`/api/suppliers/${supplier.id}/confirmations`, { method: 'POST', token, body: { beneficiary_version_id: beneficiary.id } })
      setReviewed(false); refresh()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Confirmation failed.') }
    finally { setPending(false) }
  }
  return <section className="panel supplier-request-card" id={`supplier-request-${supplier.id}`} tabIndex={-1}><div className="supplier-record-heading"><span className="service-icon"><Building2 size={22} /></span><div><span className="eyebrow">ASSIGNED SUPPLIER RECORD</span><h2>{supplier.name}</h2></div>{beneficiary ? <span className="version-label">Version {beneficiary.version}</span> : null}</div>{beneficiary ? <><dl className="snapshot-fields"><div><dt>Beneficiary name</dt><dd>{beneficiary.beneficiary_name}</dd></div><div><dt>Synthetic destination</dt><dd className="mono">{beneficiary.sandbox_account_id}</dd></div><div><dt>Version identifier</dt><dd className="mono small-value">{beneficiary.id}</dd></div></dl><div className="checkpoint-row"><Checkpoint label="Supplier confirmed" done={Boolean(beneficiary.confirmation)} /><Checkpoint label="Finance accepted" done={Boolean(beneficiary.acceptance)} /></div>{supplier.allowed_actions.includes('confirm') ? <div className="confirmation-action"><label className="review-checkbox"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} /><span>I confirm the beneficiary name and synthetic destination shown above for this exact version.</span></label><Button onClick={confirm} disabled={!reviewed || pending}>{pending ? <LoaderCircle className="spin" /> : <Check />}Confirm beneficiary details</Button></div> : beneficiary.confirmation ? <p className="supplier-confirmed-note"><Check size={15} />Your confirmation is recorded for this version.</p> : null}<p className="authority-note">Your confirmation is an attestation of these details. It does not prove bank-account ownership or approve a payment.</p></> : <p className="payment-empty-copy">Finance has not proposed a beneficiary for this supplier.</p>}<ActionError error={error} /><HoldReasons reasons={supplier.hold_reasons} /><AuditTimeline events={supplier.audit_events} /></section>
}

export function SupplierRequests({ token }: { token: string }) {
  const [revision, setRevision] = useState(0)
  const result = useApi<{ suppliers: SupplierView[] }>('/api/supplier/requests', token, true, revision)
  const refresh = () => setRevision(value => value + 1)
  return <><div className="page-heading"><div><span className="eyebrow">SUPPLIER CONFIRMATIONS</span><h1>Your details. Your confirmation.</h1><p>Review the exact beneficiary version assigned to your supplier account.</p></div><Button variant="outline" onClick={refresh} disabled={result.loading}><RefreshCw className={result.loading ? 'spin' : ''} />Refresh</Button></div><SupplierInbox token={token} suppliers={result.data?.suppliers ?? []} /><ActionError error={result.error} />{result.loading ? <div className="loading-state" role="status"><LoaderCircle className="spin" size={22} />Checking assigned requests…</div> : result.data?.suppliers.length ? <div className="supplier-requests-list">{result.data.suppliers.map(supplier => <ConfirmationCard key={`${supplier.id}:${supplier.current_beneficiary?.id ?? 'none'}`} supplier={supplier} token={token} refresh={refresh} />)}</div> : result.data ? <section className="panel payment-empty"><FileCheck2 size={32} /><h2>No supplier assignments yet.</h2><p>An administrator must assign your identity to a supplier before you can confirm details.</p></section> : null}</>
}
