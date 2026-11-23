import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { normalize, record } from './t04_daily_record.mjs';

const ok = (t, v) => async () => ({ ok: true, json: async () => ({ current_units: { temperature_2m: '°C' }, current: { time: t, temperature_2m: v } }) });
const clock = () => '2026-11-23T05:50:00.000Z';
const validFetch = ok('2026-11-23T14:45', 5.1);
const response = (raw) => async () => ({ ok: true, json: async () => raw });

test('같은 KST 날짜는 1행, 다음 날은 새 행, 실패는 파일 보존', async () => {
  const f = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  await record(f, ok('2026-11-23T14:45', 5.1), () => '2026-11-23T05:50:00.000Z');
  let d = await record(f, ok('2026-11-23T15:00', 6.2), () => '2026-11-23T06:05:00.000Z');
  assert.equal(d.rows.length, 1);
  assert.equal(d.rows[0].reading.normalized_value, 6.2);
  assert.equal(d.rows[0].raw.current.temperature_2m, 6.2); // 원본과 정규화 값 일치
  // 14:59Z = KST 23:59, 15:01Z = KST 다음 날 00:01
  d = await record(f, ok('2026-11-24T00:01', 3), () => '2026-11-23T15:01:00.000Z');
  assert.equal(d.rows.length, 2);
  assert.equal(d.rows[1].reading.record_date, '2026-11-24');
  const before = await readFile(f, 'utf8');
  await assert.rejects(record(f, async () => ({ ok: false, status: 429 })), /http_429/);
  await assert.rejects(record(f, async () => ({ ok: true, json: async () => ({ weird: 1 }) })), /schema_error/);
  assert.equal(await readFile(f, 'utf8'), before);
});

test('normalize의 잘못된 응답은 schema_error를 던지고 파일을 보존한다', async (t) => {
  const file = join(await mkdtemp(join(tmpdir(), 't04-')), 'daily.json');
  await record(file, validFetch, clock);
  const before = await readFile(file);
  const valid = await (await validFetch()).json();
  const invalid = {
    '시간 형식 오류': { ...valid, current: { ...valid.current, time: '14:45' } },
    '시간 값 오류': { ...valid, current: { ...valid.current, time: '2026-11-23T25:45' } },
    '숫자 아닌 값': { ...valid, current: { ...valid.current, temperature_2m: '5.1' } },
    '단위 누락': { ...valid, current_units: {} }
  };
  for (const [name, raw] of Object.entries(invalid)) {
    await t.test(name, async () => {
      assert.throws(() => normalize(raw, clock()), { message: 'schema_error' });
      await assert.rejects(record(file, response(raw), clock), { message: 'schema_error' });
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
  const valid = await (await validFetch()).json();
  const invalid = { ...valid, current_units: { temperature_2m: invalidUnit } };
  const schemaError = { message: 'schema_error' };
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
  await assert.rejects(record(file, ok('2026-11-24T00:01', 3), () => '2026-11-23T15:01:00.000Z'), schemaError);
  assert.deepEqual(await readFile(file), invalidBefore);
});

test('argv[1]이 없는 모듈 가져오기에서는 기록을 실행하지 않는다', () => {
  const url = new URL('./t04_daily_record.mjs', import.meta.url);
  execFileSync(process.execPath, ['--input-type=module', '-e', `
    if (process.argv[1] !== undefined) throw new Error('Unexpected argv[1]');
    globalThis.fetch = () => { throw new Error('Unexpected fetch'); };
    await import(${JSON.stringify(url.href)});
  `]);
});
