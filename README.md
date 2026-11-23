# 대전 한적 나들이 추천 프로젝트

대전도시철도1호선의 예상 이동 혼잡과 실제 장소를 조합해 시간·이용역·목적지를 추천하는 로컬 웹 프로젝트입니다. **다음 AI는 [인수인계](docs/HANDOFF.md)를 먼저 읽으세요.** 기준2026-11-18입니다. 실험·재학습·모델교체는 사용자 지시가 있을 때만 합니다.

## 현재 동작

- 실제 POI 548곳을 지도·목록·필터에 연결했습니다. 532곳에 좌표가 있고, 좌표 없는 산책로 11곳은 텍스트로 표시합니다.
- 출발지·운행일·05~24시 범위·장소 종류·걷는 시간 합계 한도·한산함/거리 비중(10% 단위)을 고르고 추천을 요청합니다. 결과는 총 추정시간 30분을 기준으로 **가까운 곳 / 지하철로 멀리**로 나뉩니다.
- Open-Meteo 시간별 날씨를 API 키 없이 조회하고 캐시·호출 간격 제한을 적용합니다. 장소·날씨·혼잡도는 실제 자료와 Python 예측 API를 사용합니다.
- 지도는 Kakao를 사용합니다. 대전 1호선 선로는 OpenStreetMap 양방향 선형을 바탕으로 그리며, 역 사이 곡선은 사용자가 전달한 역 좌표에 맞춰 보정했습니다.
- `outputs/load_predictor.joblib`과 시간표로 열차 이동 후보와 구간별 예상 재차인원을 계산합니다. 장소 방문객 수나 장소 자체 혼잡도를 예측하지 않습니다.

### 좌표와 화면 확인 상태

역 22개 좌표는 사용자가 지도에서 확인해 전달한 위도·경도이며 [역 좌표표](docs/AI/STATION_COORDINATES.md)에 기록했습니다. 웹과 API는 `web/app.js`의 `STATIONS`를 공유합니다. API는 서버 시작 때 좌표를 읽으므로 좌표를 바꾼 뒤에는 서버 재시작이 필요합니다.

코드와 선로 자료의 역 좌표 연결은 검사했습니다. D-015~D-020에는 당시의 브라우저 확인 기록이 있습니다. 최근 수동 좌표·선로 곡선 보정과 플로팅 창 변경은 브라우저 화면에서 아직 확인하지 않았고, 모바일·터치 기기도 최종 검증하지 않았습니다. 상세는 [웹 연결](docs/AI/WEB_INTEGRATION_DESIGN.md)의 검증 구분을 참고하세요.

## 모델 상태와 한계

production HGB모델은 2026-11-19부터 **열차 단위 OD 라벨 61일**(2024-11-01부터 12일 간격, 균일 기준 q, λ=0.01)로 학습한 모델입니다. 검증 MAE23.94명/R²0.838은 **추정라벨 재현성**이며 라벨 정의가 달라 이전 production(Adam 라벨 731일, MAE20.14)과 비교하지 않습니다. 배포파일은 평가후 전체 61일로 refit했습니다. 이전 production은 `outputs/backup_before_od_swap_20261119/`와 git 이력에 있고 [HANDOFF §4](docs/HANDOFF.md)에 교체 근거·한계·되돌리는 법이 있습니다.

**절대 인원 수는 신뢰할 수 없습니다.** 수준은 기준 분포 q가 정하며 검증되지 않았습니다(항저우 균일 q 1.26배 과대, 대전 피크 약 0.5~0.6배 과소). 믿을 수 있는 것은 시간대·역의 상대 순서입니다(항저우 정답 대비 같은 역·방향 시간대 순서 상관 0.96, 2칸 이내 93%). 열차 한 대 단위 구분은 복원되지 않았습니다. 대전 자체 검증은 피크 19건뿐입니다([E-34~E-38](docs/EXPERIMENTS.md)).

이전 production은 Adam으로 GT분배율을 추정하는 방식(이전200회solver의 clamp·종점0보정 라벨, 731일)이었습니다. 이후 배분소실 수정/raw·slack 기록/1000회 후보와3가정 실험은 production에 적용하지 않았습니다. 현재 GT생성코드(`generate_ground_truth.py`)를 기본실행하면 OD 라벨과 다른 방법으로 생성됩니다.

실제피크19사례에는 약376명의 큰MAE가 남았고 추천순위도 미검증입니다. [방법론](docs/AI/METHODOLOGY.md)과 [실험결과](outputs/diagnostics/assumption_ablation/report.md)를 참고하세요.

## 정적 웹 실행 (Python 예측 서버 불필요)

별도 정적 웹은 `static-web/index.html`입니다. 이 폴더의 내용 전체를 정적 호스팅에 올리면 브라우저가 추천을 계산합니다. 서버에서 Python·joblib·OD 계산을 실행하지 않으며 YML은 추가하지 않았습니다. 기존 Python 웹은 `web/`에 보존했습니다.

현재 모델에서 정적 웹을 다시 만들거나 동등성을 확인할 때만 다음 명령을 사용합니다. 재학습은 하지 않습니다.

```powershell
.venv/Scripts/python.exe scripts/build_static_web.py
.venv/Scripts/python.exe scripts/validate_static_web.py
```

빌더는 현재 HGB의 범주형 전처리·300개 트리를 JSON으로 내보내고, `static_src/`의 브라우저 엔진·화면 소스에 필요한 공용 웹 파일과 시간표·휴일·역·POI·732일 날씨만 조합합니다. 이미 생성된 `static-web/`을 운영할 때는 이 변환 명령이나 Python 환경이 필요 없습니다. 정적 사이트도 파일을 HTTP(S)로 제공해야 하므로 `index.html`을 `file://`로 직접 열지는 마세요. 로컬 확인용 파일 서버의 예는 다음과 같습니다(이 서버는 예측을 계산하지 않습니다).

```powershell
.venv/Scripts/python.exe -m http.server 5501 --bind 127.0.0.1 --directory static-web
```

접속: `http://127.0.0.1:5501/`. 과거 보관 날씨는 정적 JSON으로 읽고, 보관되지 않은 날짜는 브라우저가 Open-Meteo를 직접 조회합니다. 정적 호스팅을 사용해도 외부 날씨·지도 연결까지 오프라인이 되는 것은 아닙니다. 모델 파일은 브라우저로 내려받지만 인원 수치를 화면에 출력하지 않는 정책은 유지합니다.

지도 설정이 필요하면 `static-web/config.example.js`를 참고해 해당 폴더의 `config.local.js`를 별도로 설정합니다. 빌더는 기존 `web/config.local.js`나 `.env`를 읽거나 복사하지 않고 출력 폴더의 기존 사용자 설정도 덮어쓰지 않습니다. 키가 없으면 역 선택·추천·분석을 사용할 수 있는 대체 화면이 나옵니다. `station_profile.json`·학습 라벨·원본 개인 태그·Python 파일·joblib는 정적 패키지에 포함하지 않습니다.

검증: 모델 입력 14,296건의 Python–JS 최대 예측 오차 0, 전체 추천 66조건의 구조·순위 일치. Chrome에서 하위 경로(`/demo/`) 검색·필터·키 없는 장소 선택과 분석·출발지 변경 후 재검색, 320~1440px 소개 화면과 실제 예보의 브라우저 직접 조회를 확인했습니다. 실제 Pages 게시와 지도 도메인 설정 확인은 수행하지 않았습니다.

## 기존 Python 웹 로컬 실행

**Kakao 키 설정:** `web/config.example.js`를 `web/config.local.js`로 복사하고 JavaScript 키를 넣습니다. `config.local.js`는 gitignore 대상이라 커밋되지 않습니다. 키가 없으면 지도 대신 노선도 대체 화면이 표시됩니다.

프로젝트 루트에서 Python3.12 환경 `.venv/Scripts/python.exe`를 사용합니다. 웹 페이지와 API는 **하나의 프로세스, 5500 포트**로 함께 제공됩니다(Live Server 불필요). 먼저 5500의 기존 서버를 확인하고 중복 기동하지 마세요.

```powershell
Get-NetTCPConnection -LocalPort 5500 -State Listen -ErrorAction SilentlyContinue
.venv/Scripts/python.exe prediction_api.py --port 5500
```

페이지: [127.0.0.1:5500/web/index.html](http://127.0.0.1:5500/web/index.html). API(`/api/*`)는 같은 주소·같은 출처로 동작해 CORS가 필요 없습니다. `web/` 폴더의 파일만 정적으로 제공하며 `.env`, `outputs/`, 원본 `data/`는 제공하지 않습니다. 정적 소스만 수정했으면 브라우저를 새로고침하고, 역 좌표를 수정했으면 API 프로세스도 재시작하세요. 공개배포·ONNX·브라우저 직접 joblib 추론은 구현하지 않았습니다.

정적 파일 `web/data/station_profile.json`(실제 평균 승하차)은 `.venv/Scripts/python.exe scripts/build_web_station_profile.py`로 다시 만들 수 있습니다(원본 `data/processed/subway/`는 읽기만 합니다).

## 문서

- [인수인계·확정요구·백업·남은일](docs/HANDOFF.md), [로드맵](ROADMAP.md)
- [방법론](docs/AI/METHODOLOGY.md), [모델 개요](docs/AI/MODEL.md), [웹 연결](docs/AI/WEB_INTEGRATION_DESIGN.md)
- [추출기](docs/AI/EXTRACT_TRAIN_LOADS.md), [승하차](docs/AI/SUBWAY.md), [날씨](docs/AI/WEATHER.md), [POI](docs/AI/POI_COLLECTION_TASK.md)
- [항저우 태그 시간표 복원 지침](docs/AI/HANGZHOU_TIMETABLE_BRIEF.md)(진행 중단, [E-22](docs/EXPERIMENTS.md)), [재차인원 역산 실행 지침서](docs/AI/LOAD_ESTIMATION_RUNBOOK.md)
- [가정](docs/ASSUMPTIONS.md), [결정](docs/DECISIONS.md), [실패 기록](docs/FAILURES.md), [시도·실험 기록](docs/EXPERIMENTS.md)

지도는Kakao이고 `best_model.pt`는 이전모델입니다. `.env`의 키값을 출력하거나 문서·로그에 복사하지 마세요.
