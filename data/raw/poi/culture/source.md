# 문화시설 출처

- 배포처: 공공데이터포털 / 대전광역시
- 데이터셋: 대전광역시_문화시설
- 원본 URL: https://www.data.go.kr/data/15112114/openapi.do
- API 경로: `https://apis.data.go.kr/6300000/openapi2022/ctlstt/getctlstt`
- 수집일: 2026-11-16 (Asia/Seoul), 페이지당 100건으로 2회 호출
- 원본: `raw/culture_page1.json`, `raw/culture_page2.json` (총 131개)
- 이용허락: 제한 없음(포털 표시)
- 처리: `fcltyKnd` 값이 정확히 `전시관`인 항목만 추출했다. 원본 유형은 공연장·미술관·박물관·화랑이며 일치 항목이 없어 가공본은 0건이다.
