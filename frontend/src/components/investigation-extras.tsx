import { useEffect, useRef, useState } from 'react'
import { BookOpen, Brain, LoaderCircle, Volume2 } from 'lucide-react'
import { request, requestBlob } from '../lib/api'
import { providerConfigured, type Integrations, type Investigation, type MemoryResult, type MemoryWrite } from '../lib/integrations'
import { ActionError } from './payment-primitives'
import { Button } from './ui/button'

export function InvestigationExtras({ investigation, token, integrations }: { investigation: Investigation; token: string; integrations: Integrations | null }) {
  const [memory, setMemory] = useState<MemoryResult | null>(null)
  const [receipt, setReceipt] = useState<MemoryWrite | null>(null)
  const [attemptedWrite, setAttemptedWrite] = useState(false)
  const [pending, setPending] = useState<'retrieve' | 'write' | 'audio' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl) }, [audioUrl])
  const memoryConfigured = providerConfigured(integrations, 'breeth')
  const voiceConfigured = providerConfigured(integrations, 'elevenlabs')
  async function perform(action: 'retrieve' | 'write' | 'audio') {
    if (pending) return
    const current = new AbortController()
    controller.current = current
    setPending(action); setError(null)
    if (action === 'write') setAttemptedWrite(true)
    try {
      if (action === 'retrieve') {
        const result = await request<MemoryResult>(`/api/payments/${investigation.payment_id}/memory`, { token, signal: current.signal, timeoutMs: 45000 })
        if (!current.signal.aborted) setMemory(result)
      } else if (action === 'write') {
        const result = await request<MemoryWrite>(`/api/investigations/${investigation.id}/memory`, { token, method: 'POST', body: {}, signal: current.signal, timeoutMs: 60000 })
        if (!current.signal.aborted) setReceipt(result)
      } else {
        const blob = await requestBlob(`/api/investigations/${investigation.id}/audio`, { token, method: 'POST', body: {}, signal: current.signal, timeoutMs: 90000, acceptedTypes: ['audio/mpeg'], maxBytes: 10 * 1024 * 1024 })
        if (!current.signal.aborted) setAudioUrl(URL.createObjectURL(blob))
      }
    } catch (failure) { if (!current.signal.aborted) setError(failure instanceof Error ? failure.message : 'The provider operation could not be confirmed.') }
    finally { if (!current.signal.aborted) setPending(null) }
  }
  return <div className="investigation-extras"><section><div className="extras-heading"><Brain size={18} /><h3>Advisory case memory</h3><span>Breeth AI</span></div><p>Only reviewed, redacted context is stored. Retrieved memory cannot override current evidence or accepted payment details.</p><div className="extras-actions"><Button size="sm" variant="outline" onClick={() => perform('retrieve')} disabled={!memoryConfigured || Boolean(pending)}>{pending === 'retrieve' ? <LoaderCircle className="spin" /> : <BookOpen />}Retrieve context</Button><Button size="sm" variant="outline" onClick={() => perform('write')} disabled={!memoryConfigured || !investigation.review || Boolean(pending) || attemptedWrite}>{pending === 'write' ? <LoaderCircle className="spin" /> : <Brain />}Store reviewed context</Button></div>{!memoryConfigured ? <p className="unconfigured-note">{integrations ? 'Breeth is not configured.' : 'Breeth configuration is unavailable.'}</p> : !investigation.review ? <p className="authority-note">Review this investigation before storing memory.</p> : null}{receipt ? <p className="operation-notice" role="status">Memory operation {receipt.operation_id.slice(0, 8)} · {receipt.status.replace(/_/g, ' ')}. Advisory context only.</p> : attemptedWrite && !pending ? <p className="authority-note">The memory write was attempted. Its outcome has not been confirmed; it will not be automatically repeated.</p> : null}{memory ? <div className="memory-results">{memory.items.length ? memory.items.map((item, index) => <article key={`${item.source}:${index}`}><span>Advisory memory</span><p>{item.text}</p><small>Source: {item.source}</small></article>) : <p>No advisory context was returned for this payment.</p>}</div> : null}</section><section><div className="extras-heading"><Volume2 size={18} /><h3>Listen to the explanation</h3><span>ElevenLabs</span></div><p>A stock voice reads the server-redacted, reviewed summary. Audio does not confirm a supplier or approve a transfer.</p><Button size="sm" variant="outline" onClick={() => perform('audio')} disabled={!voiceConfigured || !investigation.review || Boolean(pending)}>{pending === 'audio' ? <LoaderCircle className="spin" /> : <Volume2 />}{audioUrl ? 'Generate a fresh explanation' : 'Generate spoken explanation'}</Button>{!voiceConfigured ? <p className="unconfigured-note">{integrations ? 'ElevenLabs is not configured.' : 'ElevenLabs configuration is unavailable.'}</p> : !investigation.review ? <p className="authority-note">A reviewed investigation is required.</p> : null}{audioUrl ? <audio className="case-audio" controls src={audioUrl} preload="metadata" aria-label="Reviewed investigation explanation" /> : null}</section><ActionError error={error} /></div>
}
