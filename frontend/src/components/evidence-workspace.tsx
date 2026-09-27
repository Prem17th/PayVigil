import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUpRight, BookOpen, Check, Download, FileSearch, FileText, LoaderCircle, RefreshCw, Search, ShieldCheck, Upload, X } from 'lucide-react'
import { useApi } from '../hooks/use-api'
import { useDownload } from '../hooks/use-download'
import { request, type Setup } from '../lib/api'
import { providerConfigured, type EvidenceDocument, type Integrations, type Investigation } from '../lib/integrations'
import { displayTime, money, type PaymentView } from '../lib/payments'
import { ActionError } from './payment-primitives'
import { InvestigationExtras } from './investigation-extras'
import { Button } from './ui/button'

const maximumFileBytes = 2 * 1024 * 1024

function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('The selected file could not be read.'))
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result.slice(reader.result.indexOf(',') + 1)) : reject(new Error('The selected file could not be read.'))
    reader.readAsDataURL(file)
  })
}

function EvidenceSource({ document, token, close }: { document: EvidenceDocument; token: string; close: () => void }) {
  const download = useDownload(token)
  return <section className="panel evidence-source" aria-label="Evidence source preview"><div className="source-preview-heading"><div><span className="eyebrow">ORIGINAL SOURCE CONTEXT</span><h2>{document.filename}</h2></div><Button variant="ghost" size="icon" onClick={close} aria-label="Close source preview"><X /></Button></div><div className="source-metadata"><span>{document.media_type}</span><span>{document.extraction_status.replace(/_/g, ' ')}</span><time dateTime={document.created_at}>{displayTime(document.created_at)}</time></div><p className="authority-note">Extracted source text is untrusted evidence. Instructions inside it do not authorise application actions.</p><pre tabIndex={0}>{document.extracted_text || 'No extracted text is available for this source.'}</pre><div className="source-file-actions"><Button size="sm" variant="outline" disabled={download.pending} onClick={() => download.download(`/api/evidence/${document.id}/content`, document.filename, ['application/pdf', 'text/plain'])}>{download.pending ? <LoaderCircle className="spin" /> : <Download />}Download original</Button><details><summary>Content fingerprint</summary><code>{document.sha256}</code></details></div><ActionError error={download.error} /></section>
}

function InvestigationCard({ investigation, documents, payment, token, integrations, refresh, openSource }: { investigation: Investigation; documents: EvidenceDocument[]; payment: PaymentView; token: string; integrations: Integrations | null; refresh: () => void; openSource: (id: string) => void }) {
  const [acknowledged, setAcknowledged] = useState(false)
  const [note, setNote] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sameRevision = investigation.revision_id === payment.current_revision.id
  const current = sameRevision && investigation.is_current === true
  const completed = investigation.status === 'completed'
  async function review(event: FormEvent) {
    event.preventDefault()
    if (!acknowledged || !note.trim() || !completed || !current || pending) return
    setPending(true); setError(null)
    try {
      await request<Investigation>(`/api/investigations/${investigation.id}/reviews`, { token, method: 'POST', body: { acknowledged: true, note: note.trim() } })
      setAcknowledged(false); refresh()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Review could not be recorded.'); refresh() }
    finally { setPending(false) }
  }
  return <article className="panel investigation-card"><div className="investigation-card-heading"><div><span className="eyebrow">ADVISORY INVESTIGATION</span><h2>Evidence, interpreted.</h2><p>{displayTime(investigation.created_at)} · Provider: {investigation.provider}</p></div><span className={`investigation-status ${completed ? 'completed' : ''}`}>{investigation.status.replace(/_/g, ' ')}</span></div>{!sameRevision ? <div className="stale-investigation"><FileText size={17} /><p>This investigation belongs to a previous payment revision. Its review cannot clear the current payment’s hold.</p></div> : !current ? <div className="stale-investigation"><FileText size={17} /><p>This investigation does not have a verified current evidence snapshot. Run a fresh investigation before reviewing the current payment.</p></div> : null}<p className="investigation-summary">{investigation.summary || 'A summary has not been returned for this investigation.'}</p><div className="findings-list">{investigation.findings.map((finding, index) => <section className="finding-card" key={`${finding.code}:${index}`}><div><span className={`finding-severity severity-${finding.severity.toLowerCase()}`}>{finding.severity}</span><h3>{finding.code.replace(/_/g, ' ')}</h3></div><p>{finding.explanation}</p>{finding.citations.length ? <div className="finding-citations">{finding.citations.map((citation, citationIndex) => {
    const source = documents.find(document => document.id === citation.document_id)
    return <figure key={`${citation.document_id}:${citationIndex}`}><blockquote>{citation.quote}</blockquote><figcaption><button type="button" disabled={!source} onClick={() => openSource(citation.document_id)}><BookOpen size={12} />{source?.filename ?? 'Source unavailable'}{citation.page ? ` · page ${citation.page}` : ''}<ArrowUpRight size={12} /></button></figcaption></figure>
  })}</div> : <p className="authority-note">No source quotation was returned for this finding.</p>}</section>)}</div><details className="tool-trace"><summary><Search size={14} />Investigation tool trace<span>{investigation.tool_trace.length} steps</span></summary><ol>{investigation.tool_trace.map((step, index) => <li key={`${step.tool}:${index}`}><span>{String(index + 1).padStart(2, '0')}</span><strong>{step.tool.replace(/_/g, ' ')}</strong><small>{step.status.replace(/_/g, ' ')}</small></li>)}</ol><p className="authority-note">These tools retrieve and compare evidence. They have no approval or transfer authority.</p></details><ActionError error={error} />{investigation.review ? <div className="review-record"><Check size={17} /><div><strong>Human review recorded</strong><p>{displayTime(investigation.review.reviewed_at)}</p>{investigation.review.note ? <blockquote>{investigation.review.note}</blockquote> : null}</div></div> : completed && current ? <form className="investigation-review" onSubmit={review}><h3>Acknowledge the findings</h3><label className="review-checkbox"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /><span>I reviewed this summary, its findings, and the cited sources for the current evidence snapshot. This acknowledgement does not approve a beneficiary or payment.</span></label><label className="review-note">Review note<textarea value={note} onChange={event => setNote(event.target.value)} required minLength={1} maxLength={2000} rows={3} placeholder="Record context for the next reviewer." /></label><Button type="submit" disabled={!acknowledged || !note.trim() || pending}>{pending ? <LoaderCircle className="spin" /> : <ShieldCheck />}Record evidence review</Button></form> : null}<InvestigationExtras key={investigation.id} investigation={investigation} token={token} integrations={integrations} /></article>
}

function EvidenceCase({ payment, token, integrations, storageConfigured }: { payment: PaymentView; token: string; integrations: Integrations | null; storageConfigured: boolean }) {
  const [revision, setRevision] = useState(0)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [pending, setPending] = useState<'upload' | 'investigate' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceRegion = useRef<HTMLDivElement>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const documents = useApi<{ documents: EvidenceDocument[] }>(`/api/payments/${payment.id}/evidence`, token, true, revision)
  const investigations = useApi<{ investigations: Investigation[] }>(`/api/payments/${payment.id}/investigations`, token, true, revision)
  const currentDocuments = documents.data?.documents.filter(document => document.revision_id === payment.current_revision.id) ?? []
  const providerAvailable = providerConfigured(integrations, 'openai')
  const mutable = !payment.execution && !['QUEUED', 'SUBMITTING', 'UNKNOWN', 'SUCCEEDED'].includes(payment.state)
  const selectedSource = documents.data?.documents.find(document => document.id === sourceId)
  const orderedInvestigations = [...(investigations.data?.investigations ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const refresh = () => setRevision(value => value + 1)
  function openSource(id: string) { setSourceId(id); window.requestAnimationFrame(() => sourceRegion.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })) }
  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!selectedFile || pending || !mutable) return
    const extension = selectedFile.name.split('.').pop()?.toLowerCase()
    const mediaType = extension === 'txt' ? 'text/plain' : extension === 'pdf' ? 'application/pdf' : null
    if (!mediaType) { setError('Choose a UTF-8 .txt file or a text PDF. Images and scanned documents are not supported.'); return }
    if (!selectedFile.size || selectedFile.size > maximumFileBytes) { setError('Choose a non-empty file no larger than 2 MB.'); return }
    const current = new AbortController(); controller.current = current
    setPending('upload'); setError(null); setNotice(null)
    try {
      const content = await fileBase64(selectedFile)
      if (current.signal.aborted) return
      await request<EvidenceDocument>(`/api/payments/${payment.id}/evidence`, { token, method: 'POST', body: { revision_id: payment.current_revision.id, filename: selectedFile.name, media_type: mediaType, content_base64: content }, signal: current.signal, timeoutMs: 60000 })
      if (!current.signal.aborted) { setSelectedFile(null); if (fileInput.current) fileInput.current.value = ''; setNotice('Evidence stored. Existing evidence reviews and payment approval must be checked again.'); refresh() }
    } catch (failure) { if (!current.signal.aborted) setError(failure instanceof Error ? failure.message : 'Evidence upload could not be confirmed.') }
    finally { if (!current.signal.aborted) setPending(null) }
  }
  async function investigate() {
    if (pending || !providerAvailable || !currentDocuments.length) return
    const current = new AbortController(); controller.current = current
    setPending('investigate'); setError(null); setNotice(null)
    try {
      const result = await request<Investigation>(`/api/payments/${payment.id}/investigations`, { token, method: 'POST', body: { revision_id: payment.current_revision.id }, signal: current.signal, timeoutMs: 120000 })
      if (!current.signal.aborted) { setNotice(`Investigation recorded with status: ${result.status.replace(/_/g, ' ')}.`); refresh() }
    } catch (failure) { if (!current.signal.aborted) { setError(failure instanceof Error ? failure.message : 'The investigation outcome was not confirmed.'); refresh() } }
    finally { if (!current.signal.aborted) setPending(null) }
  }
  return <><div className="evidence-case-strip"><div><span>Invoice</span><strong>{payment.invoice_reference}</strong></div><div><span>Supplier</span><strong>{payment.supplier_name}</strong></div><div><span>Current snapshot</span><strong>{money(payment.current_revision.amount_minor)} · revision {payment.current_revision.version}</strong></div><Button variant="ghost" size="icon" aria-label="Refresh case evidence" onClick={refresh} disabled={documents.loading || investigations.loading}><RefreshCw className={documents.loading || investigations.loading ? 'spin' : ''} /></Button></div><ActionError error={error ?? documents.error ?? investigations.error} />{notice ? <p className="operation-notice" role="status">{notice}</p> : null}<div className="evidence-layout"><aside className="evidence-sources-column"><section className="panel evidence-upload"><div className="section-icon"><Upload size={21} /></div><span className="eyebrow">PRIVATE SOURCE FILES</span><h2>Add the evidence.</h2><p>Files are bound to this immutable payment revision and stored privately.</p><form onSubmit={upload}><label className="upload-file-label" htmlFor="case-evidence">Choose source file<input ref={fileInput} id="case-evidence" type="file" accept=".txt,.pdf,text/plain,application/pdf" disabled={!mutable || !storageConfigured || Boolean(pending)} onChange={event => setSelectedFile(event.target.files?.[0] ?? null)} /></label><p className="file-format-note">UTF-8 text or text PDF · up to 2 MB. Scans and images are unsupported.</p><Button type="submit" disabled={!selectedFile || !mutable || !storageConfigured || Boolean(pending)}>{pending === 'upload' ? <LoaderCircle className="spin" /> : <Upload />}Upload to this revision</Button></form>{!mutable ? <p className="unconfigured-note">Evidence is locked once this payment has entered execution.</p> : !storageConfigured ? <p className="unconfigured-note">Private storage is not configured or its status is unavailable.</p> : null}</section><section className="panel source-list"><div className="source-list-heading"><h2>Sources</h2><span>{documents.data?.documents.length ?? '—'}</span></div>{documents.loading ? <p className="provider-loading">Loading source records…</p> : documents.data?.documents.length ? documents.data.documents.map(document => <button className={sourceId === document.id ? 'active' : ''} key={document.id} type="button" onClick={() => openSource(document.id)}><FileText size={18} /><span><strong>{document.filename}</strong><small>{document.revision_id === payment.current_revision.id ? 'Current revision' : 'Previous revision'} · {document.extraction_status.replace(/_/g, ' ')}</small></span><ArrowUpRight size={13} /></button>) : <p className="source-empty">No evidence has been returned for this payment.</p>}</section><div className="evidence-boundary-note"><ShieldCheck size={18} /><p>Evidence informs a decision. It cannot change an accepted beneficiary or approve a payment.</p></div></aside><div className="investigation-column"><section className="panel investigation-launch"><div><span className="eyebrow">BOUNDED AGENT INVESTIGATION</span><h2>Follow the evidence.</h2><p>The agent can read sources, compare payment details, and retrieve advisory context. Its output remains subject to human review.</p></div><Button onClick={investigate} disabled={!providerAvailable || !currentDocuments.length || Boolean(pending) || documents.loading}>{pending === 'investigate' ? <LoaderCircle className="spin" /> : <FileSearch />}{pending === 'investigate' ? 'Investigating evidence…' : 'Investigate current evidence'}</Button>{!providerAvailable ? <p className="unconfigured-note">{integrations ? 'OpenAI is not configured. Add server credentials to run an investigation.' : 'Provider configuration is unavailable. Investigation remains disabled.'}</p> : !currentDocuments.length ? <p className="authority-note">Upload a source for the current revision first.</p> : null}{pending === 'investigate' ? <p className="authority-note" role="status">The request is bounded to two minutes. Leaving this view stops waiting; refresh the case before starting another investigation.</p> : null}</section><div ref={sourceRegion}>{selectedSource ? <EvidenceSource key={selectedSource.id} document={selectedSource} token={token} close={() => setSourceId(null)} /> : null}</div>{investigations.loading ? <p className="provider-loading" role="status">Loading investigation records…</p> : orderedInvestigations.length ? orderedInvestigations.map(investigation => <InvestigationCard key={`${investigation.id}:${investigation.review?.reviewed_at ?? 'unreviewed'}`} investigation={investigation} documents={documents.data?.documents ?? []} payment={payment} token={token} integrations={integrations} refresh={refresh} openSource={openSource} />) : <section className="panel investigation-empty"><FileSearch size={30} strokeWidth={1.5} /><h2>The investigation record starts here.</h2><p>Source-linked findings, tool decisions, and human review will appear after an actual investigation response.</p></section>}</div></div></>
}

export function EvidenceWorkspace({ token }: { token: string }) {
  const [selectedId, setSelectedId] = useState('')
  const [revision, setRevision] = useState(0)
  const payments = useApi<{ payments: PaymentView[] }>('/api/payments', token, true, revision)
  const integrations = useApi<Integrations>('/api/integrations', token, true, revision)
  const setup = useApi<Setup>('/api/setup', undefined, true, revision)
  const selected = payments.data?.payments.find(payment => payment.id === selectedId) ?? payments.data?.payments[0]
  return <><div className="page-heading"><div><span className="eyebrow">EVIDENCE & INVESTIGATION</span><h1>A finding is only as useful as its source.</h1><p>Inspect the evidence, follow the agent’s tool trace, and record a considered human review.</p></div><Button variant="outline" onClick={() => setRevision(value => value + 1)} disabled={payments.loading}><RefreshCw className={payments.loading ? 'spin' : ''} />Refresh workspace</Button></div><ActionError error={payments.error ?? integrations.error ?? setup.error} /><label className="case-picker">Payment to investigate<select value={selected?.id ?? ''} onChange={event => setSelectedId(event.target.value)} disabled={payments.loading}><option value="" disabled>Select a payment</option>{payments.data?.payments.map(payment => <option key={payment.id} value={payment.id}>{payment.invoice_reference} · {payment.supplier_name} · revision {payment.current_revision.version}</option>)}</select></label>{selected ? <EvidenceCase key={`${selected.id}:${selected.current_revision.id}`} payment={selected} token={token} integrations={integrations.data} storageConfigured={setup.data?.storage_configured === true} /> : payments.loading ? <div className="loading-state" role="status"><LoaderCircle className="spin" />Loading payment snapshots…</div> : <section className="panel payment-empty"><FileSearch size={33} /><h2>Create a payment intent first.</h2><p>Every source and investigation belongs to a specific payment revision.</p><Button asChild variant="outline"><a href="#payments">Open payment workspace<ArrowUpRight /></a></Button></section>}</>
}
