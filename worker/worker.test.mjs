import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { handleRequest } from './worker.mjs';

const ORIGIN = 'https://site.example';
const SECRET = 'test-secret-value-123456';
const ENV = { ALLOWED_ORIGINS: ORIGIN, KAKAO_MAP_API_KEY: SECRET };
const QUERY = 'center=127.3845,36.3504&lv=6&width=1024&height=640&scale=1';
const PNG = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 0]);
const request = (query = QUERY, origin = ORIGIN, method = 'GET', extra = {}) => new Request(`https://worker.example/api/map-image?${query}`, {
  method, headers: { ...(origin === undefined ? {} : { Origin: origin }), ...extra },
});
const image = (headers = {}) => new Response(PNG, { headers: { 'Content-Type': 'image/png', ...headers } });
const neverFetch = () => { throw new Error('Upstream must not be called'); };

test('only fixed API is called; authorization never appears in browser response or URL', async () => {
  let calls = 0;
  const response = await handleRequest(request(), ENV, async (url, options) => {
    calls++;
    const upstream = new URL(url);
    assert.equal(upstream.origin + upstream.pathname, 'https://dapi.kakao.com/v2/maps/staticmap');
    assert.equal(upstream.searchParams.get('coord'), 'WGS84');
    assert.equal(upstream.searchParams.get('center'), '127.3845,36.3504');
    assert.equal(upstream.searchParams.get('size'), '1024x640');
    assert.equal(upstream.searchParams.get('scale'), '1');
    assert.equal(upstream.searchParams.get('format'), 'png');
    assert.equal(upstream.searchParams.get('logo_pos'), 'BOTTOM_LEFT');
    assert.equal(url.includes(SECRET), false);
    assert.equal(options.headers.Authorization, `KakaoAK ${SECRET}`);
    assert.equal(options.redirect, 'manual');
    assert.equal(Object.keys(options.headers).length, 2);
    return image({ 'Set-Cookie': 'private=value', 'X-Upstream-Secret': SECRET });
  });
  assert.equal(calls, 1);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.equal(response.headers.get('X-Map-Center'), '127.3845,36.3504');
  assert.equal(response.headers.get('X-Map-Lv'), '6');
  assert.equal(response.headers.get('X-Map-Width'), '1024');
  assert.equal(response.headers.get('X-Map-Height'), '640');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('Set-Cookie'), null);
  assert.equal(response.headers.get('X-Upstream-Secret'), null);
  assert.equal(JSON.stringify([...response.headers]).includes(SECRET), false);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), PNG);
});

test('unapproved, opaque, missing and lookalike origins are denied without upstream calls', async () => {
  for (const origin of ['https://other.example', 'null', '', `${ORIGIN}.evil.example`, `${ORIGIN}/path`]) {
    const response = await handleRequest(request(QUERY, origin), ENV, neverFetch);
    assert.equal(response.status, 403);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
  }
  const absent = new Request(`https://worker.example/api/map-image?${QUERY}`);
  assert.equal((await handleRequest(absent, ENV, neverFetch)).status, 403);
});

test('default origins are explicit and empty configured allowlist denies all', async () => {
  const defaultEnv = { KAKAO_MAP_API_KEY: SECRET };
  const response = await handleRequest(request(QUERY, 'https://huigeun6011-prog.github.io'), defaultEnv, async () => image());
  assert.equal(response.status, 200);
  assert.equal((await handleRequest(request(QUERY, 'https://huigeun6011-prog.github.io'), { ...defaultEnv, ALLOWED_ORIGINS: '' }, neverFetch)).status, 403);
});

test('invalid, duplicate, injected and out-of-bounds parameters are rejected', async () => {
  const invalid = [
    QUERY + '&url=https://evil.example', QUERY + '&key=secret', QUERY + '&lv=5',
    QUERY.replace('lv=6', 'lv=16'), QUERY.replace('lv=6', 'lv=0'), QUERY.replace('lv=6', 'lv=6.1'),
    QUERY.replace('width=1024', 'width=2049'), QUERY.replace('width=1024', 'width=0'),
    QUERY.replace('height=640', 'height=1025'), QUERY.replace('scale=1', 'scale=3'),
    QUERY.replace('127.3845,36.3504', '181,36'), QUERY.replace('127.3845,36.3504', '127,91'),
    QUERY.replace('127.3845,36.3504', 'NaN,36'), QUERY.replace('127.3845,36.3504', '127,36,10'),
    QUERY.replace('127.3845,36.3504', 'https://evil.example'), '',
    QUERY + '&marker=127,36|option:false', QUERY + '&marker=https://evil.example',
    QUERY + '&marker=181,36', QUERY + '&marker=127,91', QUERY + '&marker=',
    QUERY + '&marker=127,36'.repeat(6),
  ];
  for (const query of invalid) assert.equal((await handleRequest(request(query), ENV, neverFetch)).status, 400, query);
});

test('calibration markers accept at most five coordinate pairs with fixed server options', async () => {
  const response = await handleRequest(request(QUERY + '&marker=127.3845,36.3504&marker=127.3855,36.3504'), ENV, async url => {
    assert.deepEqual(new URL(url).searchParams.getAll('markers'), [
      'location:127.3845,36.3504|option:true',
      'location:127.3855,36.3504|option:true',
    ]);
    return image();
  });
  assert.equal(response.status, 200);
});

test('Cloudflare default fetch ignores ExecutionContext as injectable transport', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => image();
  try {
    const response = await worker.fetch(request(), ENV, { waitUntil() {} });
    assert.equal(response.status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('method and preflight restrictions enforce image-only GET contract', async () => {
  assert.equal((await handleRequest(request(QUERY, ORIGIN, 'POST'), ENV, neverFetch)).status, 405);
  const response = await handleRequest(request(QUERY, ORIGIN, 'OPTIONS', { 'Access-Control-Request-Method': 'GET' }), ENV, neverFetch);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Access-Control-Allow-Methods'), 'GET, OPTIONS');
  assert.equal((await handleRequest(request(QUERY, ORIGIN, 'OPTIONS', { 'Access-Control-Request-Method': 'POST' }), ENV, neverFetch)).status, 403);
  assert.equal((await handleRequest(request(QUERY, ORIGIN, 'OPTIONS', { 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'Authorization' }), ENV, neverFetch)).status, 403);
});

test('redirects, upstream errors, exception text and non-image bodies are sanitized', async () => {
  const variants = [
    () => new Response(SECRET, { status: 302, headers: { Location: `https://evil.example/?key=${SECRET}` } }),
    () => new Response(SECRET, { status: 401 }),
    () => new Response(SECRET, { headers: { 'Content-Type': 'application/json' } }),
    () => new Response(SECRET, { headers: { 'Content-Type': 'image/png' } }),
    () => { throw new Error(SECRET); },
  ];
  for (const upstream of variants) {
    const response = await handleRequest(request(), ENV, upstream);
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: 'map_unavailable' });
    assert.equal(JSON.stringify([...response.headers]).includes(SECRET), false);
  }
});

test('image type and signature agree; JPEG is allowed but fake JPEG is rejected', async () => {
  const good = await handleRequest(request(), ENV, async () => new Response(new Uint8Array([255, 216, 255, 0]), { headers: { 'Content-Type': 'image/jpeg' } }));
  assert.equal(good.status, 200);
  assert.equal(good.headers.get('Content-Type'), 'image/jpeg');
  const bad = await handleRequest(request(), ENV, async () => image({ 'Content-Type': 'image/jpeg' }));
  assert.equal(bad.status, 502);
});

test('both advertised and streamed image size are bounded', async () => {
  const advertised = await handleRequest(request(), ENV, async () => image({ 'Content-Length': String(16 * 1024 * 1024 + 1) }));
  assert.equal(advertised.status, 502);
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(16 * 1024 * 1024 + 1)); },
    cancel() { cancelled = true; },
  });
  const streamed = await handleRequest(request(), ENV, async () => new Response(stream, { headers: { 'Content-Type': 'image/png' } }));
  assert.equal(streamed.status, 502);
  assert.equal(cancelled, true);
});

test('health and unknown paths reveal no configuration, key, or upstream body', async () => {
  const health = await worker.fetch(new Request('https://worker.example/api/health'), ENV, {});
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: 'ok', service: 'map-image-proxy' });
  assert.equal((await handleRequest(new Request('https://worker.example/'), ENV, neverFetch)).status, 404);
  assert.equal((await handleRequest(request(), { ALLOWED_ORIGINS: ORIGIN }, neverFetch)).status, 503);
});
