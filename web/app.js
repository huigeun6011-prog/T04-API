'use strict';

// 대전 1호선 22개 역 사용자 제공 지도 좌표 (판암 0 ~ 반석 21)
const STATIONS = [
  { name: '판암',         idx: 0,  lat: 36.31696, lng: 127.45843 },
  { name: '신흥',         idx: 1,  lat: 36.31966, lng: 127.44880 },
  { name: '대동',         idx: 2,  lat: 36.32959, lng: 127.44284 },
  { name: '대전',         idx: 3,  lat: 36.33152, lng: 127.43367 },
  { name: '중앙로',       idx: 4,  lat: 36.32867, lng: 127.42583 },
  { name: '중구청',       idx: 5,  lat: 36.32480, lng: 127.41955 },
  { name: '서대전네거리', idx: 6,  lat: 36.32242, lng: 127.41258 },
  { name: '오룡',         idx: 7,  lat: 36.32869, lng: 127.40492 },
  { name: '용문',         idx: 8,  lat: 36.33817, lng: 127.39341 },
  { name: '탄방',         idx: 9,  lat: 36.34555, lng: 127.38457 },
  { name: '시청',         idx: 10, lat: 36.35153, lng: 127.38675 },
  { name: '정부청사',     idx: 11, lat: 36.35747, lng: 127.38127 },
  { name: '갈마',         idx: 12, lat: 36.35758, lng: 127.37280 },
  { name: '월평',         idx: 13, lat: 36.35826, lng: 127.36460 },
  { name: '갑천',         idx: 14, lat: 36.35475, lng: 127.35469 },
  { name: '유성온천',     idx: 15, lat: 36.35372, lng: 127.34145 },
  { name: '구암',         idx: 16, lat: 36.35670, lng: 127.33073 },
  { name: '현충원',       idx: 17, lat: 36.35909, lng: 127.32180 },
  { name: '월드컵경기장', idx: 18, lat: 36.36686, lng: 127.31700 },
  { name: '노은',         idx: 19, lat: 36.37415, lng: 127.31788 },
  { name: '지족',         idx: 20, lat: 36.38410, lng: 127.31950 },
  { name: '반석',         idx: 21, lat: 36.39218, lng: 127.31456 },
];

const state = {
  departure: null,
  date: null,
  selectedCategory: 'all',
  map: null,
  departureMarker: null,
  poiMarkers: [],
  poiInfoOverlay: null,
  routePolylines: [],
  metroSegments: null,
  pois: [],
  weatherRequestId: 0,
  startHour: 5,
  endHour: 24,
  quietWeight: 0.5,
  recommendationRequestId: 0,
  recommendationController: null,
  researchTimer: null,
  weather: null,
  nextWeather: null,
  results: [],
  lastMeta: null,
  selectedItem: null,
  activeHour: null,   // null = 장소별 최적 시간, 숫자 = 그 시간 기준 서버 재계산
  chipRange: null,    // 마지막 '장소별 최적 시간' 검색의 시간 범위
  matrix: null,
  tab: 'near',        // 'near'(가까운 곳) | 'far'(지하철로 멀리): 결과는 한 번에 받고 탭 전환은 브라우저에서만 한다(D-020)
  viewHour: null,     // 시간 막대로 보고 있는 시간(선택한 장소의 표시만 바뀜, 서버 재순위 없음). null = 그 장소의 최적(원래) 시간
  listed: [],
  rowCtx: { lo: 0, hi: 1 },
  mapPickMode: false,
  timeStripCollapsed: false,
  timeStripPosition: null,
  timeStripDrag: null,
};

const WALK_KMH = 4.5, WALK_DETOUR = 1.3; // 서버와 같은 도보 시간 어림값(D-014)
const API_BASE = (window.RECOMMENDATION_API_BASE || '').replace(/\/$/, '');

function nextDate(date) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function distKm(lat1, lng1, lat2, lng2) {
  const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLng = (lng2 - lng1) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

const catLabel = c => ({ library: '도서관', park: '공원', bookstore: '서점' })[c] || c || '기타';
// 선 아이콘(stroke 1.7, currentColor). 장식용이라 aria-hidden, 뜻은 옆의 글자가 전달한다.
const svgIcon = d => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${d}</svg>`;
const ICON = {
  park: svgIcon('<path d="M12 21v-6"/><path d="M12 15a5 5 0 1 0-4-8 4 4 0 0 0 1 8z"/><path d="M12 15a5 5 0 1 1 4-8 4 4 0 0 1-1 8z"/>'),
  library: svgIcon('<path d="M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4z"/><path d="M20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z"/>'),
  bookstore: svgIcon('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6"/>'),
  walk: svgIcon('<circle cx="13" cy="4" r="2"/><path d="M9 21l3-7M12 14l-2-4 4-2 3 4M12 14l3 7"/>'),
  train: svgIcon('<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 12h14M9 21l2-4M15 21l-2-4"/>'),
  pin: svgIcon('<path d="M12 21s-6-5.6-6-10a6 6 0 0 1 12 0c0 4.4-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>'),
  search: svgIcon('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
};
const catIcon = c => ICON[c] || ICON.pin;
const setSearchLabel = text => { document.getElementById('searchBtn').innerHTML = `${ICON.search}<span class="go-label">${text}</span>`; };
const hasCoords = p => p.latitude !== null && p.longitude !== null && p.latitude !== '' && p.longitude !== '' && Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude));

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function nearestStation(p) {
  const lat = Number(p.latitude ?? p.lat);
  const lng = Number(p.longitude ?? p.lng);
  return STATIONS.map(s => ({ station: s, km: distKm(lat, lng, s.lat, s.lng) })).sort((a, b) => a.km - b.km)[0];
}

function initTabs() {
  document.querySelectorAll('.tab-nav-btn').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
  }));
}

function tryInitMap(retries = 20) {
  if (typeof kakao !== 'undefined' && kakao.maps) kakao.maps.load(initMap);
  else if (retries > 0) setTimeout(() => tryInitMap(retries - 1), 300);
  else { renderMetroSchematic(); }
}

function initMap() {
  document.getElementById('mapFallback').style.display = 'none';
  state.map = new kakao.maps.Map(document.getElementById('kakaoMap'), { center: new kakao.maps.LatLng(36.3515, 127.3867), level: 6 });
  state.map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);
  state.map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);

  STATIONS.forEach(s => {
    const node = document.createElement('div');
    node.className = 'station-dot';
    node.title = `${s.name}역`;
    node.addEventListener('click', e => {
      e.stopPropagation();
      if (state.mapPickMode) setDeparture(s.lat, s.lng, `${s.name}역`);
    });
    new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(s.lat, s.lng),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 4,
    }).setMap(state.map);
  });

  kakao.maps.event.addListener(state.map, 'click', e => {
    if (state.mapPickMode) setDeparture(e.latLng.getLat(), e.latLng.getLng());
  });

  renderPoiMarkers(visibleResults());
}

function setDeparture(lat, lng, label = null) {
  if (state.mapPickMode) setMapPickMode(false);
  const previousDeparture = state.departure;
  const departureChanged = !!previousDeparture && (previousDeparture.lat !== lat || previousDeparture.lng !== lng);
  state.departure = { lat, lng };

  if (state.map) {
    if (state.departureMarker) state.departureMarker.setMap(null);
    const node = document.createElement('div');
    node.className = 'departure-dot';
    node.title = '선택한 출발지';
    // xAnchor: 0.5, yAnchor: 0.5로 정확히 클릭 커서 위치에 중심 배치
    state.departureMarker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(lat, lng),
      content: node,
      xAnchor: 0.5,
      yAnchor: 0.5,
      zIndex: 10,
    });
    state.departureMarker.setMap(state.map);
  }

  document.getElementById('locationBox').innerHTML = `<div class="loc-addr">${ICON.pin} ${escapeHtml(label || '출발지 지정됨')}</div><div class="loc-coords">위도 ${lat.toFixed(5)} · 경도 ${lng.toFixed(5)}</div>`;
  const slot = document.getElementById('slotOrigin');
  if (slot) slot.textContent = label || '지도에서 고른 위치';
  const near = STATIONS.map(s => ({ ...s, km: distKm(lat, lng, s.lat, s.lng) })).sort((a, b) => a.km - b.km).slice(0, 5);
  document.getElementById('stationDistList').innerHTML = near.map(s => `<div class="stn-row"><span class="stn-row-name">${escapeHtml(s.name)}역</span><span class="stn-row-dist">직선거리 ${(s.km * 1000).toFixed(0)}m</span></div>`).join('');

  if (departureChanged) {
    // 출발지를 바꾸면 이전 기준의 결과·경로·분석은 즉시 버리고, 사용자가 다시 찾기를 누를 때만 재계산한다.
    clearTimeout(state.researchTimer);
    state.researchTimer = null;
    state.recommendationController?.abort();
    state.recommendationController = null;
    state.recommendationRequestId++;
    const searchButton = document.getElementById('searchBtn');
    searchButton.disabled = false;
    searchButton.removeAttribute('aria-busy');
    setSearchLabel('찾기');
    setUpdating(false);
    setStale(false);
    state.results = [];
    state.lastMeta = null;
    state.selectedItem = null;
    state.listed = [];
    state.matrix = null;
    clearRoute();
    renderPoiMarkers([]);
    renderGroupTabs();
    document.getElementById('resultsMeta').textContent = '출발지가 바뀌어 추천이 초기화되었습니다';
    document.getElementById('resultsCards').innerHTML = '<p class="empty-state" role="status">출발지가 바뀌었어요. 다시 찾기를 눌러 주세요.</p>';
    document.getElementById('predictionAnalysis').textContent = '출발지가 바뀌었어요. 다시 찾기를 누르면 분석 결과를 볼 수 있습니다.';
    const viewStatus = document.getElementById('viewStatus');
    if (viewStatus) viewStatus.textContent = '';
    showUpdateNote('출발지가 바뀌었어요. 다시 찾기를 눌러 주세요.');
    renderTimeStrip();
    window.Analysis?.setSelected(null);
    window.Analysis?.refreshHeatmap();
  } else if (!previousDeparture) {
    // 첫 출발지 지정은 기존의 명확한 검색 전 안내를 유지한다.
    renderEmptyState();
  }
}

function renderMetroSchematic() {
  const wrap = document.getElementById('metroSchematic');
  if (!wrap) return;
  wrap.innerHTML = STATIONS.map(s => `<button class="metro-stn" onclick="setDeparture(${s.lat},${s.lng},'${escapeHtml(s.name)}역')">${escapeHtml(s.name)}</button>`).join(' → ');
}

// ─────────────────────────────────────────────
// 🗺 경로 시각화 (지하철 노선 + 보행 점선)
// ─────────────────────────────────────────────
function clearRoute() {
  state.routePolylines.forEach(p => p.setMap(null));
  state.routePolylines = [];
  if (state.poiInfoOverlay) {
    state.poiInfoOverlay.setMap(null);
    state.poiInfoOverlay = null;
  }
}

function getSubwayStationsAlong(bStation, aStation) {
  if (!bStation || !aStation) return [];
  const bIdx = bStation.idx ?? STATIONS.findIndex(s => s.name === bStation.name);
  const aIdx = aStation.idx ?? STATIONS.findIndex(s => s.name === aStation.name);
  if (bIdx === -1 || aIdx === -1 || bIdx === aIdx) return [];

  return bIdx < aIdx
    ? STATIONS.slice(bIdx, aIdx + 1)
    : STATIONS.slice(aIdx, bIdx + 1).reverse();
}

function metroPathFor(stationsAlong) {
  const fallback = () => stationsAlong.map(s => [s.lat, s.lng]);
  if (!state.metroSegments || stationsAlong.length < 2) return fallback();
  const points = [];
  for (let i = 0; i < stationsAlong.length - 1; i++) {
    const key = `${stationsAlong[i].idx}-${stationsAlong[i + 1].idx}`;
    const segment = state.metroSegments[key];
    if (!Array.isArray(segment) || segment.length < 2) return fallback();
    points.push(...(i ? segment.slice(1) : segment));
  }
  return points;
}

async function loadMetroLineGeometry() {
  try {
    const response = await fetch('./data/metro_line_geometry.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.source !== 'OpenStreetMap' || !data.segments || Object.keys(data.segments).length !== 42) {
      throw new Error('선로 좌표 자료가 올바르지 않습니다.');
    }
    state.metroSegments = data.segments;
    if (state.selectedItem && state.map) showPlaceRoute(state.selectedItem, true, false);
  } catch (error) {
    console.warn('실제 선로 좌표를 불러오지 못해 역 좌표를 연결합니다.', error);
  }
}

function showPlaceRoute(item, isRecommendation = false, adjustBounds = true) {
  if (!state.map) return;
  clearRoute();
  const prevPlaceId = state.selectedItem?.poi?.id;
  state.selectedItem = item;
  if (isRecommendation && item.poi?.id !== prevPlaceId) state.viewHour = null;
  if (isRecommendation) { window.Analysis?.setSelected(item); syncViewHour(); }

  const poi = isRecommendation ? (item.poi || {}) : item;
  const poiLat = Number(poi.latitude);
  const poiLng = Number(poi.longitude);
  if (!Number.isFinite(poiLat) || !Number.isFinite(poiLng)) return;

  const poiPos = new kakao.maps.LatLng(poiLat, poiLng);
  const required = [{ pos: poiPos, isPlace: true }];  // side 는 카드 위치 결정 후 채운다

  // 💡 1. 출발지 및 목적지 기준 가장 가까운 역을 항상 현재 위치 기준으로 정확히 결정
  // (이전 검색 결과의 '예전 역'에 묶여 경로가 엉뚱한 곳으로 이어지는 문제 해결)
  const currentDepartureStation = state.departure ? nearestStation(state.departure).station : null;
  const currentPoiStation = nearestStation(poi).station;

  // 추천 항목은 서버가 고른 승차·하차역을 그대로 그린다(화면이 따로 판단하지 않는다). 항목이 아닌 경우에만 현재 출발지의 가까운 역을 쓴다.
  const serverBoard = item.boarding_station ? (STATIONS.find(s => s.name === item.boarding_station.name) || item.boarding_station) : null;
  let bStation = (isRecommendation && serverBoard) ? serverBoard : (currentDepartureStation || serverBoard);
  let aStation = item.alighting_station ? (STATIONS.find(s => s.name === item.alighting_station.name) || item.alighting_station) : currentPoiStation;

  // 걷기만 할지 열차를 탈지는 서버의 결정(열차 없는 후보 = no_train, 승·하차역이 같음)을 따른다. 지도·카드·길찾기 링크가 서로 어긋나지 않게 한다.
  const directDist = state.departure ? distKm(state.departure.lat, state.departure.lng, poiLat, poiLng) : 999;
  const walkToBoardDist = (state.departure && bStation) ? distKm(state.departure.lat, state.departure.lng, bStation.lat, bStation.lng) : 0;
  const walkFromAlightDist = aStation ? distKm(aStation.lat, aStation.lng, poiLat, poiLng) : 0;
  const hasRide = !!(bStation && aStation && bStation.name !== aStation.name) && !(isRecommendation && item.no_train);
  const isDirectWalk = !hasRide;
  // 참고용 안내: 승·하차역까지 걷는 거리의 합보다 출발지~장소 직선이 훨씬 짧으면 걸어가는 편이 나을 수 있다(점수는 바꾸지 않는다).
  const walkMayBeBetter = hasRide && !!state.departure && directDist < (walkToBoardDist + walkFromAlightDist) * 0.85;

  if (state.departure) {
    const depPos = new kakao.maps.LatLng(state.departure.lat, state.departure.lng);
    required.push({ pos: depPos });

    if (isDirectWalk) {
      // 🚶 지하철 불필요: 출발지 → 목적지 직행 도보 점선
      const line = new kakao.maps.Polyline({
        map: state.map,
        path: [depPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    } else {
      // 🚇 지하철 이용 경로:
      // [1] 출발지 → 탑승역 보행 점선
      const bPos = new kakao.maps.LatLng(bStation.lat, bStation.lng);
      required.push({ pos: bPos });
      const walkToBoardLine = new kakao.maps.Polyline({
        map: state.map,
        path: [depPos, bPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToBoardLine);

      // 탑승역 뱃지
      const bBadge = document.createElement('div');
      bBadge.className = 'route-station-badge';
      bBadge.innerHTML = `${ICON.train}<span>승차 ${escapeHtml(bStation.name)}역</span>`;
      const bOverlay = new kakao.maps.CustomOverlay({
        position: bPos,
        content: bBadge,
        yAnchor: 1.6,
        zIndex: 16,
      });
      bOverlay.setMap(state.map);
      state.routePolylines.push(bOverlay);

      // [2] 지하철 노선 경로:
      // 지도 앱 공식 대중교통 노선 스타일 (흰색 외곽선 10px + 대전 1호선 녹색 6px 이중 레이어)
      const stationsAlong = getSubwayStationsAlong(bStation, aStation);
      if (stationsAlong.length > 1) {
        const metroPath = metroPathFor(stationsAlong).map(([lat, lng]) => new kakao.maps.LatLng(lat, lng));

        // 2-1. 흰색 테두리 밑선
        const metroUnderlay = new kakao.maps.Polyline({
          map: state.map,
          path: metroPath,
          strokeWeight: 10,
          strokeColor: '#FFFFFF',
          strokeOpacity: 0.95,
          strokeStyle: 'solid',
          zIndex: 5,
        });
        state.routePolylines.push(metroUnderlay);

        // 2-2. 대전 1호선 녹색 본선
        const metroLine = new kakao.maps.Polyline({
          map: state.map,
          path: metroPath,
          strokeWeight: 6,
          strokeColor: '#0B8F4D', // 노선 초록(디자인 토큰 --line)
          strokeOpacity: 1.0,
          strokeStyle: 'solid',
          zIndex: 6,
        });
        state.routePolylines.push(metroLine);

        // 2-3. 경유하는 각 역마다 동그란 노선도 노드 마커 표시
        stationsAlong.forEach(stn => {
          const dot = document.createElement('div');
          dot.className = 'route-station-node';
          dot.title = `${stn.name}역`;
          const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(stn.lat, stn.lng),
            content: dot,
            xAnchor: 0.5,
            yAnchor: 0.5,
            zIndex: 14,
          });
          overlay.setMap(state.map);
          state.routePolylines.push(overlay);
        });
      }

      // [3] 하차역 뱃지 & 하차역 → 목적지 보행 점선
      const aPos = new kakao.maps.LatLng(aStation.lat, aStation.lng);
      required.push({ pos: aPos });

      const aBadge = document.createElement('div');
      aBadge.className = 'route-station-badge alight';
      aBadge.innerHTML = `${ICON.walk}<span>하차 ${escapeHtml(aStation.name)}역</span>`;
      const aOverlay = new kakao.maps.CustomOverlay({
        position: aPos,
        content: aBadge,
        yAnchor: -0.6,       // 승차 뱃지는 위, 하차 뱃지는 아래: 1정거장처럼 두 역이 가까워도 겹치지 않는다
        zIndex: 16,
      });
      aOverlay.setMap(state.map);
      state.routePolylines.push(aOverlay);

      const walkToPoiLine = new kakao.maps.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToPoiLine);
    }
  } else {
    // 출발지가 아직 없을 때: 목적지 및 인근 역 표시
    if (aStation) {
      const aPos = new kakao.maps.LatLng(aStation.lat, aStation.lng);
      required.push({ pos: aPos });
      const line = new kakao.maps.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    }
  }

  // 목적지 핀: 다른 장소의 작은 점과 구별되는 큰 핀 (경로 위에 표시)
  const pin = document.createElement('div');
  pin.className = 'dest-pin';
  pin.setAttribute('role', 'img');
  pin.setAttribute('aria-label', `목적지 ${poi.name || ''}`);
  pin.innerHTML = '<svg viewBox="0 0 30 40" width="30" height="40" aria-hidden="true"><path d="M15 39C15 39 2 24 2 14a13 13 0 0 1 26 0C28 24 15 39 15 39z" fill="#13201A" stroke="#fff" stroke-width="2.5"/><circle cx="15" cy="14" r="5" fill="#fff"/></svg>';
  const pinOverlay = new kakao.maps.CustomOverlay({ position: poiPos, content: pin, xAnchor: 0.5, yAnchor: 1, zIndex: 30 });
  pinOverlay.setMap(state.map);
  state.routePolylines.push(pinOverlay);

  // 정보 카드는 경로가 들어오는 쪽의 반대편에 둔다 (경로선·역·출발지를 가리지 않도록)
  let side = 'north';
  if (required.length > 1) {
    const prev = required[required.length - 1].pos;
    const dy = poiPos.getLat() - prev.getLat();
    const dx = (poiPos.getLng() - prev.getLng()) * Math.cos(poiPos.getLat() * Math.PI / 180);
    if (Math.abs(dy) >= Math.abs(dx)) side = dy >= 0 ? 'north' : 'south';
    else side = dx >= 0 ? 'east' : 'west';
  }
  const anchors = { north: [0.5, 1], south: [0.5, 0], east: [0, 0.5], west: [1, 0.5] };
  const wrap = document.createElement('div');
  wrap.className = `poi-card-wrap side-${side}`;
  const content = document.createElement('div');
  content.className = 'poi-info-card';
  wrap.appendChild(content);
  content.innerHTML = `
    <div class="poi-info-title">
      <span class="poi-info-name">${catIcon(poi.facility_type)}<span class="poi-info-name-text">${escapeHtml(poi.name)}</span></span>
      <span class="poi-info-category">${catLabel(poi.facility_type)}</span>
    </div>
    <div class="poi-info-route">
      ${isDirectWalk
        ? `${ICON.walk}<span class="poi-info-route-text">도보 직행 (약 ${(directDist * 1000).toFixed(0)}m · 지하철 불필요)</span>`
        : `${ICON.train}<span class="poi-info-route-text">${escapeHtml(bStation.name)}역 탑승 → ${escapeHtml(aStation.name)}역 하차</span>`}
    </div>
    ${walkMayBeBetter ? `<div class="poi-info-advice">걸어서 바로 가는 편이 더 가까울 수 있어요 (직선 약 ${(directDist * 1000).toFixed(0)}m)</div>` : ''}
    <div class="poi-info-link">${kakaoRouteLink(poi, isDirectWalk)}</div>
    ${hasRide ? '<div class="poi-info-attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">선로 좌표 © OpenStreetMap</a></div>' : ''}
  `;
  ['click', 'mousedown', 'touchstart'].forEach(t => content.addEventListener(t, ev => ev.stopPropagation()));
  state.poiInfoOverlay = new kakao.maps.CustomOverlay({
    position: poiPos,
    content: wrap,
    xAnchor: anchors[side][0],
    yAnchor: anchors[side][1],
    zIndex: 20,
  });
  state.poiInfoOverlay.setMap(state.map);

  // 카드나 마커를 직접 클릭했을 때: 필요한 지점이 이미 화면 안이면 지도를 건드리지 않고, 벗어난 경우에만 최소한으로 넓힌다.
  if (adjustBounds) {
    required[0].side = side;
    const wr = wrap.getBoundingClientRect();
    required[0].size = wr.width ? { w: wr.width, h: wr.height } : null;
    ensureVisible(required);
  }
}

// 목적지(핀 + 정보 카드)·출발지·승하차역이 지도 칸 안에 모두 들어오게 한다.
// 이미 들어와 있으면 아무것도 하지 않고, 아니면 (1) 들어갈 때까지만 축소하고 (2) 가장 적게 평행이동한다. 확대는 하지 않는다.
function ensureVisible(points) {
  const map = state.map;
  const el = document.getElementById('kakaoMap');
  if (!map || !el || !points.length) return;
  map.relayout(); // 결과 영역 때문에 지도 칸 크기가 바뀐 경우 카카오 내부 크기를 먼저 맞춘다
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const pad = 14, padR = 54; // 오른쪽은 지도 확대/축소 컨트롤을 피한다
  const measure = () => {
    const proj = map.getProjection();
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    const add = (x0, y0, x1, y1) => { l = Math.min(l, x0); t = Math.min(t, y0); r = Math.max(r, x1); b = Math.max(b, y1); };
    points.forEach(({ pos, isPlace, side, size }) => {
      const c = proj.containerPointFromCoords(pos);
      if (!isPlace) { add(c.x - 8, c.y - 8, c.x + 8, c.y + 8); return; }
      const w = size?.w || 250, h = size?.h || 110;
      add(c.x - 15, c.y - 40, c.x + 15, c.y);                       // 핀
      if (side === 'north') add(c.x - w / 2, c.y - h, c.x + w / 2, c.y);
      else if (side === 'south') add(c.x - w / 2, c.y, c.x + w / 2, c.y + h);
      else if (side === 'east') add(c.x, c.y - h / 2, c.x + w, c.y + h / 2);
      else add(c.x - w, c.y - h / 2, c.x, c.y + h / 2);
    });
    return { l, t, r, b };
  };
  let rect = measure();
  const fits = q => q.l >= pad && q.t >= pad && q.r <= W - padR && q.b <= H - pad;
  if (fits(rect)) return;
  let guard = 0;
  while ((rect.r - rect.l > W - pad - padR || rect.b - rect.t > H - 2 * pad) && map.getLevel() < 14 && guard++ < 8) {
    map.setLevel(map.getLevel() + 1, { animate: false });
    rect = measure();
  }
  const dx = rect.l < pad ? rect.l - pad : (rect.r > W - padR ? rect.r - (W - padR) : 0);
  const dy = rect.t < pad ? rect.t - pad : (rect.b > H - pad ? rect.b - (H - pad) : 0);
  if (dx || dy) map.panBy(dx, dy);
}

// ─────────────────────────────────────────────
// POI 데이터 및 날씨
// ─────────────────────────────────────────────
async function loadPois() {
  const cards = document.getElementById('resultsCards');
  cards.innerHTML = '<p class="empty-state" role="status">장소 데이터를 불러오는 중입니다.</p>';
  try {
    const response = await fetch('./data/pois.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error('POI 데이터 형식이 배열이 아닙니다.');
    // 유효한 장소(도서관, 공원, 서점)만 필터링
    state.pois = data.filter(p => p.facility_type === 'library' || p.facility_type === 'park' || p.facility_type === 'bookstore');
    renderEmptyState();
  } catch (error) {
    console.error('POI 데이터 로드 실패:', error);
    cards.innerHTML = '<p class="empty-state">장소 데이터를 불러오지 못했습니다. 웹 서버에서 페이지를 열고 다시 시도해 주세요.</p>';
    document.getElementById('resultsMeta').textContent = '데이터 로드 실패';
  }
}

function initDateInput() {
  const input = document.getElementById('dateInput');
  const today = new Date().toLocaleDateString('sv-SE');
  input.value = today;
  state.date = today;
  loadWeather(today);
  input.addEventListener('change', e => {
    if (!e.target.value) return;
    state.date = e.target.value;
    loadWeather(state.date);
    if (state.results.length > 0) {
      setSearchLabel('다시 찾기');
      document.getElementById('predictionAnalysis').textContent = '날짜가 변경되었습니다. [다시 찾기]를 누르면 해당 날짜 예보와 시간표로 다시 계산합니다.';
    }
  });
}

async function loadWeather(date) {
  const box = document.getElementById('weatherBox'), id = ++state.weatherRequestId;
  state.weather = null;
  state.nextWeather = null;
  box.innerHTML = '<span class="placeholder-text">날씨를 불러오는 중입니다…</span>';
  if (!window.WeatherClient || typeof window.WeatherClient.fetchForDate !== 'function') {
    box.innerHTML = '<span class="placeholder-text">날씨 서비스를 사용할 수 없습니다.</span>';
    return;
  }
  const result = await window.WeatherClient.fetchForDate(date);
  if (id !== state.weatherRequestId) return;
  if (!result.available) {
    box.innerHTML = `<span class="placeholder-text">선택한 날짜의 날씨를 불러오지 못했습니다.${result.reason ? ` (${escapeHtml(result.reason)})` : ''}</span>`;
    return;
  }
  state.weather = result;
  state.nextWeather = null;
  renderHourlyWeather();
  const following = await window.WeatherClient.fetchForDate(nextDate(date));
  if (id !== state.weatherRequestId) return;
  state.nextWeather = following;
  renderHourlyWeather();
}

function weatherNumber(value, unit) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}${unit}` : '자료 없음';
}

function renderHourlyWeather() {
  if (!state.weather?.available) return;
  const rows = [];
  for (let hour = state.startHour; hour <= state.endHour; hour++) {
    const day = hour === 24 ? state.nextWeather : state.weather, key = `${hour === 24 ? nextDate(state.date) : state.date}T${String(hour % 24).padStart(2, '0')}:00`;
    const h = day?.hourly, i = h?.time?.indexOf(key) ?? -1;
    rows.push(`<tr><th>${hour === 24 ? '24시 (익일 00시)' : `${hour}시`}</th><td>${weatherNumber(h?.temperature_2m?.[i], '°C')}</td><td>${weatherNumber(h?.precipitation?.[i], 'mm')}</td><td>${weatherNumber(h?.snowfall?.[i], 'cm')}</td></tr>`);
  }
  document.getElementById('weatherBox').innerHTML = `<div class="weather-badge">Open-Meteo · ${state.weather.source === 'archive' ? '과거 날씨' : '예보'}</div><div class="weather-hourly"><table><caption>선택한 시간대의 대전 날씨</caption><thead><tr><th>시간</th><th>기온</th><th>강수</th><th>적설</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>${state.endHour === 24 && !state.nextWeather?.available ? '<p class="control-help">익일 00시 날씨는 조회 중이거나 제공 범위 밖입니다.</p>' : ''}`;
}

function initRecommendationControls() {
  for (const [id, value] of [['startHour', state.startHour], ['endHour', state.endHour]]) {
    const input = document.getElementById(id);
    input.innerHTML = Array.from({ length: 20 }, (_, i) => i + 5).map(h => `<option value="${h}">${h === 24 ? '24시 (익일 00시)' : `${h}시`}</option>`).join('');
    input.value = value;
    input.addEventListener('change', () => {
      state.startHour = Number(document.getElementById('startHour').value);
      state.endHour = Number(document.getElementById('endHour').value);
      if (state.startHour > state.endHour) {
        if (id === 'startHour') state.endHour = state.startHour;
        else state.startHour = state.endHour;
        document.getElementById('startHour').value = state.startHour;
        document.getElementById('endHour').value = state.endHour;
      }
      renderHourlyWeather();
      if (state.results.length > 0) {
        setSearchLabel('다시 찾기');
        document.getElementById('predictionAnalysis').textContent = '시간 범위가 변경되었습니다. [다시 찾기]를 누르면 새 시간대 열차를 계산합니다.';
      }
    });
  }

  // 💡 슬라이더: 이전에 계산된 결과가 있으면 결과를 날리지 않고 즉시 가중치를 재계산해 재정렬!
  document.getElementById('quietWeight').addEventListener('input', e => {
    const val = Number(e.target.value);
    state.quietWeight = val / 100;
    document.getElementById('quietWeightLabel').textContent = `한산함 ${val}%`;
    document.getElementById('distanceWeightLabel').textContent = `거리 ${100 - val}%`;

    if (state.results && state.results.length > 0) {
      const w = state.quietWeight;
      state.results.forEach(r => {
        const qScore = typeof r.quiet_score === 'number' ? r.quiet_score : 50;
        const dScore = typeof r.distance_score === 'number' ? r.distance_score : 50;
        r.score = Number((w * qScore + (1 - w) * dScore).toFixed(1));
      });
      state.results.sort((a, b) => (b.score - a.score) || (a.distance_km - b.distance_km));
      renderRecommendations({ results: state.results, meta: state.lastMeta });
    }
  });
}

function initFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-pressed', 'false'); });
    btn.classList.add('active');
    btn.setAttribute('aria-pressed', 'true');
    state.selectedCategory = btn.dataset.cat;
    const sel = document.getElementById('catSelect');
    if (sel) sel.value = state.selectedCategory;

    if (state.results && state.results.length > 0) {
      // 추천 결과 모드일 때: 현재 카테고리에 맞게 필터링 렌더링 (지도 마커도 함께 갱신)
      renderRecommendations({ results: state.results, meta: state.lastMeta });
    } else {
      // 검색 전: 장소를 지도에 쏟아내지 않고 안내만 유지
      renderEmptyState();
    }
  }));
  document.getElementById('catSelect')?.addEventListener('change', e => {
    document.querySelector(`.filter-btn[data-cat="${e.target.value}"]`)?.click();
  });
}

function visibleResults() {
  const results = (state.results || []).filter(r => !r.group || r.group === state.tab);
  return state.selectedCategory === 'all' ? results : results.filter(r => r.poi?.facility_type === state.selectedCategory);
}

// ─────────────────────────────────────────────
// 검색 전 안내 (장소 마커/카드를 미리 보여주지 않음)
// ─────────────────────────────────────────────
function renderEmptyState() {
  renderPoiMarkers([]);
  state.results = state.results || [];
  renderGroupTabs();
  document.getElementById('resultsMeta').textContent = '추천 결과 대기 중';
  document.getElementById('resultsCards').innerHTML = `<div class="empty-state empty-guide" role="status">
    <strong>추천을 받을 준비가 되었어요</strong>
    <ol>
      <li>출발지 선택을 눌러 지도 선택을 켠 뒤, 지도에서 위치를 고릅니다.</li>
      <li>방문 날짜와 이용할 시간 범위를 정합니다.</li>
      <li>[찾기] 버튼을 누르면 추천 장소가 지도와 목록에 나타납니다.</li>
    </ol>
  </div>`;
}

// 추천된 장소만 지도에 표시한다 (같은 장소의 여러 열차 후보는 가장 높은 순위 하나만 마커로 표시).
function renderPoiMarkers(results = visibleResults()) {
  state.poiMarkers.forEach(m => m.setMap(null));
  state.poiMarkers = [];
  if (!state.map) return;

  const seen = new Set();
  results.forEach((r, idx) => {
    const p = r.poi || {};
    if (!hasCoords(p)) return;
    const key = p.name || `${p.latitude},${p.longitude}`;
    if (seen.has(key)) return;
    seen.add(key);

    const node = document.createElement('button');
    node.className = 'poi-map-dot';
    node.type = 'button';
    node.title = p.name || '';
    node.setAttribute('aria-label', p.name || '장소');
    node.addEventListener('click', e => {
      e.stopPropagation();
      showPlaceRoute(r, true);
      const cards = document.querySelectorAll('#resultsCards .result-card');
      cards.forEach(c => c.classList.remove('selected'));
      const card = document.querySelector(`#resultsCards .result-card[data-index="${idx}"]`);
      if (card) {
        card.classList.add('selected');
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      }
    });

    const overlay = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(Number(p.latitude), Number(p.longitude)),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 2,
    });
    overlay.setMap(state.map);
    state.poiMarkers.push(overlay);
  });
}

// 같은 장소의 다른 시간 선택지를 한 줄로 (최대 2개)
function altLine(r) {
  const alts = Array.isArray(r.alt_times) ? r.alt_times.slice(0, 2) : [];
  if (!alts.length) return '';
  const text = alts.map(a => `${formatTrainTime(a.departure_time)}${typeof a.mean_load === 'number' ? ` · ${Math.round(a.mean_load)}명` : ''}`).join(', ');
  return `<div class="result-alt">다른 시간 ${escapeHtml(text)}</div>`;
}

// 카카오맵 길찾기 링크 (공식 지도 URL 링크 형식: /link/by/{walk|traffic}/이름,위도,경도/이름,위도,경도, 출발지가 없으면 /link/to/이름,위도,경도)
// 링크를 누를 때만 장소 좌표와 출발 위치가 카카오로 전달된다.
function kakaoRouteUrl(poi, walk) {
  const lat = Number(poi.latitude), lng = Number(poi.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return '';
  const clean = t => encodeURIComponent(String(t || '장소').replace(/[,/\\]/g, ' ').trim() || '장소');
  const dest = `${clean(poi.name)},${lat.toFixed(6)},${lng.toFixed(6)}`;
  if (!state.departure) return `https://map.kakao.com/link/to/${dest}`;
  const origin = `${encodeURIComponent('출발 위치')},${state.departure.lat.toFixed(6)},${state.departure.lng.toFixed(6)}`;
  return `https://map.kakao.com/link/by/${walk ? 'walk' : 'traffic'}/${origin}/${dest}`;
}

function kakaoRouteLink(poi, walk) {
  const url = kakaoRouteUrl(poi, walk);
  return url ? `<a class="kakao-route" href="${url}" target="_blank" rel="noopener noreferrer">카카오맵 길찾기</a>` : '';
}

function stationName(station) {
  return typeof station === 'string' ? station : (station?.name || '역 정보 없음');
}

function formatTrainTime(time) {
  if (!time) return '시간 정보 없음';
  const [h, m] = String(time).split(':');
  return Number(h) >= 24 ? `익일 ${String(Number(h) - 24).padStart(2, '0')}:${m}` : String(time);
}

function countLabel(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}명` : '예측 없음';
}

// ─────────────────────────────────────────────
// 🏆 실제 추천 결과 렌더링
// ─────────────────────────────────────────────
// 결과 행 내부. view = {hour, cell}이면 시간 막대로 고른 시간의 값(출발·재차·점수)으로 표시하고, 목록 순서·구성은 건드리지 않는다.
function rowInner(r, i, view) {
  const p = r.poi || {}, noTrain = r.no_train;
  const { lo, hi } = state.rowCtx, span = hi - lo || 1;
  const qOf = v => `var(--q${Math.max(1, Math.min(5, 1 + Math.floor(((v - lo) / span) * 4.999)))})`;
  const cell = view?.cell;
  const missing = !!view && !noTrain && typeof cell?.mean_load !== 'number';
  const dep = view && !missing ? cell.departure_time : r.departure_time;
  const load = view ? cell?.mean_load : r.mean_load;
  const score = view ? cell?.score : r.score;
  const hasLoad = !noTrain && !missing && typeof load === 'number';
  const wa = r.walk_access_minutes, we = r.walk_egress_minutes, wt = r.walk_total_minutes;
  const haveWalk = typeof wt === 'number';
  const total = view && !missing && typeof cell?.total_minutes === 'number' ? cell.total_minutes : r.total_minutes;
  const ride = haveWalk && typeof total === 'number' ? total - wt : r.ride_minutes;
  const route = `${escapeHtml(stationName(r.boarding_station))} → ${escapeHtml(stationName(r.alighting_station))}`;
  // 걷는 시간은 직선거리로 어림한 추정치라 항상 "추정"을 붙인다. 대기·환승 시간은 포함하지 않는다.
  const walkLine = !haveWalk ? ''
    : noTrain ? `<span class="rt">${ICON.walk}걷기 약 ${wt}분 (추정) · 열차 없음</span>`
    : `<span class="rt">${ICON.walk}걷기 ${wa}분 + ${we}분 = ${wt}분${typeof ride === 'number' && !missing ? ` · 지하철 ${ride}분 · 총 ${total}분` : ''} (추정)</span>`;
  const meta = noTrain
    ? walkLine
    : missing
      ? `<span class="rt">${ICON.train}${route} · ${view.hour}시에는 맞는 열차 없음</span>${walkLine}`
      : `<span class="rt">${ICON.train}${route} · ${escapeHtml(formatTrainTime(dep))} 출발</span>${walkLine}`;
  // 직선으로 걷는 편이 더 가까울 수 있을 때의 참고 안내(순위·점수에는 영향 없음)
  const advice = (!noTrain && typeof r.distance_km === 'number' && typeof r.walking_distance_km === 'number' && r.distance_km < r.walking_distance_km * 0.85)
    ? `<div class="walk-advice">걸어서 바로 가는 편이 더 가까울 수 있어요 (직선 약 ${Math.round(r.distance_km * 1000)}m)</div>` : '';
  const tag = view ? `<div class="view-tag">${view.hour}시 기준</div>` : '';
  return `
        <div class="rank">${i + 1}</div>
        <div class="row-main">
          <div class="name">${catIcon(p.facility_type)}<span class="name-text">${escapeHtml(p.name)}</span><span class="cat-text">${catLabel(p.facility_type)}</span></div>
          ${tag}
          <div class="meta">${meta}</div>
          ${advice}
          ${view ? '' : altLine(r)}
          <div class="addr">${escapeHtml(p.address || '주소 정보 없음')}${typeof r.distance_km === 'number' ? ` · 직선 ${r.distance_km.toFixed(1)}km` : ''}</div>
          <div class="row-foot">${typeof score === 'number' ? `<span class="result-score">추천점수 ${score.toFixed(1)}</span>` : '<span></span>'}${kakaoRouteLink(p, noTrain)}</div>
        </div>
        <div class="q">${hasLoad ? `<b>${Math.round(load)}</b><small>예상 재차 · 명</small><div class="meter" aria-hidden="true"><i style="width:${Math.min(100, Math.max(8, Math.round((load / hi) * 100)))}%;background:${qOf(load)}"></i></div>` : '<b>–</b><small>열차 없음</small>'}</div>
  `;
}

// 가까운 곳 / 지하철로 멀리 탭 (탭 전환은 브라우저에서만 처리: 서버 재순위 없음)
const GROUP_LABEL = { near: '가까운 곳', far: '지하철로 멀리' };
function groupCount(g) {
  const list = (state.results || []).filter(r => r.group === g && (state.selectedCategory === 'all' || r.poi?.facility_type === state.selectedCategory));
  const more = state.selectedCategory === 'all' && (state.lastMeta?.groups?.[g]?.places || 0) > list.length;
  return `${list.length}${more ? '+' : ''}`;
}
function renderGroupTabs() {
  const box = document.getElementById('groupTabs');
  if (!box) return;
  const has = (state.results || []).some(r => r.group);
  box.hidden = !has;
  document.getElementById('groupNote').hidden = !has;
  if (!has) return;
  box.querySelectorAll('[role="tab"]').forEach(t => {
    const g = t.dataset.group, on = g === state.tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    t.querySelector('.cnt').textContent = `(${groupCount(g)})`;
  });
  document.getElementById('resultsBody')?.setAttribute('aria-labelledby', state.tab === 'near' ? 'tabNear' : 'tabFar');
  document.getElementById('groupNote').textContent = state.tab === 'near'
    ? '총 30분 이하(걷기 + 지하철, 대기·환승 시간 제외, 추정)인 장소예요.'
    : '총 30분을 넘는 장소예요. 점수(거리·한산함)는 이 탭 안의 장소끼리만 비교한 값입니다.';
}
function switchTab(name) {
  if (state.tab === name) return;
  state.tab = name;
  state.viewHour = null;
  showUpdateNote('');
  clearRoute();
  state.selectedItem = null;
  window.Analysis?.setSelected(null);
  renderRecommendations({ results: state.results, meta: state.lastMeta });
  if (state.listed.length) {
    document.querySelector('#resultsCards .result-card[data-index="0"]')?.classList.add('selected');
    showPlaceRoute(state.listed[0], true);
  } else {
    renderTimeStrip();
  }
  window.Analysis?.refreshHeatmap();
}
function initGroupTabs() {
  const box = document.getElementById('groupTabs');
  if (!box) return;
  const tabs = [...box.querySelectorAll('[role="tab"]')];
  tabs.forEach(t => t.addEventListener('click', () => switchTab(t.dataset.group)));
  box.addEventListener('keydown', e => {
    const i = tabs.findIndex(t => t === document.activeElement);
    if (i < 0) return;
    const next = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    switchTab(tabs[next].dataset.group);
    tabs[next].focus();
  });
}

// 선택한 장소의 matrix 행과 보고 있는 시간의 칸
function viewTarget() {
  const m = state.matrix, id = state.selectedItem?.poi?.id;
  if (!m || id == null) return null;
  const row = m.rows.find(r => r.poi_id === id && (!r.group || r.group === state.tab));
  if (!row) return null;
  const usable = row.cells.some(c => typeof c.mean_load === 'number');
  const i = state.viewHour === null ? -1 : m.hours.indexOf(state.viewHour);
  return { row, usable, cell: i >= 0 ? row.cells[i] : null };
}

// 보고 있는 시간이 바뀌었을 때: 이전에 바꾼 행을 되돌리고 선택한 행만 갱신한다. 순서·구성은 그대로.
function syncViewHour() {
  document.querySelectorAll('#resultsCards .result-card[data-view]').forEach(card => {
    const i = Number(card.dataset.index);
    card.removeAttribute('data-view');
    if (state.listed[i]) card.innerHTML = rowInner(state.listed[i], i, null);
  });
  const t = viewTarget();
  if (state.viewHour !== null && !(t && t.cell)) state.viewHour = null;
  let announce = '';
  if (state.viewHour !== null && t && t.cell && state.selectedItem) {
    const i = state.listed.findIndex(r => r.poi?.id === state.selectedItem.poi?.id);
    const card = document.querySelector(`#resultsCards .result-card[data-index="${i}"]`);
    if (card && i >= 0) {
      card.dataset.view = String(state.viewHour);
      card.innerHTML = rowInner(state.listed[i], i, { hour: state.viewHour, cell: t.cell });
      const c = t.cell;
      announce = `${state.selectedItem.poi.name} ${state.viewHour}시 기준: ` + (typeof c.mean_load === 'number' ? `${formatTrainTime(c.departure_time)} 출발, 예상 재차 ${Math.round(c.mean_load)}명` : '맞는 열차 없음');
    }
  }
  const live = document.getElementById('viewStatus');
  if (live) live.textContent = announce;
  renderTimeStrip();
}

function renderRecommendations(payload) {
  state.lastMeta = payload.meta || state.lastMeta;
  const results = (payload.results || []).filter(r => (!r.group || r.group === state.tab) && (state.selectedCategory === 'all' || r.poi?.facility_type === state.selectedCategory));
  renderPoiMarkers(results);
  renderGroupTabs();

  document.getElementById('resultsMeta').textContent = `${state.date} 운행일 · ${state.activeHour !== null ? `${state.activeHour}시 기준` : `${state.startHour}~${state.endHour}시`} · 한산함 ${Math.round(state.quietWeight * 100)}%`;

  const cards = document.getElementById('resultsCards');
  if (!results.length) {
    state.listed = [];
    const hint = state.tab === 'near'
      ? '걷는 시간 합계가 이 한도 안이고 총 30분 이내인 가까운 곳이 없습니다. 걷는 시간 한도를 늘리거나 [지하철로 멀리] 탭을 눌러 보세요.'
      : '총 30분을 넘는 먼 곳이 없습니다. 걷는 시간 한도가 짧으면 먼 곳이 걸러질 수 있어요. 한도를 늘려 보세요.';
    cards.innerHTML = `<p class="empty-state" role="status">${hint}</p>`;
    syncViewHour();
    return;
  }

  const loads = results.filter(r => !r.no_train && typeof r.mean_load === 'number').map(r => r.mean_load);
  state.rowCtx = { lo: Math.min(...loads), hi: Math.max(...loads) };
  state.listed = results;
  cards.innerHTML = results.map((r, i) => `<article class="result-card row" data-index="${i}">${rowInner(r, i, null)}</article>`).join('');

  // 카드 클릭 이벤트 바인딩
  cards.querySelectorAll('.result-card').forEach(card => {
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.addEventListener('keydown', ev => { if (ev.target.closest('.kakao-route')) return; if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); card.click(); } });
    card.addEventListener('click', ev => {
      if (ev.target.closest('.kakao-route')) return;
      cards.querySelectorAll('.result-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      const idx = Number(card.dataset.index);
      const item = results[idx];
      showPlaceRoute(item, true);
    });
  });

  syncViewHour();

  const transit = results.filter(r => !r.no_train);
  document.getElementById('predictionAnalysis').innerHTML = transit.length
    ? `<div class="analysis-scroll"><table><thead><tr><th>출발 시각</th><th>이용 구간 / 장소</th><th>평균 재차</th><th>최대 재차</th></tr></thead><tbody>${transit.map(r => `<tr><td>${escapeHtml(formatTrainTime(r.departure_time))}</td><td>${escapeHtml(stationName(r.boarding_station))} → ${escapeHtml(stationName(r.alighting_station))}<br><strong>${escapeHtml(r.poi?.name)}</strong></td><td>${countLabel(r.mean_load)}</td><td>${countLabel(r.max_load)}</td></tr>`).join('')}</tbody></table></div>`
    : '열차 이동이 필요한 추천이 없습니다.';

  const notes = payload.meta?.limitations;
  if (Array.isArray(notes) && notes.length) {
    const note = document.createElement('details');
    note.className = 'limits-note';
    note.innerHTML = `<summary>예측의 한계</summary><p>${escapeHtml(notes.join(' · '))}</p>`;
    cards.prepend(note);
  }
}

function setUpdating(on) {
  document.getElementById('resultsSection')?.classList.toggle('is-updating', on);
  const badge = document.getElementById('mapUpdating');
  if (badge) badge.hidden = !on;
  if (on) {
    state.routePolylines.forEach(p => { try { if (typeof p.setOptions === 'function') p.setOptions({ strokeOpacity: 0.3 }); } catch (_) { /* 무시 */ } });
  }
}

function setStale(on) {
  document.getElementById('resultsSection')?.classList.toggle('is-stale', on);
}

function showUpdateNote(message, retry = false) {
  const note = document.getElementById('updateNote');
  if (!note) return;
  if (!message) { note.hidden = true; note.textContent = ''; return; }
  note.textContent = message + ' ';
  if (retry) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'update-retry';
    btn.textContent = '다시 시도';
    btn.addEventListener('click', () => requestRecommendations());
    note.appendChild(btn);
  }
  note.hidden = false;
}

async function requestRecommendations(opts = {}) {
  const auto = opts.auto === true;
  clearTimeout(state.researchTimer);
  state.researchTimer = null;
  const hourMode = Number.isInteger(opts.hour) ? opts.hour : (auto ? state.activeHour : null);
  const prevPoiId = auto ? (state.selectedItem?.poi?.id ?? null) : null;
  if (!state.departure) {
    document.getElementById('resultsCards').innerHTML = '<p class="empty-state">먼저 위의 출발지 선택을 눌러 지도 선택을 켜거나, 역 목록에서 출발지를 골라 주세요.</p>';
    renderMetroSchematic();
    return;
  }
  state.recommendationController?.abort();
  const controller = new AbortController();
  state.recommendationController = controller;
  const id = ++state.recommendationRequestId;
  const button = document.getElementById('searchBtn');
  const startedAt = Date.now();
  let tick = null;
  setStale(false);
  showUpdateNote('');
  if (auto) {
    setUpdating(true);   // 이전 결과는 흐리게 두고 새 결과가 오면 바꾼다
  } else {
    setUpdating(false);
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span><span class="go-label">계산 중…</span>';
    const cardsBox = document.getElementById('resultsCards');
    document.getElementById('resultsMeta').textContent = '추천 계산 중';
    cardsBox.innerHTML = `<div class="loading-status" role="status"><span id="loadingElapsed">계산 중 · 0초</span></div><div class="skeleton-row" aria-hidden="true">${'<div class="skeleton-card"><i></i><i></i><i></i><i></i></div>'.repeat(4)}</div>`;
    tick = setInterval(() => {
      const el = document.getElementById('loadingElapsed');
      if (el) el.textContent = `계산 중 · ${Math.floor((Date.now() - startedAt) / 1000)}초`;
    }, 1000);
  }
  const timeout = setTimeout(() => controller.abort(), 90000);

  try {
    const response = await fetch(`${API_BASE}/api/recommend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        date: state.date,
        start_hour: hourMode ?? state.startHour,
        end_hour: hourMode ?? state.endHour,
        ...(hourMode === null ? { include_matrix: true } : {}),
        quiet_weight: Math.round(state.quietWeight * 100),
        category: state.selectedCategory,
        origin: state.departure,
        limit: 50,
        ...(document.getElementById('maxWalk').value !== '' ? { max_walk_minutes: Number(document.getElementById('maxWalk').value) } : {}),
      }),
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new Error('예측 서비스 응답을 읽을 수 없습니다.');
    }
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '예측 서비스가 요청을 처리하지 못했습니다.');
    if (!Array.isArray(payload.results)) throw new Error('예측 결과 형식을 확인할 수 없습니다.');
    if (id !== state.recommendationRequestId) return;

    setUpdating(false);
    if (!auto) { state.viewHour = null; state.tab = 'near'; }
    state.results = payload.results;
    state.lastMeta = payload.meta || state.lastMeta;
    state.activeHour = hourMode;
    if (hourMode === null) {
      state.chipRange = { start: state.startHour, end: state.endHour };
      state.matrix = payload.matrix || null;
    }
    renderRecommendations(payload);
    renderTimeStrip();
    window.Analysis?.refreshHeatmap();
    if (!auto) document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });

    if (auto && prevPoiId !== null) {
      // 출발지 변경 후 재검색: 같은 탭에 같은 장소가 있으면 새 결과로 경로를 다시 그린다(카메라는 움직이지 않음)
      const idx = state.listed.findIndex(r => r.poi?.id === prevPoiId);
      if (idx >= 0) {
        document.querySelector(`.result-card[data-index="${idx}"]`)?.classList.add('selected');
        showPlaceRoute(state.listed[idx], true, false);
        syncViewHour(); // 같은 장소이고 그 시간이 새 matrix에 있으면 유지, 아니면 초기화
      } else {
        clearRoute();
        state.selectedItem = null;
        window.Analysis?.setSelected(null);
        state.viewHour = null;
        syncViewHour();
        const other = payload.results.some(r => r.poi?.id === prevPoiId);
        showUpdateNote(other ? '선택했던 장소가 새 출발지 기준으로 다른 탭으로 옮겨져 선택을 해제했습니다.' : '선택했던 장소가 새 출발지 기준 결과에 없어 선택을 해제했습니다.');
      }
    } else if (state.listed.length > 0) {
      // 현재 탭 1위 장소의 경로를 지도에 기본 표시
      const firstCard = document.querySelector('.result-card[data-index="0"]');
      if (firstCard) firstCard.classList.add('selected');
      showPlaceRoute(state.listed[0], true);
    }
  } catch (error) {
    if (id !== state.recommendationRequestId) return;
    if (auto) {
      // 이전 결과는 그대로 두되(흐림 해제 후 '이전 결과' 표시) 오류와 재시도 버튼을 보인다
      setUpdating(false);
      setStale(true);
      showUpdateNote(`새 출발지 기준으로 다시 계산하지 못했습니다(${error.name === 'AbortError' ? '응답 시간 초과' : (error.message === 'Failed to fetch' ? '예측 서비스에 연결할 수 없음' : error.message)}). 아래는 이전 출발지 기준 결과입니다.`, true);
      return;
    }
    renderPoiMarkers([]);
    document.getElementById('resultsMeta').textContent = '추천을 불러오지 못했습니다';
    document.getElementById('resultsCards').innerHTML = `<p class="empty-state is-error" role="alert">${escapeHtml(error.name === 'AbortError' ? '응답 시간이 길어 요청을 중단했습니다. 잠시 후 다시 시도해 주세요.' : error.message === 'Failed to fetch' ? '예측 서비스에 연결할 수 없습니다. prediction_api.py 가 실행 중인지, 주소가 http://127.0.0.1:5500/web/index.html 인지 확인해 주세요.' : error.message)}<br>혼잡도나 추천 점수를 임의로 대신 표시하지 않습니다.</p>`;
    document.getElementById('predictionAnalysis').textContent = '예측 자료를 불러오지 못했습니다.';
  } finally {
    clearTimeout(timeout);
    clearInterval(tick);
    if (id === state.recommendationRequestId && !auto) {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      setSearchLabel('찾기');
    }
  }
}

// 시간 막대: 검색 뒤 응답의 matrix(실제 값)로만 그린다. 막대를 눌러도 순위·목록은 바뀌지 않고, 선택한 장소의 표시만 그 시간 값으로 바뀐다(D-019).
function renderTimeStrip() {
  const box = document.getElementById('timeStrip');
  if (!box) return;
  const m = state.matrix;
  if (!m || !m.rows?.length || !state.results.length) { box.hidden = true; box.innerHTML = ''; return; }
  const t = viewTarget();
  const own = !!(t && t.usable);                       // 선택한 장소의 시간별 값이 있을 때만 막대를 누를 수 있다
  const series = m.hours.map((h, i) => {
    if (own) return t.row.cells[i]?.mean_load ?? null;
    const v = m.rows.filter(r => !r.no_train && (!r.group || r.group === state.tab)).map(r => r.cells[i]?.mean_load).filter(x => typeof x === 'number');
    return v.length ? Math.min(...v) : null;
  });
  const vals = series.filter(v => typeof v === 'number');
  if (!vals.length) { box.hidden = true; box.innerHTML = ''; return; }
  const preferredWidth = Math.max(370, Math.min(780, 220 + m.hours.length * 28));
  box.style.setProperty('--strip-preferred-width', `${preferredWidth}px`);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const qn = v => Math.min(5, 1 + Math.floor(((v - lo) / span) * 4.999));
  const qLabel = ['매우 한산', '한산', '보통', '붐빔', '매우 붐빔'];
  const sel = state.selectedItem;
  const walkOnly = !!sel?.no_train;
  const basis = own
    ? `선택한 장소(${t.row.name}) 기준`
    : walkOnly
      ? '도보 전용 장소 자체의 혼잡도가 아님'
      : '상위 후보 중 가장 한산한 값 기준';
  const recommendationHour = sel && !sel.no_train && sel.departure_time
    ? Number(String(sel.departure_time).split(':')[0])
    : null;
  const currentView = walkOnly
    ? '선택한 장소는 도보 전용'
    : state.viewHour === null ? '기본 추천 보기' : `현재 표시: ${state.viewHour}시`;
  const hint = own ? '시간을 누르면 선택한 장소의 그 시간 정보를 보여줍니다 (순위는 그대로)'
    : !sel ? '장소를 고르면 시간을 눌러 그 장소의 시간별 정보를 볼 수 있어요'
    : walkOnly ? '이 그래프는 이 장소의 혼잡도가 아닙니다. 같은 탭의 지하철 추천안 중 시간별 최소값입니다.'
    : '이 장소는 시간별 값이 없어 막대만 보여 줍니다 (상위 15곳만 제공)';
  const cols = m.hours.map((h, i) => {
    const v = series[i], selectedHour = state.viewHour === null ? recommendationHour : state.viewHour;
    const on = selectedHour === h;
    if (typeof v !== 'number') return `<div class="col empty" role="img" aria-label="${h}시 열차 없음"><span class="bar"></span><span class="h">${h}</span><span class="v">–</span></div>`;
    const n = qn(v), height = 8 + Math.round(((v - lo) / span) * 28);
    const label = `${h}시, 예상 재차 ${Math.round(v)}명, ${qLabel[n - 1]}`;
    const inner = `<span class="bar" style="height:${height}px;background:var(--q${n})"></span><span class="h">${h}</span><span class="v">${Math.round(v)}</span>`;
    if (!own) return `<div class="col static${on ? ' sel' : ''}" role="img" aria-label="${label}${on ? ', 선택됨' : ''}" title="${label}">${inner}</div>`;
    return `<button type="button" class="col${on ? ' sel' : ''}" data-hour="${h}" aria-pressed="${on}" aria-label="${label}${on ? ', 선택됨' : ''}" title="${label}">${inner}</button>`;
  }).join('');
  box.hidden = false;
  box.classList.toggle('is-collapsed', state.timeStripCollapsed);
  const chartTitle = walkOnly ? '다른 지하철 추천안 · 예상 재차인원(명)' : '시간대별 예상 재차인원(명)';
  box.innerHTML = `<div class="strip-head"><div class="strip-title" tabindex="0" aria-label="플로팅 창을 끌어 이동할 수 있습니다. 방향키로 이동하고 Home 키로 처음 위치로 되돌립니다." aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight Home"><div class="strip-heading"><strong>언제 가면 한산할까</strong><span class="strip-drag-affordance" aria-hidden="true" title="창의 빈 곳을 끌어 이동">⠿ 끌어 이동</span></div><span class="strip-current">${escapeHtml(currentView)}</span><span class="strip-basis">${escapeHtml(chartTitle)} · ${escapeHtml(basis)}</span></div>
      <div class="strip-actions"><button type="button" class="strip-best" aria-pressed="${state.viewHour === null}"${own ? '' : ' disabled'}>기본 추천 보기</button>
      <button type="button" class="strip-reset" aria-label="패널 위치 초기화" title="패널 위치 초기화">↺</button>
      <button type="button" class="strip-toggle" aria-expanded="${!state.timeStripCollapsed}" aria-controls="timeStripContent">${state.timeStripCollapsed ? '펼치기' : '접기'}</button></div></div>
    <div class="strip-content" id="timeStripContent"><div class="strip-scroll in-range"><div class="cols" style="--n:${m.hours.length}">${cols}</div></div>
    <div class="legend"><span><i style="background:var(--q1)"></i>한산</span><span><i style="background:var(--q3)"></i>보통</span><span><i style="background:var(--q5)"></i>붐빔</span><span class="legend-hint">${hint}</span></div></div>`;
  box.querySelector('.strip-toggle').addEventListener('click', e => {
    state.timeStripCollapsed = !state.timeStripCollapsed;
    box.classList.toggle('is-collapsed', state.timeStripCollapsed);
    e.currentTarget.setAttribute('aria-expanded', String(!state.timeStripCollapsed));
    e.currentTarget.textContent = state.timeStripCollapsed ? '펼치기' : '접기';
  });
  bindTimeStripHandle(box);
  box.querySelectorAll('.col[data-hour]').forEach(btn => btn.addEventListener('click', () => { state.viewHour = Number(btn.dataset.hour); syncViewHour(); document.querySelector(`#timeStrip .col[data-hour="${state.viewHour}"]`)?.focus(); }));
  box.querySelector('.strip-best').addEventListener('click', () => { state.viewHour = null; syncViewHour(); document.querySelector('#timeStrip .strip-best')?.focus(); });
  requestAnimationFrame(applyTimeStripPosition);
}

const TIME_STRIP_POSITION_KEY = 'timeStrip.position.v1';

function readTimeStripPosition() {
  try {
    const value = JSON.parse(localStorage.getItem(TIME_STRIP_POSITION_KEY) || 'null');
    if (value && Number.isFinite(value.x) && Number.isFinite(value.y)) {
      return { x: Math.max(0, Math.min(1, value.x)), y: Math.max(0, Math.min(1, value.y)) };
    }
  } catch (_) { /* 저장소를 사용할 수 없으면 기본 위치를 쓴다 */ }
  return null;
}

function stripPositionLimits(box) {
  const area = document.querySelector('.map-area');
  if (!area || !box) return null;
  const xRange = Math.max(0, area.clientWidth - box.offsetWidth - 16);
  const yRange = Math.max(0, area.clientHeight - box.offsetHeight - 16);
  return { area, xRange, yRange };
}

function applyTimeStripPosition() {
  const box = document.getElementById('timeStrip');
  if (!box || box.hidden) return;
  const limits = stripPositionLimits(box);
  if (!limits) return;
  const p = state.timeStripPosition || { x: 0, y: 1 };
  box.style.left = `${8 + p.x * limits.xRange}px`;
  box.style.top = `${8 + p.y * limits.yRange}px`;
  box.style.right = 'auto';
  box.style.bottom = 'auto';
}

function saveTimeStripPosition() {
  const box = document.getElementById('timeStrip');
  const limits = stripPositionLimits(box);
  if (!box || !limits) return;
  const left = Math.max(8, Math.min(limits.area.clientWidth - box.offsetWidth - 8, box.offsetLeft));
  const top = Math.max(8, Math.min(limits.area.clientHeight - box.offsetHeight - 8, box.offsetTop));
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  state.timeStripPosition = {
    x: limits.xRange ? (left - 8) / limits.xRange : 0,
    y: limits.yRange ? (top - 8) / limits.yRange : 1,
  };
  try { localStorage.setItem(TIME_STRIP_POSITION_KEY, JSON.stringify(state.timeStripPosition)); }
  catch (_) { /* 저장소를 쓸 수 없어도 현재 위치 이동은 유지한다 */ }
}

function resetTimeStripPosition() {
  state.timeStripPosition = null;
  try { localStorage.removeItem(TIME_STRIP_POSITION_KEY); } catch (_) { /* 기본 위치로 복귀는 계속 진행 */ }
  applyTimeStripPosition();
}

function moveTimeStripBy(dx, dy) {
  const box = document.getElementById('timeStrip');
  const limits = stripPositionLimits(box);
  if (!box || !limits) return;
  const left = Math.max(8, Math.min(limits.area.clientWidth - box.offsetWidth - 8, box.offsetLeft + dx));
  const top = Math.max(8, Math.min(limits.area.clientHeight - box.offsetHeight - 8, box.offsetTop + dy));
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  saveTimeStripPosition();
}

function bindTimeStripHandle(box) {
  const handle = box.querySelector('.strip-title');
  const resetButton = box.querySelector('.strip-reset');
  if (!handle) return;
  box.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button, a, input, select, .strip-scroll')) return;
    const startLeft = box.offsetLeft, startTop = box.offsetTop;
    state.timeStripDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: startLeft, top: startTop };
    box.classList.add('is-dragging');
    box.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  box.addEventListener('pointermove', e => {
    const drag = state.timeStripDrag;
    if (!drag || drag.id !== e.pointerId) return;
    const limits = stripPositionLimits(box);
    if (!limits) return;
    const left = Math.max(8, Math.min(limits.area.clientWidth - box.offsetWidth - 8, drag.left + e.clientX - drag.x));
    const top = Math.max(8, Math.min(limits.area.clientHeight - box.offsetHeight - 8, drag.top + e.clientY - drag.y));
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  });
  const finishDrag = e => {
    const drag = state.timeStripDrag;
    if (!drag || drag.id !== e.pointerId) return;
    state.timeStripDrag = null;
    box.classList.remove('is-dragging');
    saveTimeStripPosition();
    if (box.hasPointerCapture(e.pointerId)) box.releasePointerCapture(e.pointerId);
  };
  box.addEventListener('pointerup', finishDrag);
  box.addEventListener('pointercancel', finishDrag);
  handle.addEventListener('keydown', e => {
    const step = e.shiftKey ? 40 : 12;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (delta) { e.preventDefault(); moveTimeStripBy(...delta); }
    else if (e.key === 'Home') { e.preventDefault(); resetTimeStripPosition(); }
  });
  resetButton?.addEventListener('click', resetTimeStripPosition);
}

function initTimeStripPosition() {
  state.timeStripPosition = readTimeStripPosition();
  const area = document.querySelector('.map-area'), box = document.getElementById('timeStrip');
  if (typeof ResizeObserver !== 'undefined' && area && box) {
    const observer = new ResizeObserver(applyTimeStripPosition);
    observer.observe(area);
    observer.observe(box);
  }
  window.addEventListener('resize', applyTimeStripPosition);
}

// 출발지 문장 칸: 눌러서 지도 안내와 역 목록을 연다 (Esc/바깥 클릭으로 닫힘)
function initQueryBar() {
  const slot = document.getElementById('slotOrigin'), pop = document.getElementById('originPop'), sel = document.getElementById('originStation');
  const pickButton = document.getElementById('mapPickButton'), pickCancel = document.getElementById('mapPickCancel');
  if (!slot || !pop || !sel) return;
  sel.innerHTML += STATIONS.map(s => `<option value="${s.idx}">${escapeHtml(s.name)}역</option>`).join('');
  const close = (focus = false) => { pop.hidden = true; slot.setAttribute('aria-expanded', 'false'); if (focus) slot.focus(); };
  slot.addEventListener('click', () => {
    if (state.mapPickMode) setMapPickMode(false);
    const open = pop.hidden;
    pop.hidden = !open;
    slot.setAttribute('aria-expanded', String(open));
    if (open) pickButton?.focus();
  });
  pickButton?.addEventListener('click', () => {
    setMapPickMode(true);
    close();
    pickCancel?.focus();
  });
  pickCancel?.addEventListener('click', () => {
    setMapPickMode(false);
    slot.focus();
  });
  sel.addEventListener('change', () => {
    const st = STATIONS.find(x => String(x.idx) === sel.value);
    if (!st) return;
    setDeparture(st.lat, st.lng, `${st.name}역`);
    state.map?.setCenter(new kakao.maps.LatLng(st.lat, st.lng));
    close(true);
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (state.mapPickMode) { setMapPickMode(false); slot.focus(); }
    else if (!pop.hidden) close(true);
  });
  document.addEventListener('click', e => { if (!pop.hidden && !e.target.closest('.slot-box')) close(); });
}

function setMapPickMode(active) {
  state.mapPickMode = !!active;
  const hint = document.getElementById('mapPickHint');
  const button = document.getElementById('mapPickButton');
  if (hint) hint.hidden = !state.mapPickMode;
  button?.setAttribute('aria-pressed', String(state.mapPickMode));
  document.querySelector('.map-area')?.classList.toggle('is-picking', state.mapPickMode);
}

function initSearchBtn() {
  document.getElementById('maxWalk').addEventListener('change', () => {
    if (state.results.length > 0) {
      setSearchLabel('다시 찾기');
      document.getElementById('predictionAnalysis').textContent = '도보 시간이 변경되었습니다. [다시 찾기]를 누르면 다시 계산합니다.';
    }
  });
  setSearchLabel('찾기');
  document.getElementById('searchBtn').addEventListener('click', () => requestRecommendations());
}

document.addEventListener('DOMContentLoaded', () => {
  initTimeStripPosition();
  initTabs();
  initRecommendationControls();
  initDateInput();
  initFilters();
  initGroupTabs();
  initQueryBar();
  initSearchBtn();
  loadPois();
  loadMetroLineGeometry();
  setTimeout(tryInitMap, 400);
});
