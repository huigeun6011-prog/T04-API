import test from 'node:test';
import assert from 'node:assert/strict';
import { deflateSync } from 'node:zlib';
import { decodePNG, expectedTip } from './check_map_proxy.mjs';

function chunk(type, body) {
  const length = Buffer.alloc(4); length.writeUInt32BE(body.length);
  // Decoder does not use CRC; the fixtures exercise unfiltering and palette extraction.
  return Buffer.concat([length, Buffer.from(type), body, Buffer.alloc(4)]);
}
function png(colorType, depth, raw, palette) {
  const header = Buffer.alloc(13); header.writeUInt32BE(2, 0); header.writeUInt32BE(1, 4); header[8] = depth; header[9] = colorType;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), ...(palette ? [chunk('PLTE', palette)] : []), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

test('RGB Sub-filter pixels decode correctly', () => {
  const image = decodePNG(png(2, 8, Buffer.from([1, 200, 40, 10, 66, 20, 10])));
  assert.equal(image.width, 2); assert.equal(image.height, 1);
  assert.deepEqual([...image.rgba], [200, 40, 10, 255, 10, 60, 20, 255]);
});
test('one-bit indexed palette pixels decode correctly', () => {
  const image = decodePNG(png(3, 1, Buffer.from([0, 0b01000000]), Buffer.from([1, 2, 3, 254, 253, 252])));
  assert.deepEqual([...image.rgba], [1, 2, 3, 255, 254, 253, 252, 255]);
});
test('invalid image bodies are rejected', () => {
  assert.throws(() => decodePNG(Buffer.from('not a png')), /invalid_png/);
});
test('logical zoom resolution and physical scale expected tips agree', () => {
  assert.deepEqual(expectedTip(100, 0, 2, 1), { x: 520, y: 240 });
  assert.deepEqual(expectedTip(100, 0, 3, 1), { x: 420, y: 240 });
  assert.deepEqual(expectedTip(0, 100, 4, 1), { x: 320, y: 190 });
  assert.deepEqual(expectedTip(0, 100, 3, 2), { x: 640, y: 280 });
});
