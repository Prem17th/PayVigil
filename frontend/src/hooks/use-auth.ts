import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'

export function useAuth() {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(Boolean(supabase))
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!supabase) return
    let active = true
    let authEventReceived = false
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!active) return
      authEventReceived = true
      setSession(nextSession)
      setLoading(false)
      setError(null)
    })
    supabase.auth.getSession().then(({ data, error: sessionError }) => {
      if (!active || authEventReceived) return
      setSession(data.session)
      setError(sessionError ? 'Your session could not be restored. Please sign in again.' : null)
      setLoading(false)
    }).catch(() => {
      if (!active) return
      setError('Authentication could not be reached. Please try again.')
      setLoading(false)
    })
    return () => { active = false; subscription.unsubscribe() }
  }, [])
  return { session, loading, error }
}
