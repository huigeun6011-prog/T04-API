import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { normalize, record, SIGNAL_ID } from './t04_daily_record.mjs';

const clock = () => '2026-11-23T05:50:00.000Z';
const afterMidnight = () => '2026-11-23T15:01:00.000Z';
const response = (raw) => async () => ({ ok: true, json: async () => raw });
const schemaError = { message: 'schema_error' };

function forecast(date, temperature = 5) {
  return {
    hourly_units: { time: 'iso8601', temperature_2m: '°C', precipitation: 'mm', snowfall: 'cm' },
    hourly: {
      time: Array.from({ length: 24 }, (_, hour) => `${date}T${String(hour).padStart(2, '0')}:00`),
      temperature_2m: Array.from({ length: 24 }, (_, hour) => temperature + hour / 10),
      precipitation: Array(24).fill(0),
      snowfall: Array(24).fill(0.1)
    }
  };
}

const validFetch = response(forecast('2026-11-24'));

test('평균 반올림 경계의 저장 바이트가 공통 함수 도입 전과 같다', async () => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  const raw = forecast('2026-11-24');
  raw.hourly.temperature_2m.fill(2.15);
  const saved = await record(file, response(raw), clock);
  assert.equal(saved.rows[0].reading.normalized_value, 2.2);
  const hash = createHash('sha256').update(await readFile(file)).digest('hex');
  // Captured from the recorder before extracting its rounding rule.
  assert.equal(hash, 'da19721abe293ea287c122855d4c8405b213bf755c266bfbac3a52b8d0b4d550');
});

test('normalize은 원본에서 대상일 24칸만 골라 시간순으로 저장하고 평균을 계산한다', () => {
  const raw = forecast('2026-11-24');
  const wanted = structuredClone(raw.hourly);
  for (const values of Object.values(raw.hourly)) values.reverse();
  const extra = forecast('2026-11-25').hourly;
  for (const key of Object.keys(raw.hourly)) raw.hourly[key].push(...extra[key]);
  const before = structuredClone(raw);
  const row = normalize(raw, clock());
  assert.equal(row.target_date, '2026-11-24');
  assert.equal(row.reading.signal_id, SIGNAL_ID);
  assert.equal(row.reading.normalized_value, 6.2);
  assert.equal(row.reading.unit, '°C');
  assert.equal(row.reading.source_time, '2026-11-23T15:00:00.000Z');
  assert.equal(row.reading.fetched_at, clock());
  assert.equal(row.reading.record_date, '2026-11-23');
  assert.equal(row.reading.record_timezone, 'Asia/Seoul');
  assert.equal(Object.keys(row.reading).length, 9);
  assert.deepEqual(row.hourly, wanted);
  assert.deepEqual(row.hourly_units, { temperature_2m: '°C', precipitation: 'mm', snowfall: 'cm' });
  assert.strictEqual(row.raw, raw);
  assert.deepEqual(row.raw, before);
  assert.equal(normalize(forecast('2026-11-24', -7.3), clock()).reading.normalized_value, -6.2);
});

test('같은 KST 날짜는 1행, 다음 날은 새 행, 실패는 파일 보존', async () => {
  const f = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  await record(f, validFetch, clock);
  let samples = 0;
  let d = await record(f, async (url) => {
    assert.equal(url, 'https://api.open-meteo.com/v1/forecast?latitude=36.35&longitude=127.38&hourly=temperature_2m,precipitation,snowfall&timezone=Asia%2FSeoul&start_date=2026-11-24&end_date=2026-11-24');
    return response(forecast('2026-11-24', 6))();
  }, () => {
    samples += 1;
    return samples === 1 ? '2026-11-23T14:59:59.000Z' : afterMidnight();
  });
  assert.equal(samples, 1);
  assert.equal(d.rows.length, 1);
  assert.equal(d.rows[0].reading.normalized_value, 7.2);
  d = await record(f, async (url) => {
    const params = new URL(url).searchParams;
    assert.equal(params.get('start_date'), '2026-11-25');
    assert.equal(params.get('end_date'), '2026-11-25');
    return response(forecast('2026-11-25'))();
  }, afterMidnight);
  assert.equal(d.rows.length, 2);
  assert.equal(d.rows[1].reading.record_date, '2026-11-24');
  assert.equal(d.rows[1].target_date, '2026-11-25');
  assert.equal(d.rows[1].reading.source_url.split('start_date=')[1], '2026-11-25&end_date=2026-11-25');
  const before = await readFile(f, 'utf8');
  await assert.rejects(record(f, async () => ({ ok: false, status: 429 })), /http_429/);
  await assert.rejects(record(f, async () => ({ ok: true, json: async () => ({ weird: 1 }) })), /schema_error/);
  assert.equal(await readFile(f, 'utf8'), before);
});

test('기존 현재 기온 행은 같은 날짜의 새 신호를 갱신해도 그대로 보존한다', async () => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  const old = {
    reading: {
      signal_id: 'daejeon-temperature-2m',
      normalized_value: 5.1,
      unit: '°C',
      source_name: 'Open-Meteo 대전 현재 기온',
      source_url: 'https://api.open-meteo.com/v1/forecast?current=temperature_2m',
      source_time: '2026-11-23T05:45:00.000Z',
      fetched_at: clock(),
      record_timezone: 'Asia/Seoul',
      record_date: '2026-11-23'
    },
    raw: { current: { time: '2026-11-23T14:45', temperature_2m: 5.1 } }
  };
  const asFile = JSON.stringify({ rows: [old] }, null, 2);
  await writeFile(file, asFile + '\n');
  const rowBytes = Buffer.from(asFile.slice(asFile.indexOf('    {'), asFile.lastIndexOf('\n  ]')));
  await record(file, validFetch, clock);
  const updated = await record(file, response(forecast('2026-11-24', 6)), clock);
  assert.deepEqual(updated.rows.map(({ reading }) => reading.signal_id), [old.reading.signal_id, SIGNAL_ID]);
  assert.deepEqual(updated.rows[0], old);
  assert.equal(updated.rows[1].reading.normalized_value, 7.2);
  assert.ok((await readFile(file)).includes(rowBytes));
});

test('normalize의 잘못된 응답은 schema_error를 던지고 파일을 보존한다', async (t) => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  await record(file, validFetch, clock);
  const before = await readFile(file);
  const valid = forecast('2026-11-24');
  const { hourly } = valid;
  const invalid = {
    '시간 형식 오류': { ...valid, hourly: { ...hourly, time: ['00:00', ...hourly.time.slice(1)] } },
    '시간 중복': { ...valid, hourly: { ...hourly, time: [hourly.time[1], ...hourly.time.slice(1)] } },
    '23시간만 포함': {
      ...valid, hourly: Object.fromEntries(Object.entries(hourly).map(([key, values]) => [key, values.slice(0, 23)]))
    },
    'null 적설': { ...valid, hourly: { ...hourly, snowfall: [null, ...hourly.snowfall.slice(1)] } },
    '문자열 기온': { ...valid, hourly: { ...hourly, temperature_2m: ['5.1', ...hourly.temperature_2m.slice(1)] } },
    '기온 단위 누락': { ...valid, hourly_units: { ...valid.hourly_units, temperature_2m: undefined } },
    '강수 단위 누락': { ...valid, hourly_units: { ...valid.hourly_units, precipitation: undefined } }
  };
  for (const [name, raw] of Object.entries(invalid)) {
    await t.test(name, async () => {
      assert.throws(() => normalize(raw, clock()), schemaError);
      await assert.rejects(record(file, response(raw), clock), schemaError);
      assert.deepEqual(await readFile(file), before);
    });
  }
});

test('깨진 기존 JSON은 파싱 실패 뒤에도 원래 바이트를 보존한다', async () => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  const before = Buffer.from('{"rows": [');
  await writeFile(file, before);
  await assert.rejects(record(file, validFetch, clock), SyntaxError);
  assert.deepEqual(await readFile(file), before);
});

test('화면의 정규화 규칙을 어긴 새 응답과 이전 행을 저장하지 않는다', async () => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  const invalidUnit = 'x'.repeat(25);
  const valid = forecast('2026-11-24');
  const invalid = { ...valid, hourly_units: { ...valid.hourly_units, temperature_2m: invalidUnit } };
  await assert.rejects(record(file, response(invalid), clock), schemaError);
  await assert.rejects(readFile(file), { code: 'ENOENT' });

  await record(file, validFetch, clock);
  const before = await readFile(file);
  await assert.rejects(record(file, response(invalid), clock), schemaError);
  assert.deepEqual(await readFile(file), before);

  const existing = JSON.parse(before);
  existing.rows[0].reading.unit = invalidUnit;
  const invalidBefore = Buffer.from(JSON.stringify(existing));
  await writeFile(file, invalidBefore);
  await assert.rejects(record(file, response(forecast('2026-11-25')), afterMidnight), schemaError);
  assert.deepEqual(await readFile(file), invalidBefore);

  const missingHourly = structuredClone(JSON.parse(before));
  delete missingHourly.rows[0].hourly;
  const incompleteBefore = Buffer.from(JSON.stringify(missingHourly));
  await writeFile(file, incompleteBefore);
  await assert.rejects(record(file, response(forecast('2026-11-25')), afterMidnight), schemaError);
  assert.deepEqual(await readFile(file), incompleteBefore);
});

test('argv[1]이 없는 모듈 가져오기에서는 기록을 실행하지 않는다', () => {
  const url = new URL('./t04_daily_record.mjs', import.meta.url);
  execFileSync(process.execPath, ['--input-type=module', '-e', `
    if (process.argv[1] !== undefined) throw new Error('Unexpected argv[1]');
    globalThis.fetch = () => { throw new Error('Unexpected fetch'); };
    await import(${JSON.stringify(url.href)});
  `]);
});
