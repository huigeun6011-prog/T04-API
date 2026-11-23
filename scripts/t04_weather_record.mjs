import { mkdir, open, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import weather from '../static_src/weather-daily.js';

const defaultFile = fileURLToPath(new URL(`../static-web/${weather.recordPath}`, import.meta.url));

export async function recordToday(file = defaultFile, options = {}) {
  await mkdir(dirname(file), { recursive: true });
  const lockPath = `${file}.lock`;
  const lock = await open(lockPath, 'wx');
  const temp = `${file}.tmp`;
  try {
    let previous = { rows: [] };
    try {
      previous = JSON.parse(await readFile(file, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    const rows = weather.readRows(previous);
    const record = await weather.requestToday({ signal: AbortSignal.timeout(20000), ...options });
    const updated = weather.upsert(rows, record);
    await writeFile(temp, `${JSON.stringify({ rows: updated }, null, 2)}\n`);
    await rename(temp, file);
    return { record, count: updated.length };
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

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { record, count } = await recordToday();
    console.log(`RECORDED date=${record.reading.record_date} fetched_at=${record.reading.fetched_at} mean=${record.summary.mean}°C rows=${count}`);
  } catch (error) {
    console.error(`FAILED ${error.kind || error.code || 'schema_error'}: ${error.message}`);
    process.exitCode = 1;
  }
}
