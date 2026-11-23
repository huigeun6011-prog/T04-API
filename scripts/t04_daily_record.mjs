// T04 일별 기록: 대전 1호선 운행일 총 승하차 합계(명)를 data.go.kr getTicketTypeTraffic01 에서 받아 기록한다.
//
// 값 정의: 운행일 D 의 합계 = (승차+하차, 모든 권종·모든 역)의 D일 05~23시 + D+1일 00시.
//   D일 자신의 00시는 제외하고 01~04시는 무시한다(docs/DECISIONS.md D-002, data/processed/subway 와 같은 규칙).
//   entryFlag 0=승차, 1=하차(scripts/data_prep/process_subway.py). 합계에서는 둘 다 더한다.
// 공개 시점: 날짜 T 14시(KST) 이후 T-1일 자료가 열린다. 그래서 조회일 T 에 완성되는 최신 운행일은 D=T-2.
// 기록 키: record_date = 조회한 KST 날짜(같은 signal_id+record_date 는 갱신, 다음 날은 새 행).
// 미집계(D 또는 D+1 자료가 비어 있음)는 실패가 아니라 정상 상태: 행을 만들지 않고 종료 코드 0.
// 조회 실패는 daily.json 을 건드리지 않는다. 비밀키(SUBWAY_API_KEY)는 환경변수로만 읽고 어디에도 쓰지 않는다.
import { readFile, writeFile, rename, mkdir, access, readdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const { kstDate, validateNormalizedReading } = createRequire(import.meta.url)('../static_src/t04-core.js');
export { kstDate };

export const SIGNAL_ID = 'daejeon-metro-business-day-total-passengers';
export const BASE_URL = 'https://apis.data.go.kr/B554695/TicketTypeTrafficSVC/getTicketTypeTraffic01';
export const DEFAULT_DAILY_FILE = 'static-web/data/t04/daily.json';
// 원본만 커밋한다. static-web 쪽 공개 사본은 scripts/sync_static_data.mjs 가 배포·로컬 실행 때 만든다.
export const DEFAULT_RAW_DIR = 'data/raw/subway';
// daily.json 의 raw_xml 에 적는 경로(static-web 기준 상대 경로).
const RAW_REF_PREFIX = 'data/t04/raw';
export const ERROR_KINDS = Object.freeze(['timeout', 'auth', 'rate_limit', 'offline', 'schema_error']);
const NUM_OF_ROWS = 100; // scripts/utils/collect_data.py 와 같다
const REQUEST_TIMEOUT_MS = 30000;
const PAGE_GAP_MS = 300;
const DATE_GAP_MS = 500;
const HOUR_KEYS = [...Array.from({ length: 19 }, (_, i) => String(i + 5)), '24']; // 5..23 + 익일 00시("24")

// ---------- 날짜 ----------
export function addDays(date, days) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
const compact = (date) => date.replaceAll('-', '');
export const businessDayFor = (recordDate) => addDays(recordDate, -2);

// ---------- 비밀키 보호 ----------
// 로그·예외·저장 파일에 키가 남지 않게 한다. URL 은 통째로 가리고 키 값(원문·인코딩)은 어디서든 지운다.
export function redact(text, key) {
  let out = String(text ?? '');
  const secrets = new Set();
  if (key) {
    secrets.add(key);
    secrets.add(encodeURIComponent(key));
    try { secrets.add(decodeURIComponent(key)); } catch { /* 이미 원문 */ }
  }
  for (const secret of [...secrets].filter((s) => s.length > 0).sort((a, b) => b.length - a.length)) {
    out = out.split(secret).join('<redacted>');
  }
  return out
    .replace(/service_?key=[^&\s"'<>]*/gi, 'serviceKey=<redacted>')
    .replace(/https?:\/\/[^\s"'<>]+/gi, '<url>');
}

// ---------- 오류 분류 ----------
export class RecordError extends Error {
  constructor(kind, detail = '') {
    super(detail ? `${kind}: ${detail}` : kind);
    this.name = 'RecordError';
    this.kind = kind;
  }
}

export function classifyHttpStatus(status) {
  if (status === 401 || status === 403) return 'auth';
  if (status === 429) return 'rate_limit';
  if (status === 408 || status === 504) return 'timeout';
  if (status >= 500) return 'offline';
  return 'schema_error';
}

// data.go.kr 은 오류도 HTTP 200 으로 주므로 resultCode(또는 게이트웨이의 returnReasonCode)로 가른다.
const RESULT_CODE_KIND = {
  '01': 'offline', '02': 'offline', '04': 'offline', '12': 'offline', '99': 'offline',
  '05': 'timeout',
  '10': 'schema_error', '11': 'schema_error',
  '20': 'auth', '21': 'auth', '30': 'auth', '31': 'auth', '32': 'auth', '33': 'auth',
  '22': 'rate_limit'
};
export function classifyResultCode(code) {
  return RESULT_CODE_KIND[String(code).padStart(2, '0')] ?? 'schema_error';
}

const TIMEOUT_CODES = new Set(['ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT']);
const NETWORK_CODES = new Set(['ENOTFOUND', 'ECONNREFUSED', 'ECONNRESET', 'EAI_AGAIN', 'ENETUNREACH', 'EHOSTUNREACH', 'EPIPE', 'UND_ERR_SOCKET']);

// 던져진 예외 하나를 다섯 분류 중 하나로 바꾼다.
export function classifyError(error) {
  if (error instanceof RecordError) return error.kind;
  const codes = [error?.code, error?.cause?.code];
  if (error?.name === 'TimeoutError' || error?.name === 'AbortError' || codes.some((c) => TIMEOUT_CODES.has(c))) return 'timeout';
  if (codes.some((c) => NETWORK_CODES.has(c)) || (error instanceof TypeError && /fetch failed|network/i.test(error.message))) return 'offline';
  return 'schema_error';
}

// ---------- XML 처리(정규식: 형식이 고정된 data.go.kr 응답) ----------
const tag = (text, name) => text.match(new RegExp(`<${name}>([^<]*)</${name}>`))?.[1];

// 응답 한 쪽을 검사해 {items:[원문 item 문자열], totalCount} 를 돌려준다. 오류 응답은 RecordError.
export function parsePage(xml) {
  if (typeof xml !== 'string' || !xml.includes('<')) throw new RecordError('schema_error', 'response is not XML');
  const code = tag(xml, 'resultCode') ?? tag(xml, 'returnReasonCode');
  if (code === undefined) throw new RecordError('schema_error', 'resultCode missing');
  const normalized = code.padStart(2, '0');
  if (normalized === '03') return { items: [], totalCount: 0 }; // NODATA: 미집계 후보
  if (normalized !== '00') throw new RecordError(classifyResultCode(normalized), `resultCode=${normalized}`);
  const items = [...xml.matchAll(/<item>[\s\S]*?<\/item>/g)].map((m) => m[0]);
  return { items, totalCount: Number(tag(xml, 'totalCount') ?? 0) };
}

export function parseItem(item) {
  const businessDay = tag(item, 'businessDay');
  const stationNo = tag(item, 'stationNo');
  const entryFlag = tag(item, 'entryFlag');
  if (!/^\d{8}$/.test(businessDay ?? '') || !stationNo || !['0', '1'].includes(entryFlag)) {
    throw new RecordError('schema_error', 'item fields are invalid');
  }
  const hours = [];
  for (let h = 0; h < 24; h += 1) {
    const text = tag(item, `cnt${String(h).padStart(2, '0')}`);
    const value = Number(text);
    if (text === undefined || text === '' || !Number.isInteger(value) || value < 0) {
      throw new RecordError('schema_error', `cnt${h} is invalid`);
    }
    hours.push(value);
  }
  return { businessDay, stationNo, entryFlag, hours };
}

export function parseDayXml(xml, date) {
  const items = [...String(xml).matchAll(/<item>[\s\S]*?<\/item>/g)].map((m) => parseItem(m[0]));
  for (const item of items) {
    if (item.businessDay !== compact(date)) throw new RecordError('schema_error', `businessDay mismatch for ${date}`);
  }
  return items;
}

// 자료가 비었거나 전부 0 이면 아직 집계되지 않은 날이다.
export const isUnpublished = (items) => items.length === 0 || items.every((i) => i.hours.every((v) => v === 0));

// 운행일 D 의 합계. xmlD: D일 XML, xmlNext: D+1일 XML. 미집계면 null.
export function sumBusinessDay(xmlD, xmlNext, day) {
  const itemsD = parseDayXml(xmlD, day);
  const itemsNext = parseDayXml(xmlNext, addDays(day, 1));
  if (isUnpublished(itemsD) || isUnpublished(itemsNext)) return null;
  const hourly = Object.fromEntries(HOUR_KEYS.map((k) => [k, 0]));
  const stations = {};
  const add = (item, hour, key) => {
    const value = item.hours[hour];
    hourly[key] += value;
    const st = (stations[item.stationNo] ??= { boardings: 0, alightings: 0 });
    st[item.entryFlag === '0' ? 'boardings' : 'alightings'] += value;
  };
  for (const item of itemsD) for (let h = 5; h <= 23; h += 1) add(item, h, String(h));
  for (const item of itemsNext) add(item, 0, '24');
  const total = Object.values(hourly).reduce((a, b) => a + b, 0);
  const sortedStations = Object.fromEntries(Object.entries(stations).sort(([a], [b]) => a.localeCompare(b)));
  return { total, hourly, stations: sortedStations };
}

// ---------- 수집(XML 저장) ----------
const exists = (file) => access(file).then(() => true, () => false);
const sleepDefault = (ms) => new Promise((done) => setTimeout(done, ms));

function requestKey(key) {
  if (!key) throw new RecordError('auth', 'SUBWAY_API_KEY is not set');
  return key.includes('%') ? decodeURIComponent(key) : key; // 인코딩 키가 들어와도 이중 인코딩하지 않는다
}

async function fetchPage(date, pageNo, key, fetchImpl) {
  const params = new URLSearchParams({
    serviceKey: key, startDate: compact(date), endDate: compact(date), pageNo: String(pageNo), numOfRows: String(NUM_OF_ROWS)
  });
  const res = await fetchImpl(`${BASE_URL}?${params}`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (!res.ok) throw new RecordError(classifyHttpStatus(res.status), `http_${res.status}`);
  return parsePage(await res.text());
}

// 하루치 전체 페이지를 모아 item 원문 배열로 돌려준다(collect_data.py 와 같은 페이지 처리).
async function fetchDay(date, key, fetchImpl, sleep) {
  const all = [];
  for (let pageNo = 1; ; pageNo += 1) {
    const page = await fetchPage(date, pageNo, key, fetchImpl);
    all.push(...page.items);
    if (page.items.length === 0 || pageNo * NUM_OF_ROWS >= page.totalCount) break;
    await sleep(PAGE_GAP_MS);
  }
  return all;
}

const xmlDocument = (items) => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode>' +
  `<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items>${items.join('')}</items></body></response>`;

async function writeAtomic(file, text) {
  await mkdir(dirname(file), { recursive: true });
  await writeFile(`${file}.tmp`, text);
  await rename(`${file}.tmp`, file);
}

// D 와 D+1 의 XML 을 rawDir/YYYY-MM-DD.xml 로 저장한다. 이미 있으면 재호출하지 않는다.
// 반환: {status:'collected', day} | {status:'pending', day, reason}. 실패는 RecordError(kind).
export async function collect({
  rawDir = DEFAULT_RAW_DIR, fetchImpl = fetch, now = () => new Date().toISOString(), key = process.env.SUBWAY_API_KEY, sleep = sleepDefault
} = {}) {
  const fetchedAt = now(); // 요청 시각은 한 번만 잡는다
  const day = businessDayFor(kstDate(fetchedAt));
  try {
    const apiKey = requestKey(key);
    let called = false;
    for (const date of [day, addDays(day, 1)]) {
      const file = join(rawDir, `${date}.xml`);
      if (await exists(file)) continue;
      if (called) await sleep(DATE_GAP_MS);
      called = true;
      const items = await fetchDay(date, apiKey, fetchImpl, sleep);
      const parsed = items.map(parseItem);
      for (const item of parsed) {
        if (item.businessDay !== compact(date)) throw new RecordError('schema_error', `businessDay mismatch for ${date}`);
      }
      if (isUnpublished(parsed)) return { status: 'pending', day, reason: `${date} 자료가 아직 집계되지 않음` };
      await writeAtomic(file, xmlDocument(items));
    }
    return { status: 'collected', day };
  } catch (error) {
    const kind = classifyError(error);
    const detail = error instanceof RecordError ? error.message.replace(/^[a-z_]+:?\s*/, '') : error?.message;
    throw new RecordError(kind, redact(detail, key));
  }
}

// ---------- 정제(daily.json 갱신) ----------
function validateRow(row) {
  validateNormalizedReading(row?.reading);
  if (row.reading.signal_id !== SIGNAL_ID) return;
  const sumHours = Object.values(row.hourly ?? {}).reduce((a, b) => a + b, 0);
  const hoursOk = row.hourly && HOUR_KEYS.length === Object.keys(row.hourly).length &&
    HOUR_KEYS.every((k) => Number.isInteger(row.hourly[k]) && row.hourly[k] >= 0);
  if (row.business_day !== businessDayFor(row.reading.record_date) || row.reading.unit !== '명' || !hoursOk ||
      sumHours !== row.reading.normalized_value || !row.stations || !Array.isArray(row.raw_xml) || row.raw_xml.length !== 2) {
    throw new TypeError('business-day row is inconsistent');
  }
}

export function upsert(rows, row) {
  try {
    const { reading } = row;
    validateRow(row);
    const next = rows.filter((existing) => existing?.reading?.signal_id !== reading.signal_id ||
      existing.reading.record_date !== reading.record_date);
    for (const existing of next) validateRow(existing);
    next.push(row);
    return next.sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
  } catch (cause) {
    throw new RecordError('schema_error', cause?.message);
  }
}

// 저장된 XML 두 개로 행을 만든다. 미집계면 null.
export function buildRow({ xmlD, xmlNext, day, fetchedAt }) {
  const sums = sumBusinessDay(xmlD, xmlNext, day);
  if (!sums) return null;
  const next = addDays(day, 1);
  const row = {
    reading: {
      signal_id: SIGNAL_ID,
      normalized_value: sums.total,
      unit: '명',
      source_name: '대전교통공사 1호선 운행일 총 승하차',
      // 응답 businessDay=D 의 합계에 D+1일 00시 구간(~00:59:59 KST)이 포함되므로, 포함된 마지막 관측 시각인 D+1 00:59:59 KST 로 둔다.
      source_url: `${BASE_URL}?startDate=${compact(day)}&endDate=${compact(next)}`, // serviceKey 없음
      source_time: new Date(`${next}T00:59:59+09:00`).toISOString(),
      fetched_at: new Date(fetchedAt).toISOString(),
      record_timezone: 'Asia/Seoul',
      record_date: kstDate(fetchedAt)
    },
    business_day: day,
    hourly: sums.hourly,
    stations: sums.stations,
    raw_xml: [`${RAW_REF_PREFIX}/${day}.xml`, `${RAW_REF_PREFIX}/${next}.xml`]
  };
  validateNormalizedReading(row.reading);
  return row;
}

async function readDoc(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  return { rows: [] };
}

// 저장된 XML 에서 daily.json 을 갱신한다. 반환: {status:'recorded', doc, row} | {status:'pending', reason}
export async function refine(file = DEFAULT_DAILY_FILE, {
  rawDir = DEFAULT_RAW_DIR, now = () => new Date().toISOString()
} = {}) {
  const fetchedAt = now();
  const day = businessDayFor(kstDate(fetchedAt));
  const fileD = join(rawDir, `${day}.xml`);
  const fileNext = join(rawDir, `${addDays(day, 1)}.xml`);
  if (!(await exists(fileD)) || !(await exists(fileNext))) {
    return { status: 'pending', day, reason: `${day} 또는 ${addDays(day, 1)} XML 이 없음(미집계)` };
  }
  const doc = await readDoc(file);
  let row;
  try {
    row = buildRow({ xmlD: await readFile(fileD, 'utf8'), xmlNext: await readFile(fileNext, 'utf8'), day, fetchedAt });
  } catch (error) {
    throw error instanceof RecordError ? error : new RecordError('schema_error', error?.message);
  }
  if (!row) return { status: 'pending', day, reason: `${day} 합계에 필요한 자료가 비어 있음(미집계)` };
  doc.rows = upsert(doc.rows, row);
  await writeAtomic(file, JSON.stringify(doc, null, 2) + '\n');
  return { status: 'recorded', day, doc, row };
}

// 수집+정제를 한 번에. 미집계면 daily.json 을 만들거나 바꾸지 않는다.
export async function record(file = DEFAULT_DAILY_FILE, options = {}) {
  const collected = await collect(options);
  if (collected.status === 'pending') return collected;
  return refine(file, { rawDir: options.rawDir, now: options.now });
}

// ---------- 날씨(Open-Meteo, 키 불필요) ----------
// scripts/utils/backfill_weather.py 와 같은 형식·검증(24개 숫자).
// 원본 data/raw/weather/D.json: {"date","hourly":{time,precipitation,snowfall,temperature_2m}} indent=2, CRLF, 끝 줄바꿈 없음, 실수는 0.0 처럼 소수점 유지.
// 정적 사본(sync_static_data.mjs 가 생성, 커밋 안 함) static-web/data/weather/D.json: {"hourly":{time,temperature_2m,precipitation,snowfall}} 공백 없는 JSON.
export const DEFAULT_WEATHER_DIR = 'data/raw/weather'; // 원본(존재 판정·history 입력)
const WEATHER_VARS = ['temperature_2m', 'precipitation', 'snowfall'];
// 날씨는 '지난 날의 기록'(archive)만 인정한다. 값이 비면 저장하지 않고 다음 실행에서 다시 시도한다(forecast 대체 없음).
const WEATHER_URL = 'https://archive-api.open-meteo.com/v1/archive';
export const WEATHER_BACKFILL_DAYS = 14;
const WEATHER_GAP_MS = 2500;

export function validateWeather(payload, day) {
  const hourly = payload?.hourly;
  const times = hourly?.time;
  if (!Array.isArray(times) || times.length !== 24 || times.some((t) => !String(t).startsWith(day))) return null;
  const out = { time: [...times] };
  for (const name of WEATHER_VARS) {
    const values = hourly[name];
    if (!Array.isArray(values) || values.length !== 24 || values.some((v) => typeof v !== 'number' || !Number.isFinite(v))) return null;
    out[name] = [...values];
  }
  return { hourly: out };
}

const num = (n) => (Object.is(n, -0) ? '-0.0' : Number.isInteger(n) ? n.toFixed(1) : String(n)); // Python json 과 같은 실수 표기
const arr = (values, fmt, sep, open, close) => `[${open}${values.map(fmt).join(sep)}${close}]`;
const hourlyKeys = (hourly, keys, fmt, kv, sep, indent) => keys.map((k) => `${indent}${JSON.stringify(k)}${kv}${fmt(k, hourly[k])}`).join(sep);

export function weatherRawText(day, hourly) {
  const fmt = (k, v) => arr(v, k === 'time' ? (t) => JSON.stringify(t) : num, ',\r\n      ', '\r\n      ', '\r\n    ');
  const body = hourlyKeys(hourly, ['time', 'precipitation', 'snowfall', 'temperature_2m'], fmt, ': ', ',\r\n', '    ');
  return `{\r\n  "date": ${JSON.stringify(day)},\r\n  "hourly": {\r\n${body}\r\n  }\r\n}`;
}

export function weatherStaticText(hourly) {
  const fmt = (k, v) => arr(v, k === 'time' ? (t) => JSON.stringify(t) : num, ',', '', '');
  return `{"hourly":{${hourlyKeys(hourly, ['time', 'temperature_2m', 'precipitation', 'snowfall'], fmt, ':', ',', '')}}}`;
}

// 운행일 D 의 날씨를 원본 weatherDir/D.json 에 저장한다(정적 사본은 scripts/sync_static_data.mjs 가 만든다).
// 존재 판정은 원본 폴더 기준이다. 실패는 던지지 않고 {status:'failed'}(미수집).
export async function fetchWeather(day, {
  weatherDir = DEFAULT_WEATHER_DIR, fetchImpl = fetch, force = false
} = {}) {
  const file = join(weatherDir, `${day}.json`);
  if (!force && await exists(file)) return { status: 'exists', day };
  try {
    const params = new URLSearchParams({
      latitude: '36.35', longitude: '127.38', start_date: day, end_date: day,
      hourly: WEATHER_VARS.join(','), timezone: 'Asia/Seoul'
    });
    const res = await fetchImpl(`${WEATHER_URL}?${params}`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
    if (res.ok) {
      const doc = validateWeather(await res.json(), day);
      if (doc) {
        await writeAtomic(file, weatherRawText(day, doc.hourly));
        return { status: 'saved', day, source: 'archive' };
      }
    }
  } catch { /* 미수집 */ }
  return { status: 'failed', day };
}

// 운행일 D 와 최근 14일 중 날씨 파일이 없는 날짜를 시도한다. 반환: 날짜별 결과 배열.
export async function fetchWeatherRecent(day, { weatherDir = DEFAULT_WEATHER_DIR, fetchImpl = fetch, sleep = sleepDefault, days = WEATHER_BACKFILL_DAYS } = {}) {
  const results = [];
  for (let i = 0; i < days; i += 1) {
    const target = addDays(day, -i);
    if (await exists(join(weatherDir, `${target}.json`))) continue;
    if (results.length > 0) await sleep(WEATHER_GAP_MS);
    results.push(await fetchWeather(target, { weatherDir, fetchImpl }));
  }
  return results;
}

// ---------- 이력(business_days.json) ----------
export const DEFAULT_HISTORY_FILE = 'static-web/data/t04/business_days.json';
export const DEFAULT_RAW_DIRS = [DEFAULT_RAW_DIR];
const round1 = (x) => Math.round((x + 1e-9) * 10) / 10;

// 운행일 D 의 05~23시 시간별 날씨 요약. 자료가 없거나 값이 올바르지 않으면 null.
export function summarizeWeather(doc) {
  const hourly = doc?.hourly;
  if (!hourly || !Array.isArray(hourly.time)) return null;
  let precip = 0; let rain = 0; let snow = 0; let n = 0;
  for (let i = 0; i < hourly.time.length; i += 1) {
    const hour = Number(String(hourly.time[i]).slice(11, 13));
    if (!(hour >= 5 && hour <= 23)) continue;
    const p = hourly.precipitation?.[i]; const s = hourly.snowfall?.[i];
    if (typeof p !== 'number' || typeof s !== 'number' || !Number.isFinite(p) || !Number.isFinite(s)) return null;
    precip += p; snow += s; n += 1;
    if (s === 0) rain += p;
  }
  if (n !== 19) return null;
  const weather = { precip_mm: round1(precip), rain_mm: round1(rain), snow_cm: round1(snow) };
  const kind = weather.snow_cm > 0 && weather.rain_mm > 0 ? 'rain_snow' : weather.snow_cm > 0 ? 'snow' : weather.rain_mm > 0 ? 'rain' : 'none';
  return { ...weather, kind };
}

// rawDirs 의 YYYY-MM-DD.xml 을 모두 읽는다. 같은 날짜가 두 곳에 있으면 내용(파싱한 item)이 같아야 한다.
async function loadRawXml(rawDirs) {
  const byDate = new Map();
  for (const dir of rawDirs) {
    let names;
    try { names = await readdir(dir); } catch (e) { if (e.code === 'ENOENT') continue; throw e; }
    for (const name of names.filter((n) => /^\d{4}-\d{2}-\d{2}\.xml$/.test(n))) {
      const date = name.slice(0, 10);
      const xml = await readFile(join(dir, name), 'utf8');
      const prior = byDate.get(date);
      if (prior) {
        const same = JSON.stringify(parseDayXml(prior.xml, date)) === JSON.stringify(parseDayXml(xml, date));
        if (!same) throw new RecordError('schema_error', `${date}.xml differs between ${prior.dir} and ${dir}`);
      } else {
        byDate.set(date, { xml, dir });
      }
    }
  }
  return byDate;
}

// 완성된 운행일(D, D+1 XML 이 모두 있고 합계가 계산되는 날)만 오름차순으로 모은다.
export async function buildHistory({
  rawDirs = DEFAULT_RAW_DIRS, weatherDir = DEFAULT_WEATHER_DIR, now = () => new Date().toISOString()
} = {}) {
  const raw = await loadRawXml(rawDirs);
  const days = [];
  for (const date of [...raw.keys()].sort()) {
    const next = raw.get(addDays(date, 1));
    if (!next) continue;
    let sums;
    try { sums = sumBusinessDay(raw.get(date).xml, next.xml, date); } catch (error) {
      throw error instanceof RecordError ? new RecordError(error.kind, `${date}: ${error.message}`) : error;
    }
    if (!sums) continue;
    let weather = null;
    try { weather = summarizeWeather(JSON.parse(await readFile(join(weatherDir, `${date}.json`), 'utf8'))); } catch { weather = null; }
    days.push({ business_day: date, total: sums.total, weather });
  }
  return { generated_at: new Date(now()).toISOString(), days };
}

export async function history(file = DEFAULT_HISTORY_FILE, options = {}) {
  const doc = await buildHistory(options);
  await writeAtomic(file, JSON.stringify(doc));
  return { status: 'history', doc };
}

// ---------- CLI ----------
// node scripts/t04_daily_record.mjs [collect|refine|weather|history|all] [daily.json 경로]
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const MODES = ['collect', 'refine', 'weather', 'history', 'all'];
  const mode = MODES.includes(process.argv[2]) ? process.argv[2] : 'all';
  const file = (MODES.includes(process.argv[2]) ? process.argv[3] : process.argv[2]) ?? DEFAULT_DAILY_FILE;
  // 날씨 실패는 전체 실패가 아니다(경고만, weather 는 null 로 계속).
  const runWeather = async () => {
    const day = businessDayFor(kstDate(new Date().toISOString()));
    const results = await fetchWeatherRecent(day);
    const failed = results.filter((r) => r.status === 'failed').map((r) => r.day);
    console.log(`WEATHER saved=${results.filter((r) => r.status === 'saved').length}${failed.length ? ` 날씨 미수집=${failed.join(',')} (weather=null 로 계속)` : ''}`);
    return { status: 'weather' };
  };
  const runHistory = async () => {
    const r = await history();
    const days = r.doc.days;
    console.log(`HISTORY days=${days.length} first=${days[0]?.business_day} last=${days.at(-1)?.business_day}`);
    return r;
  };
  const runAll = async () => {
    const result = await record(file);
    await runWeather();
    await runHistory();
    return result;
  };
  const run = mode === 'collect' ? collect() : mode === 'refine' ? refine(file) : mode === 'weather' ? runWeather()
    : mode === 'history' ? runHistory() : runAll();
  run.then((result) => {
    if (result.status === 'pending') {
      console.log(`PENDING(미집계) day=${result.day}: ${result.reason}`);
    } else if (result.status === 'recorded') {
      const { reading, business_day } = result.row;
      console.log(`RECORDED rows=${result.doc.rows.length} record_date=${reading.record_date} business_day=${business_day} total=${reading.normalized_value}${reading.unit}`);
    } else if (result.status === 'collected') {
      console.log(`COLLECTED day=${result.day}`);
    }
  }).catch((e) => {
    const kind = e instanceof RecordError ? e.kind : classifyError(e);
    console.error(`FAILED kind=${kind} (${redact(e?.message, process.env.SUBWAY_API_KEY)})`);
    process.exit(1);
  });
}
