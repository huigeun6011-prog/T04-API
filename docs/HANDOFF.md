# 다음 AI를 위한 인수인계

기준: 2026-11-18. 이 문서를 먼저 읽고 [README](../README.md), [방법론](AI/METHODOLOGY.md), 필요한 상세 보고서를 읽는다. **실험·재학습·모델 교체·웹 수정은 사용자 지시가 있을 때만 한다.** 진행 중인 작업, 완료 기록, 다음 후보는 [ROADMAP](../ROADMAP.md)에, 시도·실험 전체와 실패 이유는 [EXPERIMENTS](EXPERIMENTS.md)에 있다.

## 1. 목표와 확정한 요구

- 대전 1호선으로 이동할 때 덜 붐비는 시간·이용 역·목적지를 추천한다. 모델은 장소 자체의 방문객 수를 예측하지 않는다.
- 지도는 Kakao Maps, 주소 좌표 변환은 VWorld다. `best_model.pt`는 이전 모델이고 공식 추론 파일은 `outputs/load_predictor.joblib`이다.
- 실제 POI와 Open-Meteo 날씨를 사용한다. 날짜 선택 시 시간별 날씨를 조회하고 캐시·호출 간격으로 중복 호출을 줄인다.
- 사용자가 출발점·운행일·시간 범위·카테고리·한산함/거리 비중을 고른다. 비중은 10% 단위다. 각 시간 h는 h:00~h+1:00 구간이다.
- 전체 재학습 범위는 **2024-11-01 05시~2026-11-02 00시 버킷**이다. 운행일로는 2024-11-01~2026-11-01, 731일이다. 마지막 00시 버킷은 00:00~00:59에 해당하며 00:00 한 순간을 뜻하지 않는다.
- 출발 승차 전 0은 고정한다. 종점 0·음수 억제는 **soft penalty**로 유지한다. 종점 0을 강제로 맞췄다는 사실을 물리적 성공으로 해석하지 않는다.
- 실제 피크 사례는 validation only다. 학습 라벨·손실 가중치·튜닝 근거로 쓰지 않는다. 시간표 미매칭 1건은 사용자가 이번 비교에서 무시하도록 했다.
- 축제 등 비정규 운행일을 제외하자는 기존 요구가 있지만 **제외 목록 확정·실제 학습 제외는 아직 하지 않았다**. 잔차만 보고 임의로 날을 지우지 않는다.
- 사용자는 메인 AI가 지휘하고 작업은 다른 에이전트에게 맡기길 원한다. 기존 에이전트를 재활용하고 완료·중요 결과를 root에게 직접 보고한다. 사용자는 작업 중 root와 계속 대화할 수 있어야 한다.
- `.env`, API 키 값은 출력·문서화·프런트 전달하지 않는다. 과거 키 노출 후 사용자가 재발급했다. 키 이름과 설정 여부만 다룬다.

## 2. 시간표 a/b/c/d의 출처: 미확인으로 남겨두지 말 것

모두 `data/raw/subway_time/`에 있다. raw라는 폴더명만 보고 모든 파일이 무가공 다운로드라고 판단하지 않는다.

| 파일 | 사용자 설명과 실제 역할 |
|---|---|
| (a) `260330_대전1호선_평일시간표_공식대조수정.xlsx` | 공식 홈페이지에서 추출한 평일 운행계획. 역·시각·방향별 열차가 오는 시각이다. |
| (b) `대전교통공사_열차운행 상황 및 시각표_20250930.csv` | data.go.kr 시간표에 사용자가 일부 누락 추정 시각을 추가했다. 이유는 [ASSUMPTIONS A-001](ASSUMPTIONS.md). |
| (c) `대전교통공사_열차운행 상황 및 시각표_20260330.csv` | (a)를 (b)와 같은 5열 형식으로 바꾼 결과. 기존 CSV 처리 코드를 재사용하려는 목적이다. |
| (d) `대전교통공사_열차 혼잡도 분석_20261031.csv` | 실제 피크 시간 일부의 재차인원·혼잡도 20사례. 전체 열차 정답이 아니며 사후 비교 자료다. |

`time_xlsx_to_csv.py`가 (a)→(c)를 만든다. 현재 이 스크립트의 상대경로는 `scripts/data_prep/` 작업 디렉터리를 기준으로 한다. `subway_time_to_json.py`는 이제 `--input`, `--output` 인자를 받는다. 기존에는 공통 이름 `subway_time.json`을 출력했고 **사용자가 버전 구분용 날짜를 붙였다**.

두 CSV를 같은 변환기로 다시 만든 JSON과 현재 날짜별 JSON을 대조한 결과 **20250930은 460열차, 20260330은 242열차이며 JSON 전체가 각각 정확히 일치했다**. 현재 생성 경로는 확인된 것이다. 검사용 파일은 `outputs/timetable_check_20250930.json`, `outputs/timetable_check_20260330.json`이다. CSV 연결은 1~4분 인접역 연결 및 종착역 보간이라는 가정이 남으며, 이 대조가 실운행까지 입증하지는 않는다.

운행일이 2026-03-30 이후이고 평일이면 20260330 시간표, 그 외에는 20250930 시간표를 사용한다. 개편 후 휴일도 이전 휴일표로 폴백한다. 미래 평일에는 이후 표를 쓰지만 미래 휴일 폴백은 현재도 남아 있다.

## 3. 달력 날짜와 운행일

승하차 API는 실제 달력 날짜 기준이다. 23:50 출발 열차가 다음 날00:10까지 운행하므로 재차인원 궤적은 운행일을 따라 연속으로 계산한다.

| 요청/입력 | 모델·시간표 날짜 | 날씨/승하차 실제 날짜 |
|---|---|---|
| D일05~23시 | D 운행일, 해당 hour | D일 해당 시각 |
| D 운행일24시 | D 운행일, hour=24 | D+1일00시 |
| 달력 D일00시 단일 예측 | D−1 운행일, hour=24 | D일00시 |

요일·휴일·시간표 버전은 운행일을 기준으로 한다. `predict_load.py --hour 0`과 `/api/predict`는 전날24시로 변환한다. 웹 `/api/recommend`는 사용자가 고른 **운행일**과05~24시 범위를 받는다. 01~04시 승하차 자료는 정제 시 제외되어 있고 24시에 합쳐지지 않는다. 과거 AI가 01~04시를24시에 합쳤다고 말한 것은 잘못된 설명이었다.

24시 날씨를 운행일 당일00시에서 가져오던 오류는 수정됐다. 전체 재생성 때 24시18,035행의 날씨가 익일00시와 일치함을 확인했다. 날씨는 GT 최적화 손실에 들어가지 않고 최적화 후 지도학습 피처로 붙는다.

## 4. 지금 API가 읽는 production과 후보를 반드시 구분

### production

- `outputs/ground_truth_train_loads.csv`: 731일, 3,733,691행. 24시 날씨를 고친 뒤 **이전200회 solver**로 만든 라벨이다. 순차 음수 clamp와 종점0 덮어쓰기가 들어 있다.
- `outputs/load_predictor.joblib`: HistGradientBoostingRegressor. API는 이 경로만 읽고 파일 mtime 변경 시 다시 로드한다.
- `outputs/model_metrics.json`: 앞584일(마지막2026-06-07) 학습/뒤147일(2026-06-08~11-01) 검증. MAE20.14196명, RMSE29.41249명, R²0.876645. **추정 라벨 재현 지표**다. 배포 파일은 평가 후 전체731일로 refit했다.
- 피처 순서: `station_idx,hour,dir_code,is_weekend,temp,precip,snow,plan_version`. 상행0/하행1, 역 인덱스 판암0~반석21이다. 현 모델에는 월~일 구분 피처가 없다.
- CSV SHA256: `8a7c1822c2bd2d5cb9d583bd24a390391728b46ee7b74b4d7b7ce9b1484ad5f6` (git 추적 안 함. 다른 곳에서는 이 해시로 같은 파일인지 확인한다.)
- joblib SHA256: `6a1e4ec8e1f66be5c90d865d9ef5e625768d5dcc0835f69fcd82fcc62800467a`
- 기존12일·61,788행 모델/CSV/지표는 `outputs/backup_before_rebuild_20261116_124052/`에 보관했다. 이 백업은24시 날씨 수정 전 자료이므로 검증된 대안으로 오인하지 않는다.

**현재 `generate_ground_truth.py` 기본 구현은 이미 후보 방식으로 바뀌었다. 따라서 현재 기본 명령을 실행해도 production과 동일한 CSV가 재현되지는 않는다.** 이전 solver는 `outputs/diagnostics/gt_solver_before_improvement.py`에 보관했다. 재생성은 별도 출력 경로·백업·검증을 전제로 해야 한다.

### 배분 개선 후보: production에 미적용

`outputs/diagnostics/candidate_training/`에731일 CSV·모델·metrics·전체감사·peak_validation이 있다. [개선 보고서](../outputs/diagnostics/gt_improvement_report.md)가 상세 정본이다.

- 불가능한 방향으로 배분되어 사라지던 인원을 가능한 방향으로 정규화한다. 양쪽 모두 배분 불가능하면 명시 slack으로 남긴다.
- 최대1000회 Adam, 최저손실 iterate 복원, 정체 종료 옵션. 실제 전체731일은 모두1000회까지 실행했다.
- `raw_load`는 승차−하차의 원시 누적값이다. `load=max(raw_load,0)`, `load_correction=load−raw_load`를 명시하며 종점0을 덮어쓰지 않는다. 원시 종점 잔여는 `terminal_raw_residual`에 남긴다.
- 전체 raw 보존식 위반0(허용1.6e−6명). 321,640역시간 셀의 배분+slack=원본 확인, 미설명 오차0.001명 초과0셀. slack은 승차2,716명·하차15,184명이다.
- 원시 음수105,609행, 최소−775.31명. 종점 잔여 절댓값95%44.88명·최대3,127.19명이다. **원시 보존식이 맞는 것과 물리적으로 타당한 인원이 나오는 것은 다르다.**
- 후보 holdout MAE21.93854, RMSE31.80450, R²0.859286. 라벨 정의가 달라 production 지표와 단순 비교하지 않는다. 실제 정확도 개선이 확보되지 않아 배포하지 않았다.

production 전체 감사에서도 저장 load≥0·종점0은 만족했지만 보존식은187,731행에서 깨졌다(허용0.015명). 종점0 덮어쓰기 전 양수 잔여93,943열차·최대380.66명, 비종점 clamp17,006행이었다. soft penalty가 물리 제약을 만족시켰다고 주장하면 안 된다.

## 5. 수렴 진단과 세 가정 실험

[수렴 결과](../outputs/diagnostics/gt_convergence.json): 대표6일×200/500/1000회 및 초기값2종. 200→1000회 손실이4.47~14.17% 줄지만 종점·음수 위반이 남았다. 반복수만 늘려 해결됐다고 판단하지 않았다.

[3가정 보고서](../outputs/diagnostics/assumption_ablation/report.md): 동일6일×기본/시간정규화/동요일pooling/승차headway/전부×초기값2종×1000회, 총60회·약115초. 구성·seed·template source hash·평가일을 저장했다.

- 시간정규화: p/q 인접 차이에 Huber soft penalty. 큰 출퇴근 변화 허용, 강제 평탄화하지 않는다.
- 동요일 pooling: 월~일7종+명시 공휴일 별도, 시간표버전 분리. 과거112일·동일그룹만 사용, 평가6일 전체 제외. 최소2일, confidence=n/(n+4). 미래/평가일 값을 바꿔도 template 불변 검사를 통과했다. template 자체도 기존 추정 비율의 평균으로 실측값이 아니다.
- headway: **승차만** 직전 시간표 출발~이번 출발 구간에 비례시킨다. 시간 내 균등 입장을 가정하며 실제 대기시간 관측이 아니다. 첫차는05시부터, 시간 경계를 넘은 승차는 `boarding_sources`로 원본 시간별 기록, 마지막 운행 후 입장 가정량은 slack. 하차에 같은 가정을 적용하지 않았다.
- 정상5일 평균 종점MSE: 기본539.62/시간정규화541.72/pooling541.91/headway1107.80/전부1147.53. 음수MSE: 기본12.14/전부53.10.
- 시간정규화는 인접 변화량26.3% 감소, pooling은 template 거리45.3% 감소. 다만 물리 잔차가 전반 개선됐다는 뜻은 아니다. 전부 적용은 평일3일 악화·토요일2일 개선이다.
- 자정 이상 가능일의 잔차 감소는 마지막차 이후 균등입장 가정상 slack 증가가 크게 설명한다. 실제 운행·실제 인원 개선 증거가 아니다.
- 변수는 계속 하루800개(731일584,800개)다. 부분공유를 넣었다고 일별 변수가 없어지지 않는다. 1000회 중앙 실행시간 기본1.67초/전부2.25초였다.
- 세 가정은 코드 옵션으로 구현했지만 기본 활성화·전체 all 재학습·production 교체는 하지 않았다. **baseline 대비 smooth+pooling 두 개만 묶은 실험과 가중치 탐색은 아직 안 했다.** 다음 권고안일 뿐 실행 승인으로 간주하지 않는다.

### 열차 단위 OD 후보 (E-13~E-20, production 미적용)

헤드웨이·정원·도착률 곡선은 실패했고(E-13, E-15), 열차 단위 OD 변수(E-16)가 피크 추정/실제를 0.51→0.62로 올린 가장 나은 후보다. 열차별 재차는 합계만으로 식별되지 않고(E-17), 열차 계수 w_k는 조건부로만 복원된다(E-18~19). 61일 표본 점검(E-20)에서 추천 상위10 겹침 0.76, 피크 19건 MAE 322(production 376)였고 합성 정답에서 순위는 잘 복원하나 수준은 prior에 좌우됐다. 사용자는 2026-11-17에 Step 4의 A(교체 안 함)·B(731일 재생성)를 모두 고르지 않고 보류했다. **production은 그대로다.** 상세는 [EXPERIMENTS](EXPERIMENTS.md), 진행·다음 후보는 [ROADMAP](../ROADMAP.md).

## 6. 실제 피크와 정확도 해석

(d)20사례 중 출발역·시각·방향·운행일·최고혼잡역으로19건을 연결했다. 2026-08-18 하행1171열차는 시간표 미매칭이며 사용자가 이번 비교에서 무시하도록 했다. 임의로 다른 열차에 맞추지 않는다.

- production 모델MAE375.99명, 라벨MAE312.52명.
- 배분 개선 후보 모델MAE374.45명, 라벨MAE324.88명.
- 선택된 극단 사례이고 전체 학습기간의 날짜도 포함하므로 일반적인 독립 holdout 정확도가 아니다. 모두 과소추정하는 큰 괴리가 남았다.
- 실제 재차인원의 **출발 전/후 측정 정의는 공식적으로 확인되지 않았다**. 사용자는 우선 출발 후 값으로 보고 작업하자고 했다. 이 작업 가정을 실측 정의 확정으로 쓰지 않는다.
- 모델의 실제 정확도, 운영시간별 추천 순위의 타당성, 장소 한적함은 확보되지 않았다. 물리 loss·추정 라벨 MAE가 좋아져도 이 결론은 바뀌지 않는다.

## 7. 웹 구현과 중요한 미해결 항목

웹 변경 이력은 [DECISIONS](DECISIONS.md) D-010~D-026, 현재 코드 설명과 검증 구분은 [웹 연결](AI/WEB_INTEGRATION_DESIGN.md)이 정본이다. 아래는 `web/`과 `prediction_api.py`를 직접 읽어 확인한 상태다.

- POI 파일은 548곳(532개 좌표)이며 좌표 없는 산책로 11곳은 텍스트로 표시한다. 역 22개 좌표는 사용자가 직접 제공한 WGS84 좌표다. 브라우저와 API는 `web/app.js`의 `STATIONS`를 공유하고 API는 시작 때 값을 읽으므로 좌표 변경 뒤에는 재시작이 필요하다.
- `prediction_api.py`는 표준 `ThreadingHTTPServer`로 기본 포트 5500에서 웹과 API를 함께 제공한다. 경로는 `GET /api/health`, `/api/stations`, `/api/predict`, `/api/profile`, `POST /api/recommend`다. FastAPI/ONNX는 사용하지 않는다.
- 추천은 Open-Meteo 날씨, 시간표, `outputs/load_predictor.joblib`, POI와 출발지 좌표를 사용한다. 한산함/거리 비중은 10% 단위다. 도보는 직선거리 기반 추정이며 실제 보행 경로·운영시간은 없다. 열차 ETA는 걷기와 열차 이동만 포함하고 대기·환승은 포함하지 않는다. API 성공이 추천 효용이나 실제 승객 수 정확도를 증명하지 않는다.
- UI는 시간 막대, 가까운 곳/지하철로 멀리 탭, 걷는 시간 합계 한도, 분석·모델 소개 화면을 제공한다. 막대 조작은 서버 재순위 없이 선택 장소의 시간 표시를 바꾼다. 도보 전용 장소 자체에는 재차인원이 없으며, 해당 화면의 비교 막대는 현재 탭의 지하철 후보 값임을 구분한다. 이 막대·선택 시각·창 크기/이동 변경은 코드에서 확인했으나 최근 수정 후 브라우저 시각 확인은 하지 않았다.
- 지도 선로 자료는 OSM 양방향 관계에서 뽑은 42개 구간이며, 곡선 끝점을 사용자 제공 역 좌표에 맞췄다. 코드상 22개 역과 구간 끝점 연결은 확인했다. 최근 좌표 보정 후 지도 정합, 터치·모바일 최종 확인은 미완료다. D-015~D-020에는 그 당시 핀·카드·패널·시간 막대·탭 등의 브라우저 확인 기록이 있으므로 최근 변경 검증과 혼동하지 않는다.
- `prediction_api.py` 254·285행의 `dict(**base, walking_distance_km=...)`는 중복 키워드가 있으면 예외가 나 추천이 400으로 실패할 수 있어, 사용자가 `dict(base, walking_distance_km=...)`로 고쳤다(D-026). 현재 수정된 코드 형태를 확인했다.
- `extract_train_loads.py`의 출력 종점 0 보정은 개선 GT의 raw 잔차 정책과 다르며, 이를 raw 물리 검증으로 간주하지 않는다.
- SVG는 자료 흐름 설명용이며 현행 웹 배포 상태의 정본은 아니다.

## 8. 실행 환경과 상태 확인

프로젝트 루트에서 `.venv/Scripts/python.exe`를 쓴다. 기본 시스템 Python3.15에는 torch가 없어 Python3.12 환경을 만들었다. production metadata 당시 Python3.12.16, torch2.15.0+cpu, scikit-learn1.9.1이다. 완전한 의존성 lockfile은 아직 없다.

```powershell
# 먼저 포트 상태를 확인한다. 이미 실행된 서버를 중복 시작하지 않는다.
Get-NetTCPConnection -LocalPort 5500 -State Listen -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:5500/api/health

# 없을 때 시작 (웹 페이지 + API를 5500 한 포트로 제공)
.venv/Scripts/python.exe prediction_api.py --port 5500
```

페이지는 `http://127.0.0.1:5500/web/index.html`이고 API도 같은 5500(`/api/*`, 같은 출처)이다. `web/` 아래 파일만 GET/HEAD로 정적 제공하고 그 밖(`.env`, `outputs/`, `data/` 등)은 404이다. 예전 2포트 방식(Live Server 5500 + API 8000, `--port 8000`)을 쓰려면 `web/config.local.js` 등에서 `window.RECOMMENDATION_API_BASE = 'http://127.0.0.1:8000'`을 지정하면 되고, CORS는 5500의 localhost/127.0.0.1을 허용한다. 미리보기 도구용 설정은 `.claude/launch.json`(이름 `app`)이다. 현재 프로세스가 실행 중이라는 상태는 시간이 지나면 바뀌므로 이 문서만 보고 가정하지 않는다. 재시작은 해당 서버 터미널에서 종료한 후 같은 명령으로 한다.

## 9. 파일 안내

경로는 프로젝트 루트 기준이다. 루트에는 `prediction_api.py`, `predict_load.py`, `extract_train_loads.py`, `train_predict_model.py`, `train_load_model.py`가 있다.

| 경로 | 역할 |
|---|---|
| `scripts/utils/collect_data.py`, `collect_weather.py` | 원본 승하차/과거날씨 수집. 기존 자료를 재수집할 필요 없음. |
| `scripts/data_prep/process_subway.py` | XML→역별 JSON,01~04시 제거. |
| `scripts/data_prep/time_xlsx_to_csv.py`, `subway_time_to_json.py` | 공식엑셀→CSV→열차별 JSON. |
| `scripts/data_prep/generate_ground_truth.py`, `gt_assumptions.py` | 개선후보 GT,선택적3가정,raw/slack 기록. |
| `train_predict_model.py`(루트) | HGB 지도학습,날짜holdout후전체refit,별도후보출력지원. |
| `scripts/data_prep/diagnose_gt_convergence.py`, `compare_gt_improvement.py`, `experiment_gt_assumptions.py`, `validate_gt_dataset.py` | 수렴/배분개선/3가정/보존식 감사. |
| `scripts/data_prep/evaluate_peak_cases.py` | 레시피고정후실제피크사후검증.튜닝용아님. |
| `predict_load.py`, `prediction_api.py`, `extract_train_loads.py`(모두 루트) | 단일예측/웹API/파일추출. |
| `scripts/collect_poi_once.py`, `scripts/build_web_poi.py`, `scripts/build_web_station_profile.py` | POI수집→웹JSON, 실제 평균 승하차→`web/data/station_profile.json`. |
| `train_load_model.py`(루트), `outputs/best_model.pt` | 이전PyTorch예측모델.현공식HGB와혼용금지. |
| `scripts/data_prep/gen_station_hourly.py` | 이전모델용역시간열차수.현GT는시간표에서직접셈. |
| `scripts/data_prep/diagnose_feasibility_bound.py` | 실제피크 실현가능성 상한 진단(진단전용, 2026-11-16, E-12). |
| `scripts/data_prep/gt_queue_model.py`, `experiment_queue_model.py`, `validate_queue_peaks.py` | 대기열·정원 모델(E-13, 폐기). |
| `scripts/data_prep/gt_od_prior.py`, `experiment_od_prior.py`, `validate_od_prior_peaks.py` | 방향 prior(E-14, 폐기·진단용). |
| `scripts/data_prep/gt_arrival_curve.py`, `experiment_arrival_curve.py`, `validate_arrival_curve_peaks.py`, `diagnose_headway_mass.py`, `diagnose_headway_transplant.py` | 연속 도착률 곡선·headway 진단(E-15). |
| `scripts/data_prep/gt_train_od.py`, `experiment_train_od.py`, `validate_train_od_peaks.py`, `lp_bounds_train_od.py` | 열차 단위 OD 변수(E-16)와 LP 가능 범위(E-17). 후보 보류. |
| `scripts/data_prep/gt_train_factor.py`, `gt_train_factor_v2.py`, `experiment_train_factor_synth.py`, `experiment_train_factor_v2.py` | 열차 계수 합성 복원(E-18, E-19). |
| `scripts/data_prep/make_od_labels.py`, `compare_od_vs_production_recommend.py`, `experiment_synthetic_od.py` | OD 라벨 생성·조립기, 추천 민감도 비교, 합성 정답 복원(E-20). 실행 절차는 [LOAD_ESTIMATION_RUNBOOK](AI/LOAD_ESTIMATION_RUNBOOK.md). |
| `scripts/hangzhou/`(+`LINE_C_PROTOCOL.md`), `outputs/hangzhou/`, `data/external/hangzhou/`(gitignore) | 항저우 태그 자료 시간표 복원 시도(E-22). §11 참고. |
| `design/` | 항저우 노선도 시각화(`hangzhou_network.html`, `hangzhou_overlay.html`, `gen_network.js`)와 웹 디자인 프로토타입(`prototype_ab.html`, D-018). 현상태의 정본이 아니다. |
| `scripts/analysis/` | 독립분석/과거실험.미참조가미실행증거는아님. |

## 10. 다음 AI가 먼저 할 일

1. 현재 사용자 지시가 무엇인지 확인하고, 진행 중인 작업과 완료 기록은 [ROADMAP](../ROADMAP.md)에서 먼저 본다. 새 실험·재학습은 사용자 지시가 있을 때만 한다. 이전 에이전트의 맥락은 세션 밖으로 이어지지 않으므로 새로 시킬 때는 이 문서와 ROADMAP을 읽히고 시작한다.
2. 다음 작업 승인 시 production/candidate 경로·원시측정정의·마커-실제역사 정합 및 터치/모바일 미검증(§7)·비정규운행일 제외 미실행을 먼저 기억한다.
3. 제안된 smooth+pool 조합이나 가중치 탐색은 별도 실험이다. 실제피크값으로 맞추지 않고 같은 연산예산·누수없는 날짜검증을 유지한다.
4. 모델을 바꾸려면 별도후보생성→원시보존/물리잔차/날짜검증→한계보고를 거친다. 낮은 내부loss만으로production교체나실제정확도완료를 선언하지 않는다.
5. 과거 문서를 근거로60000행·12일·더미웹·JSON변환미확인·물리제약충족·Naver·ONNX완료로 되돌리지 않는다.

## 11. 항저우 태그 자료 시간표 복원 (E-22, E-23, 2026-11-18, 보류)

**진행 상태: 보류 ([D-022](DECISIONS.md)).** 사용자가 제공한 항저우 지하철 카드 태그(2019-01, `data/external/hangzhou/`, gitignore)에서 열차 도착시각을 복원해 OD 역산을 실제 태그로 시험할 전 단계를 시도했다. 지침은 [HANGZHOU_TIMETABLE_BRIEF](AI/HANGZHOU_TIMETABLE_BRIEF.md)(자료 구성 포함), C선 실행 기준은 `scripts/hangzhou/LINE_C_PROTOCOL.md`, 결과는 `outputs/hangzhou/`다. 시간표와 열차별 재차 정답이 없고 노선 A/B/C가 실제 어느 호선인지는 확인되지 않았다. 대전 production·웹과 무관하다.

- 어디까지: C선 1/08만. (E-22) 피크 연결 방식은 후보 1,200개 중 양끝 2역 이내 17.42%(기준 ≥60%), 1~2역 조각 53.00%(기준 ≤5%)로 조각화 관문 실패. (E-23) shift-and-stack 방식은 후보 439개, 양끝 2역 이내 45.33%(미통과), 조각 0.00%(통과), 숨긴 역 재현율 82.3%(대조 31.2%). 수치는 보고서 기준이다. 1/15는 열지 않았고 시간표는 발행하지 않았다.
- 왜 바꾸나: 공식 시간표가 없어 평가가 같은 날 태그 안의 내부 일관성에 머물고, 산출은 모든 열차가 전 역을 운행한다는 가정이며 열차별 실제 출발점·종점·정차역(회차·단축 포함)은 관측되지 않았고, 그 위의 재차인원은 순환 위험이 있으며, 사전 관문 지표는 귀무도 25~41%라 변별력이 낮았다(E-23). 사용자의 목표는 시간표가 아니라 해당 일자 모든 열차의 출발점·종점·정차역이다.
- 사용자 결정: C선만 진행([D-021](DECISIONS.md), 분석 일자·규칙 고정은 불필요). 항저우 추가 작업(1/15 독립 검증 등)은 보류하고 열차 단위 공식 시간표와 개인별 태그(또는 열차별 재차 실측)를 가진 공개 자료를 조사한다(D-022, 조사 결과는 아직 없음). 보류이지 폐기가 아니다.
- 후속(E-24~E-27, 파일 기준): 사용자 결정(2026-11-18)으로 C선만 보고(분기 Y자 없음) 1/01~25 전부 사용·과적합 허용·평일/주말 별도 풀링한다. 도메인 제약은 관측 = 계획 + 지연(≥0)이다. 환승 제외 입장 태그 검증은 사전 기준 미통과(E-24), 풀링 + 역별 랙으로 창 안 92.6%·방향 일치 71.9%(E-25, 랙 5분위 때문에 음수 대기 5%는 해석하지 않음), pool2 수정으로 가짜 열차 0·공백 0, 열차 430개, 양끝 2역 이내 85.1%(E-26), 단축·회차는 증거 없음이나 양성 대조 미실시(E-27). 산출은 `outputs/hangzhou/lineC_direct_check/`, `lineC_pool/`, `lineC_pool2/`, `lineC_struct/`.
- E-28~E-29(파일 기준): pool3(놓친 열차 채우기)로 열차 440개, 07~09시 34/66 배차 비 1.43→1.02, 양끝 2역 이내 83.9%, 방향 일치 66.9%이며 사용자가 pool3를 최종 시간표 후보로 채택했다(채운 열차 10개는 낮은 문턱 후보, 실제 열차 확정 아님). 05~07시와 34번 방향 19~23:30시는 못 채웠다. 양성 대조에서 현재 단축 진단 규칙(E1 필수)은 심은 단축을 한 번도 '지원'하지 못해 기준 미충족이고 가짜 지원은 0이었다. 따라서 기존 "반박 20/22칸"은 혼잡시간대 중·후반 구간에서 10~25% 이상 단축을 배제하는 정도로만 신뢰하고, 알 수 없음 칸은 단축 여부에 대해 말해 주지 않는다. 산출은 `outputs/hangzhou/lineC_pool3/`, `lineC_pos/`.
- E-30~E-31(파일 기준): E1 필수를 뺀 새 종합 규칙(E3 absent ≥0.15 또는 E2 supportive)은 평일 혼잡시간대 f=25·50% 단축을 모든 시나리오에서 검출했고(f=10%는 V1 p=18·23만 기준 초과), 가짜 지원은 0이었다. 심지 않은 데이터 60칸은 반박 44·알 수 없음 4·미확인 12(05~07시)·지원 0이며, 반박 44칸 중 12칸만 검출 시험을 거쳤고 32칸(구간 p 이전, 낮 9~17시, 19~23:30시)은 검출력 미확인이다. 최종 시간표 후보는 `outputs/hangzhou/lineC_final/candidate_arrival_events_final.csv`(평일, 440열차, 14,080행, imputed 20)이고 분석 구간(열차당 하차 일평균 중앙값 ≥350, 사용자 확정) 밖인 05~07시 열차 37개는 삭제하지 않고 low_signal로 표시했다. `structure_status`의 반박은 전 구간 운행과 모순 없다는 뜻이지 전 열차가 끝까지 갔다는 확정이 아니다.
- **궁극 목표 상태:** 목표(해당 일자 모든 열차의 출발점·종점·정차역, 단축·회차 포함)는 평일 기준 전 구간 운행 가정과 모순 없는 시간표 후보까지이고, 혼잡시간대 중·후반 구간에서 10~25% 이상 단축은 없다는 증거까지만 있다. 공식 시간표와의 비교, 05~07시·낮·저녁 구조, 열차 한 대 단위 판정은 얻지 못했다.
- E-32~E-33(파일 기준): 반박 칸 검출 시험에서 f=25·50% 단축은 모든 시간대·위치·변형에서 검출(종합 지원 1.0), f=10%는 낮 p=23 V1만 기준 초과, 가짜 지원 0. 시험한 반박 칸은 12→37칸이고 구간 0의 7칸은 미시험이다. 각 칸의 반박은 25% 이상(일부 10% 이상) 단축을 배제하는 정도로만 신뢰한다. 주말 최종 시간표 `candidate_arrival_events_final_weekend.csv`(7일, 491열차, 15,712행): 양끝 2역 이내 70.9%, 창 안 93.1%, 방향 일치 66.8%, 600초 초과 공백 0. 주말은 단축 진단을 하지 않았고 `low_signal`·`structure_status`가 문자열 '미확인', `refuted_share_cell`은 비어 있다(파서 주의). 방향 비대칭(05~07시 0.80, 19~23:30시 0.83)과 주말 낮 배차가 평일보다 짧은 점(약 240초 대 286~290초)은 확인하지 못했다.
- 사용자 결정(2026-11-18): 구간 0 반박 7칸 시험, 주말 단축 진단, 주말 비대칭 채우기, 1/01 제외 재생성은 하지 않는다. 열차별 정답 재차인원 구성과 OD 역산 q 민감도 시험은 방향 메모만 작성했고(미실행) 별도 에이전트와 사용자 승인을 기다린다: [HANGZHOU_OD_TEST_BRIEF](AI/HANGZHOU_OD_TEST_BRIEF.md).
