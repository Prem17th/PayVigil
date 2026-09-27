import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ArrowRight, ArrowUpRight, Building2, Check, ChevronRight, CircleHelp, Database, FileCheck2, Fingerprint, GitBranch, LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, Menu, Network, Plug, RefreshCw, ShieldCheck, ShieldEllipsis, UserRound, UsersRound, Wallet, X, type LucideIcon } from 'lucide-react'
import { Button } from './components/ui/button'
import { useApi, type Resource } from './hooks/use-api'
import { useAuth } from './hooks/use-auth'
import { apiConfigurationError, request, type Health, type Identity, type Setup, type StorageCheck, type Workspace } from './lib/api'
import { authConfigurationError, supabase } from './lib/supabase'
import { cn } from './lib/utils'
import { PaymentWorkspace } from './components/payment-workspace'
import { SupplierRequests } from './components/supplier-requests'
import { LocalSandboxBanner } from './components/local-sandbox-banner'
import { localSandboxEnabled } from './lib/local-sandbox'
import { EvidenceWorkspace } from './components/evidence-workspace'
import { BillingWorkspace } from './components/billing-workspace'
import { IntegrationStatusPanel } from './components/integration-status'

type View = 'overview' | 'access' | 'connections' | 'roadmap' | 'portal' | 'payments' | 'evidence' | 'billing'
type Tone = 'good' | 'neutral' | 'warning' | 'muted'
const viewTitles: Record<View, string> = { overview: 'Workspace overview', access: 'Workspace access', connections: 'Connections', roadmap: 'The build roadmap', portal: 'Supplier portal', payments: 'Payment authority', evidence: 'Evidence & investigation', billing: 'Subscription & reports' }
const roleNames = { finance_admin: 'Finance administrator', finance_reviewer: 'Finance reviewer', supplier: 'Supplier' }
const navigation: { id: View; label: string; icon: LucideIcon }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'payments', label: 'Payment authority', icon: Wallet },
  { id: 'evidence', label: 'Evidence & investigation', icon: FileCheck2 },
  { id: 'billing', label: 'Subscription & reports', icon: Building2 },
  { id: 'access', label: 'Workspace access', icon: Fingerprint },
  { id: 'connections', label: 'Connections', icon: Plug },
  { id: 'roadmap', label: 'Build roadmap', icon: GitBranch },
]
const phases = [
  { name: 'Workspace & readiness', description: 'Product boundaries, provider requirements, and the implementation plan.', status: 'complete' },
  { name: 'Runnable foundation', description: 'Local application shell, secure identity adapters, and private storage checks.', status: 'complete' },
  { name: 'Payment authority & sandbox', description: 'Versioned beneficiaries, exact human approvals, and controlled execution.', status: 'complete' },
  { name: 'Evidence & investigation', description: 'Private documents, source-linked findings, and a bounded investigation agent.', status: 'staged' },
  { name: 'Supplier confirmation', description: 'Approved requests and reminders delivered through n8n.', status: 'staged' },
  { name: 'Investigation memory', description: 'Advisory context from previous investigations with Breeth AI.', status: 'staged' },
  { name: 'Spoken explanations', description: 'Redacted, accessible case explanations with ElevenLabs.', status: 'staged' },
  { name: 'Subscription billing', description: 'Test-mode subscriptions and report access through Dodo Payments.', status: 'staged' },
  { name: 'Validation & demonstration', description: 'Verify local behavior, then connect providers and prepare the hosted release.', status: 'current' },
]

function getView(): View {
  const value = window.location.hash.slice(1)
  return Object.hasOwn(viewTitles, value) ? value as View : 'overview'
}

function Badge({ children, tone = 'neutral', dot = false }: { children: ReactNode; tone?: Tone; dot?: boolean }) {
  return <span className={cn('badge', `badge-${tone}`)}>{dot ? <span className="status-dot" aria-hidden="true" /> : null}{children}</span>
}

function Notice({ children, title, tone = 'neutral' }: { children: ReactNode; title?: string; tone?: 'neutral' | 'warning' }) {
  return <div className={cn('notice', `notice-${tone}`)} role={tone === 'warning' ? 'alert' : undefined}><CircleHelp size={18} aria-hidden="true" /><div>{title ? <strong>{title}</strong> : null}<div>{children}</div></div></div>
}

function Loading({ label = 'Checking your workspace…' }: { label?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle size={22} className="spin" aria-hidden="true" /><span>{label}</span></div>
}

function Brand() {
  return <a className="brand" href="#overview" aria-label="PayVigil home"><span className="brand-mark"><ShieldCheck size={25} strokeWidth={1.7} /></span><span>Pay<span className="brand-light">Vigil</span><small>CONFIDENCE, BEFORE PAYMENT.</small></span></a>
}

function ChainIllustration() {
  return <div className="hero-illustration" aria-hidden="true">
    <div className="orbit orbit-one" /><div className="orbit orbit-two" />
    <div className="illustration-label label-top"><span /> Evidence first</div>
    <div className="document-shadow" />
    <div className="illustration-document"><div className="document-heading"><FileCheck2 size={25} /><span>PAYMENT INSTRUCTIONS</span></div><div className="document-line wide" /><div className="document-line short" /><div className="document-divider" /><div className="document-row"><span>Supplier</span><div /></div><div className="document-row"><span>Beneficiary</span><div /></div><div className="document-row"><span>Approval</span><div /></div><div className="document-footer"><LockKeyhole size={12} /> Human authority, by design</div></div>
    <div className="illustration-seal"><ShieldCheck size={42} strokeWidth={1.4} /></div>
    <div className="illustration-label label-bottom"><span /> One clear audit trail</div>
  </div>
}

function VerificationChain() {
  const steps = [
    { icon: FileCheck2, label: 'Invoice evidence', text: 'Understand the original instructions.', phase: 'Private sources' },
    { icon: Building2, label: 'Supplier confirmation', text: 'Confirm the assigned beneficiary version.', phase: 'Version bound' },
    { icon: ShieldCheck, label: 'Finance approval', text: 'Approve the exact payment details.', phase: 'Version bound' },
    { icon: Wallet, label: 'Sandbox transfer', text: 'Execute once. Independently verify.', phase: 'Version bound' },
  ]
  return <section className="chain-section" aria-labelledby="chain-heading"><div className="section-heading"><div><span className="eyebrow">THE VERIFICATION PATH</span><h2 id="chain-heading">Four steps. Clear accountability.</h2></div><span className="subtle-label"><LockKeyhole size={13} /> Verification workflow</span></div><ol className="verification-chain">{steps.map((step, index) => <li key={step.label}><div className="chain-top"><span className="chain-icon"><step.icon size={22} strokeWidth={1.6} /></span><span className="chain-number">0{index + 1}</span>{index < 3 ? <ArrowRight className="chain-arrow" size={17} aria-hidden="true" /> : null}</div><h3>{step.label}</h3><p>{step.text}</p><span className="chain-phase">{step.phase}<span>Auditable</span></span></li>)}</ol></section>
}

function ConnectionLine({ icon: Icon, name, note, status, tone = 'neutral' }: { icon: LucideIcon; name: string; note: string; status: string; tone?: Tone }) {
  return <div className="connection-line"><div className="connection-icon"><Icon size={19} strokeWidth={1.7} /></div><div className="connection-copy"><strong>{name}</strong><p>{note}</p></div><Badge tone={tone} dot>{status}</Badge></div>
}

function Overview({ health, setup, identity, workspace }: { health: Resource<Health>; setup: Resource<Setup>; identity: Identity | null; workspace: Resource<Workspace> }) {
  const healthy = health.data?.status === 'ok' && health.data.service === 'beforetransfer-api'
  return <>
    <div className="page-heading"><div><span className="eyebrow">YOUR VERIFICATION WORKSPACE</span><h1>{identity ? `Welcome to ${identity.tenant.name}.` : 'A stronger foundation for trust.'}</h1><p>Bring clarity to supplier payments, before money moves.</p></div><Button asChild variant="outline"><a href={identity ? '#payments' : '#access'}>{identity ? 'Open payment workspace' : 'Access workspace'}<ArrowUpRight /></a></Button></div>
    <section className="hero-card"><div className="hero-copy"><div className="hero-kicker"><span /> EVIDENCE. CONFIRMATION. CONTROL.</div><h2>Confidence comes<br />before the <em>transfer.</em></h2><p>A workspace for investigating payment instructions and keeping the final decision in human hands.</p><a href="#roadmap" className="hero-link">Explore the build roadmap <ArrowRight size={17} /></a></div><ChainIllustration /><div className="hero-footer"><span><ShieldEllipsis size={15} /> Evidence & authority</span><span>Provider checks pending</span></div></section>
    <VerificationChain />
    <div className="overview-bottom"><section className="panel foundation-panel"><div className="panel-heading"><div><span className="eyebrow">FOUNDATION STATUS</span><h2>A clear view of what is ready.</h2></div><a href="#connections" className="text-link">Details <ArrowUpRight size={15} /></a></div><ConnectionLine icon={Network} name="Application API" note="A live response confirms service availability." status={health.loading ? 'Checking' : healthy ? 'Responding' : 'Unavailable'} tone={healthy ? 'good' : health.loading ? 'neutral' : 'warning'} /><ConnectionLine icon={Fingerprint} name="Workspace identity" note={identity ? roleNames[identity.role] : 'Sign in to verify your assigned role.'} status={identity ? 'Verified' : supabase ? 'Sign-in available' : 'Not configured'} tone={identity ? 'good' : 'neutral'} /><ConnectionLine icon={Database} name="Private workspace" note={workspace.data ? 'Authenticated workspace access confirmed.' : setup.data?.database_configured ? 'Database configured; authenticated access not yet checked.' : 'Database connection needs verification.'} status={workspace.data ? 'Access verified' : setup.data?.database_configured ? 'Configured' : 'Not verified'} tone={workspace.data ? 'good' : 'neutral'} /></section><aside className="principle-card"><div className="principle-icon"><UsersRound size={22} /></div><span className="eyebrow">HUMANS HOLD THE AUTHORITY</span><h2>The agent investigates.<br />You decide.</h2><p>Supplier confirmation, beneficiary acceptance, and payment approval are separate decisions.</p><div className="principle-bottom"><span>Designed into every step</span><ArrowUpRight size={18} /></div></aside></div>
    <div className="foundation-note"><span className="small-square" /><p>Evidence, delivery, memory, voice, and test billing use server-configured providers. Configuration presence and successful live verification remain separate.</p></div>
  </>
}

function Access({ sessionEmail, identity, identityError, busy, retry }: { sessionEmail?: string; identity: Identity | null; identityError: string | null; busy: boolean; retry: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const available = Boolean(supabase) && !apiConfigurationError
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!supabase || !available || submitting) return
    setSubmitting(true); setError(null); setMessage(null)
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
      if (signInError) setError(signInError.message)
      else { setPassword(''); setMessage('Signed in. Verifying workspace access…') }
    } catch { setError('Authentication is unreachable. Please try again.') }
    finally { setSubmitting(false) }
  }
  return <><PageHeading eyebrow="IDENTITY & PERMISSIONS" title="Your workspace. Your role." description="Secure access starts with an authenticated identity and an assigned workspace." /><div className="access-layout"><section className="panel access-panel"><span className="access-icon"><Fingerprint size={27} strokeWidth={1.5} /></span><h2>{sessionEmail ? 'Your signed-in account' : 'Sign in to PayVigil'}</h2><p className="section-description">{sessionEmail ? 'Workspace permissions are checked by the application API.' : 'Use the email and password for your provisioned workspace account.'}</p>{sessionEmail ? <div className="signed-in-info"><div><span>Email</span><strong>{sessionEmail}</strong></div>{busy ? <Loading label="Verifying membership…" /> : identity ? <><div><span>Workspace</span><strong>{identity.tenant.name}</strong></div><div><span>Assigned role</span><Badge tone="good">{roleNames[identity.role]}</Badge></div><Button asChild><a href={identity.role === 'supplier' ? '#portal' : '#payments'}>Open workspace<ArrowRight /></a></Button></> : <><Notice title="Workspace access is not verified" tone="warning">{identityError ?? 'An administrator must assign your account to a workspace before you can continue.'}</Notice><Button variant="outline" onClick={retry}><RefreshCw />Retry access check</Button></>}</div> : <><form onSubmit={signIn} className="signin-form"><label htmlFor="email">Work email<input id="email" type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="username" required disabled={!available || submitting} /></label><label htmlFor="password">Password<input id="password" type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="Enter your password" autoComplete="current-password" required disabled={!available || submitting} /></label>{error ? <Notice tone="warning">{error}</Notice> : null}{message ? <p className="form-message" role="status">{message}</p> : null}<Button type="submit" disabled={!available || submitting}>{submitting ? <LoaderCircle className="spin" /> : <LockKeyhole />}{submitting ? 'Signing in…' : 'Sign in securely'}<ArrowRight className="ml-auto" /></Button></form>{!available ? <Notice title={authConfigurationError ?? 'Workspace API not configured'}>Workspace access will be available once the application’s secure connections are configured.</Notice> : null}<p className="account-help">Need access or a password reset? Contact your workspace administrator.</p></>}<div className="access-footer"><LockKeyhole size={13} /> {localSandboxEnabled ? 'Simulated local identity · backend permissions enforced' : 'Identity verified by Supabase Auth'}</div></section><aside className="access-aside"><span className="eyebrow">ACCESS WITH INTENTION</span><h2>The right information.<br />For the right people.</h2><div className="role-item"><ShieldCheck /><div><h3>Finance administrators</h3><p>Workspace administration and verification access.</p></div></div><div className="role-item"><FileCheck2 /><div><h3>Finance reviewers</h3><p>Access to the finance verification workspace.</p></div></div><div className="role-item"><Building2 /><div><h3>Suppliers</h3><p>A separate portal for their own confirmation requests.</p></div></div><p className="aside-note">Roles are assigned by the workspace administrator and enforced on the server.</p></aside></div></>
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function Connections({ health, setup, identity, token, refresh, workspace }: { health: Resource<Health>; setup: Resource<Setup>; identity: Identity | null; token?: string; refresh: () => void; workspace: Resource<Workspace> }) {
  const [probe, setProbe] = useState<{ data: StorageCheck | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: false })
  const controllerRef = useRef<AbortController | null>(null)
  useEffect(() => () => controllerRef.current?.abort(), [])
  const finance = identity && identity.role !== 'supplier'
  const healthy = health.data?.status === 'ok' && health.data.service === 'beforetransfer-api'
  const storageVerified = probe.data?.status === 'verified' && Object.values(probe.data.checks).every(Boolean)
  async function checkStorage() {
    if (!finance || !token || probe.loading) return
    const controller = new AbortController()
    controllerRef.current = controller
    setProbe({ data: null, error: null, loading: true })
    try {
      const data = await request<StorageCheck>('/api/storage/check', { token, signal: controller.signal, method: 'POST' })
      if (!controller.signal.aborted) setProbe({ data, error: null, loading: false })
    } catch (error) {
      if (!controller.signal.aborted) setProbe({ data: null, error: error instanceof Error ? error.message : 'Storage verification failed.', loading: false })
    }
  }
  return <><PageHeading eyebrow="SERVICE CONNECTIONS" title="Configured is a start. Verified is better." description="Connection status reflects the latest API response and authenticated checks." action={<Button variant="outline" onClick={refresh} disabled={health.loading || setup.loading}><RefreshCw className={health.loading ? 'spin' : ''} />Refresh status</Button>} />{health.error ? <Notice tone="warning" title="Application API unavailable">{health.error}</Notice> : null}{setup.error && !health.error ? <Notice tone="warning" title="Setup status unavailable">{setup.error}</Notice> : null}<div className="connection-grid"><section className="panel connection-card"><div className="service-top"><span className="service-icon"><Network /></span><Badge tone={healthy ? 'good' : 'neutral'} dot>{health.loading ? 'Checking' : healthy ? 'Responding' : 'Not verified'}</Badge></div><h2>Application API</h2><p>The service that enforces workspace permissions and application rules.</p><dl><div><dt>Service availability</dt><dd>{healthy ? 'Live response received' : health.loading ? 'Checking…' : 'Awaiting verification'}</dd></div><div><dt>Version</dt><dd>{health.data?.version ?? '—'}</dd></div></dl><div className="connection-card-note">Availability alone does not confirm database or storage access.</div></section><section className="panel connection-card"><div className="service-top"><span className="service-icon"><Fingerprint /></span><Badge tone={identity ? 'good' : 'neutral'} dot>{identity ? 'Access verified' : setup.data?.auth_configured && supabase ? 'Configured' : 'Not configured'}</Badge></div><h2>{localSandboxEnabled ? 'Local identity fixture' : 'Supabase Auth'}</h2><p>{localSandboxEnabled ? 'Simulated identity for local testing. This is not a verified Supabase integration.' : 'Secure sign-in and workspace membership verified with every protected request.'}</p><dl><div><dt>Server configuration</dt><dd>{setup.loading ? 'Checking…' : setup.data ? setup.data.auth_configured ? 'Present' : 'Not configured' : 'Unknown'}</dd></div><div><dt>Workspace membership</dt><dd>{identity ? 'Verified' : 'Sign-in required'}</dd></div></dl><Button asChild variant="outline" size="sm"><a href="#access">{identity ? 'View your access' : 'Sign in to verify'}<ArrowUpRight /></a></Button></section><section className="panel connection-card"><div className="service-top"><span className="service-icon"><Database /></span><Badge tone={workspace.data ? 'good' : 'neutral'} dot>{workspace.data ? 'Access verified' : setup.data?.database_configured ? 'Configured' : 'Not verified'}</Badge></div><h2>PostgreSQL</h2><p>The source of truth for workspace membership, immutable payment revisions, and payment authority.</p><dl><div><dt>Server configuration</dt><dd>{setup.loading ? 'Checking…' : setup.data ? setup.data.database_configured ? 'Present' : 'Not configured' : 'Unknown'}</dd></div><div><dt>Authenticated workspace</dt><dd>{workspace.loading ? 'Checking…' : workspace.data ? 'Access confirmed' : 'Not verified'}</dd></div></dl>{workspace.error ? <p className="inline-error">{workspace.error}</p> : <div className="connection-card-note">Workspace reads are restricted to authenticated finance roles.</div>}</section><section className="panel connection-card"><div className="service-top"><span className="service-icon"><LockKeyhole /></span><Badge tone={storageVerified ? 'good' : 'neutral'} dot>{storageVerified ? 'Access verified' : setup.data?.storage_configured ? 'Configured' : 'Not verified'}</Badge></div><h2>Private Storage</h2><p>Verify a private bucket using a temporary probe, then remove the probe object.</p><dl><div><dt>Server configuration</dt><dd>{setup.loading ? 'Checking…' : setup.data ? setup.data.storage_configured ? 'Present' : 'Not configured' : 'Unknown'}</dd></div><div><dt>Latest access check</dt><dd>{storageVerified && probe.data ? new Date(probe.data.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Not verified'}</dd></div></dl><Button variant="outline" size="sm" onClick={checkStorage} disabled={!finance || !setup.data?.storage_configured || probe.loading}>{probe.loading ? <LoaderCircle className="spin" /> : <ShieldCheck />}{probe.loading ? 'Verifying storage…' : 'Verify private access'}</Button>{!finance ? <p className="card-help">Sign in with a finance role to run this check.</p> : null}{probe.error ? <p className="inline-error" role="alert">{probe.error}</p> : null}{probe.data ? <div className="storage-results" aria-live="polite">{Object.entries(probe.data.checks).map(([name, passed]) => <span key={name}>{passed ? <Check size={13} /> : <X size={13} />}{({ bucket_private: 'Private bucket', upload: 'Probe uploaded', authenticated_read: 'Authenticated read', anonymous_read_denied: 'Anonymous access denied', deleted: 'Probe removed' } as Record<string, string>)[name]}</span>)}</div> : null}</section></div>{finance && token ? <IntegrationStatusPanel token={token} /> : null}<section className="panel upcoming-integrations"><div><span className="eyebrow">A CONNECTED WORKFLOW, BUILT IN PHASES</span><h2>Specialised tools. Separate authority.</h2></div><div className="integration-labels"><span>n8n <small>05</small></span><span>Breeth AI <small>06</small></span><span>ElevenLabs <small>07</small></span><span>Dodo Payments <small>08</small></span></div><p>Provider integrations appear as connected only after their live calls are verified.</p></section></>
}

function Roadmap() {
  return <><PageHeading eyebrow="BUILDING WITH INTENTION" title="Nine phases. One trusted workflow." description="From secure identity to a verified workflow, with evidence at every stage." /><section className="roadmap-summary"><div><Badge tone="good">Current work · Validation</Badge><h2>Build the proof, step by step.</h2><p>The local workflow is built. Provider credentials, live checks, and deployment follow.</p></div><span className="roadmap-numeral" aria-hidden="true">09<span>/09</span></span></section><ol className="roadmap-list">{phases.map((phase, index) => <li className={cn('roadmap-item', `roadmap-${phase.status}`)} key={phase.name}><div className="roadmap-index">{phase.status === 'complete' ? <Check size={18} /> : String(index + 1).padStart(2, '0')}</div><div className="roadmap-copy"><h2>{phase.name}</h2><p>{phase.description}</p></div><Badge tone={phase.status === 'current' ? 'good' : 'neutral'}>{phase.status === 'complete' ? 'Completed' : phase.status === 'current' ? 'In progress' : phase.status === 'staged' ? 'Live checks pending' : 'Upcoming'}</Badge></li>)}</ol><Notice>Local test evidence does not verify hosted providers. Credentials, successful provider calls, and deployment remain explicit release checks.</Notice></>
}

export default function App() {
  const auth = useAuth()
  const [requestedView, setRequestedView] = useState<View>(getView)
  const [menuOpen, setMenuOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const [signOutError, setSignOutError] = useState<string | null>(null)
  const [signingOut, setSigningOut] = useState(false)
  const mainRef = useRef<HTMLElement>(null)
  const token = auth.session?.access_token
  const health = useApi<Health>('/api/health', undefined, true, revision)
  const setup = useApi<Setup>('/api/setup', undefined, true, revision)
  const membership = useApi<Identity>('/api/me', token, Boolean(token), revision)
  const identity = membership.data
  const supplier = identity?.role === 'supplier'
  const finance = Boolean(identity && !supplier)
  const workspace = useApi<Workspace>('/api/workspace', token, finance, revision)
  const view: View = supplier ? requestedView === 'access' ? 'access' : 'portal' : requestedView === 'portal' ? 'access' : requestedView
  const waitingForIdentity = auth.loading || Boolean(token && membership.loading)
  const accessUnverified = Boolean(token && !membership.loading && !identity)
  const renderedView = accessUnverified ? 'access' : view
  const refresh = () => setRevision(value => value + 1)
  useEffect(() => {
    const onHashChange = () => { setRequestedView(getView()); setMenuOpen(false); mainRef.current?.focus() }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  useEffect(() => { document.title = `${viewTitles[renderedView]} — PayVigil` }, [renderedView])
  useEffect(() => {
    if (!menuOpen) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [menuOpen])
  async function signOut() {
    if (!supabase) return
    setSigningOut(true); setSignOutError(null)
    try {
      const { error } = await supabase.auth.signOut()
      if (error) setSignOutError('Sign-out could not be completed. Please try again.')
      else { window.location.hash = 'access'; setRevision(value => value + 1) }
    } catch { setSignOutError('Sign-out could not be completed. Please try again.') }
    finally { setSigningOut(false) }
  }
  const visibleNavigation = supplier ? [{ id: 'portal' as const, label: 'Supplier portal', icon: Building2 }, { id: 'access' as const, label: 'Your account', icon: UserRound }] : navigation
  return <div className="app-shell"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>{menuOpen ? <button type="button" className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMenuOpen(false)} /> : null}<aside className={cn('sidebar', menuOpen && 'sidebar-open')} id="workspace-navigation"><Brand /><button className="mobile-close" type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)}><X size={20} /></button><div className="workspace-picker"><span className="workspace-avatar">{supplier ? <Building2 size={18} /> : <LayersMark />}</span><span><strong>{identity?.tenant.name ?? 'Verification workspace'}</strong><small>{supplier ? 'Supplier access' : identity ? roleNames[identity.role] : 'Payment authority'}</small></span><LockKeyhole size={13} className="workspace-lock" /></div><span className="nav-caption">{supplier ? 'YOUR PORTAL' : 'WORKSPACE'}</span><nav aria-label="Main navigation">{visibleNavigation.map(item => <a href={`#${item.id}`} key={item.id} className={cn('nav-link', renderedView === item.id && 'nav-active')} aria-current={renderedView === item.id ? 'page' : undefined} onClick={() => setMenuOpen(false)}><item.icon size={19} strokeWidth={1.6} /><span>{item.label}</span>{renderedView === item.id ? <span className="nav-active-dot" /> : null}</a>)}</nav>{!supplier ? <div className="sidebar-next"><span className="nav-caption">AUTHORITY BOUNDARY</span><div><ShieldCheck size={18} />Humans approve payments</div></div> : null}<div className="sidebar-bottom"><div className="phase-card"><span className="phase-card-icon"><GitBranch size={16} /></span><div><strong>Built in thoughtful steps</strong><p>Provider checks pending</p></div></div><div className="sidebar-account"><span className="account-avatar"><UserRound size={17} /></span><div><strong>{identity ? identity.email ?? 'Workspace member' : auth.session ? 'Verifying account' : 'Workspace visitor'}</strong><small>{identity ? roleNames[identity.role] : 'Sign in for protected access'}</small></div>{auth.session ? <button type="button" aria-label="Sign out" className="signout-button" disabled={signingOut} onClick={signOut}>{signingOut ? <LoaderCircle className="spin" size={16} /> : <LogOut size={16} />}</button> : <a href="#access" aria-label="Sign in"><ArrowUpRight size={18} /></a>}</div></div></aside><div className="main-shell"><LocalSandboxBanner role={identity?.role} /><header className="topbar"><div className="breadcrumbs"><button className="menu-button" type="button" aria-label="Open navigation" aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(true)}><Menu size={21} /></button><span className="breadcrumb-home">Workspace</span><ChevronRight size={13} /><strong>{viewTitles[renderedView]}</strong></div><div className="topbar-meta"><span className="release-label">{localSandboxEnabled ? 'LOCAL SANDBOX' : 'VERIFICATION'}</span><span className="topbar-separator" /><span className="workspace-security"><LockKeyhole size={13} />{identity ? 'Authenticated access' : 'Sign-in required'}</span></div></header><main className="main-content" id="main-content" ref={mainRef} tabIndex={-1}>{signOutError ? <Notice tone="warning">{signOutError}</Notice> : null}{auth.error ? <Notice tone="warning">{auth.error}</Notice> : null}{waitingForIdentity ? <Loading label="Verifying your session and workspace…" /> : renderedView === 'access' ? <Access sessionEmail={auth.session?.user.email} identity={identity} identityError={membership.error} busy={membership.loading} retry={refresh} /> : supplier && identity && token ? <SupplierRequests token={token} /> : renderedView === 'payments' ? finance && token ? <PaymentWorkspace key={identity?.user_id} token={token} /> : <Access sessionEmail={auth.session?.user.email} identity={identity} identityError={membership.error} busy={membership.loading} retry={refresh} /> : renderedView === 'evidence' ? finance && token ? <EvidenceWorkspace key={identity?.user_id} token={token} /> : <Access sessionEmail={auth.session?.user.email} identity={identity} identityError={membership.error} busy={membership.loading} retry={refresh} /> : renderedView === 'billing' ? finance && token ? <BillingWorkspace key={identity?.user_id} token={token} /> : <Access sessionEmail={auth.session?.user.email} identity={identity} identityError={membership.error} busy={membership.loading} retry={refresh} /> : renderedView === 'connections' ? <Connections key={identity?.user_id ?? 'visitor'} health={health} setup={setup} identity={identity} token={token} refresh={refresh} workspace={workspace} /> : renderedView === 'roadmap' ? <Roadmap /> : <Overview health={health} setup={setup} identity={identity} workspace={workspace} />}<footer className="page-footer"><span>PayVigil<span className="footer-dot">·</span>Clarity before commitment.</span><span><ShieldCheck size={13} /> Human approval by design</span></footer></main></div></div>
}

function LayersMark() {
  return <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 3 7 4-7 4-7-4 7-4Z" stroke="currentColor" strokeWidth="1.4" /><path d="m3 10 7 4 7-4M3 13l7 4 7-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
}
