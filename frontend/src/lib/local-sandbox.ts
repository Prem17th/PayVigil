const authOrigin = import.meta.env.VITE_SUPABASE_URL?.trim()
const apiOrigin = import.meta.env.VITE_API_BASE_URL?.trim()

function localOrigin(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && ['http:', 'https:'].includes(url.protocol)
      && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/'
      ? url.origin : null
  } catch { return null }
}

export const localSandboxOrigin = import.meta.env.DEV
  && import.meta.env.VITE_LOCAL_SANDBOX === 'true'
  && localOrigin(window.location.origin)
  && (!apiOrigin || localOrigin(apiOrigin))
  ? localOrigin(authOrigin) : null

export const localSandboxEnabled = Boolean(localSandboxOrigin)
