import { useEffect, useRef, useState } from 'react'
import { requestBlob } from '../lib/api'

export function useDownload(token: string) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const urls = useRef(new Set<string>())
  useEffect(() => () => { controller.current?.abort(); for (const url of urls.current) URL.revokeObjectURL(url); urls.current.clear() }, [])
  async function download(path: string, filename: string, acceptedTypes: string[]) {
    if (pending) return
    const current = new AbortController()
    controller.current = current
    setPending(true); setError(null)
    try {
      const blob = await requestBlob(path, { token, signal: current.signal, acceptedTypes, timeoutMs: 45000 })
      if (current.signal.aborted) return
      const url = URL.createObjectURL(blob)
      urls.current.add(url)
      const link = document.createElement('a')
      link.href = url
      link.download = filename.replace(/[\u0000-\u001f<>:"/\\|?*]/g, '_').slice(0, 180)
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => { URL.revokeObjectURL(url); urls.current.delete(url) }, 30000)
    } catch (failure) { if (!current.signal.aborted) setError(failure instanceof Error ? failure.message : 'The file could not be downloaded.') }
    finally { if (!current.signal.aborted) setPending(false) }
  }
  return { download, pending, error }
}
