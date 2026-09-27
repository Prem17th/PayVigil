import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import ts from 'typescript'

const root = fileURLToPath(new URL('../', import.meta.url))
const context = { exports: {}, Intl, Number, Date }
const source = readFileSync(new URL('../src/lib/payments.ts', import.meta.url), 'utf8')
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context)
const amounts = [
  ['1', 100], ['1.01', 101], ['25000.50', 2500050], [' 12.9 ', 1290],
  ['0', null], ['1.001', null], ['-1', null], ['1e3', null],
  ['10000000000.00', 1_000_000_000_000], ['10000000000.01', null], ['90071992547410', null],
]
for (const [input, expected] of amounts) assert.equal(context.exports.toMinor(input), expected, 'INR input must preserve exact paise and enforce the sandbox limit')
console.log(`PASS: ${amounts.length} INR conversion and rejection boundaries`)

const integrations = { exports: {}, URL }
const integrationSource = readFileSync(new URL('../src/lib/integrations.ts', import.meta.url), 'utf8')
vm.runInNewContext(ts.transpileModule(integrationSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, integrations)
assert.equal(integrations.exports.checkoutDestination('https://test.checkout.dodopayments.com/session/synthetic'), 'https://test.checkout.dodopayments.com/session/synthetic')
for (const invalid of [
  'javascript:alert(1)', 'http://test.checkout.dodopayments.com/session/test',
  'https://test.checkout.dodopayments.com.evil.invalid/', 'https://evil.invalid/?next=https://checkout.dodopayments.com',
  'https://user:synthetic@test.checkout.dodopayments.com/', 'https://test.checkout.dodopayments.com:8443/', 'https://test.checkout.dodopayments.com/#unexpected',
]) assert.equal(integrations.exports.checkoutDestination(invalid), null, 'Checkout links must stay on exact approved HTTPS origins')
console.log('PASS: checkout destination allowlist and seven unsafe URL rejections')

let fixtureResponse
let observedRequest
const api = {
  exports: {}, URL, Blob, Response, AbortController,
  window: { setTimeout, clearTimeout },
  fetch: async (_url, options) => { observedRequest = options; return fixtureResponse },
}
const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8').replaceAll('import.meta.env', '({ DEV: true, PROD: false })')
vm.runInNewContext(ts.transpileModule(apiSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, api)
fixtureResponse = new Response('synthetic audio', { headers: { 'content-type': 'audio/mpeg' } })
const audio = await api.exports.requestBlob('/fixture/audio', { token: 'SYNTHETIC_TEST_TOKEN', acceptedTypes: ['audio/mpeg'], maxBytes: 100 })
assert.equal(audio.type, 'audio/mpeg')
assert.equal(observedRequest.headers.Authorization, 'Bearer SYNTHETIC_TEST_TOKEN')
assert.equal(observedRequest.redirect, 'error')
fixtureResponse = new Response('<html>unexpected</html>', { headers: { 'content-type': 'text/html' } })
await assert.rejects(api.exports.requestBlob('/fixture/audio', { acceptedTypes: ['audio/mpeg'] }), /unsupported file type/)
fixtureResponse = new Response('oversized synthetic audio', { headers: { 'content-type': 'audio/mpeg' } })
await assert.rejects(api.exports.requestBlob('/fixture/audio', { acceptedTypes: ['audio/mpeg'], maxBytes: 4 }), /exceeds the size limit/)
fixtureResponse = new Response(JSON.stringify({ error: { message: 'Reports require current entitlement.' } }), { status: 403, headers: { 'content-type': 'application/json' } })
await assert.rejects(api.exports.requestBlob('/fixture/report', { acceptedTypes: ['application/json'] }), /Reports require current entitlement/)
console.log('PASS: authenticated binary requests reject redirects, unexpected types, oversized streams, and denied entitlements')
api.fetch = async () => { throw new TypeError('Synthetic network interruption') }
await assert.rejects(api.exports.request('/fixture/queue', { method: 'POST', body: {} }), /outcome could not be confirmed.*Refresh the record/)
console.log('PASS: uncertain writes require record refresh rather than blind retry')

const guards = [
  ['privileged key prefix', { VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_secret_SYNTHETIC_TEST_ONLY' }, 'Privileged credentials cannot be bundled'],
  ['legacy privileged JWT', { VITE_SUPABASE_PUBLISHABLE_KEY: `e30.${Buffer.from(JSON.stringify({ role: 'service_role' })).toString('base64url')}.synthetic` }, 'Privileged credentials cannot be bundled'],
  ['insecure API origin', { VITE_API_BASE_URL: 'http://example.invalid' }, 'must be an HTTPS origin'],
  ['credential-bearing origin', { VITE_API_BASE_URL: 'https://test:synthetic@example.invalid' }, 'must be an HTTPS origin'],
  ['query-bearing origin', { VITE_API_BASE_URL: 'https://example.invalid?test=synthetic' }, 'must be an HTTPS origin'],
  ['local synthetic identity flag', { VITE_LOCAL_SANDBOX: 'true' }, 'cannot be enabled in a production build'],
]
for (const [label, overrides, expected] of guards) {
  const result = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
    cwd: root,
    env: { ...process.env, VITE_SUPABASE_URL: '', VITE_SUPABASE_PUBLISHABLE_KEY: '', VITE_API_BASE_URL: '', VITE_LOCAL_SANDBOX: '', ...overrides },
    encoding: 'utf8',
  })
  assert.notEqual(result.status, 0, `${label} must be rejected`)
  assert.ok(`${result.stdout}${result.stderr}`.includes(expected), `${label} must fail before bundling`)
  console.log(`PASS: ${label} rejected before bundling`)
}
