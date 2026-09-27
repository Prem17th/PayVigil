import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  if (command === 'build' && env.VITE_LOCAL_SANDBOX === 'true') {
    throw new Error('VITE_LOCAL_SANDBOX is local test infrastructure and cannot be enabled in a production build.')
  }
  const key = env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim()
  let privilegedKey = key?.startsWith('sb_secret_') ?? false
  if (key?.split('.').length === 3) {
    try { privilegedKey ||= JSON.parse(Buffer.from(key.split('.')[1], 'base64url').toString()).role === 'service_role' } catch { /* Invalid public keys will be rejected by authentication. */ }
  }
  if (privilegedKey) throw new Error('VITE_SUPABASE_PUBLISHABLE_KEY must contain a browser-safe publishable or anon key. Privileged credentials cannot be bundled.')
  for (const name of ['VITE_SUPABASE_URL', 'VITE_API_BASE_URL']) {
    const value = env[name]?.trim()
    if (!value) continue
    let valid = false
    try {
      const url = new URL(value)
      const localHttp = command === 'serve' && url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname)
      valid = (url.protocol === 'https:' || localHttp) && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/'
    } catch { /* Report the variable name only, never its value. */ }
    if (!valid) throw new Error(`${name} must be an HTTPS origin without credentials, paths, query parameters, or fragments.`)
  }
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5176,
      strictPort: true,
      proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
    },
  }
})
