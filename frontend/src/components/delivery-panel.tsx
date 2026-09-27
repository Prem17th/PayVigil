import { useState } from 'react'
import { Inbox, LoaderCircle, RefreshCw, Send } from 'lucide-react'
import { useApi } from '../hooks/use-api'
import { request } from '../lib/api'
import type { Delivery } from '../lib/integrations'
import { displayTime, type SupplierView } from '../lib/payments'
import { ActionError } from './payment-primitives'
import { Button } from './ui/button'

function DeliveryList({ deliveries, remind, pending, currentVersionId, confirmed }: { deliveries: Delivery[]; remind?: (id: string) => void; pending?: string | null; currentVersionId?: string; confirmed: boolean }) {
  return <ol className="delivery-list">{deliveries.map(delivery => <li key={delivery.id}><div><strong>{delivery.status.replace(/_/g, ' ')}</strong><span>{displayTime(delivery.created_at)}</span></div><p>Beneficiary version <code>{delivery.beneficiary_version_id.slice(0, 8)}</code> · {delivery.attempts} {delivery.attempts === 1 ? 'attempt' : 'attempts'}</p>{delivery.delivered_at ? <small>Delivery recorded {displayTime(delivery.delivered_at)}</small> : null}{delivery.beneficiary_version_id !== currentVersionId ? <small>Previous beneficiary version · reminders disabled</small> : null}{remind && !confirmed && delivery.attempts < 3 && delivery.beneficiary_version_id === currentVersionId && delivery.status === 'DELIVERED' && delivery.delivered_at ? <Button size="sm" variant="outline" disabled={Boolean(pending)} onClick={() => remind(delivery.id)}>{pending === delivery.id ? <LoaderCircle className="spin" /> : <RefreshCw />}Request reminder</Button> : null}</li>)}</ol>
}

export function SupplierDeliveryPanel({ supplier, token, configured }: { supplier: SupplierView; token: string; configured: boolean | null }) {
  const [revision, setRevision] = useState(0)
  const [approved, setApproved] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const deliveries = useApi<{ deliveries: Delivery[] }>(`/api/suppliers/${supplier.id}/deliveries`, token, true, revision)
  const currentBeneficiary = supplier.current_beneficiary
  const currentDelivery = deliveries.data?.deliveries.find(delivery => delivery.beneficiary_version_id === currentBeneficiary?.id && delivery.status !== 'FAILED')
  const mayRequest = configured && Boolean(currentBeneficiary) && !currentBeneficiary?.confirmation && Boolean(deliveries.data) && !currentDelivery
  async function deliver(reminderId?: string) {
    const version = supplier.current_beneficiary
    if (!configured || !version || version.confirmation || pending || (!reminderId && (!approved || !mayRequest))) return
    setPending(reminderId ?? 'request'); setError(null); setNotice(null)
    try {
      const result = await request<Delivery>(reminderId ? `/api/deliveries/${reminderId}/reminders` : `/api/suppliers/${supplier.id}/deliveries`, { token, method: 'POST', body: reminderId ? {} : { beneficiary_version_id: version.id }, timeoutMs: 45000 })
      setNotice(`Delivery request recorded with status: ${result.status.replace(/_/g, ' ')}.`)
      setApproved(false); setRevision(value => value + 1)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Delivery outcome was not confirmed.'); setRevision(value => value + 1) }
    finally { setPending(null); setApproved(false) }
  }
  return <details className="delivery-panel"><summary><Send size={14} />Supplier inbox delivery<span>n8n</span></summary><p className="authority-note">The server selects the assigned supplier’s inbox. Delivery status cannot confirm a beneficiary or approve a payment.</p>{configured ? <><label className="review-checkbox"><input type="checkbox" checked={approved} onChange={event => setApproved(event.target.checked)} disabled={!mayRequest || Boolean(pending)} /><span>I approve delivery of a confirmation request for the current beneficiary version to its assigned supplier.</span></label><Button size="sm" disabled={!approved || !mayRequest || Boolean(pending)} onClick={() => deliver()}>{pending === 'request' ? <LoaderCircle className="spin" /> : <Send />}Approve and request delivery</Button>{currentBeneficiary?.confirmation ? <p className="authority-note">This beneficiary version is already confirmed by its supplier.</p> : currentDelivery ? <p className="authority-note">A request already exists for this version. Refresh its recorded status before taking another action. Reminders require a delivered request and remain limited by the server.</p> : null}</> : <p className="unconfigured-note">{configured === null ? 'n8n configuration is unavailable. Refresh connection status before delivery.' : 'n8n is not configured. Delivery remains unavailable until server credentials are added.'}</p>}<Button size="sm" variant="ghost" disabled={deliveries.loading || Boolean(pending)} onClick={() => setRevision(value => value + 1)}><RefreshCw className={deliveries.loading ? 'spin' : ''} />Refresh delivery status</Button><ActionError error={error ?? deliveries.error} />{notice ? <p className="operation-notice" role="status">{notice}</p> : null}{deliveries.loading ? <p className="provider-loading">Checking delivery records…</p> : deliveries.data?.deliveries.length ? <DeliveryList deliveries={deliveries.data.deliveries} currentVersionId={supplier.current_beneficiary?.id} confirmed={Boolean(currentBeneficiary?.confirmation)} remind={configured ? id => deliver(id) : undefined} pending={pending} /> : <p className="authority-note">No delivery records returned.</p>}</details>
}

export function SupplierInbox({ token, suppliers }: { token: string; suppliers: SupplierView[] }) {
  const [revision, setRevision] = useState(0)
  const inbox = useApi<{ deliveries: Delivery[] }>('/api/supplier/inbox', token, true, revision)
  return <section className="panel supplier-inbox"><div className="panel-heading"><div><span className="eyebrow">YOUR ASSIGNED INBOX</span><h2>Confirmation deliveries</h2></div><Button variant="ghost" size="icon" aria-label="Refresh supplier inbox" onClick={() => setRevision(value => value + 1)} disabled={inbox.loading}><RefreshCw className={inbox.loading ? 'spin' : ''} /></Button></div><ActionError error={inbox.error} />{inbox.loading ? <p className="provider-loading" role="status">Checking your inbox…</p> : inbox.data?.deliveries.length ? <div className="supplier-inbox-items">{inbox.data.deliveries.map(delivery => {
    const supplier = suppliers.find(item => item.id === delivery.supplier_id)
    const current = supplier?.current_beneficiary?.id === delivery.beneficiary_version_id
    return <div key={delivery.id}><Inbox size={18} /><div><strong>{supplier?.name ?? 'Assigned supplier request'}</strong><p>{delivery.status.replace(/_/g, ' ')} · {displayTime(delivery.created_at)}</p><small>{current ? 'Current beneficiary version' : 'Previous or unavailable version — do not confirm from this request.'}</small></div>{current ? <Button size="sm" variant="outline" onClick={() => { const card = document.getElementById(`supplier-request-${delivery.supplier_id}`); card?.scrollIntoView({ behavior: 'smooth', block: 'start' }); card?.focus() }}>Review details</Button> : null}</div>
  })}</div> : <div className="inbox-empty"><Inbox size={20} /><p>No confirmation deliveries have been returned for your account.</p></div>}<p className="authority-note">Review and confirmation remain separate from delivery.</p></section>
}
