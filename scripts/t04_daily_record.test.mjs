import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, readdir, mkdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  SIGNAL_ID, collect, refine, record, sumBusinessDay, upsert, redact, classifyError,
  classifyHttpStatus, classifyResultCode, RecordError, addDays,
  summarizeWeather, validateWeather, fetchWeather, buildHistory, history, weatherRawText, weatherStaticText
} from './t04_daily_record.mjs';
import { syncStaticData } from './sync_static_data.mjs';

const RAW = new URL('../data/raw/subway/', import.meta.url);
const KEY = 'FAKE-KEY+abc/123==';
// 조회일 2024-11-07 15:10 KST -> 운행일 D = 2024-11-05, D+1 = 2024-11-06
const NOW = () => '2024-11-07T06:10:00.000Z';
const NEXT_DAY_NOW = () => '2024-11-08T06:10:00.000Z'; // D = 2024-11-06, D+1 = 2024-11-07

const localXml = (date) => readFile(new URL(`${date}.xml`, RAW), 'utf8');
const xmlFor = (url) => {
  const day = new URL(url).searchParams.get('startDate');
  return localXml(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`);
};
const okFetch = (log = []) => async (url) => {
  log.push(url);
  return { ok: true, status: 200, text: async () => xmlFor(url) };
};
const emptyXml = '<response><header><resultCode>00</resultCode></header><body><items></items></body></response>';
const errorXml = (code) => `<response><header><resultCode>${code}</resultCode><resultMsg>x</resultMsg></header></response>`;

async function setup() {
  const dir = await mkdtemp(join(tmpdir(), 't04-'));
  return { dir, file: join(dir, 'daily.json'), rawDir: join(dir, 'raw') };
}
const opts = (rawDir, fetchImpl, now = NOW) => ({ rawDir, fetchImpl, now, key: KEY, sleep: async () => {} });

test('손으로 계산한 값: 2024-11-05 05~23시 211236 + 2024-11-06 00시 240 = 211476', async () => {
  const sums = sumBusinessDay(await localXml('2024-11-05'), await localXml('2024-11-06'), '2024-11-05');
  assert.equal(sums.total, 211476);
  assert.equal(sums.hourly['24'], 240);
  assert.equal(Object.keys(sums.hourly).length, 20);
  assert.equal(sums.hourly['0'], undefined); // D일 00시는 제외
});

test('합계가 data/processed 가공 결과(D 05~23시 + D+1 00시)와 여러 날짜에서 일치한다', async () => {
  for (const day of ['2024-11-01', '2024-11-05', '2024-12-25', '2025-03-10']) {
    const next = addDays(day, 1);
    const [d, n] = await Promise.all([day, next].map(async (x) =>
      JSON.parse(await readFile(new URL(`../data/processed/subway/${x}.json`, import.meta.url), 'utf8'))));
    let expected = 0;
    for (const s of Object.values(d.stations)) for (let h = 5; h <= 23; h += 1) expected += s.boardings[h] + s.alightings[h];
    for (const s of Object.values(n.stations)) expected += s.boardings[0] + s.alightings[0];
    const sums = sumBusinessDay(await localXml(day), await localXml(next), day);
    assert.equal(sums.total, expected, day);
    const byStation = Object.values(sums.stations).reduce((a, s) => a + s.boardings + s.alightings, 0);
    assert.equal(byStation, expected);
  }
});

test('같은 KST 날짜는 1행, 다음 날은 새 행, 저장 XML 은 재호출하지 않는다', async () => {
  const { file, rawDir } = await setup();
  const log = [];
  let r = await record(file, opts(rawDir, okFetch(log)));
  assert.equal(r.status, 'recorded');
  const row = r.doc.rows[0];
  assert.equal(row.reading.signal_id, SIGNAL_ID);
  assert.equal(row.reading.normalized_value, 211476);
  assert.equal(row.reading.unit, '명');
  assert.equal(row.reading.record_date, '2024-11-07');
  assert.equal(row.reading.record_timezone, 'Asia/Seoul');
  assert.equal(row.reading.source_time, '2024-11-05T15:59:59.000Z'); // 2024-11-06 00:59:59 KST
  assert.equal(Object.keys(row.reading).length, 9);
  assert.equal(row.business_day, '2024-11-05');
  assert.deepEqual(row.raw_xml, ['data/t04/raw/2024-11-05.xml', 'data/t04/raw/2024-11-06.xml']);
  assert.equal(log.length, 2);
  assert.deepEqual((await readdir(rawDir)).sort(), ['2024-11-05.xml', '2024-11-06.xml']);

  r = await record(file, opts(rawDir, okFetch(log)));
  assert.equal(r.doc.rows.length, 1);
  assert.equal(log.length, 2); // 재호출 없음

  r = await record(file, opts(rawDir, okFetch(log), NEXT_DAY_NOW));
  assert.equal(r.doc.rows.length, 2);
  assert.deepEqual(r.doc.rows.map((x) => x.reading.record_date), ['2024-11-07', '2024-11-08']);
  assert.equal(r.doc.rows[1].business_day, '2024-11-06');
  assert.equal(log.length, 3); // 2024-11-06 은 이미 있고 11-07 만 새로 호출
});

test('source_url 과 저장 파일 어디에도 키가 없다', async () => {
  const { dir, file, rawDir } = await setup();
  await record(file, opts(rawDir, okFetch()));
  const row = JSON.parse(await readFile(file, 'utf8')).rows[0];
  assert.ok(!/service/i.test(row.reading.source_url));
  for (const name of ['daily.json', 'raw/2024-11-05.xml', 'raw/2024-11-06.xml']) {
    const text = await readFile(join(dir, name), 'utf8');
    for (const part of [KEY, encodeURIComponent(KEY), 'FAKE-KEY']) assert.ok(!text.includes(part), name);
  }
});

test('호출 URL 에 페이지·행 수가 있고 여러 페이지는 합쳐진다', async () => {
  const { rawDir } = await setup();
  const items = [...(await localXml('2024-11-05')).matchAll(/<item>[\s\S]*?<\/item>/g)].map((m) => m[0]);
  const next = items.slice(0, 3).map((i) => i.replace(/20241105/, '20241106').replace(/<cnt00>\d+/, '<cnt00>5'));
  const seen = [];
  const fetchImpl = async (url) => {
    const p = new URL(url).searchParams;
    seen.push(`${p.get('startDate')}:${p.get('pageNo')}:${p.get('numOfRows')}`);
    const first = p.get('startDate') === '20241105';
    const list = first ? items.slice((Number(p.get('pageNo')) - 1) * 100, Number(p.get('pageNo')) * 100) : next;
    const total = first ? items.length : next.length;
    return { ok: true, status: 200, text: async () => `<response><header><resultCode>00</resultCode></header><body><items>${list.join('')}</items><totalCount>${total}</totalCount></body></response>` };
  };
  assert.equal((await collect(opts(rawDir, fetchImpl))).status, 'collected');
  const pages = Math.ceil(items.length / 100);
  assert.deepEqual(seen, [...Array.from({ length: pages }, (_, i) => `20241105:${i + 1}:100`), '20241106:1:100']);
  const saved = await readFile(join(rawDir, '2024-11-05.xml'), 'utf8');
  assert.equal([...saved.matchAll(/<item>/g)].length, items.length);
});

test('미집계: D+1 이 비어 있으면 행을 만들지 않고 파일이 그대로이며 오류가 아니다', async () => {
  const { file, rawDir } = await setup();
  const fetchImpl = async (url) => ({
    ok: true, status: 200,
    text: async () => (new URL(url).searchParams.get('startDate') === '20241106' ? emptyXml : await xmlFor(url))
  });
  assert.equal((await record(file, opts(rawDir, fetchImpl))).status, 'pending');
  assert.ok(!existsSync(file));
  assert.ok(!existsSync(join(rawDir, '2024-11-06.xml'))); // 빈 응답은 저장하지 않는다
  await writeFile(file, '{"rows":[]}\n');
  const before = await readFile(file);
  const raw2 = (await setup()).rawDir;
  const noData = async () => ({ ok: true, status: 200, text: async () => errorXml('03') });
  assert.equal((await record(file, opts(raw2, noData))).status, 'pending');
  assert.deepEqual(await readFile(file), before);
  // 모두 0 인 자리표시 응답도 미집계
  const zeros = async (url) => ({ ok: true, status: 200, text: async () => (await xmlFor(url)).replace(/<cnt(\d\d)>\d+/g, '<cnt$1>0') });
  assert.equal((await collect(opts((await setup()).rawDir, zeros))).status, 'pending');
});

test('refine 은 XML 이 없으면 pending 이고 파일을 만들지 않는다', async () => {
  const { file, rawDir } = await setup();
  assert.equal((await refine(file, { rawDir, now: NOW })).status, 'pending');
  assert.ok(!existsSync(file));
});

test('실패 시 daily.json 과 raw 가 변하지 않고 분류가 맞다', async () => {
  const { file, rawDir } = await setup();
  await record(file, opts(rawDir, okFetch()));
  const before = await readFile(file);
  const cases = [
    ['timeout', async () => { throw Object.assign(new Error('The operation was aborted'), { name: 'TimeoutError' }); }],
    ['offline', async () => { throw new TypeError('fetch failed', { cause: { code: 'ENOTFOUND' } }); }],
    ['auth', async () => ({ ok: false, status: 401 })],
    ['rate_limit', async () => ({ ok: false, status: 429 })],
    ['auth', async () => ({ ok: true, status: 200, text: async () => errorXml('30') })],
    ['rate_limit', async () => ({ ok: true, status: 200, text: async () => errorXml('22') })],
    ['schema_error', async () => ({ ok: true, status: 200, text: async () => 'not xml' })],
    ['schema_error', async () => ({
      ok: true, status: 200,
      text: async () => '<response><header><resultCode>00</resultCode></header><body><items><item><businessDay>x</businessDay></item></items></body></response>'
    })]
  ];
  for (const [kind, fetchImpl] of cases) {
    const dir = join(await mkdtemp(join(tmpdir(), 't04-raw-')), 'raw');
    await assert.rejects(record(file, opts(dir, fetchImpl)), (e) => e instanceof RecordError && e.kind === kind, kind);
    assert.ok(!existsSync(dir) || (await readdir(dir)).length === 0);
  }
  assert.deepEqual(await readFile(file), before);
  const noKey = { ...opts(join((await setup()).dir, 'raw'), okFetch()), key: '' };
  await assert.rejects(record(file, noKey), (e) => e.kind === 'auth');
});

test('fetch 예외 메시지에 URL·키가 섞여도 제거된다', async () => {
  const { file, rawDir } = await setup();
  const leaky = async (url) => { throw new Error(`request to ${url} failed, key=${KEY} enc=${encodeURIComponent(KEY)}`); };
  await assert.rejects(record(file, opts(rawDir, leaky)), (e) => {
    const shown = `${e.message}\n${e.stack.split('\n')[0]}`;
    for (const part of [KEY, encodeURIComponent(KEY), 'FAKE-KEY', 'apis.data.go.kr']) assert.ok(!shown.includes(part), part);
    return true;
  });
  assert.equal(redact(`GET https://x.test/a?serviceKey=${encodeURIComponent(KEY)}&b=1 ${KEY}`, KEY).includes('FAKE'), false);
  assert.equal(redact('serviceKey=ZZZ', undefined), 'serviceKey=<redacted>');
});

test('분류 함수 표', () => {
  assert.deepEqual([401, 403, 429, 408, 504, 500, 502, 404].map(classifyHttpStatus),
    ['auth', 'auth', 'rate_limit', 'timeout', 'timeout', 'offline', 'offline', 'schema_error']);
  assert.deepEqual(['05', '20', '21', '22', '30', '31', '32', '33', '01', '99', '10', '11', '77'].map(classifyResultCode),
    ['timeout', 'auth', 'auth', 'rate_limit', 'auth', 'auth', 'auth', 'auth', 'offline', 'offline', 'schema_error', 'schema_error', 'schema_error']);
  assert.equal(classifyError({ name: 'AbortError' }), 'timeout');
  assert.equal(classifyError({ cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } }), 'timeout');
  assert.equal(classifyError({ cause: { code: 'ECONNREFUSED' } }), 'offline');
  assert.equal(classifyError(new Error('boom')), 'schema_error');
});

test('깨진 기존 JSON 은 바이트를 보존한다', async () => {
  const { file, rawDir } = await setup();
  const before = Buffer.from('{"rows": [');
  await writeFile(file, before);
  await assert.rejects(record(file, opts(rawDir, okFetch())), SyntaxError);
  assert.deepEqual(await readFile(file), before);
});

test('다른 신호 행은 보존하고 잘못된 행은 schema_error', async () => {
  const { file, rawDir } = await setup();
  const r = await record(file, opts(rawDir, okFetch()));
  const row = r.doc.rows[0];
  const other = { reading: { ...row.reading, signal_id: 'other-signal' } };
  assert.equal(upsert([other], row).length, 2);
  assert.throws(() => upsert([], { ...row, hourly: { ...row.hourly, 5: 0 } }), { message: /schema_error/ });
  assert.throws(() => upsert([], { ...row, business_day: '2024-11-06' }), { message: /schema_error/ });
});

test('argv[1]이 없는 모듈 가져오기에서는 기록을 실행하지 않는다', () => {
  const url = new URL('./t04_daily_record.mjs', import.meta.url);
  execFileSync(process.execPath, ['--input-type=module', '-e', `
    if (process.argv[1] !== undefined) throw new Error('Unexpected argv[1]');
    globalThis.fetch = () => { throw new Error('Unexpected fetch'); };
    await import(${JSON.stringify(url.href)});
  `]);
});

// ---------- history / 날씨 ----------
const hourlyDoc = (day, precip = {}, snow = {}) => ({
  hourly: {
    time: Array.from({ length: 24 }, (_, h) => `${day}T${String(h).padStart(2, '0')}:00`),
    temperature_2m: Array(24).fill(5),
    precipitation: Array.from({ length: 24 }, (_, h) => precip[h] ?? 0),
    snowfall: Array.from({ length: 24 }, (_, h) => snow[h] ?? 0)
  }
});

test('날씨 kind 판정과 05~23시 범위·눈 시각 강수 처리', () => {
  const d = '2024-11-05';
  assert.deepEqual(summarizeWeather(hourlyDoc(d)), { precip_mm: 0, rain_mm: 0, snow_cm: 0, kind: 'none' });
  assert.deepEqual(summarizeWeather(hourlyDoc(d, { 8: 1.1, 9: 2.1 })), { precip_mm: 3.2, rain_mm: 3.2, snow_cm: 0, kind: 'rain' });
  assert.deepEqual(summarizeWeather(hourlyDoc(d, { 8: 0.5 }, { 8: 0.4 })), { precip_mm: 0.5, rain_mm: 0, snow_cm: 0.4, kind: 'snow' });
  assert.equal(summarizeWeather(hourlyDoc(d, { 8: 0.5, 10: 1 }, { 8: 0.4 })).kind, 'rain_snow');
  // 00~04시 강수는 무시, 23시는 포함
  assert.equal(summarizeWeather(hourlyDoc(d, { 3: 9 })).kind, 'none');
  assert.equal(summarizeWeather(hourlyDoc(d, { 23: 1 })).kind, 'rain');
  assert.equal(summarizeWeather(null), null);
  const bad = hourlyDoc(d); bad.hourly.precipitation[10] = null;
  assert.equal(summarizeWeather(bad), null);
});

test('날씨 저장은 24개 숫자가 아니면 거부하고 archive 가 비면 미수집(forecast 대체 없음)', async () => {
  const day = '2024-11-05';
  assert.ok(validateWeather(hourlyDoc(day), day));
  const nulls = hourlyDoc(day); nulls.hourly.snowfall[3] = null;
  assert.equal(validateWeather(nulls, day), null);
  const short = hourlyDoc(day); short.hourly.time.pop();
  assert.equal(validateWeather(short, day), null);
  const dir = await mkdtemp(join(tmpdir(), 't04-w-'));
  const urls = [];
  const emptyFetch = async (url) => { urls.push(url); return { ok: true, json: async () => nulls }; };
  assert.equal((await fetchWeather(day, { weatherDir: dir, fetchImpl: emptyFetch })).status, 'failed');
  assert.deepEqual(await readdir(dir), []);
  assert.ok(urls.every((u) => u.startsWith('https://archive-api.open-meteo.com/')));
  const good = async () => ({ ok: true, json: async () => hourlyDoc(day) });
  assert.equal((await fetchWeather(day, { weatherDir: dir, fetchImpl: good })).status, 'saved');
  assert.equal((await fetchWeather(day, { weatherDir: dir, fetchImpl: emptyFetch })).status, 'exists');
  assert.deepEqual(JSON.parse(await readFile(join(dir, `${day}.json`), 'utf8')), { date: day, ...hourlyDoc(day) });
});

test('날씨 원본 형식은 기존 파일과 바이트까지 같고, fetchWeather 는 원본 폴더에만 쓰며 존재 판정도 원본 기준이다', async () => {
  // 기존 원본(CRLF, indent 2, 0.0 표기, 끝 줄바꿈 없음)을 그대로 재현한다. -0.0 이 든 2024-11-18 포함.
  for (const day of ['2024-11-18', '2026-11-02']) {
    const rawFile = await readFile(new URL(`../data/raw/weather/${day}.json`, import.meta.url), 'utf8');
    assert.equal(weatherRawText(day, JSON.parse(rawFile).hourly), rawFile, `raw ${day}`);
  }
  const day = '2026-11-03';
  const base = await mkdtemp(join(tmpdir(), 't04-ws-'));
  const weatherDir = join(base, 'raw');
  let calls = 0;
  const good = async () => { calls += 1; return { ok: true, json: async () => hourlyDoc(day) }; };
  assert.equal((await fetchWeather(day, { weatherDir, fetchImpl: good })).status, 'saved');
  const raw = await readFile(join(weatherDir, `${day}.json`), 'utf8');
  assert.ok(raw.includes('\r\n') && !raw.endsWith('\n') && raw.includes('0.0'));
  assert.deepEqual(Object.keys(JSON.parse(raw)), ['date', 'hourly']);
  assert.deepEqual(Object.keys(JSON.parse(raw).hourly), ['time', 'precipitation', 'snowfall', 'temperature_2m']);
  assert.deepEqual(await readdir(base), ['raw']); // 정적 사본은 만들지 않는다
  assert.equal((await fetchWeather(day, { weatherDir, fetchImpl: good })).status, 'exists');
  assert.equal(calls, 1);
});

test('history: 완성된 운행일만, 날씨 없으면 null, 누락일 건너뜀, 두 폴더 일치/불일치', async () => {
  const base = await mkdtemp(join(tmpdir(), 't04-h-'));
  const [a, b] = [join(base, 'a'), join(base, 'b')];
  const wdir = join(base, 'w');
  await mkdir(a); await mkdir(b); await mkdir(wdir);
  // 2024-11-05, 06, 07 이 있고 08 은 없다 -> 05, 06 만 완성. 10-11 은 D+1 없는 외톨이.
  for (const d of ['2024-11-05', '2024-11-06', '2024-11-07', '2024-11-10']) await writeFile(join(a, `${d}.xml`), await localXml(d));
  await writeFile(join(b, '2024-11-05.xml'), await localXml('2024-11-05')); // 같은 내용 중복
  await writeFile(join(wdir, '2024-11-05.json'), JSON.stringify(hourlyDoc('2024-11-05', { 9: 2 })));
  const doc = await buildHistory({ rawDirs: [a, b], weatherDir: wdir, now: () => '2024-11-23T06:10:00.000Z' });
  assert.equal(doc.generated_at, '2024-11-23T06:10:00.000Z');
  assert.deepEqual(doc.days.map((x) => x.business_day), ['2024-11-05', '2024-11-06']);
  assert.equal(doc.days[0].total, 211476);
  assert.equal(doc.days[0].weather.kind, 'rain');
  assert.equal(doc.days[1].weather, null);
  const out = join(base, 'business_days.json');
  await history(out, { rawDirs: [a, b], weatherDir: wdir });
  assert.ok(!(await readFile(out, 'utf8')).includes('\n'));
  // 내용이 다른 중복은 오류
  await writeFile(join(b, '2024-11-06.xml'), await localXml('2024-11-07'));
  await assert.rejects(buildHistory({ rawDirs: [a, b], weatherDir: wdir }), (e) => e instanceof RecordError);
});

test('collect 는 원본 폴더에만 저장하고 재호출하지 않는다', async () => {
  const { dir, rawDir } = await setup();
  const log = [];
  await collect(opts(rawDir, okFetch(log)));
  assert.deepEqual((await readdir(rawDir)).sort(), ['2024-11-05.xml', '2024-11-06.xml']);
  assert.deepEqual(await readdir(dir), ['raw']);
  const calls = log.length;
  await collect(opts(rawDir, okFetch(log)));
  assert.equal(log.length, calls);
});

test('sync_static_data: 날씨 사본 형식, 참조된 XML 만 복사, 원본 누락 오류, 멱등', async () => {
  const base = await mkdtemp(join(tmpdir(), 't04-sync-'));
  const p = (...x) => join(base, ...x);
  await mkdir(p('w'), { recursive: true }); await mkdir(p('x'), { recursive: true });
  const rawW = await readFile(new URL('../data/raw/weather/2024-11-18.json', import.meta.url), 'utf8');
  await writeFile(p('w', '2024-11-18.json'), rawW);
  for (const d of ['2024-11-05', '2024-11-06', '2024-11-07']) await writeFile(p('x', `${d}.xml`), await localXml(d));
  await mkdir(p('out', 'raw'), { recursive: true });
  await writeFile(p('out', 'raw', '1999-01-01.xml'), 'stale'); // 참조되지 않는 옛 사본은 지운다
  await writeFile(p('daily.json'), JSON.stringify({ rows: [{ raw_xml: ['data/t04/raw/2024-11-05.xml', 'data/t04/raw/2024-11-06.xml'] }] }));
  const o = { root: base, weatherSrc: p('w'), weatherDst: p('out', 'weather'), dailyFile: p('daily.json'), xmlSrc: p('x'), xmlDst: p('out', 'raw') };
  const r1 = await syncStaticData(o);
  assert.deepEqual(r1.errors, []);
  assert.equal(await readFile(p('out', 'weather', '2024-11-18.json'), 'utf8'), weatherStaticText(JSON.parse(rawW).hourly));
  const copy = JSON.parse(await readFile(p('out', 'weather', '2024-11-18.json'), 'utf8'));
  assert.deepEqual(Object.keys(copy), ['hourly']);
  assert.deepEqual(Object.keys(copy.hourly), ['time', 'temperature_2m', 'precipitation', 'snowfall']);
  assert.deepEqual((await readdir(p('out', 'raw'))).sort(), ['2024-11-05.xml', '2024-11-06.xml']); // 07 은 미참조, 1999 는 삭제
  assert.equal(r1.xml.removed, 1);
  const r2 = await syncStaticData(o); // 멱등
  assert.deepEqual([r2.weather.written, r2.xml.written, r2.xml.removed, r2.errors.length], [0, 0, 0, 0]);
  await writeFile(p('daily.json'), JSON.stringify({ rows: [{ raw_xml: ['data/t04/raw/2030-01-01.xml'] }] }));
  const r3 = await syncStaticData(o);
  assert.ok(r3.errors.some((e) => e.includes('2030-01-01.xml')));
  // 비어 있는 daily.json: 사본 디렉터리를 만들지 않는다
  await writeFile(p('daily.json'), JSON.stringify({ rows: [] }));
  const empty = { ...o, xmlDst: p('none', 'raw') };
  assert.deepEqual((await syncStaticData(empty)).errors, []);
  assert.ok(!existsSync(p('none')));
});
