export interface Health {
  status: 'ok'
  service: 'beforetransfer-api'
  version: string
  phase: number
}

export interface Setup {
  auth_configured: boolean
  database_configured: boolean
  storage_configured: boolean
  phase: number
  capabilities: { payments: boolean; investigations: boolean }
}

export interface Identity {
  user_id: string
  email: string | null
  tenant: { id: string; name: string }
  role: 'finance_admin' | 'finance_reviewer' | 'supplier'
}

export interface Workspace {
  phase: number
  tenant: { id: string; name: string }
  role: 'finance_admin' | 'finance_reviewer'
  status: 'empty'
  cases: []
  capabilities: { payments: boolean; investigations: boolean }
}

export interface SupplierPortal {
  phase: number
  tenant: { id: string; name: string }
  role: 'supplier'
  status: 'empty'
  requests: []
}

export interface StorageCheck {
  phase: number
  status: 'verified'
  checked_at: string
  checks: {
    bucket_private: boolean
    upload: boolean
    authenticated_read: boolean
    anonymous_read_denied: boolean
    deleted: boolean
  }
}

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
function configurationError(): string | null {
  if (!apiBase) return import.meta.env.PROD ? 'API connection not configured. Set the production API origin to enable workspace access.' : null
  try {
    const url = new URL(apiBase)
    const localHttp = import.meta.env.DEV && url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname)
    if ((url.protocol !== 'https:' && !localHttp) || url.username || url.password || url.search || url.hash || url.pathname !== '/') return 'API connection configuration is invalid.'
    return null
  } catch { return 'API connection configuration is invalid.' }
}
export const apiConfigurationError = configurationError()

export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); this.name = 'ApiError' }
}

interface RequestOptions {
  token?: string
  signal?: AbortSignal
  method?: 'GET' | 'POST'
  body?: Record<string, unknown>
  idempotencyKey?: string
  timeoutMs?: number
  accept?: string
}

async function performRequest<T>(path: string, options: RequestOptions, decode: (response: Response) => Promise<T>): Promise<T> {
  if (apiConfigurationError) throw new ApiError(apiConfigurationError)
  const controller = new AbortController()
  const timeoutMs = options.timeoutMs ?? (options.method === 'POST' && path === '/api/storage/check' ? 60000 : 12000)
  const timeout = window.setTimeout(() => controller.abort(), Math.max(1000, Math.min(timeoutMs, 180000)))
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) controller.abort()
  try {
    const response = await fetch(`${apiBase}${path}`, {
      method: options.method ?? 'GET',
      headers: {
        Accept: options.accept ?? 'application/json',
        ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
      redirect: 'error',
    })
    if (!response.ok) {
      const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null
      const message = typeof body?.error?.message === 'string' ? body.error.message : typeof body?.detail === 'string' ? body.detail : 'The request could not be completed.'
      throw new ApiError(message, response.status)
    }
    return await decode(response)
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (options.signal?.aborted) throw error
    if (options.method === 'POST') throw new ApiError('The outcome could not be confirmed. Refresh the record before trying another action.')
    if (controller.signal.aborted) throw new ApiError('The API took too long to respond. Please try again.')
    throw new ApiError('The API is unreachable. Check that the service is running, then try again.')
  } finally {
    window.clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return performRequest(path, options, async response => {
    if (!response.headers.get('content-type')?.includes('application/json')) throw new ApiError('The API returned an unexpected response. Check the API connection.', response.status)
    try { return await response.json() as T }
    catch { throw new ApiError('The API returned an invalid JSON response.', response.status) }
  })
}

export function requestBlob(path: string, options: RequestOptions & { acceptedTypes: string[]; maxBytes?: number }): Promise<Blob> {
  return performRequest(path, { ...options, accept: options.acceptedTypes.join(', ') }, async response => {
    const mediaType = (response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase()
    if (!options.acceptedTypes.includes(mediaType)) throw new ApiError('The API returned an unsupported file type.')
    const maxBytes = options.maxBytes ?? 10 * 1024 * 1024
    if (Number(response.headers.get('content-length') ?? 0) > maxBytes) throw new ApiError('The returned file exceeds the size limit.')
    if (!response.body) throw new ApiError('The API returned an empty file.')
    const reader = response.body.getReader()
    const chunks: ArrayBuffer[] = []
    let size = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > maxBytes) { await reader.cancel(); throw new ApiError('The returned file exceeds the size limit.') }
        chunks.push(value.slice().buffer as ArrayBuffer)
      }
    } finally { reader.releaseLock() }
    if (!size) throw new ApiError('The API returned an empty file.')
    return new Blob(chunks, { type: mediaType })
  })
}
