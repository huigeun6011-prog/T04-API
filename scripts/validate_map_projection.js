// Run: node scripts/validate_map_projection.js
// Independent reference values were measured from the official Kakao live demo:
// https://apis.map.kakao.com/web/sample/basicMap/ (LatLng.toCoords()).
'use strict';
const assert = require('node:assert/strict');
global.window = global;
require('../static_src/map-projection.js');
const fixtures = [
  { lat: 38, lng: 127, x: 500000, y: 1250000 },
  { lat: 33.450701, lng: 126.570667, x: 400206.345643045, y: -11702.439372717636 },
  { lat: 37.5, lng: 127, x: 500000, y: 1111260.3087119653 },
];
let maximum = 0;
for (const fixture of fixtures) {
  const point = MapViewProjection.forward(fixture.lat, fixture.lng);
  // The adapter works in WTM metres; the Kakao demo returns WCONGNAMUL (x2.5).
  const error = Math.hypot(point.x * 2.5 - fixture.x, point.y * 2.5 - fixture.y);
  maximum = Math.max(maximum, error);
  assert.ok(error < 0.002, `Official coordinate fixture mismatch: ${error}`);
}
for (const lat of [33, 35, 36.3515, 38, 39]) {
  for (const lng of [124, 126, 127.3867, 129, 130]) {
    const point = MapViewProjection.forward(lat, lng);
    const coords = MapViewProjection.inverse(point.x, point.y);
    assert.ok(Math.abs(coords.lat - lat) < 1e-7, 'Latitude round trip mismatch');
    assert.ok(Math.abs(coords.lng - lng) < 1e-7, 'Longitude round trip mismatch');
  }
}
console.log(`Projection passed 3 official fixtures and 25 Korea-area round trips; maximum WCONGNAMUL error ${maximum.toFixed(7)}.`);
