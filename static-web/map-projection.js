/* Korea 2000 / Central Belt (EPSG:5181), GRS80 transverse Mercator.
 * Kakao's WTM is this CRS; WCONGNAMUL values are WTM metres multiplied by 2.5.
 * Kakao confirmation: https://devtalk.kakao.com/t/topic/38086/2
 * and https://devtalk.kakao.com/t/wtm/59226
 * Working in metres avoids an unnecessary WCONGNAMUL conversion.
 */
(function () {
  'use strict';
  const a = 6378137, flattening = 1 / 298.257222101;
  const e2 = flattening * (2 - flattening), ep2 = e2 / (1 - e2);
  const rad = Math.PI / 180, lon0 = 127 * rad;
  const e4 = e2 * e2, e6 = e4 * e2;
  const meridian = phi => a * (
    (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
    - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
    + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
    - 35 * e6 / 3072 * Math.sin(6 * phi)
  );
  const m0 = meridian(38 * rad);
  function forward(lat, lng) {
    const phi = lat * rad, lambda = lng * rad;
    const sin = Math.sin(phi), cos = Math.cos(phi), tan = Math.tan(phi);
    const n = a / Math.sqrt(1 - e2 * sin * sin);
    const t = tan * tan, c = ep2 * cos * cos, aa = cos * (lambda - lon0);
    return {
      x: 200000 + n * (aa + (1 - t + c) * aa ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * aa ** 5 / 120),
      y: 500000 + meridian(phi) - m0 + n * tan * (aa * aa / 2 + (5 - t + 9 * c + 4 * c * c) * aa ** 4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * aa ** 6 / 720),
    };
  }
  function inverse(x, y) {
    const m = m0 + y - 500000;
    const mu = m / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
    const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    const phi1 = mu
      + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
      + (21 * e1 * e1 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
      + 151 * e1 ** 3 / 96 * Math.sin(6 * mu)
      + 1097 * e1 ** 4 / 512 * Math.sin(8 * mu);
    const sin = Math.sin(phi1), cos = Math.cos(phi1), tan = Math.tan(phi1);
    const n = a / Math.sqrt(1 - e2 * sin * sin);
    const r = a * (1 - e2) / (1 - e2 * sin * sin) ** 1.5;
    const t = tan * tan, c = ep2 * cos * cos, d = (x - 200000) / n;
    const lat = phi1 - n * tan / r * (d * d / 2 - (5 + 3 * t + 10 * c - 4 * c * c - 9 * ep2) * d ** 4 / 24 + (61 + 90 * t + 298 * c + 45 * t * t - 252 * ep2 - 3 * c * c) * d ** 6 / 720);
    const lng = lon0 + (d - (1 + 2 * t + c) * d ** 3 / 6 + (5 - 2 * c + 28 * t - 3 * c * c + 8 * ep2 + 24 * t * t) * d ** 5 / 120) / cos;
    return { lat: lat / rad, lng: lng / rad };
  }
  window.MapViewProjection = Object.freeze({ forward, inverse });
})();
