# POI 수집 결과 보고서

수집일: 2026-11-16 (Asia/Seoul)

| 시설 | 레코드 | 좌표 포함 |
|---|---:|---:|
| library | 24 | 23 |
| culture | 0 | 0 |
| bookstore | 101 | 97 |
| park | 412 | 412 |
| trail | 11 | 0 |

통합 파일 `poi_all.csv`에는 548개 행이 있다. 공원은 API 제공 좌표를 사용했고, 도서관과 서점 주소는 VWorld로 변환했다.

## 확인 사항

- VWorld 키의 앞 공백을 제거한 뒤 인증과 좌표 변환이 정상 작동했다. 주소 표기 문제로 도서관 1건, 서점 4건은 변환되지 않았으며 주소 목록은 [failures.md](failures.md)에 있다.
- 문화시설 API 전체 131개 항목을 페이지당 100개로 두 번 호출해 원본을 보관했다. 원본 유형은 공연장·미술관·박물관·화랑이며 `fcltyKnd == 전시관` 항목이 없어 가공 결과는 0건이다.
- 서점은 대전시 공식 2026년 11월 인증 목록 101건이다.
- 도서관 원본은 24건이며 기준일은 2023-09-30이다.
- 작업지시서에 적힌 대전둘레산길 CSV를 공식 포털에서 확인하지 못해 대청호반길 산책길 데이터 11개 코스로 대체했다. 좌표는 원본에 없어 추정하지 않았다.
- 공원 API는 JSON 형식 지정에도 XML을 반환해 원본 XML을 보관했다.

## 원본 출처

- 도서관: [공공데이터포털](https://www.data.go.kr/data/15086348/fileData.do)
- 문화시설: [공공데이터포털](https://www.data.go.kr/data/15112114/openapi.do)
- 서점: [대전시 2026년 11월 인증 목록](https://www.daejeon.go.kr/drh/board/boardNormalView.do?boardId=normal_0096&menuSeq=1631&ntatcSeq=1526417624&pageIndex=1)
- 산책길: [대청호반길 데이터](https://www.data.go.kr/data/3075825/fileData.do)

## 재현 방법

프로젝트 루트에서 `.env`에 `DATA_GO_KR_SERVICE_KEY`, `VWORLD_API_KEY`가 각각 설정되어 있는지 확인하고 `python scripts/collect_poi_once.py`를 실행한다. 키 값은 출력하거나 코드·문서에 저장하지 않는다.
