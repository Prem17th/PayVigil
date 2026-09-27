import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, Building2, Check, CirclePlus, FileCheck2, LoaderCircle, RefreshCw, Send, ShieldCheck, Wallet } from 'lucide-react'
import { request } from '../lib/api'
import { useApi } from '../hooks/use-api'
import { providerConfigured, type Integrations } from '../lib/integrations'
import { SupplierDeliveryPanel } from './delivery-panel'
import { displayTime, money, simulationNames, toMinor, type PaymentView, type Simulation, type SupplierView } from '../lib/payments'
import { Button } from './ui/button'
import { ActionError, AuditTimeline, Checkpoint, HoldReasons, PaymentBadge } from './payment-primitives'

function useWorkspaceData(token: string, revision: number) {
  const [data, setData] = useState<{ owner: string; suppliers: SupplierView[]; payments: PaymentView[]; error: string | null; loading: boolean }>({ owner: '', suppliers: [], payments: [], error: null, loading: true })
  useEffect(() => {
    const controller = new AbortController()
    setData(previous => previous.owner === token ? { ...previous, loading: true, error: null } : { owner: token, suppliers: [], payments: [], error: null, loading: true })
    Promise.allSettled([
      request<{ suppliers: SupplierView[] }>('/api/suppliers', { token, signal: controller.signal }),
      request<{ payments: PaymentView[] }>('/api/payments', { token, signal: controller.signal }),
    ]).then(([suppliers, payments]) => {
      if (controller.signal.aborted) return
      const errors = [suppliers, payments].filter(result => result.status === 'rejected').map(result => result.status === 'rejected' && result.reason instanceof Error ? result.reason.message : 'The workspace could not be loaded.')
      setData(previous => ({ owner: token, suppliers: suppliers.status === 'fulfilled' ? suppliers.value.suppliers : previous.owner === token ? previous.suppliers : [], payments: payments.status === 'fulfilled' ? payments.value.payments : previous.owner === token ? previous.payments : [], error: errors.length ? [...new Set(errors)].join(' ') : null, loading: false }))
    })
    return () => controller.abort()
  }, [token, revision])
  return data.owner === token ? data : { suppliers: [], payments: [], error: null, loading: true }
}

function SimulationField({ value, onChange }: { value: Simulation; onChange: (value: Simulation) => void }) {
  return <label>Sandbox outcome<select value={value} onChange={event => onChange(event.target.value as Simulation)}>{Object.entries(simulationNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select><small>This scenario is part of the approved payment snapshot.</small></label>
}

function SupplierRecord({ supplier, token, onChange, deliveryConfigured }: { supplier: SupplierView; token: string; onChange: () => void; deliveryConfigured: boolean | null }) {
  const beneficiary = supplier.current_beneficiary
  const [name, setName] = useState(beneficiary?.beneficiary_name ?? supplier.name)
  const [destination, setDestination] = useState('')
  const [showProposal, setShowProposal] = useState(!beneficiary)
  const [accepted, setAccepted] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function mutate(path: string, body: Record<string, unknown>) {
    if (pending) return
    setPending(true); setError(null)
    try { await request(path, { token, method: 'POST', body }); setAccepted(false); setShowProposal(false); onChange() }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Supplier update failed.') }
    finally { setPending(false) }
  }
  function propose(event: FormEvent) {
    event.preventDefault()
    if (!/^SIM-[A-Z0-9-]{3,64}$/.test(destination.trim())) { setError('Use SIM- followed by 3–64 uppercase letters, numbers, or hyphens.'); return }
    void mutate(`/api/suppliers/${supplier.id}/beneficiaries`, { beneficiary_name: name.trim(), sandbox_account_id: destination.trim(), expected_version_id: beneficiary?.id ?? null })
  }
  return <section className="panel supplier-record"><div className="supplier-record-heading"><span className="service-icon"><Building2 size={21} /></span><div><span className="eyebrow">BENEFICIARY RECORD</span><h2>{supplier.name}</h2></div>{beneficiary ? <span className="version-label">Version {beneficiary.version}</span> : null}</div>{beneficiary ? <><dl className="snapshot-fields"><div><dt>Beneficiary name</dt><dd>{beneficiary.beneficiary_name}</dd></div><div><dt>Synthetic destination</dt><dd className="mono">{beneficiary.sandbox_account_id}</dd></div></dl><div className="checkpoint-row"><Checkpoint label="Supplier confirmed" done={Boolean(beneficiary.confirmation)} /><Checkpoint label="Finance accepted" done={Boolean(beneficiary.acceptance)} /></div>{supplier.allowed_actions.includes('accept') ? <div className="confirmation-action"><label className="review-checkbox"><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} /><span>I accept this supplier-confirmed beneficiary version for future payment review.</span></label><Button disabled={!accepted || pending} onClick={() => mutate(`/api/suppliers/${supplier.id}/acceptances`, { beneficiary_version_id: beneficiary.id })}>{pending ? <LoaderCircle className="spin" /> : <ShieldCheck />}Accept beneficiary version</Button></div> : null}</> : <p className="payment-empty-copy">Add a synthetic beneficiary to begin the confirmation process.</p>}<ActionError error={error} /><HoldReasons reasons={supplier.hold_reasons} />{supplier.allowed_actions.includes('add_beneficiary') ? <>{beneficiary ? <Button variant="outline" size="sm" onClick={() => setShowProposal(value => !value)} disabled={pending}><CirclePlus />{showProposal ? 'Close proposal' : 'Propose beneficiary change'}</Button> : null}{showProposal ? <form className="payment-form beneficiary-form" onSubmit={propose}><label>Beneficiary name<input value={name} onChange={event => setName(event.target.value)} required maxLength={160} /></label><label>Synthetic destination<input value={destination} onChange={event => setDestination(event.target.value)} placeholder="SIM-SUPPLIER-002" required maxLength={68} pattern="SIM-[A-Z0-9\-]{3,64}" autoComplete="off" /></label><p className="authority-note">A new version needs fresh supplier confirmation and finance acceptance. Existing payment approvals become stale.</p><Button type="submit" disabled={pending}>{pending ? <LoaderCircle className="spin" /> : <CirclePlus />}Propose version</Button></form> : null}</> : null}<SupplierDeliveryPanel key={beneficiary?.id ?? "none"} supplier={supplier} token={token} configured={deliveryConfigured} /><AuditTimeline events={supplier.audit_events} /></section>
}

function CreatePayment({ suppliers, token, onCreated }: { suppliers: SupplierView[]; token: string; onCreated: (id: string) => void }) {
  const [supplierId, setSupplierId] = useState(suppliers[0]?.id ?? '')
  const [invoice, setInvoice] = useState('')
  const [amount, setAmount] = useState('')
  const [simulation, setSimulation] = useState<Simulation>('success')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function create(event: FormEvent) {
    event.preventDefault()
    const amountMinor = toMinor(amount)
    if (!amountMinor) { setError('Enter a positive INR amount up to ₹10,00,00,00,000 with no more than two decimal places.'); return }
    if (!supplierId || pending) return
    setPending(true); setError(null)
    try {
      const payment = await request<PaymentView>('/api/payments', { token, method: 'POST', body: { supplier_id: supplierId, invoice_reference: invoice.trim(), amount_minor: amountMinor, currency: 'INR', simulation } })
      onCreated(payment.id)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Payment creation failed.') }
    finally { setPending(false) }
  }
  return <section className="panel create-payment"><span className="eyebrow">A NEW PAYMENT INTENT</span><h2>Define what finance will review.</h2><p className="payment-empty-copy">Synthetic INR only. Creating an intent does not approve or execute a transfer.</p><form className="payment-form" onSubmit={create}><label>Supplier<select value={supplierId} onChange={event => setSupplierId(event.target.value)} required><option value="" disabled>Select supplier</option>{suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label><div className="form-pair"><label>Invoice reference<input value={invoice} onChange={event => setInvoice(event.target.value)} required maxLength={80} placeholder="TEST-INV-001" autoComplete="off" /></label><label>Amount · INR<input inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} required placeholder="0.00" autoComplete="off" /></label></div><SimulationField value={simulation} onChange={setSimulation} /><ActionError error={error} /><Button type="submit" disabled={pending || !suppliers.length}>{pending ? <LoaderCircle className="spin" /> : <CirclePlus />}Create payment intent</Button></form></section>
}

function PaymentDetail({ payment, token, onChange }: { payment: PaymentView; token: string; onChange: () => void }) {
  const revision = payment.current_revision
  const [reviewed, setReviewed] = useState(false)
  const [revising, setRevising] = useState(false)
  const [amount, setAmount] = useState((revision.amount_minor / 100).toFixed(2))
  const [simulation, setSimulation] = useState<Simulation>(revision.simulation)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const queueKey = useRef(crypto.randomUUID())
  const uncertain = payment.state === 'UNKNOWN'
  async function action(name: 'approvals' | 'queue' | 'revisions', body: Record<string, unknown>) {
    if (pending || (name === 'queue' && uncertain)) return
    setPending(name); setError(null)
    try {
      await request<PaymentView>(`/api/payments/${payment.id}/${name}`, { token, method: 'POST', body, ...(name === 'queue' ? { idempotencyKey: queueKey.current } : {}) })
      setReviewed(false); setRevising(false); onChange()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'The requested action failed.'); onChange() }
    finally { setPending(null) }
  }
  function revise(event: FormEvent) {
    event.preventDefault()
    const amountMinor = toMinor(amount)
    if (!amountMinor) { setError('Enter a positive INR amount up to ₹10,00,00,00,000 with no more than two decimal places.'); return }
    void action('revisions', { expected_revision_id: revision.id, amount_minor: amountMinor, simulation })
  }
  return <section className="panel payment-detail"><div className="payment-detail-heading"><div><span className="eyebrow">EXACT PAYMENT SNAPSHOT</span><h2>{payment.invoice_reference}</h2><p>{payment.supplier_name}</p></div><PaymentBadge state={payment.state} /></div><div className="payment-amount"><strong>{money(revision.amount_minor)}</strong><span>INR · synthetic funds</span><span className="version-label">Revision {revision.version}</span></div><dl className="snapshot-fields"><div><dt>Beneficiary</dt><dd>{revision.beneficiary_name}</dd></div><div><dt>Synthetic destination</dt><dd className="mono">{revision.sandbox_account_id}</dd></div><div><dt>Scenario</dt><dd>{simulationNames[revision.simulation]}</dd></div><div><dt>Beneficiary version</dt><dd className="mono small-value">{revision.beneficiary_version_id}</dd></div><div><dt>Payment revision</dt><dd className="mono small-value">{revision.id}</dd></div></dl><details className="digest-details"><summary>Approval fingerprint <ShieldCheck size={13} /></summary><code>{revision.digest}</code><p>This server-issued digest binds the invoice, supplier, amount, destination, currency, and scenario.</p></details>{uncertain ? <div className="unknown-notice" role="status"><LoaderCircle size={20} className="spin" /><div><strong>The execution outcome is unknown.</strong><p>The worker is checking the same execution identifier with the independent sandbox. No replacement transfer is permitted. A missing readback is not proof of failure.</p></div></div> : null}{payment.state === 'SUCCEEDED' ? <div className="success-notice"><Check size={20} /><div><strong>Independent readback verified.</strong><p>The sandbox result matches the approved snapshot. No real funds moved.</p></div></div> : null}{payment.state === 'FAILED' ? <div className="payment-error"><FileCheck2 size={19} /><div><strong>Terminal sandbox rejection.</strong><p>This execution is not automatically retried.</p></div></div> : null}<ActionError error={error} /><HoldReasons reasons={payment.hold_reasons} />{payment.approval ? <div className="approval-record"><ShieldCheck size={18} /><div><strong>Exact revision approved</strong><p>Expires {displayTime(payment.approval.expires_at)}</p></div></div> : null}{payment.allowed_actions.includes('approve') && !uncertain ? <div className="approval-action"><label className="review-checkbox"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} /><span>I reviewed the invoice, supplier, INR amount, beneficiary, and scenario above. I approve only this exact revision.</span></label><Button disabled={!reviewed || Boolean(pending)} onClick={() => action('approvals', { revision_id: revision.id, digest: revision.digest })}>{pending === 'approvals' ? <LoaderCircle className="spin" /> : <ShieldCheck />}Approve exact snapshot</Button></div> : null}{payment.allowed_actions.includes('queue') && !uncertain ? <div className="queue-action"><Button disabled={Boolean(pending)} onClick={() => action('queue', { revision_id: revision.id, digest: revision.digest })}>{pending === 'queue' ? <LoaderCircle className="spin" /> : <Send />}Queue sandbox transfer</Button><p>The worker rechecks authority before execution. The transfer is simulated.</p></div> : null}{payment.allowed_actions.includes('revise') && !uncertain ? <><Button variant="outline" size="sm" disabled={Boolean(pending)} onClick={() => setRevising(value => !value)}>{revising ? 'Cancel revision' : 'Revise payment snapshot'}<ArrowRight /></Button>{revising ? <form className="payment-form revision-form" onSubmit={revise}><label>Revised amount · INR<input inputMode="decimal" required value={amount} onChange={event => setAmount(event.target.value)} /></label><SimulationField value={simulation} onChange={setSimulation} /><p className="authority-note">This creates a new immutable revision using the supplier’s current beneficiary. A fresh payment approval is required.</p><Button type="submit" disabled={Boolean(pending)}>{pending === 'revisions' ? <LoaderCircle className="spin" /> : <CirclePlus />}Save new revision</Button></form> : null}</> : null}{payment.execution ? <div className="execution-record"><span className="eyebrow">PERSISTED EXECUTION</span><dl className="snapshot-fields"><div><dt>Execution identifier</dt><dd className="mono small-value">{payment.execution.id}</dd></div><div><dt>Sandbox transfer</dt><dd className="mono small-value">{payment.execution.transfer_id ?? 'Awaiting independent confirmation'}</dd></div></dl></div> : null}<AuditTimeline events={payment.audit_events} /></section>
}

export function PaymentWorkspace({ token }: { token: string }) {
  const [revision, setRevision] = useState(0)
  const [tab, setTab] = useState<'payments' | 'suppliers'>('payments')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newSupplier, setNewSupplier] = useState('')
  const [adding, setAdding] = useState(false)
  const [supplierError, setSupplierError] = useState<string | null>(null)
  const [pollPaused, setPollPaused] = useState(false)
  const data = useWorkspaceData(token, revision)
  const integrations = useApi<Integrations>('/api/integrations', token)
  const active = data.payments.some(payment => ['QUEUED', 'SUBMITTING', 'UNKNOWN'].includes(payment.state))
  const refresh = () => setRevision(value => value + 1)
  useEffect(() => {
    if (!active) { setPollPaused(false); return }
    let count = 0
    const interval = window.setInterval(() => {
      if (count >= 30) { window.clearInterval(interval); setPollPaused(true); return }
      count += 1; setRevision(value => value + 1)
    }, 4000)
    return () => clearInterval(interval)
  }, [active, token])
  const selected = data.payments.find(payment => payment.id === selectedId) ?? data.payments[0]
  async function addSupplier(event: FormEvent) {
    event.preventDefault()
    if (adding) return
    setAdding(true); setSupplierError(null)
    try { await request<SupplierView>('/api/suppliers', { token, method: 'POST', body: { name: newSupplier.trim() } }); setNewSupplier(''); refresh() }
    catch (failure) { setSupplierError(failure instanceof Error ? failure.message : 'Supplier creation failed.') }
    finally { setAdding(false) }
  }
  return <><div className="page-heading"><div><span className="eyebrow">PAYMENT AUTHORITY · PHASE 03</span><h1>Every detail. Every decision.</h1><p>Separate confirmation, acceptance, and approval — with independent sandbox readback.</p></div><Button variant="outline" onClick={refresh} disabled={data.loading}><RefreshCw className={data.loading ? 'spin' : ''} />Refresh</Button></div><div className="payment-scope-note"><ShieldCheck size={16} /><span>Supplier transfers are simulated. Only destinations beginning with <strong>SIM-</strong> are accepted.</span></div><div className="workspace-tabs" role="tablist" aria-label="Payment workspace sections" onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'payments' : event.key === 'End' ? 'suppliers' : tab === 'payments' ? 'suppliers' : 'payments'; setTab(next); document.getElementById(`tab-${next}`)?.focus() } }}><button role="tab" type="button" id="tab-payments" tabIndex={tab === 'payments' ? 0 : -1} aria-selected={tab === 'payments'} aria-controls="panel-payments" onClick={() => setTab('payments')}><Wallet size={16} />Payment intents</button><button role="tab" type="button" id="tab-suppliers" tabIndex={tab === 'suppliers' ? 0 : -1} aria-selected={tab === 'suppliers'} aria-controls="panel-suppliers" onClick={() => setTab('suppliers')}><Building2 size={16} />Supplier records</button></div><ActionError error={data.error} />{tab === 'suppliers' ? <section role="tabpanel" id="panel-suppliers" aria-labelledby="tab-suppliers" tabIndex={0}><form className="add-supplier-form payment-form" onSubmit={addSupplier}><label htmlFor="new-supplier">Add a supplier record<input id="new-supplier" value={newSupplier} onChange={event => setNewSupplier(event.target.value)} required maxLength={160} placeholder="Synthetic supplier name" /></label><Button disabled={adding || !newSupplier.trim()} type="submit">{adding ? <LoaderCircle className="spin" /> : <CirclePlus />}Add supplier</Button></form><ActionError error={supplierError} /><p className="authority-note supplier-assignment-note">Supplier identities must be assigned to records by an administrator. Creating a record does not assign access.</p><div className="supplier-record-grid">{data.suppliers.map(supplier => <SupplierRecord key={`${supplier.id}:${supplier.current_beneficiary?.id ?? 'none'}`} supplier={supplier} token={token} onChange={refresh} deliveryConfigured={integrations.data ? providerConfigured(integrations.data, 'n8n') : null} />)}</div>{!data.suppliers.length ? <div className="payment-empty panel"><Building2 size={30} /><h2>{data.loading ? 'Loading suppliers…' : 'Start with a supplier record.'}</h2><p>Record a synthetic beneficiary, then obtain confirmation from its assigned supplier identity.</p></div> : null}</section> : <section role="tabpanel" id="panel-payments" aria-labelledby="tab-payments" tabIndex={0}>{active ? <div className="poll-status" role="status"><span className={!pollPaused ? 'pulse-dot' : ''} />{pollPaused ? 'Automatic status checks paused after two minutes. Refresh to read the latest state; reconciliation continues on the server.' : 'Reading execution status every 4 seconds. No transfer requests are retried.'}</div> : null}<div className="payments-layout"><section className="payment-list panel"><div className="payment-list-heading"><h2>Payment intents</h2><Button size="sm" variant="outline" onClick={() => setCreating(value => !value)}><CirclePlus />{creating ? 'Close' : 'New'}</Button></div>{data.payments.map(payment => <button type="button" className={`payment-list-item ${!creating && payment.id === selected?.id ? 'selected' : ''}`} key={payment.id} onClick={() => { setSelectedId(payment.id); setCreating(false) }} aria-pressed={!creating && payment.id === selected?.id}><div><strong>{payment.invoice_reference}</strong><span>{money(payment.current_revision.amount_minor)}</span></div><p>{payment.supplier_name}</p><PaymentBadge state={payment.state} /></button>)}{!data.payments.length ? <div className="list-empty"><FileCheck2 size={25} /><p>{data.loading ? 'Loading payment intents…' : 'No payment intents yet.'}</p><span>Your actual payment records will appear here.</span></div> : null}</section><div className="payment-detail-column">{creating ? <CreatePayment key={data.suppliers.map(s => s.id).join(':')} suppliers={data.suppliers} token={token} onCreated={id => { setSelectedId(id); setCreating(false); refresh() }} /> : selected ? <PaymentDetail key={`${selected.id}:${selected.current_revision.id}:${selected.current_revision.digest}`} payment={selected} token={token} onChange={refresh} /> : <div className="panel payment-empty"><ShieldCheck size={35} strokeWidth={1.4} /><h2>Begin with an exact payment intent.</h2><p>Add supplier details first, then define the invoice and amount for human review.</p><Button onClick={() => setCreating(true)}><CirclePlus />Create payment intent</Button></div>}</div></div></section>}</>
}
