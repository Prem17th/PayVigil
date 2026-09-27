import { useEffect, useState } from 'react'
import { request } from '../lib/api'

export interface Resource<T> { data: T | null; loading: boolean; error: string | null }

export function useApi<T>(path: string, token?: string, enabled = true, revision = 0): Resource<T> {
  const key = `${path}:${token ?? 'public'}:${revision}`
  const [state, setState] = useState<Resource<T> & { key: string }>({ key: '', data: null, loading: enabled, error: null })
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setState({ key, data: null, loading: true, error: null })
    request<T>(path, { token, signal: controller.signal }).then(
      (data) => { if (!controller.signal.aborted) setState({ key, data, loading: false, error: null }) },
      (error: unknown) => { if (!controller.signal.aborted) setState({ key, data: null, loading: false, error: error instanceof Error ? error.message : 'Request failed.' }) },
    )
    return () => controller.abort()
  }, [path, token, enabled, key])
  if (!enabled) return { data: null, loading: false, error: null }
  if (state.key !== key) return { data: null, loading: true, error: null }
  return state
}
