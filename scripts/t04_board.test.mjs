import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { record, sumBusinessDay, SIGNAL_ID } from './t04_daily_record.mjs';

const core = createRequire(import.meta.url)('../static_src/t04-core.js');
const RAW = new URL('../data/raw/subway/', import.meta.url);
const localXml = (date) => readFile(new URL(`${date}.xml`, RAW), 'utf8');

// ---- 행 만들기(테스트 안에서만 쓰는 가짜 행) ----
function fakeRow(day, value, recordDate = core.addDaysStr(day, 2)) {
  const hourly = Object.fromEntries(core.BUSINESS_HOUR_KEYS.map((k) => [k, 0]));
  hourly['5'] = value;
  return {
    reading: {
      signal_id: core.BUSINESS_SIGNAL_ID, normalized_value: value, unit: '명', source_name: '테스트',
      source_url: 'https://example.test/x', source_time: `${core.addDaysStr(day, 1)}T00:59:59+09:00`,
      fetched_at: `${recordDate}T06:10:00.000Z`, record_timezone: 'Asia/Seoul', record_date: recordDate
    },
    business_day: day, hourly, stations: { 101: { boardings: value, alightings: 0 } },
    raw_xml: [`data/t04/raw/${day}.xml`, `data/t04/raw/${core.addDaysStr(day, 1)}.xml`]
  };
}

test('미집계 판정: 15시(KST) 이후엔 T-2부터 숫자, T-1·T 는 미집계', () => {
  const now = '2026-11-23T06:10:00.000Z'; // 2026-11-23(월) 15:10 KST
  assert.equal(core.latestCompleteDay(now), '2026-11-21');
  const rows = [fakeRow('2026-11-21', 1000), fakeRow('2026-11-20', 900)];
  const days = core.recentDays(rows, now, 5);
  assert.deepEqual(days.map((d) => [d.date, d.weekday, d.state]), [
    ['2026-11-23', '월', 'pending'], ['2026-11-22', '일', 'pending'],
    ['2026-11-21', '토', 'recorded'], ['2026-11-20', '금', 'recorded'], ['2026-11-19', '목', 'not_recorded']
  ]);
  assert.equal(days[2].value, 1000);
  assert.equal(days[0].value, undefined);
});

test('미집계 판정: 15시 전에는 T-3부터, 기록된 행이 있어도 오늘·어제는 숫자를 내지 않는다', () => {
  const now = '2026-11-23T05:59:00.000Z'; // 14:59 KST
  assert.equal(core.latestCompleteDay(now), '2026-11-20');
  const days = core.recentDays([fakeRow('2026-11-21', 5)], now, 4);
  assert.deepEqual(days.map((d) => d.state), ['pending', 'pending', 'pending', 'not_recorded']);
  assert.ok(days.every((d) => d.value === undefined));
  // KST 날짜 경계: 2026-11-22 15:30 UTC 는 KST 로 11-23 00:30
  assert.equal(core.recentDays([], '2026-11-22T15:30:00.000Z', 1)[0].date, '2026-11-23');
});

test('전일 대비: 계산식·두 입력값·일수 차이·빈 상태', () => {
  assert.deepEqual(core.dayOverDay([]), { state: 'no_previous' });
  assert.deepEqual(core.dayOverDay([fakeRow('2026-11-20', 5)]), { state: 'no_previous' });
  const other = { reading: { ...fakeRow('2026-11-20', 5).reading, signal_id: 'other' } };
  assert.deepEqual(core.dayOverDay([fakeRow('2026-11-20', 5), other]), { state: 'no_previous' });

  const c = core.dayOverDay([fakeRow('2026-11-21', 80000), fakeRow('2026-11-20', 100000)]); // 입력 순서와 무관
  assert.equal(c.state, 'ok');
  assert.equal(c.delta, -20000);
  assert.equal(c.direction, 'decrease');
  assert.equal(c.formula, '80000 − 100000 = -20000');
  assert.deepEqual([c.prev.business_day, c.prev.weekday, c.prev.value, c.last.business_day, c.last.weekday, c.last.value],
    ['2026-11-20', '금', 100000, '2026-11-21', '토', 80000]);
  assert.equal(c.consecutive, true);
  assert.equal(c.days_apart, 1);

  const gap = core.dayOverDay([fakeRow('2026-11-14', 90), fakeRow('2026-11-21', 90)]);
  assert.equal(gap.consecutive, false);
  assert.equal(gap.days_apart, 7);
  assert.equal(gap.direction, 'unchanged');
});

test('같은 운행일의 행이 여럿이면 가장 최근에 조회한 행 하나만 쓴다', () => {
  const rows = [fakeRow('2026-11-20', 1, '2026-11-22'), fakeRow('2026-11-20', 2, '2026-11-24'), fakeRow('2026-11-19', 7)];
  assert.deepEqual(core.businessRows(rows).map((r) => r.reading.normalized_value), [7, 2]);
  assert.equal(core.dayOverDay(rows).delta, -5);
});

test('조회 실패 분류: 화면의 daily.json 불러오기', () => {
  assert.equal(core.classifyLoadError({ status: 401 }), 'auth');
  assert.equal(core.classifyLoadError({ status: 403 }), 'auth');
  assert.equal(core.classifyLoadError({ status: 429 }), 'rate_limit');
  assert.equal(core.classifyLoadError({ status: 504 }), 'timeout');
  assert.equal(core.classifyLoadError({ status: 503 }), 'offline');
  assert.equal(core.classifyLoadError({ status: 200 }), 'schema_error');
  assert.equal(core.classifyLoadError({ name: 'AbortError' }), 'timeout');
  assert.equal(core.classifyLoadError(new TypeError('Failed to fetch')), 'offline');
  assert.equal(core.classifyLoadError(new SyntaxError('bad json')), 'schema_error');
  for (const kind of ['timeout', 'auth', 'rate_limit', 'offline', 'schema_error']) assert.ok(core.ERROR_INFO[kind]);
});

test('브라우저 합계 재계산이 백엔드 계산과 같다(손 계산 211476 포함)', async () => {
  for (const day of ['2024-11-05', '2024-12-25']) {
    const [d, n] = [await localXml(day), await localXml(core.addDaysStr(day, 1))];
    const browser = core.sumBusinessDayXml(d, n, day);
    assert.deepEqual(browser, sumBusinessDay(d, n, day));
  }
  assert.equal(core.sumBusinessDayXml(await localXml('2024-11-05'), await localXml('2024-11-06'), '2024-11-05').total, 211476);
  assert.equal(core.sumBusinessDayXml('<items></items>', await localXml('2024-11-06'), '2024-11-05'), null);
  const wrongDay = await localXml('2024-11-06');
  assert.throws(() => core.sumBusinessDayXml(wrongDay, wrongDay, '2024-11-05'));
});

test('#t04-lab 해시만 재생 패널을 허용한다', () => {
  assert.equal(core.isLabHash('#t04-lab'), true);
  for (const h of ['', '#t04', '#t04-lab2', '#T04-LAB', '#t04-lab/']) assert.equal(core.isLabHash(h), false);
});

test('index.html: 재생 패널은 template 안에만 있고 정적 DOM 에는 없다', async () => {
  const html = await readFile(new URL('../static_src/index.html', import.meta.url), 'utf8');
  const start = html.indexOf('<template id="t04LabTemplate">');
  const end = html.indexOf('</template>', start);
  assert.ok(start > 0 && end > start);
  const outside = html.slice(0, start) + html.slice(end);
  for (const id of ['t04Reset', 't04D1A', 't04AutoOk', 't04FailKind', 't04Synth']) {
    assert.ok(html.slice(start, end).includes(`id="${id}"`), id);
    assert.ok(!outside.includes(`id="${id}"`), `${id} 가 template 밖에 있음`);
  }
  assert.ok(!/href="#t04-lab"/.test(html));
});

const wd = (business_day, total, weather) => ({ business_day, total, weather });
const bdJson = (days) => JSON.stringify({ generated_at: '2026-11-23T06:00:00Z', days: days.map((d, i) => wd(d, 100000 + i * 1000, null)) });
const findAll = (node, pred, out = []) => { if (pred(node)) out.push(node); (node.children || []).forEach((c) => findAll(c, pred, out)); return out; };

// ---- 아주 작은 가짜 DOM 으로 board 스크립트를 실제로 돌려 본다 ----
class FNode {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.parent = null; this._text = ''; this.id = ''; this.className = ''; }
  get textContent() { return this._text + this.children.map((c) => (c.isText ? c.data : c.textContent)).join(''); }
  set textContent(v) { this.children = []; this._text = String(v); }
  appendChild(c) {
    if (c.isFragment) { for (const k of [...c.children]) this.appendChild(k); return c; }
    c.parent = this; this.children.push(c); return c;
  }
  append(...xs) { xs.forEach((x) => this.appendChild(typeof x === 'string' ? Object.assign(new FNode('#text'), { isText: true, data: x }) : x)); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ??= []).push(f); }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n.isRoot === true; }
  replaceWith(x) { const i = this.parent.children.indexOf(this); x.parent = this.parent; this.parent.children[i] = x; }
  before() {}
  focus() {}
  get content() { return this._content; }
  cloneNode() {
    const c = new FNode(this.tagName); c.id = this.id; c.className = this.className; c._text = this._text;
    c.isFragment = this.isFragment; c.isText = this.isText; c.data = this.data;
    for (const k of this.children) c.appendChild(k.cloneNode());
    return c;
  }
  contains(n) { return n === this || this.children.some((c) => c.contains?.(n)); }
  find(id) {
    if (this.id === id) return this;
    for (const k of this.children) { const f = k.find?.(id); if (f) return f; }
    return null;
  }
}

function makeDom() {
  const body = new FNode('body'); body.isRoot = true;
  const add = (tag, id, parent = body) => { const n = new FNode(tag); n.id = id; parent.appendChild(n); return n; };
  const real = add('div', 't04Real'); real.textContent = '불러오는 중…';
  add('div', 't04LabMount');
  const tpl = add('template', 't04LabTemplate');
  const frag = new FNode('#frag'); frag.isFragment = true;
  const section = new FNode('section'); section.className = 't04-synth'; frag.appendChild(section);
  const head = new FNode('h2'); head.textContent = '합성 테스트 재생'; section.appendChild(head);
  for (const id of ['t04Reset', 't04D1A', 't04D1B', 't04D2', 't04Fail', 't04AutoOk', 't04AutoFail', 't04AutoRec']) add('button', id, section);
  add('select', 't04FailKind', section); add('p', 't04Reason', section); add('p', 't04Live', section); add('div', 't04Synth', section);
  tpl._content = frag; // template.content 는 body 트리에 속하지 않는다(inert)
  tpl.children = [];
  return { body };
}

function FixedDate(iso) {
  return class extends Date {
    constructor(...a) { if (a.length) super(...a); else super(iso); }
    static now() { return new Date(iso).getTime(); }
  };
}

async function runBoard({ hash = '', files, now }) {
  const { body } = makeDom();
  const hashListeners = [];
  const location = { hash };
  const ctx = {
    document: {
      readyState: 'complete', getElementById: (id) => body.find(id),
      createElement: (t) => new FNode(t), createElementNS: (ns, t) => new FNode(t), createTextNode: (data) => Object.assign(new FNode('#text'), { isText: true, data }),
      querySelector: () => null, activeElement: null
    },
    location, Node: FNode, Intl, Number, JSON, Date: now ? FixedDate(now) : Date, Math, Object, Array, String, Promise, RegExp, Set, Map, Error, TypeError, SyntaxError,
    AbortController, setTimeout, clearTimeout, console,
    fetch: async (url) => {
      if (ctx.failStatus && url.includes(ctx.failMatch || '')) return { ok: false, status: ctx.failStatus, text: async () => '', json: async () => ({}) };
      const body = files[url];
      if (body === undefined) return { ok: false, status: 404, text: async () => '', json: async () => ({}) };
      return { ok: true, status: 200, text: async () => body, json: async () => JSON.parse(body) };
    }
  };
  ctx.window = ctx;
  ctx.window.addEventListener = (type, fn) => { if (type === 'hashchange') hashListeners.push(fn); };
  ctx.T04Core = core;
  runInNewContext(await readFile(new URL('../static_src/t04-board.js', import.meta.url), 'utf8'), ctx);
  const settle = () => new Promise((r) => setTimeout(r, 30));
  await settle();
  return {
    body, location, settle, setFail: (status, match = '') => { ctx.failStatus = status; ctx.failMatch = match; },
    setHash: async (h) => { location.hash = h; hashListeners.forEach((f) => f()); await settle(); },
    click: (node, cls) => { const hit = (n) => (n.className?.includes(cls) ? n : n.children.map(hit).find(Boolean)); const b = hit(node); b.listeners.click.forEach((f) => f()); return settle(); },
    real: () => body.find('t04Real'), lab: () => body.find('t04Reset'), mount: () => body.find('t04LabMount')
  };
}

test('빈 daily.json 이면 깨지지 않고 기록 없음 안내와 미집계 표시가 나온다', async () => {
  const page = await runBoard({ files: { 'data/t04/daily.json': '{"rows":[]}' } });
  const text = page.real().textContent;
  assert.match(text, /기록 없음: 아직 저장된/);
  assert.match(text, /자료 없음: 운행일별/); // business_days.json 이 404 → 그래프 대신 안내
  assert.ok(!page.body.find('t04BaseDate'));
  assert.match(text, /비교할 이전 기록 없음/);
  assert.doesNotMatch(text, /조회 실패/);
});

test('해시가 없으면 재생 패널이 DOM 에 없고 #t04-lab 일 때만 나타났다 사라진다', async () => {
  const page = await runBoard({ files: { 'data/t04/daily.json': '{"rows":[]}' } });
  assert.equal(page.lab(), null);
  assert.equal(page.mount().textContent, '');
  await page.setHash('#t04-lab');
  assert.ok(page.lab());
  assert.match(page.mount().textContent, /합성 테스트/);
  await page.setHash('#t04');
  assert.equal(page.lab(), null);
  assert.equal(page.mount().children.length, 0);
  // 처음부터 #t04-lab 으로 열어도 나타난다
  const direct = await runBoard({ hash: '#t04-lab', files: { 'data/t04/daily.json': '{"rows":[]}' } });
  assert.ok(direct.lab());
});

test('조회 실패는 유형을 구분해 보이고 마지막 정상값을 유지하며 다시 시도가 된다', async () => {
  const files = { 'data/t04/daily.json': '{"rows":[]}' };
  const page = await runBoard({ files });
  delete files['data/t04/daily.json']; // 404 는 빈 기록으로 취급된다
  const text404 = (await runBoard({ files })).real().textContent;
  assert.match(text404, /기록 없음/);
  const broken = await runBoard({ files: { 'data/t04/daily.json': '{not json' } });
  assert.match(broken.real().textContent, /schema_error/);
  assert.match(broken.real().textContent, /다시 시도/);
  assert.match(broken.real().textContent, /정상 조회한 기록이 아직 없어/);
  assert.ok(page.real());
});

test('조회 실패 유형 구분: 일별 자료만 실패해도 대표값은 유지, 다시 시도·stale·복구, 새로고침 버튼 없음', async () => {
  const dir = await mkdtemp(join(tmpdir(), 't04-board-'));
  const file = join(dir, 'daily.json');
  const fetchImpl = async (url) => {
    const day = new URL(url).searchParams.get('startDate');
    return { ok: true, status: 200, text: async () => localXml(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`) };
  };
  await record(file, { rawDir: join(dir, 'raw'), fetchImpl, now: () => '2024-11-07T06:10:00.000Z', key: 'FAKE', sleep: async () => {} });
  const good = bdJson(['2024-11-05']);
  const files = { 'data/t04/daily.json': await readFile(file, 'utf8'), 'data/t04/business_days.json': '{"days": 3}',
    'data/t04/raw/2024-11-05.xml': await localXml('2024-11-05'), 'data/t04/raw/2024-11-06.xml': await localXml('2024-11-06') };
  const page = await runBoard({ files, now: '2024-11-08T06:00:00.000Z' });
  const t1 = page.real().textContent;
  assert.match(t1, /일별 자료 조회 실패.*schema_error/);
  assert.match(t1, /정상 조회한 일별 자료가 아직 없어/);
  assert.match(t1, /운행일 2024-11-05/);
  assert.doesNotMatch(t1, /다시 불러오기/);
  // 일별 자료는 복구되지만 이번엔 daily.json 이 실패: 마지막 정상값이 stale 로 남는다
  files['data/t04/business_days.json'] = good;
  page.setFail(503, 'daily.json');
  await page.click(page.real(), 't04-btn-primary');
  const failed = page.real().textContent;
  assert.match(failed, /기록 조회 실패/);
  assert.match(failed, /offline/);
  assert.doesNotMatch(failed, /일별 자료 조회 실패/);
  assert.ok(page.body.find('t04BaseDate'));
  page.setFail(null);
  await page.click(page.real(), 't04-btn-primary');
  assert.doesNotMatch(page.real().textContent, /조회 실패/);
  assert.match(page.real().textContent, /운행일 2024-11-05/);
});

test('실제 기록: 대표값·전일 대비·원본 대조가 일치로 나온다(임시 파일 사용)', async () => {
  const dir = await mkdtemp(join(tmpdir(), 't04-board-'));
  const file = join(dir, 'daily.json');
  const rawDir = join(dir, 'raw');
  const fetchImpl = async (url) => {
    const day = new URL(url).searchParams.get('startDate');
    return { ok: true, status: 200, text: async () => localXml(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`) };
  };
  const run = (iso) => record(file, { rawDir, fetchImpl, now: () => iso, key: 'FAKE', sleep: async () => {} });
  await run('2024-11-07T06:10:00.000Z'); // 운행일 11-05
  await run('2024-11-09T06:10:00.000Z'); // 운행일 11-07 (연속 아님: 이전 행과 2일 차이)
  const files = { 'data/t04/daily.json': await readFile(file, 'utf8') };
  for (const day of ['2024-11-05', '2024-11-06', '2024-11-07', '2024-11-08']) files[`data/t04/raw/${day}.xml`] = await localXml(day);
  const page = await runBoard({ files });
  const text = page.real().textContent;
  assert.match(text, /운행일 2024-11-07 \(목\) 총 승하차 합계/);
  assert.match(text, /2024-11-05 \(화\)/);
  assert.match(text, /연속된 운행일이 아닙니다: 2일 차이/);
  assert.match(text, /합계 대조: 세 값 일치/);
  assert.match(text, /시간별·역별 저장값과 원본 재계산 대조: 일치/);
  assert.match(text, /자료 없음: 운행일별/); // 일별 그래프 자료가 없으면 안내(미집계 표시는 그래프 테스트에서 검사)
  assert.ok(JSON.parse(files['data/t04/daily.json']).rows.every((r) => r.reading.signal_id === SIGNAL_ID));
});

test('합성 재생은 기존 fixture 로 별도 상태만 바꾸고 실제 기록 영역은 건드리지 않는다', async () => {
  const dir = new URL('../static-web/data/t04/', import.meta.url);
  const files = { 'data/t04/daily.json': '{"rows":[]}' };
  const manifest = await readFile(new URL('fixture-manifest.json', dir), 'utf8');
  files['data/t04/fixture-manifest.json'] = manifest;
  for (const f of JSON.parse(manifest).fixtures) files[`data/t04/fixtures/${f.file}`] = await readFile(new URL(`fixtures/${f.file}`, dir), 'utf8');
  const page = await runBoard({ hash: '#t04-lab', files });
  const before = page.real().textContent;
  const d1a = page.body.find('t04D1A');
  d1a.listeners.click.forEach((f) => f());
  await page.settle();
  const synth = page.body.find('t04Synth').textContent;
  assert.match(synth, /T04-NORMAL-D1-A 재생/);
  assert.match(page.body.find('t04Live').textContent, /fresh/);
  assert.equal(page.real().textContent, before);
  assert.doesNotMatch(page.real().textContent, /합성/);
});


// ---- 기준일 선택 + 7일 선 그래프 ----
const NOW = '2026-11-23T06:10:00.000Z'; // 월 15:10 KST → 최근 완성 운행일 2026-11-21
const RAIN = { precip_mm: 3.2, rain_mm: 3.2, snow_cm: 0, kind: 'rain' };
const SNOW = { precip_mm: 1.2, rain_mm: 0, snow_cm: 1.5, kind: 'snow' };
const BOTH = { precip_mm: 4, rain_mm: 2, snow_cm: 1.5, kind: 'rain_snow' };
const NONE = { precip_mm: 0, rain_mm: 0, snow_cm: 0, kind: 'none' };
const bdFile = (days) => JSON.stringify({ generated_at: '2026-11-23T06:00:00Z', days });

test('7일 윈도우: 기준일 포함 오름차순, 월·연 경계를 넘는다', () => {
  assert.deepEqual(core.weekWindow('2026-11-21'), ['2026-11-15', '2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-21']);
  assert.deepEqual(core.weekWindow('2026-01-03'), ['2025-12-28', '2025-12-29', '2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02', '2026-01-03']);
});

test('날씨 문구: 비/눈/비·눈/강수 없음/null', () => {
  assert.equal(core.weatherText(RAIN), '비 3.2mm');
  assert.equal(core.weatherText(SNOW), '눈 1.5cm');
  assert.equal(core.weatherText(BOTH), '비 2.0mm·눈 1.5cm');
  assert.deepEqual(core.weatherLines(BOTH), ['비 2.0mm', '눈 1.5cm']);
  assert.equal(core.weatherText(NONE), '강수 없음');
  assert.equal(core.weatherText(null), '날씨 자료 없음');
  assert.equal(core.weatherText(undefined), '날씨 자료 없음');
  assert.equal(core.weatherText({ kind: 'mystery' }), '날씨 자료 없음');
});

test('trendSeries: 미집계·자료 없음·기록을 구분하고 선을 끊는다(보간 없음)', () => {
  const days = [wd('2026-11-17', 100, RAIN), wd('2026-11-18', 200, null), wd('2026-11-20', 400, SNOW), wd('2026-11-21', 500, NONE)];
  const series = core.trendSeries(days, '2026-11-23', NOW);
  assert.deepEqual(series.map((p) => p.date), ['2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23']);
  assert.deepEqual(series.map((p) => p.state), ['recorded', 'recorded', 'no_data', 'recorded', 'recorded', 'pending', 'pending']);
  assert.equal(series[5].label, '미집계');
  assert.equal(series[2].label, '자료 없음');
  const L = core.chartLayout(series);
  assert.deepEqual(L.segments.map((s) => s.map((p) => p.date)), [['2026-11-17', '2026-11-18'], ['2026-11-20', '2026-11-21']]);
  assert.equal(L.paths.length, 2);
  assert.ok(L.paths.every((d) => /^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+$/.test(d)));
  assert.ok(L.points.filter((p) => p.state !== 'recorded').every((p) => p.y === null));
  // 이웃 없는 단독 점은 선이 없다
  const lone = core.chartLayout(core.trendSeries([wd('2026-11-20', 7, null)], '2026-11-21', NOW));
  assert.equal(lone.paths.length, 0);
  assert.equal(lone.segments.length, 1);
});

test('기준일이 첫날 근처면 앞쪽은 자료 없음, 눈금은 0부터 값을 덮는다', () => {
  const days = [wd('2026-11-03', 211476, RAIN), wd('2026-11-04', 150000, null)];
  const series = core.trendSeries(days, '2026-11-04', NOW);
  assert.deepEqual(series.map((p) => p.state), ['no_data', 'no_data', 'no_data', 'no_data', 'no_data', 'recorded', 'recorded']);
  const L = core.chartLayout(series);
  assert.equal(L.yTicks[0].value, 0);
  assert.ok(L.max >= 211476);
  assert.deepEqual(core.niceTicks(211476).ticks, [0, 100000, 200000, 300000]);
  assert.equal(core.niceTicks(0).ticks[0], 0); // 값이 하나도 없어도 눈금이 나온다
  assert.ok(L.points[5].y < L.points[6].y); // 큰 값이 위쪽(작은 y)
  assert.ok(L.points.every((p) => p.x > L.left && p.x < L.width - L.right));
});

test('business_days 검증: 형식이 틀리면 오류, 빈 목록은 통과', () => {
  assert.deepEqual(core.validateBusinessDays({ days: [] }), []);
  assert.throws(() => core.validateBusinessDays({}));
  assert.throws(() => core.validateBusinessDays({ days: [{ business_day: '2026-13-40', total: 1 }] }));
  assert.throws(() => core.validateBusinessDays({ days: [{ business_day: '2026-11-03', total: 'x' }] }));
  assert.throws(() => core.validateBusinessDays({ days: [{ business_day: '2026-11-03', total: 1, weather: 5 }] }));
  assert.equal(core.validateBusinessDays({ days: [wd('2026-11-03', 1, null)] }).length, 1);
  assert.equal(core.parseDateInput('2026-02-30'), null);
  assert.equal(core.parseDateInput(''), null);
  assert.equal(core.parseDateInput('2026-02-28'), '2026-02-28');
});

test('역 이름 매핑: 101~122 → app.js STATIONS 순서(판암~반석), 범위 밖은 이름 없음', async () => {
  const app = await readFile(new URL('../static_src/app.js', import.meta.url), 'utf8');
  const names = [...app.matchAll(/\{\s*name:\s*'([^']+)',\s*idx:\s*(\d+)/g)].map((m) => [m[1], Number(m[2])]);
  assert.equal(names.length, 22);
  for (const [name, idx] of names) assert.equal(core.stationName(101 + idx), name);
  assert.equal(core.stationLabel('101'), '101번 판암');
  assert.equal(core.stationLabel('122'), '122번 반석');
  assert.equal(core.stationName(100), null);
  assert.equal(core.stationName(123), null);
  assert.equal(core.stationLabel('999'), '999번');
});

test('렌더: 그래프 SVG(path/circle/text), 날씨 띠, 표', async () => {
  const days = [wd('2026-11-17', 100000, RAIN), wd('2026-11-18', 120000, BOTH), wd('2026-11-19', 130000, null),
    wd('2026-11-20', 140000, SNOW), wd('2026-11-21', 150000, NONE)];
  const files = { 'data/t04/daily.json': '{"rows":[]}', 'data/t04/business_days.json': bdFile(days) };
  const page = await runBoard({ files, now: NOW });
  const input = page.body.find('t04BaseDate');
  assert.equal(input.value, '2026-11-21'); // 기본: 최근 완성 운행일
  assert.equal(input.min, '2026-11-17');
  assert.equal(input.max, undefined);
  const svgRoot = findAll(page.real(), (n) => n.tagName === 'svg')[0];
  assert.equal(svgRoot.attrs.role, 'img');
  assert.match(svgRoot.attrs['aria-label'], /집계 5일/);
  assert.match(svgRoot.attrs.viewBox, /^0 0 640 /);
  assert.equal(findAll(svgRoot, (n) => n.tagName === 'path').length, 1); // 11-17~21 연속 → 선 1개
  assert.equal(findAll(svgRoot, (n) => n.attrs.class === 't04-dot').length, 5);
  const texts = findAll(svgRoot, (n) => n.tagName === 'text' || n.tagName === 'tspan').map((n) => n.textContent);
  for (const want of ['11-15', '11-21', '(토)', '비 3.2mm', '눈 1.5cm', '강수 없음', '날씨 자료 없음', '50,000', '150,000']) {
    assert.ok(texts.some((t) => t.includes(want)), want);
  }
  assert.ok(texts.includes('비 2.0mm') && texts.includes('눈 1.5cm'));
  assert.equal(texts.filter((t) => t === '자료 없음').length, 2); // 11-15·16 은 파일에 없음
  assert.equal(findAll(svgRoot, (n) => n.tagName === 'g' && n.attrs.tabindex === '0').length, 5);
  // 점에 포커스하면 상세가 나온다
  const g = findAll(svgRoot, (n) => n.tagName === 'g')[1];
  g.listeners.focus.forEach((f) => f());
  assert.match(findAll(page.real(), (n) => n.className === 't04-detail')[0].textContent, /2026-11-18 \(수\) 승하차 120,000명 · 날씨 비 2\.0mm·눈 1\.5cm/);
  // 표(접근성 대체물)에 같은 값
  const tableText = findAll(page.real(), (n) => n.className?.includes('t04-days'))[0].textContent;
  assert.match(tableText, /2026-11-21토150,000 명강수 없음/);
  assert.match(tableText, /비 2\.0mm·눈 1\.5cm/);
});

test('기준일 버튼(▶)과 입력으로 그래프가 바뀐다: 미집계는 선이 끊기고 점이 없다', async () => {
  const days = [wd('2026-11-19', 130000, null), wd('2026-11-20', 140000, SNOW), wd('2026-11-21', 150000, NONE)];
  const files = { 'data/t04/daily.json': '{"rows":[]}', 'data/t04/business_days.json': bdFile(days) };
  const page = await runBoard({ files, now: NOW });
  const next = findAll(page.real(), (n) => n.tagName === 'button' && /다음 날/.test(n.textContent))[0];
  next.listeners.click.forEach((f) => f());
  const input = page.body.find('t04BaseDate');
  assert.equal(input.value, '2026-11-22');
  let svgRoot = findAll(page.real(), (n) => n.tagName === 'svg')[0];
  assert.equal(findAll(svgRoot, (n) => n.attrs.class === 't04-dot').length, 3);
  assert.equal(findAll(svgRoot, (n) => n.attrs.class === 't04-gap-text' && n.textContent === '미집계').length, 1);
  // 입력으로 첫날로 이동: 앞쪽 자료 없음, 이전 버튼 비활성
  input.value = '2026-11-19';
  input.listeners.change.forEach((f) => f());
  svgRoot = findAll(page.real(), (n) => n.tagName === 'svg')[0];
  assert.equal(findAll(svgRoot, (n) => n.attrs.class === 't04-dot').length, 1);
  assert.equal(findAll(svgRoot, (n) => n.tagName === 'path').length, 0);
  assert.equal(findAll(page.real(), (n) => n.tagName === 'button' && /이전 날/.test(n.textContent))[0].disabled, true);
  // 잘못된 입력은 무시되어 그래프가 그대로다
  input.value = '';
  input.listeners.change.forEach((f) => f());
  assert.equal(findAll(page.real(), (n) => n.tagName === 'svg').length, 1);
});

test('business_days 가 비어 있으면 안내만 보이고 깨지지 않는다', async () => {
  const page = await runBoard({ files: { 'data/t04/daily.json': '{"rows":[]}', 'data/t04/business_days.json': '{"days":[]}' }, now: NOW });
  assert.match(page.real().textContent, /자료 없음: 운행일별/);
  assert.equal(findAll(page.real(), (n) => n.tagName === 'svg').length, 0);
});

test('역별 표에 역 번호와 이름이 함께 나온다', async () => {
  const dir = await mkdtemp(join(tmpdir(), 't04-board-'));
  const file = join(dir, 'daily.json');
  const fetchImpl = async (url) => {
    const day = new URL(url).searchParams.get('startDate');
    return { ok: true, status: 200, text: async () => localXml(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`) };
  };
  await record(file, { rawDir: join(dir, 'raw'), fetchImpl, now: () => '2024-11-07T06:10:00.000Z', key: 'FAKE', sleep: async () => {} });
  const page = await runBoard({ files: { 'data/t04/daily.json': await readFile(file, 'utf8') }, now: '2024-11-08T06:00:00.000Z' });
  assert.match(page.real().textContent, /101번 판암/);
  assert.match(page.real().textContent, /122번 반석/);
});
