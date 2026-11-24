import { mkdir, open, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import weather from '../static_src/weather-daily.js';
import Core from '../static_src/t04-core.js';

const defaultFile = fileURLToPath(new URL(`../static-web/${weather.recordPath}`, import.meta.url));

async function withWeatherFileLock(file, update) {
  await mkdir(dirname(file), { recursive: true });
  const lockPath = `${file}.lock`;
  const lock = await open(lockPath, 'wx');
  const temp = `${file}.tmp`;
  try {
    return await update(async (doc) => {
      await writeFile(temp, `${JSON.stringify(doc, null, 2)}\n`);
      await rename(temp, file);
    });
  } finally {
    try {
      await unlink(temp).catch((error) => {
        if (error.code !== 'ENOENT') throw error;
      });
    } finally {
      await lock.close();
      await unlink(lockPath);
    }
  }
}

export async function recordToday(file = defaultFile, options = {}) {
  const { skipExisting = false, now = () => new Date(), ...requestOptions } = options;
  return withWeatherFileLock(file, async (save) => {
    let previous = { rows: [] };
    try {
      previous = JSON.parse(await readFile(file, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    weather.readRows(previous);
    const rows = previous.rows;
    let requestedAt;
    if (skipExisting) {
      requestedAt = now();
      const date = Core.kstDate(requestedAt);
      if (rows.some((row) => row.reading.record_date === date)) {
        return { skipped: true, date, count: rows.length };
      }
    }
    const record = await weather.requestObserved({
      signal: AbortSignal.timeout(20000), ...requestOptions,
      now: () => {
        const time = requestedAt ?? now();
        requestedAt = undefined;
        return time;
      }
    });
    const updated = weather.upsert(rows, record);
    await save({ ...previous, rows: updated });
    return { record, count: updated.length };
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const force = process.argv.slice(2).includes('--force') || process.env.FORCE === '1';
    const { record, count, skipped, date } = await recordToday(defaultFile, { skipExisting: !force });
    if (skipped) console.log(`SKIPPED date=${date} (이미 기록됨)`);
    else console.log(`RECORDED date=${record.reading.record_date} data_date=${weather.dataDateOf(record)} fetched_at=${record.reading.fetched_at} mean=${record.summary.mean}°C rows=${count}`);
  } catch (error) {
    if (error.kind === 'pending') {
      console.log(`PENDING date=${error.date} data_date=${error.dataDate} (${error.message})`);
    } else {
      console.error(`FAILED ${error.kind || error.code || 'schema_error'}: ${error.message}`);
      process.exitCode = 1;
    }
  }
}
