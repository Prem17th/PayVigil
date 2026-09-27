import { useState } from 'react'
import { ArrowUpRight, CreditCard, Download, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { useApi } from '../hooks/use-api'
import { useDownload } from '../hooks/use-download'
import { request } from '../lib/api'
import { checkoutDestination, type BillingStatus, type Checkout } from '../lib/integrations'
import type { PaymentView } from '../lib/payments'
import { displayTime } from '../lib/payments'
import { ActionError } from './payment-primitives'
import { Button } from './ui/button'

export function BillingWorkspace({ token }: { token: string }) {
  const [revision, setRevision] = useState(0)
  const [pending, setPending] = useState<'checkout' | 'reconcile' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [paymentId, setPaymentId] = useState('')
  const billing = useApi<BillingStatus>('/api/billing', token, true, revision)
  const payments = useApi<{ payments: PaymentView[] }>('/api/payments', token)
  const download = useDownload(token)
  const destination = checkout ? checkoutDestination(checkout.checkout_url) : null
  const mayCreate = billing.data?.mode === 'test' && billing.data.configured && ['NONE', 'CANCELLED', 'EXPIRED', 'FAILED'].includes(billing.data.status)
  async function action(type: 'checkout' | 'reconcile') {
    if (pending || billing.data?.mode !== 'test' || !billing.data.configured || (type === 'checkout' && !mayCreate)) return
    setPending(type); setError(null)
    try {
      if (type === 'checkout') {
        const result = await request<Checkout>('/api/billing/checkout', { method: 'POST', token, body: {}, timeoutMs: 45000 })
        if (!checkoutDestination(result.checkout_url)) throw new Error('Checkout returned an unrecognised destination. No checkout link was opened.')
        setCheckout(result)
        setRevision(value => value + 1)
      } else {
        await request<BillingStatus>('/api/billing/reconcile', { method: 'POST', token, body: {}, timeoutMs: 45000 })
        setRevision(value => value + 1)
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Billing could not be updated.'); setRevision(value => value + 1) }
    finally { setPending(null) }
  }
  return <><div className="page-heading"><div><span className="eyebrow">WORKSPACE SUBSCRIPTION</span><h1>Reports are premium. Safety stays available.</h1><p>Dodo handles the PayVigil subscription in test mode. Supplier transfers remain separate.</p></div><Button variant="outline" onClick={() => setRevision(value => value + 1)} disabled={billing.loading}><RefreshCw className={billing.loading ? 'spin' : ''} />Refresh</Button></div><div className="billing-scope"><ShieldCheck size={19} /><p>Beneficiary checks, payment holds, human approvals, and reconciliation are available regardless of subscription status.</p></div><ActionError error={error ?? billing.error ?? (billing.data && billing.data.mode !== 'test' ? 'Billing is not in verified test mode. Checkout is disabled.' : null)} /><div className="billing-layout"><section className="panel billing-card"><div className="billing-card-heading"><span className="service-icon"><CreditCard size={23} /></span><span className="billing-test-label">TEST MODE ONLY</span></div><h2>PayVigil reports</h2><p>Download a structured evidence report for a payment when the server confirms your subscription entitlement.</p><dl className="snapshot-fields"><div><dt>Configuration</dt><dd>{billing.loading ? 'Checking…' : billing.data?.configured ? 'Present · live checks separate' : billing.data ? 'Not configured' : 'Unknown'}</dd></div><div><dt>Subscription status</dt><dd>{billing.data?.status.replace(/_/g, ' ') ?? 'Not verified'}</dd></div><div><dt>Report access</dt><dd>{billing.data ? billing.data.entitled ? 'Entitled by server' : 'Not entitled' : 'Not verified'}</dd></div><div><dt>Entitlement expiry</dt><dd>{billing.data?.expires_at ? displayTime(billing.data.expires_at) : '—'}</dd></div></dl><div className="billing-actions"><Button disabled={!mayCreate || Boolean(pending)} onClick={() => action('checkout')}>{pending === 'checkout' ? <LoaderCircle className="spin" /> : <CreditCard />}Create test checkout</Button><Button variant="outline" disabled={billing.data?.mode !== 'test' || !billing.data.configured || Boolean(pending)} onClick={() => action('reconcile')}>{pending === 'reconcile' ? <LoaderCircle className="spin" /> : <RefreshCw />}Reconcile subscription</Button></div>{billing.data && ['UNKNOWN', 'CHECKOUT_PENDING'].includes(billing.data.status) ? <p className="authority-note">A checkout operation is pending or unconfirmed. Reconcile its status before creating another checkout.</p> : null}{destination ? <div className="checkout-ready"><strong>Test checkout link created.</strong><p>Opening or returning from checkout does not grant access. The server must verify the resulting subscription.</p><Button asChild variant="outline"><a href={destination} target="_blank" rel="noopener noreferrer">Open Dodo test checkout<ArrowUpRight /></a></Button></div> : null}{billing.data && !billing.data.configured ? <p className="unconfigured-note">Dodo credentials and a test product are required before checkout is available.</p> : null}</section><section className="panel report-card"><span className="eyebrow">EVIDENCE EXPORT</span><h2>A record you can inspect.</h2><p>Reports include the payment’s persisted evidence and decisions. Export access never changes payment authority.</p><label className="report-select">Payment<select value={paymentId} onChange={event => setPaymentId(event.target.value)}><option value="">Choose a payment</option>{payments.data?.payments.map(payment => <option key={payment.id} value={payment.id}>{payment.invoice_reference} · {payment.supplier_name}</option>)}</select></label><Button variant="outline" disabled={!paymentId || !billing.data?.entitled || download.pending} onClick={() => download.download(`/api/payments/${paymentId}/report`, `payvigil-report-${paymentId}.json`, ['application/json'])}>{download.pending ? <LoaderCircle className="spin" /> : <Download />}Download JSON report</Button><ActionError error={download.error ?? payments.error} /><p className="authority-note">The API checks current entitlement again when the file is requested.</p></section></div></>
}
