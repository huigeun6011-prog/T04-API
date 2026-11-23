# 시간별 날씨 자료

## 저장 자료와 학습 날짜

`data/raw/weather/YYYY-MM-DD.json`에 날짜와 `hourly.time`, `temperature_2m`, `precipitation`, `snowfall` 배열을 보관한다. 기존 수집기 `scripts/utils/collect_weather.py`는 Open-Meteo Archive, 대전 36.35/127.38, Asia/Seoul을 사용한다. T04 백필은 `scripts/utils/backfill_weather.py`로 2026-11-03~22의 Archive 자료를 추가했다. 백필 후 원본 범위는 **2024-11-01~2026-11-22의 752일치**다.

정적 웹의 추천 화면은 과거 날씨 사본 또는 Open-Meteo 조회를 사용한다. T04 정보판의 7일 그래프는 원본에서 05~23시의 강수·적설을 집계한 `static-web/data/t04/business_days.json`을 사용한다. 배포와 `run_static.bat` 실행에서 `scripts/sync_static_data.mjs`가 `static-web/data/weather/`의 공개용 사본을 생성한다. [HANDOFF §12](../HANDOFF.md) 참고.

GT최적화손실에는날씨를넣지않고,라벨생성후HGB의temp/precip/snow피처로결합한다.운행일24시에는익일00시날씨를붙인다.기존당일00시매칭오류는수정됐고재생성한18,035개24시행에서확인했다.달력D일00시추론도날씨는D일00시,요일/시간표는D−1운행일기준이다.

## 실제 웹/API 조회

- `web/weather-client.js`: 무키Open-Meteo예보/과거자료,선택일과익일00시표시용다음날조회.
- 예보캐시1시간/과거캐시7일,500ms합치기,같은날중복요청제거,localStorage및최소10초간격.
- 예보범위는코드상오늘~15일후이며범위밖·결측·오류를더미로대체하지않는다.
- `prediction_api.py`는로컬과거파일을먼저읽고없으면Open-Meteo를조회한다.서버별캐시와10초간격을적용한다.브라우저와서버캐시는별도다.
- `extract_train_loads.py`도24시에는익일파일을읽고필요날씨가없으면오류를낸다.CLI `predict_load.py`는자동날씨조회기가아니므로temp/precip/snow는호출자가제공한다.

Open-Meteo사용은사용자가명시승인했다.POI수집의국내배포처제한을날씨전체에확대적용하지않는다.추가한날씨흐름과실행한계는[HANDOFF](../HANDOFF.md),웹연결은[통합설계](WEB_INTEGRATION_DESIGN.md)를참고한다.
