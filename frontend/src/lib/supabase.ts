import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL?.trim()
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim()

function configure(): { client: SupabaseClient | null; error: string | null } {
  if (!url || !key) return { client: null, error: 'Authentication not configured' }
  try {
    const parsed = new URL(url)
    const localHttp = import.meta.env.DEV && parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname)
    let privilegedKey = key.startsWith('sb_secret_')
    if (key.split('.').length === 3) {
      try { privilegedKey ||= JSON.parse(atob(key.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).role === 'service_role' } catch { /* Auth will reject a malformed key. */ }
    }
    if (privilegedKey || (parsed.protocol !== 'https:' && !localHttp) || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') {
      return { client: null, error: 'Authentication configuration is invalid' }
    }
    return {
      client: createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } }),
      error: null,
    }
  } catch {
    return { client: null, error: 'Authentication configuration is invalid' }
  }
}

const configuration = configure()
export const supabase = configuration.client
export const authConfigurationError = configuration.error
