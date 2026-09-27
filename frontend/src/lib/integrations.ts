export type IntegrationId = 'openai' | 'n8n' | 'breeth' | 'elevenlabs' | 'dodo'
export interface IntegrationStatus { id: IntegrationId; name: string; configured: boolean; live_verified: boolean }
export interface Integrations { integrations: IntegrationStatus[] }
export interface EvidenceDocument {
  id: string
  payment_id: string
  revision_id: string
  filename: string
  media_type: string
  sha256: string
  created_at: string
  extracted_text: string
  extraction_status: 'extracted'
}
export interface Citation { document_id: string; quote: string; page: number | null }
export interface Finding { severity: 'info' | 'warning' | 'critical'; code: string; explanation: string; citations: Citation[] }
export interface Investigation {
  id: string
  payment_id: string
  revision_id: string
  status: 'completed' | 'failed' | 'unknown'
  summary: string
  findings: Finding[]
  tool_trace: { tool: string; status: string }[]
  review: { reviewed_at: string; note: string } | null
  created_at: string
  provider: string
  advisory: true
  evidence_digest: string
  is_current: boolean
}
export interface MemoryResult { items: { text: string; source: string; advisory: true }[] }
export interface MemoryWrite { status: 'written' | 'unknown' | 'failed'; operation_id: string; advisory: true }
export interface Delivery {
  id: string
  supplier_id: string
  beneficiary_version_id: string
  status: 'PENDING' | 'DELIVERED' | 'UNKNOWN' | 'FAILED' | 'STALE'
  created_at: string
  delivered_at: string | null
  attempts: number
}
export interface BillingStatus { mode: 'test'; configured: boolean; entitled: boolean; status: 'UNCONFIGURED' | 'NONE' | 'CHECKOUT_PENDING' | 'UNKNOWN' | 'ACTIVE' | 'CANCELLED' | 'EXPIRED' | 'FAILED'; expires_at: string | null }
export interface Checkout { checkout_url: string; checkout_id: string }

export function checkoutDestination(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && !url.hash
      && ['checkout.dodopayments.com', 'test.checkout.dodopayments.com'].includes(url.hostname)
      ? url.href : null
  } catch { return null }
}

export function providerConfigured(integrations: Integrations | null, id: IntegrationId) {
  return integrations?.integrations.find(integration => integration.id === id)?.configured === true
}
