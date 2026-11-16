# 현재 웹·예측API 연결

기준2026-11-16. 연결은구현됐지만실제혼잡정확도·추천순위·브라우저시각검증을완료했다는뜻은아니다. [HANDOFF](../HANDOFF.md)에정확한상태와blocker를남겼다.

## 실제 구성

- `scripts/build_web_poi.py`가통합CSV→`web/data/pois.json`을만든다.548행/좌표532개다.
- `web/index.html`+`app.js`는실제POI,출발점,운행일,시간범위,카테고리,10%단위비중을사용한다.추천전은직선거리장소미리보기이며추천버튼으로API를호출한다.
- `web/weather-client.js`는Open-Meteo시간별날씨를조회한다.500ms합치기,최소10초간격,예보1시간/과거7일캐시를쓴다.24시는익일00시다.
- `prediction_api.py`는Python표준ThreadingHTTPServer이다.FastAPI/ONNX가아니다.8000포트에시작하며`outputs/load_predictor.joblib`mtime이바뀌면다시읽는다.
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

웹은5500의 `/web/index.html`,API는8000이다.CORS는localhost/127.0.0.1:5500을허용한다.명령은[HANDOFF](../HANDOFF.md)의환경·상태확인절차를따른다.다른API설계예시인`/api/forecast/profile`은구현되지않았다.

API실제응답과JS문법/연결확인까지만했다.이전브라우저접근거절이있어지도위치·클릭·전체UX시각검증을하지않았고우회하지않는다.[좌표보정표](STATION_COORDINATES.md)와현재app.js22개값은2026-11-16문자열대조에서전부일치했다.API도app좌표를쓰므로추천에반영된다.사용자가지도표시를확인했으나마커와실제역사위치의정합은별도로검증하지않았다.

수집키는로컬.env에유지하고브라우저에전달하지않는다.KakaoJS키는브라우저SDK용이지만그값을문서에복사하지않는다.키는`web/config.local.js`(gitignore)에두고`web/kakao-loader.js`가SDK를불러온다.견본은`web/config.example.js`다.이구조는로컬실행전용이고정적호스팅배포시에는다시정해야한다.공개배포·서버호스팅·모바일최종검증은별도미완과제다.
