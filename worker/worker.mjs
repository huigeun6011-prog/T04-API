// Kakao REST credentials stay in the Worker Secret binding, never in the URL.
const UPSTREAM = 'https://dapi.kakao.com/v2/maps/staticmap';
const MAX_IMAGE_BYTES = 16 * 1024 * 1024;
const TIMEOUT_MS = 10000;
const PARAMETERS = new Set(['center', 'lv', 'width', 'height', 'scale', 'marker']);
const DEFAULT_ALLOWED_ORIGINS = 'https://huigeun6011-prog.github.io,http://127.0.0.1:5501,http://localhost:5501';

function allowedOrigin(request, env) {
  const origin = request.headers.get('Origin');
  if (!origin || origin === 'null') return null;
  const configured = String(env.ALLOWED_ORIGINS ?? DEFAULT_ALLOWED_ORIGINS).split(',').map(value => value.trim());
  return configured.includes(origin) ? origin : null;
}

function responseHeaders(origin) {
  const headers = new Headers({
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Vary': 'Origin',
  });
  if (origin) headers.set('Access-Control-Allow-Origin', origin);
  return headers;
}

function failure(status, code, origin) {
  const headers = responseHeaders(origin);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify({ error: code }), { status, headers });
}

function integer(value, minimum, maximum) {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : null;
}

function coordinate(value) {
  const coordinates = value?.split(',');
  if (coordinates?.length !== 2 || coordinates.some(value => !/^-?\d+(?:\.\d+)?$/.test(value))) return null;
  const [longitude, latitude] = coordinates.map(Number);
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) return null;
  return `${longitude},${latitude}`;
}

function parseParameters(url) {
  for (const name of url.searchParams.keys()) {
    if (!PARAMETERS.has(name) || (name !== 'marker' && url.searchParams.getAll(name).length !== 1)) return null;
  }
  const center = coordinate(url.searchParams.get('center'));
  const markers = url.searchParams.getAll('marker').map(coordinate);
  if (!center || markers.length > 5 || markers.some(value => !value)) return null;
  const lv = integer(url.searchParams.get('lv'), 1, 15);
  const width = integer(url.searchParams.get('width'), 1, 2048);
  const height = integer(url.searchParams.get('height'), 1, 1024);
  const scale = integer(url.searchParams.get('scale') ?? '1', 1, 2);
  return lv && width && height && scale ? { center, markers, lv, width, height, scale } : null;
}

async function readImage(response) {
  const type = (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
  if (type !== 'image/png' && type !== 'image/jpeg') throw new Error('invalid-image');
  const contentLength = response.headers.get('Content-Length');
  if (contentLength !== null && (!/^\d+$/.test(contentLength) || Number(contentLength) > MAX_IMAGE_BYTES)) throw new Error('invalid-image');
  if (!response.body) throw new Error('invalid-image');
  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      length += chunk.value.byteLength;
      if (length > MAX_IMAGE_BYTES) throw new Error('invalid-image');
      chunks.push(chunk.value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const png = [137, 80, 78, 71, 13, 10, 26, 10];
  const valid = type === 'image/png'
    ? bytes.length >= 8 && png.every((value, index) => bytes[index] === value)
    : bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  if (!valid) throw new Error('invalid-image');
  return { bytes, type };
}

export async function handleRequest(request, env, fetchUpstream = fetch) {
  const url = new URL(request.url);
  const origin = allowedOrigin(request, env);
  if (url.pathname === '/api/health' && request.method === 'GET') {
    const headers = responseHeaders(origin);
    headers.set('Content-Type', 'application/json; charset=utf-8');
    return new Response(JSON.stringify({ status: 'ok', service: 'map-image-proxy' }), { headers });
  }
  if (url.pathname !== '/api/map-image') return failure(404, 'not_found', origin);
  // Deny missing and opaque origins too: deployed origins must be explicitly configured.
  if (!origin) return failure(403, 'origin_not_allowed');
  if (request.method === 'OPTIONS') {
    if (request.headers.get('Access-Control-Request-Method') !== 'GET' || request.headers.get('Access-Control-Request-Headers')) return failure(403, 'preflight_not_allowed', origin);
    const headers = responseHeaders(origin);
    headers.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
    headers.set('Access-Control-Max-Age', '86400');
    return new Response(null, { status: 204, headers });
  }
  if (request.method !== 'GET') return failure(405, 'method_not_allowed', origin);
  const parameters = parseParameters(url);
  if (!parameters) return failure(400, 'invalid_parameters', origin);
  if (typeof env.KAKAO_MAP_API_KEY !== 'string' || !/^[A-Za-z0-9_-]{10,256}$/.test(env.KAKAO_MAP_API_KEY)) return failure(503, 'map_not_configured', origin);

  const upstream = new URL(UPSTREAM);
  upstream.searchParams.set('center', parameters.center);
  upstream.searchParams.set('lv', String(parameters.lv));
  upstream.searchParams.set('size', `${parameters.width}x${parameters.height}`);
  upstream.searchParams.set('scale', String(parameters.scale));
  upstream.searchParams.set('coord', 'WGS84');
  upstream.searchParams.set('format', 'png');
  upstream.searchParams.set('logo_pos', 'BOTTOM_LEFT');
  for (const marker of parameters.markers) upstream.searchParams.append('markers', `location:${marker}|option:true`);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const result = await fetchUpstream(upstream.href, {
      method: 'GET',
      redirect: 'manual',
      signal: controller.signal,
      headers: { Authorization: `KakaoAK ${env.KAKAO_MAP_API_KEY}`, Accept: 'image/png' },
    });
    if (!result.ok || result.status >= 300 || result.redirected) {
      await result.body?.cancel().catch(() => {});
      return failure(502, 'map_unavailable', origin);
    }
    const image = await readImage(result);
    const headers = responseHeaders(origin);
    headers.set('Content-Type', image.type);
    headers.set('Content-Length', String(image.bytes.byteLength));
    headers.set('X-Map-Center', parameters.center);
    headers.set('X-Map-Level', String(parameters.lv));
    headers.set('X-Map-Lv', String(parameters.lv));
    headers.set('X-Map-Width', String(parameters.width));
    headers.set('X-Map-Height', String(parameters.height));
    headers.set('X-Map-Size', `${parameters.width}x${parameters.height}`);
    headers.set('X-Map-Scale', String(parameters.scale));
    headers.set('Access-Control-Expose-Headers', 'X-Map-Center, X-Map-Level, X-Map-Lv, X-Map-Width, X-Map-Height, X-Map-Size, X-Map-Scale');
    return new Response(image.bytes, { headers });
  } catch {
    // Never return or log an upstream URL, body, exception, headers, or secret.
    return failure(controller.signal.aborted ? 504 : 502, 'map_unavailable', origin);
  } finally {
    clearTimeout(timeout);
  }
}

export default { fetch(request, env) { return handleRequest(request, env); } };
