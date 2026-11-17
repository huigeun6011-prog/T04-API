# 현재 웹·예측API 연결

기준2026-11-16. 연결은구현됐지만실제혼잡정확도·추천순위·브라우저시각검증을완료했다는뜻은아니다. [HANDOFF](../HANDOFF.md)에정확한상태와blocker를남겼다.

## 실제 구성

- `scripts/build_web_poi.py`가통합CSV→`web/data/pois.json`을만든다.548행/좌표532개다.
- `web/index.html`+`app.js`는실제POI,출발점,운행일,시간범위,카테고리,10%단위비중을사용한다.추천전은직선거리장소미리보기이며추천버튼으로API를호출한다.
- `web/weather-client.js`는Open-Meteo시간별날씨를조회한다.500ms합치기,최소10초간격,예보1시간/과거7일캐시를쓴다.24시는익일00시다.
- `prediction_api.py`는Python표준ThreadingHTTPServer이다.FastAPI/ONNX가아니다.기본 5500포트(`--port`)에서 시작하며`outputs/load_predictor.joblib`mtime이바뀌면다시읽는다.
- 지도제공자는Kakao이며예측은브라우저직접joblib실행이아닌Python이다.

## API계약

| 경로 | 역할 |
|---|---|
| GET /api/health | 모델읽기가능여부 |
| GET /api/stations | app.js에서읽은22역좌표 |
| GET /api/predict?date=YYYY-MM-DD&hour=0&station=시청&direction=하행 | 달력00시를전날운행일24시로변환한단일예측 |
| POST /api/recommend | 운행일date,start_hour/end_hour(05~24),quiet_weight(0~100·10단위),origin(lat/lng),category,limit |

API는과거날씨로컬파일을우선사용하고없으면무키Open-Meteo를조회한다.브라우저/서버날씨캐시는별도다.요청오류/결측을더미혼잡도로대체하지않는다.

## 현재 추천식

출발위치최근접역→POI최근접역의시간표상가능한열차를찾는다.선택범위는승차시각버킷기준이며탑승뒤이동이종료시각버킷을넘을수있다.각이동구간의출발후정차재차예측(하차역직전까지)을평균·최대로요약한다.같은하차역·시간에는평균load가가장작은열차를쓴다.

후보군최대거리Dmax와최대평균loadLmax를써서near=1−D/Dmax,quiet=1−mean_load/Lmax,score=w×quiet+(100−w)×near로정렬한다.같은역주변장소는열차이동이없어quiet=0.5중립이다.거리D는출발점→장소직선거리이며실제보행시간이나철도이동시간이아니다.후보군이바뀌면정규화점수도바뀐다.

이것은현재코드의정책으로,최종사용자효용이나실제한산함이검증된순위가아니다.운영시간자료가없어개방여부도모른다.장소자체방문객수는예측하지않는다.

## 실행/검증/남은일

웹 페이지(`/web/index.html`)와 API(`/api/*`)는 모두 `prediction_api.py` 한 프로세스가 5500에서 제공하며, 웹은 기본적으로 상대경로(`/api/...`, 같은 출처)로 호출한다. `web/` 아래 파일만 GET/HEAD로 정적 제공하고(경로 resolve 후 `web/` 밖·심볼릭 링크 탈출은 404, 폴더 목록 없음) 그 외 경로는 제공하지 않는다. 예전 2포트 구성은 `window.RECOMMENDATION_API_BASE`로 API 주소를 덮어쓰면 되며 CORS는 localhost/127.0.0.1:5500을 허용한다. 명령은[HANDOFF](../HANDOFF.md)의환경·상태확인절차를따른다.다른API설계예시인`/api/forecast/profile`은구현되지않았다.

API실제응답과JS문법/연결확인까지만했다.이전브라우저접근거절이있어지도위치·클릭·전체UX시각검증을하지않았고우회하지않는다.[좌표보정표](STATION_COORDINATES.md)와현재app.js22개값은2026-11-16문자열대조에서전부일치했다.API도app좌표를쓰므로추천에반영된다.사용자가지도표시를확인했으나마커와실제역사위치의정합은별도로검증하지않았다.

수집키는로컬.env에유지하고브라우저에전달하지않는다.KakaoJS키는브라우저SDK용이지만그값을문서에복사하지않는다.키는`web/config.local.js`(gitignore)에두고`web/kakao-loader.js`가SDK를불러온다.견본은`web/config.example.js`다.이구조는로컬실행전용이고정적호스팅배포시에는다시정해야한다.공개배포·서버호스팅·모바일최종검증은별도미완과제다.

**추천 결과 묶음:** `POST /api/recommend`는 점수·정규화(전체 후보 기준)·정렬을 계산한 뒤 장소(`poi.id`, 없으면 이름+주소)별로 묶어 점수가 가장 높은 후보 하나만 `results`에 둔다. `limit`은 묶은 뒤 장소 수에 적용한다. 각 결과에 `alt_times`(같은 장소의 다른 선택지 최대 3개, 점수순; 각 항목은 `departure_time`, `arrival_time`, `boarding_station`, `alighting_station`(역 이름), `mean_load`, `score`)가 추가되며 열차를 타지 않는 후보(`no_train`)는 넣지 않는다. 응답에 `place_total`(묶은 뒤 장소 수)이 추가되고 `total`은 묶기 전 후보 수 그대로다.

**카카오맵 길찾기 링크:** 카드와 지도 팝업의 "카카오맵 길찾기" 링크는 카카오맵 공식 지도 URL 링크(`https://map.kakao.com/link/by/{walk|traffic}/이름,위도,경도/이름,위도,경도`, 출발 위치가 없으면 `https://map.kakao.com/link/to/이름,위도,경도`)를 새 탭으로 연다. 열차 없는 후보는 `walk`, 열차 후보는 `traffic`(대중교통)을 쓴다. API 키와 백엔드 호출은 없으며, 사용자가 링크를 누를 때만 장소 좌표와 선택한 출발 위치가 카카오로 전달된다.

**시간 칩과 `include_matrix`:** 추천 화면의 시간 칩("장소별 최적 시간", 시간별)은 클라이언트가 순위를 다시 매기지 않고, 칩을 고를 때마다 `POST /api/recommend`를 `start_hour = end_hour = 선택 시간`으로 다시 호출한다(서버가 그 시간 기준으로 정규화·정렬). "장소별 최적 시간"은 사용자가 정한 범위로 호출하고 `include_matrix: true`를 함께 보낸다. `include_matrix`(선택, 기본 false)가 true면 응답에 `matrix`가 추가된다: `{hours:[시간...], rows:[{poi_id, name, no_train, cells:[{hour, departure_time, mean_load, score}]}]}`. 행은 최종 결과의 상위 장소 최대 15곳이며, 각 칸은 이미 계산된 후보 중 그 장소·그 시간의 최고 점수 후보(점수는 메인 순위와 같은 정규화)이고 맞는 열차가 없으면 세 값이 null이다. 점수·정렬·후보 계산은 바뀌지 않는다.

**`GET /api/profile?date=YYYY-MM-DD&boarding=<역>&alighting=<역>`:** 운행일(date)과 역 이름(앱의 22개 역 이름 그대로)을 받아, 그날 시간표에서 승차역→하차역 구간을 달리는 모든 열차의 예상 재차인원을 `predict_profile`(추천과 같은 모델·날씨·시간표 규칙)로 한 번에 계산한다. 응답: `{service_date, boarding, alighting, holiday, weather_source, hours:[{hour(5~24), count, min, median, max, trains:[{departure_time, arrival_time, direction, train_id, mean_load, max_load}]}]}`. `mean_load`/`max_load`는 승차 후 하차 직전까지 구간별 예상 재차인원의 평균/최대, hour는 승차역 출발 시간대이고 min/median/max는 그 시간대 열차들의 `mean_load` 통계이다(열차 없으면 null). 입력 오류는 400이다. (날짜, 승차, 하차) 기준 LRU(32)로 메모리에 캐시한다. 처음 보는 날짜는 날씨 조회(원격 호출은 10초 간격 제한) 때문에 첫 호출이 10초쯤 걸릴 수 있다.

**`web/data/station_profile.json`:** `scripts/build_web_station_profile.py`가 `data/processed/subway/`(읽기 전용)의 2024-11-01~2026-11-01 운행일을 읽어 만든 정적 파일이다. 역·요일 유형(평일/휴일, `predict_load.HOLIDAYS`와 주말 규칙)별로 05~24시(24시는 다음 날 0시, 01~04시 제외)의 평균 승차·하차 인원과 평균에 쓴 일수·기간을 담는다. 혼잡도 분석 탭은 승차역의 승차+하차 합계를 별도 축의 선으로 그려 모델과 독립적인 실제 평균을 보여 준다. `python scripts/build_web_station_profile.py`로 다시 만들 수 있다.

**최대 도보 시간 (`max_walk_minutes`)과 서버 준비:** `POST /api/recommend`는 선택 필드 `max_walk_minutes`(1~240)를 받는다. 값이 있으면 열차를 타지 않는 도보 후보 중 추정 도보 시간(직선거리 x 1.3 / 4.5km/h, 분 단위 반올림)이 이 값을 넘는 후보를 후보 모음에서 뺀다. 값을 생략하면 한도 없이 이전과 같다(웹 화면의 기본은 15분, "제한 없음"은 필드 생략). 도보 후보에는 `walk_minutes`가 붙고 `meta.max_walk_minutes`, `meta.walk_basis`가 응답에 추가된다. 결과의 도보 후보는 `limit`의 1/3까지만 먼저 담고 자리가 남으면 나머지 도보 후보로 채운다. 서버는 시작 직후 백그라운드 스레드로 시간표 파일, 모델 첫 예측, 오늘과 내일의 날씨를 미리 읽는다(검증: 새로 시작한 서버에서 준비 완료 후 첫 추천 0.09~0.14초, 이전에는 약 10.7초. 준비가 끝나기 전 요청은 남은 시간만큼 기다린다). 모델 소개 탭의 문서 링크는 `web/` 밖이라 열리지 않아 일반 텍스트로 바꿨다.

**지도 표시(목적지 핀과 카드):** 추천 카드나 마커를 선택하면 목적지에 큰 핀(`.dest-pin`, 가장 위 레이어)이 그려지고 정보 카드는 경로가 들어오는 방향의 반대쪽에 놓인다(`side-north/south/east/west`). 시점 조정은 핀·카드·출발지·승하차역이 모두 보이면 그대로 두고, 아니면 필요한 만큼만 축소한 뒤 최소 평행이동한다.

**출발지 변경 시 자동 재검색:** 검색한 뒤 `setDeparture()`가 불리면 `scheduleResearch()`가 진행 중 요청을 중단하고(요청 번호 증가) 600ms 디바운스 후 `requestRecommendations({auto:true})`로 같은 조건(시간 칩 상태 포함)을 다시 보낸다. 자동 요청은 스켈레톤·스크롤·버튼 상태를 바꾸지 않고 결과를 흐리게(`is-updating`) 두며, 성공하면 같은 `poi.id`의 결과로 경로를 다시 그리거나(카메라 고정) 선택을 해제하고, 실패하면 `is-stale` 상태로 이전 결과와 재시도 버튼을 보인다. API 계약은 그대로다.

**크기 조절:** `web/layout.js`가 `#splitV`(패널 너비 240~최대 560px 또는 화면의 60%), `#splitH`(결과 높이 96px~지도 200px 남기는 한도)와 접기 버튼을 관리하고 `localStorage['layout.v1']`에 `{panelW, resultsH, panelCollapsed, resultsCollapsed}`를 저장한다. 860px 이하에서는 비활성이다.
