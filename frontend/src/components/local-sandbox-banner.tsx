import { useState } from 'react'
import { FlaskConical, LoaderCircle } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { localSandboxOrigin } from '../lib/local-sandbox'

export function LocalSandboxBanner({ role }: { role?: string }) {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!localSandboxOrigin) return null
  async function switchIdentity(actor: 'finance' | 'supplier') {
    if (!supabase || pending) return
    setPending(actor); setError(null)
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    try {
      const response = await fetch(`${localSandboxOrigin}/local-demo/session?actor=${actor}`, { signal: controller.signal, cache: 'no-store', redirect: 'error' })
      if (!response.ok) throw new Error('The local identity fixture is unavailable.')
      const session = await response.json()
      if (typeof session.access_token !== 'string' || typeof session.refresh_token !== 'string') throw new Error('The local identity fixture returned an invalid session.')
      const { error: authError } = await supabase.auth.setSession({ access_token: session.access_token, refresh_token: session.refresh_token })
      if (authError) throw new Error('The simulated session could not be established.')
      window.location.hash = actor === 'finance' ? 'payments' : 'portal'
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Identity switch failed.') }
    finally { clearTimeout(timeout); setPending(null) }
  }
  return <div className="sandbox-banner"><div className="sandbox-banner-title"><FlaskConical size={16} /><strong>Local synthetic sandbox <span>• simulated identity • no real funds</span></strong></div><div className="sandbox-identity-actions"><span>View as</span>{(['finance', 'supplier'] as const).map(actor => <button key={actor} type="button" disabled={Boolean(pending) || !supabase} className={(actor === 'supplier' ? role === 'supplier' : role === 'finance_admin' || role === 'finance_reviewer') ? 'active' : ''} onClick={() => switchIdentity(actor)}>{pending === actor ? <LoaderCircle size={12} className="spin" /> : null}{actor === 'finance' ? 'Finance' : 'Supplier'}</button>)}</div>{error ? <p role="alert">{error}</p> : null}</div>
}
