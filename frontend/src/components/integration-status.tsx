import { Plug, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useApi } from '../hooks/use-api'
import type { Integrations } from '../lib/integrations'
import { ActionError } from './payment-primitives'
import { Button } from './ui/button'

const descriptions: Record<string, string> = {
  openai: 'Read-only evidence investigation and source-linked findings.',
  n8n: 'Finance-approved delivery into the assigned supplier inbox.',
  breeth: 'Redacted, advisory memory from reviewed investigations.',
  elevenlabs: 'A stock-voice explanation of a reviewed, redacted summary.',
  dodo: 'Test-mode subscription billing and report entitlements.',
}

export function IntegrationStatusPanel({ token }: { token: string }) {
  const [revision, setRevision] = useState(0)
  const integrations = useApi<Integrations>('/api/integrations', token, true, revision)
  return <section className="panel provider-status-panel"><div className="panel-heading"><div><span className="eyebrow">PROVIDER CONNECTIONS</span><h2>Presence is visible. Verification is separate.</h2></div><Button variant="ghost" size="icon" aria-label="Refresh integration configuration" onClick={() => setRevision(value => value + 1)} disabled={integrations.loading}><RefreshCw className={integrations.loading ? 'spin' : ''} /></Button></div><p className="integration-status-description">Configured indicates that server settings are present. It does not prove provider authentication, delivery, or a successful live call.</p><ActionError error={integrations.error} />{integrations.loading ? <p className="provider-loading" role="status">Checking provider configuration…</p> : integrations.data ? <div className="provider-status-list">{integrations.data.integrations.map(integration => <div key={integration.id}><span className="provider-icon"><Plug size={17} /></span><div><strong>{integration.name}</strong><p>{descriptions[integration.id] ?? 'Server-managed integration.'}</p></div><span className="provider-presence">{integration.configured ? 'Configured' : 'Not configured'}<small>{integration.live_verified ? 'Live evidence recorded' : 'Live verification pending'}</small></span></div>)}</div> : null}</section>
}
