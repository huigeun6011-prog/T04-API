// Quota-bounded live verification. This script never reads an API key or .env.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { inflateSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const MAX_BYTES = 16 * 1024 * 1024;
const CASES = [{ lv: 2, scale: 1 }, { lv: 3, scale: 1 }, { lv: 4, scale: 1 }, { lv: 3, scale: 2 }];
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function paeth(a, b, c) {
  const p = a + b - c, aa = Math.abs(p - a), bb = Math.abs(p - b), cc = Math.abs(p - c);
  return aa <= bb && aa <= cc ? a : bb <= cc ? b : c;
}

export function decodePNG(input) {
  const bytes = Buffer.from(input);
  if (bytes.length < 33 || !bytes.subarray(0, 8).equals(PNG_SIGNATURE)) throw new Error('invalid_png');
  let width, height, bitDepth, colorType, interlace, palette, transparency;
  const data = [];
  let offset = 8;
  while (offset + 12 <= bytes.length) {
    const length = bytes.readUInt32BE(offset), type = bytes.toString('ascii', offset + 4, offset + 8);
    if (offset + 12 + length > bytes.length) throw new Error('truncated_png');
    const chunk = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      if (length !== 13) throw new Error('invalid_png_header');
      width = chunk.readUInt32BE(0); height = chunk.readUInt32BE(4);
      bitDepth = chunk[8]; colorType = chunk[9]; interlace = chunk[12];
      if (chunk[10] !== 0 || chunk[11] !== 0) throw new Error('unsupported_png_compression');
    } else if (type === 'IDAT') data.push(chunk);
    else if (type === 'PLTE') palette = chunk;
    else if (type === 'tRNS') transparency = chunk;
    offset += length + 12;
    if (type === 'IEND') break;
  }
  const channels = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colorType];
  if (!width || !height || width > 4096 || height > 2048 || !channels || interlace !== 0) throw new Error('unsupported_png_layout');
  if (bitDepth !== 8 && !(colorType === 3 && [1, 2, 4].includes(bitDepth))) throw new Error('unsupported_png_bit_depth');
  if (colorType === 3 && !palette) throw new Error('missing_png_palette');
  const stride = Math.ceil(width * channels * bitDepth / 8), bpp = Math.max(1, Math.ceil(channels * bitDepth / 8));
  const raw = inflateSync(Buffer.concat(data), { maxOutputLength: (stride + 1) * height });
  if (raw.length !== (stride + 1) * height) throw new Error('invalid_png_data');
  const scan = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    if (filter > 4) throw new Error('invalid_png_filter');
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? scan[y * stride + x - bpp] : 0;
      const b = y ? scan[(y - 1) * stride + x] : 0;
      const c = y && x >= bpp ? scan[(y - 1) * stride + x - bpp] : 0;
      const prediction = [0, a, b, Math.floor((a + b) / 2), paeth(a, b, c)][filter];
      scan[y * stride + x] = (raw[y * (stride + 1) + 1 + x] + prediction) & 255;
    }
  }
  const rgba = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const out = (y * width + x) * 4, source = y * stride + x * channels;
    let red, green, blue, alpha = 255;
    if (colorType === 3) {
      const shift = 8 - bitDepth - (x * bitDepth) % 8;
      const index = (scan[y * stride + Math.floor(x * bitDepth / 8)] >> shift) & ((1 << bitDepth) - 1);
      if (index * 3 + 2 >= palette.length) throw new Error('invalid_png_palette');
      red = palette[index * 3]; green = palette[index * 3 + 1]; blue = palette[index * 3 + 2];
      alpha = transparency?.[index] ?? 255;
    } else if (colorType === 0 || colorType === 4) {
      red = green = blue = scan[source];
      if (colorType === 4) alpha = scan[source + 1];
    } else {
      red = scan[source]; green = scan[source + 1]; blue = scan[source + 2];
      if (colorType === 6) alpha = scan[source + 3];
    }
    rgba[out] = red; rgba[out + 1] = green; rgba[out + 2] = blue; rgba[out + 3] = alpha;
  }
  return { width, height, bitDepth, colorType, rgba };
}

export function expectedTip(dx, dy, lv, scale, width = 640, height = 480) {
  const metresPerPixel = 2 ** (lv - 3);
  return { x: (width / 2 + dx / metresPerPixel) * scale, y: (height / 2 - dy / metresPerPixel) * scale };
}

// A diagnostic hint only. Labels, roads and pin outlines may share these colors;
// the saved crosshair overlay remains the source for final visual verification.
function redCandidates(image, tip, scale) {
  const minX = Math.max(0, Math.floor(tip.x - 22 * scale));
  const maxX = Math.min(image.width - 1, Math.ceil(tip.x + 22 * scale));
  const minY = Math.max(0, Math.floor(tip.y - 48 * scale));
  const maxY = Math.min(image.height - 1, Math.ceil(tip.y + 5 * scale));
  let count = 0, left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
  const bottomXs = [];
  for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) {
    const p = (y * image.width + x) * 4;
    const [r, g, b, a] = image.rgba.subarray(p, p + 4);
    if (a > 200 && r > 155 && r > g * 1.5 && r > b * 1.35 && g < 145) {
      count++; left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y);
      if (y > bottom) { bottom = y; bottomXs.length = 0; }
      if (y === bottom) bottomXs.push(x);
    }
  }
  if (count < 8 * scale * scale) return null;
  return { classification: 'unverified_red_pixel_candidate', pixels: count, bounds: { left, top, right, bottom }, bottomMeanX: bottomXs.reduce((a, b) => a + b, 0) / bottomXs.length, expectedTip: tip };
}

async function boundedBody(response) {
  if (Number(response.headers.get('Content-Length') || 0) > MAX_BYTES) throw new Error('image_too_large');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('missing_image_body');
  const chunks = []; let size = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > MAX_BYTES) throw new Error('image_too_large');
      chunks.push(Buffer.from(result.value));
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  return Buffer.concat(chunks);
}

function html(report) {
  const cards = report.cases.filter(item => item.file).map(item => {
    const crosses = item.markers.map(marker => {
      const { x, y } = marker.expectedPhysicalTip;
      return `<g stroke="#00f4ff" stroke-width="${item.scale}" fill="none"><circle cx="${x}" cy="${y}" r="${7 * item.scale}"/><path d="M${x - 12 * item.scale},${y}h${24 * item.scale}M${x},${y - 12 * item.scale}v${24 * item.scale}"/></g>`;
    }).join('');
    return `<section><h2>lv ${item.lv} / scale ${item.scale}</h2><p>${item.image.width} × ${item.image.height} physical pixels; dimension check: ${item.dimensionsMatch ? 'PASS' : 'FAIL'}</p><svg width="640" viewBox="0 0 ${item.image.width} ${item.image.height}" aria-label="Expected official pin tips marked by cyan crosshairs"><image href="${item.file}" width="${item.image.width}" height="${item.image.height}"/><g class="guides">${crosses}</g></svg></section>`;
  }).join('');
  return `<!doctype html><meta charset="utf-8"><title>Map proxy calibration</title><style>body{font:15px system-ui;margin:24px;background:#152330;color:#fff}h1{font-size:24px}main{display:flex;flex-wrap:wrap;gap:24px}section{max-width:100%}svg{max-width:100%;height:auto;background:#fff}button{padding:10px;cursor:pointer}a{color:#70e4ff}.hide .guides{display:none}</style><h1>Kakao REST image calibration</h1><p>Expected tips: map center, 100 WTM metres east, 100 WTM metres north. Cyan crosshairs must meet the official pin tips. Marker color candidates in report.json are hints requiring visual review.</p><p><button onclick="document.body.classList.toggle('hide')">Toggle expected crosshairs</button> <a href="report.json">report.json</a></p><main>${cards}</main>`;
}

async function main() {
  const args = process.argv.slice(2), options = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!['--endpoint', '--origin', '--output-dir'].includes(args[i]) || !args[i + 1]) throw new Error('invalid_arguments');
    options[args[i]] = args[i + 1];
  }
  const endpoint = new URL(options['--endpoint'] || 'https://empty-frost-777b.huigeun6011.workers.dev');
  if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash || (endpoint.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(endpoint.hostname))) throw new Error('invalid_endpoint');
  const origin = options['--origin'] || 'http://127.0.0.1:5501';
  if (new URL(origin).origin !== origin) throw new Error('invalid_origin');
  const outputDir = resolve(ROOT, options['--output-dir'] || 'outputs/map-proxy-qa');
  await mkdir(outputDir, { recursive: true });
  const sandbox = { window: {} };
  runInNewContext(await readFile(join(ROOT, 'static_src/map-projection.js'), 'utf8'), sandbox, { timeout: 1000 });
  const projection = sandbox.window.MapViewProjection;
  const center = { lat: 36.3504, lng: 127.3845 }, projected = projection.forward(center.lat, center.lng);
  const markers = [{ name: 'center', dx: 0, dy: 0 }, { name: 'east100m', dx: 100, dy: 0 }, { name: 'north100m', dx: 0, dy: 100 }]
    .map(marker => ({ ...marker, coordinate: projection.inverse(projected.x + marker.dx, projected.y + marker.dy) }));
  const report = { timestamp: new Date().toISOString(), endpoint: endpoint.origin, origin, center, logicalSize: { width: 640, height: 480 }, requestsPlanned: 4, cases: [], visualCalibration: 'pending_manual_tip_verification' };
  let failed = false;
  for (const item of CASES) {
    const record = { ...item, markers: markers.map(marker => ({ ...marker, expectedPhysicalTip: expectedTip(marker.dx, marker.dy, item.lv, item.scale) })) };
    report.cases.push(record);
    const url = new URL('/api/map-image', endpoint);
    url.search = new URLSearchParams({ center: `${center.lng},${center.lat}`, lv: String(item.lv), width: '640', height: '480', scale: String(item.scale) });
    for (const marker of markers) url.searchParams.append('marker', `${marker.coordinate.lng},${marker.coordinate.lat}`);
    try {
      const response = await fetch(url, { headers: { Origin: origin }, redirect: 'manual', signal: AbortSignal.timeout(20000) });
      record.status = response.status;
      if (response.status !== 200 || response.headers.get('Content-Type')?.split(';')[0] !== 'image/png') {
        await response.body?.cancel(); record.result = 'http_or_image_type_failure'; failed = true; break;
      }
      const bytes = await boundedBody(response), image = decodePNG(bytes);
      record.image = { width: image.width, height: image.height, bitDepth: image.bitDepth, colorType: image.colorType, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
      record.dimensionsMatch = image.width === 640 * item.scale && image.height === 480 * item.scale;
      record.corsMatches = response.headers.get('Access-Control-Allow-Origin') === origin;
      record.file = `lv${item.lv}-scale${item.scale}.png`;
      record.markers.forEach(marker => { marker.redPixelCandidate = redCandidates(image, marker.expectedPhysicalTip, item.scale); });
      await writeFile(join(outputDir, record.file), bytes);
      record.result = record.dimensionsMatch && record.corsMatches ? 'structural_checks_passed_visual_review_required' : 'structural_check_failed';
      if (!record.dimensionsMatch || !record.corsMatches) failed = true;
      console.log(`lv${item.lv}/scale${item.scale}: HTTP ${record.status}, ${image.width}x${image.height}, dimensions ${record.dimensionsMatch ? 'PASS' : 'FAIL'}, CORS ${record.corsMatches ? 'PASS' : 'FAIL'}`);
    } catch {
      record.result = 'request_or_png_decode_failure'; failed = true; break;
    }
  }
  report.requestsMade = report.cases.length;
  report.structuralChecksPassed = !failed && report.cases.length === CASES.length;
  await writeFile(join(outputDir, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await writeFile(join(outputDir, 'index.html'), html(report));
  console.log(`Saved ${report.requestsMade} request results to ${outputDir}; visual pin-tip verification is pending.`);
  if (failed) process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => { console.error('Calibration utility failed; no upstream body, headers, or credentials were printed.'); process.exitCode = 1; });
}
