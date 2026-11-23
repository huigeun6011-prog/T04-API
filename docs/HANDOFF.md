# 다음 AI를 위한 인수인계

기준: 2026-11-23. 이 문서를 먼저 읽고 [README](../README.md), [방법론](AI/METHODOLOGY.md), 필요한 상세 보고서를 읽는다. **실험·재학습·모델 교체·웹 수정은 사용자 지시가 있을 때만 한다.** 진행 중인 작업, 완료 기록, 다음 후보는 [ROADMAP](../ROADMAP.md)에, 시도·실험 전체와 실패 이유는 [EXPERIMENTS](EXPERIMENTS.md)에 있다.

## 1. 목표와 확정한 요구

- **정적 웹(D-030)·T04 공개 구성(D-031):** 완료됐다. 경위·검증은 [D-030](DECISIONS.md), [D-031](DECISIONS.md), [ROADMAP 완료 기록](../ROADMAP.md), 실행은 [README](../README.md)를 본다. 정적 웹 운영에 Python API·YML·재학습은 필요 없고 원본 `web/`·Python 파일은 보존돼 있다.

- 대전 1호선으로 이동할 때 덜 붐비는 시간·이용 역·목적지를 추천한다. 모델은 장소 자체의 방문객 수를 예측하지 않는다.
- 지도는 Kakao Maps(기존 `web/`은 JS SDK, 정적 웹은 `worker/`의 REST 이미지 프록시), 주소 좌표 변환은 VWorld다. `best_model.pt`는 이전 모델이고 공식 추론 파일은 `outputs/load_predictor.joblib`이다.
- 실제 POI와 Open-Meteo 날씨를 사용한다. 날짜 선택 시 시간별 날씨를 조회하고 캐시·호출 간격으로 중복 호출을 줄인다.
- 사용자가 출발점·운행일·시간 범위·카테고리를 고른다(한산함/거리 비중 슬라이더는 D-028로 제거). 웹은 재차인원 수치·건수를 보이지 않고 같은 구간(승차역→하차역, 방향)의 시간대 상대 순위(1..N, 순위 차 2 이하는 같은 수준)만 보인다([D-028](DECISIONS.md)). 각 시간 h는 h:00~h+1:00 구간이다.
- 전체 재학습 범위는 **2024-11-01 05시~2026-11-02 00시 버킷**이다. 운행일로는 2024-11-01~2026-11-01, 731일이다. 마지막 00시 버킷은 00:00~00:59에 해당하며 00:00 한 순간을 뜻하지 않는다.
- 출발 승차 전 0은 고정한다. 종점 0·음수 억제는 **soft penalty**로 유지한다. 종점 0을 강제로 맞췄다는 사실을 물리적 성공으로 해석하지 않는다.
- 실제 피크 사례는 validation only다. 학습 라벨·손실 가중치·튜닝 근거로 쓰지 않는다. 시간표 미매칭 1건은 사용자가 이번 비교에서 무시하도록 했다.
- 축제 등 비정규 운행일을 제외하자는 기존 요구가 있지만 **제외 목록 확정·실제 학습 제외는 아직 하지 않았다**. 잔차만 보고 임의로 날을 지우지 않는다.
- 사용자는 메인 AI가 지휘하고 작업은 다른 에이전트에게 맡기길 원한다. 기존 에이전트를 재활용하고 완료·중요 결과를 root에게 직접 보고한다. 사용자는 작업 중 root와 계속 대화할 수 있어야 한다.
- 새로 알게 된 사실은 가장 알맞은 기존 문서에 적고, 맞는 문서가 없으면 사용자에게 기록하지 못한 내용을 알린다.
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

### production (2026-11-19부터: 열차 단위 OD 라벨 61일 기반, [D-027](DECISIONS.md))

- **라벨:** 열차 단위 OD 방법(`gt_train_od`, 균일 기준 q, λ=0.01, L-BFGS-B)으로 만든 61일(2024-11-01부터 12일 간격, `outputs/diagnostics/od_labels/sample61/sample_dates.json`, 휴일 18일). 보존식·종점 0·비음수가 구조로 성립한다(종점 재차 최대 2.2e-13, 61일 모두 수렴). 승하차 합계 오차는 적격 셀 L1 최대 0.67%의 소프트 제약이다.
- **재현:** `python scripts/data_prep/make_od_labels.py --dates <sample_dates.json의 날짜> --out-dir outputs/diagnostics/od_labels/sample61 --lam 0.01 --workers 3`(61일, 약 15분) 후 `--assemble`, `python train_predict_model.py --dataset outputs/diagnostics/od_labels/sample61/dataset.csv --model-output outputs/load_predictor.joblib --metrics-output outputs/model_metrics.json`. 라벨 CSV(`labels/`, `dataset.csv`)는 git에 없다.
- `outputs/load_predictor.joblib`: HistGradientBoostingRegressor(OD 라벨 61일로 앞 80% 학습/뒤 20% 검증 후 전체 refit). SHA256 `aca76083a67ab748c1a304f9f98cdc07e31926358376e928153bff768dfbc9d2`. 피처 순서와 API 계약은 이전과 같다.
- `outputs/model_metrics.json`: 검증 MAE 23.94, RMSE 34.37, R² 0.838(2026-05-31~10-22 검증). **라벨 정의가 달라 이전 production 지표(MAE 20.14)와 비교하지 않는다.** 추정 라벨 재현 지표일 뿐 실제 승객 정확도가 아니다. 이전 production 해시와 라벨 방식도 이 파일에 적었다.
- `dataset.csv` SHA256 `ebd67c595a3d78b8d43e907a6171e4cfddef8139461fc9b6e36a58c0fa922682`(git 추적 안 함).
- **근거(E-34~E-38):** 항저우 C선 실제 승객 태그로 만든 정답 대비, OD는 같은 역·방향의 시간대 순서에서 Adam보다 일관되게 낫다(새 평일 4일 사전 고정 확인: 순서 상관 0.957 대 0.775, 2칸 이내 93% 대 69%, 단순 방법 0.58~0.62). 대전 피크 19건에서도 소폭 낫다(MAE 322 대 376). 표본 크기 점검에서 122일 라벨이 61일보다 낫지 않았다(731일 재생성 불필요).
- **알려진 한계(반드시 읽을 것):** (1) 절대 인원 수(수준)는 기준 분포 q가 정하며 두 방법 모두 검증되지 않았다(항저우 균일 q 1.26배 과대, 대전 피크 약 0.5~0.6배 과소). **화면에 절대 인원을 정확한 값으로 보여 주지 않는다.** (2) 열차 한 대 단위 구분은 복원되지 않았다(시간대 평균 오라클 수준). (3) 시간대 순서 개선은 항저우 C선 한정이고 대전 정답은 피크 19건뿐이다. (4) 추천 결과가 이전과 달라진다(예: 시청 출발 7~9시 상위가 9시대에서 7시대로 바뀜).
- **되돌리기:** 이전 production 파일(joblib SHA256 `6a1e4ec8e1f66be5c90d865d9ef5e625768d5dcc0835f69fcd82fcc62800467a`, metrics SHA256 `251d2da8f1cf08db3737660a0cf31deea8f4ceeefd00df197e2b48e9381b897d`)은 `outputs/backup_before_od_swap_20261119/`에 있고(git에는 올리지 않음, `SHA256.txt` 포함) git 이력에도 있다. 교체 커밋만 `git revert`하면 된다.

### 이전 production (Adam 200회 라벨, 2026-11-19 교체 전; 백업과 git 이력에 있음)

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

### 열차 단위 OD (E-13~E-38)

2026-11-19에 production으로 교체됐다(§4, [D-027](DECISIONS.md)). 시도별 결과·수치는 [EXPERIMENTS](EXPERIMENTS.md), 이후 후보는 [ROADMAP](../ROADMAP.md)에 있다. 2026-11-17 당시 사용자가 Step 4(교체 여부)를 보류했던 경위는 ROADMAP의 지금 진행 중·사용자 결정 항목에 남아 있다.

## 6. 실제 피크와 정확도 해석

(d)20사례 중 출발역·시각·방향·운행일·최고혼잡역으로19건을 연결했다. 2026-08-18 하행1171열차는 시간표 미매칭이며 사용자가 이번 비교에서 무시하도록 했다. 임의로 다른 열차에 맞추지 않는다.

- production 모델MAE375.99명, 라벨MAE312.52명.
- 배분 개선 후보 모델MAE374.45명, 라벨MAE324.88명.
- 선택된 극단 사례이고 전체 학습기간의 날짜도 포함하므로 일반적인 독립 holdout 정확도가 아니다. 모두 과소추정하는 큰 괴리가 남았다.
- 실제 재차인원의 **출발 전/후 측정 정의는 공식적으로 확인되지 않았다**. 사용자는 우선 출발 후 값으로 보고 작업하자고 했다. 이 작업 가정을 실측 정의 확정으로 쓰지 않는다.
- 모델의 실제 정확도, 운영시간별 추천 순위의 타당성, 장소 한적함은 확보되지 않았다. 물리 loss·추정 라벨 MAE가 좋아져도 이 결론은 바뀌지 않는다.

## 7. 웹 구현과 중요한 미해결 항목

- 모델 소개 탭(D-029) 개편은 완료됐다. 결정은 [D-029](DECISIONS.md), 작업·검증 기록은 [ROADMAP](../ROADMAP.md) 완료 기록에 있다.

웹 변경 이력은 [DECISIONS](DECISIONS.md) D-010~D-028, 현재 코드 설명과 검증 구분은 [웹 연결](AI/WEB_INTEGRATION_DESIGN.md)이 정본이다. 아래는 `web/`과 `prediction_api.py`를 직접 읽어 확인한 상태다.

- POI 파일은 548곳(532개 좌표)이며 좌표 없는 산책로 11곳은 텍스트로 표시한다. 역 22개 좌표는 사용자가 직접 제공한 WGS84 좌표다. 브라우저와 API는 `web/app.js`의 `STATIONS`를 공유하고 API는 시작 때 값을 읽으므로 좌표 변경 뒤에는 재시작이 필요하다.
- `prediction_api.py`는 표준 `ThreadingHTTPServer`로 기본 포트 5500에서 웹과 API를 함께 제공한다. 경로는 `GET /api/health`, `/api/stations`, `/api/predict`(웹은 쓰지 않음), `POST /api/recommend`다(`/api/profile`은 D-028로 제거). FastAPI/ONNX는 사용하지 않는다.
- 추천은 Open-Meteo 날씨, 시간표, `outputs/load_predictor.joblib`, POI와 출발지 좌표를 사용한다. 순위는 구간별 시간대 상대 순위이며 `quiet_weight`는 없다(D-028). 도보는 직선거리 기반 추정이며 실제 보행 경로·운영시간은 없다. 열차 ETA는 걷기와 열차 이동만 포함하고 대기·환승은 포함하지 않는다. API 성공이 추천 효용이나 실제 승객 수 정확도를 증명하지 않는다.
- UI(D-028, 2026-11-23): 장소 목록은 직선거리·카테고리·도보 시간으로 정렬하고 인원·건수를 보이지 않는다. 장소를 고르면 구간별 시간대 순위와 행별 순위 히트맵을 보이고, 선택한 시간대는 그 시간 열차 출발 시각을 시간순으로 보인다. 가장 한산한 열차 한 대를 고르지 않으며 '더 나은 시간' 안내와 인접 시간 목록은 없다. 가까운 곳/지하철로 멀리 탭, 걷는 시간 합계 한도, 분석·모델 소개 화면은 유지한다. 도보 전용 장소에는 순위가 없다. 개편 후 브라우저 시각 확인은 하지 않았다(사용자 확인 예정). `scripts/data_prep/compare_od_vs_production_recommend.py`는 응답 필드 제거로 깨져 있다(ROADMAP 9번).
- 저장소의 로컬 `main`은 GitHub `origin`을 추적하고 이전 GitLab은 `old-origin`이다. 승하차 전환 전의 로컬 기준 커밋은 `a351d72`다. 승하차 전환 및 수집 워크플로 삭제는 작업 트리 변경이다. 공개 저장소 이력의 Kakao 키 폐기 상태는 확인하지 않았다([ROADMAP](../ROADMAP.md)의 사용자 결정 참고).
- 지도 선로 자료는 OSM 양방향 관계에서 뽑은 42개 구간이며, 곡선 끝점을 사용자 제공 역 좌표에 맞췄다. 코드상 22개 역과 구간 끝점 연결은 확인했다. 최근 좌표 보정 후 지도 정합, 터치·모바일 최종 확인은 미완료다. D-015~D-020에는 그 당시 핀·카드·패널·시간 막대·탭 등의 브라우저 확인 기록이 있으므로 최근 변경 검증과 혼동하지 않는다.
- 추천 400 오류(중복 키워드)는 수정 완료했다([D-026](DECISIONS.md)).
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

정적 웹은 브라우저에서 계산한다. 로컬에서는 `run_static.bat`으로 정적 파일 서버를 시작한다. 변환·검증 명령은 [README](../README.md)에 있다. T04 Node 테스트는 `node --test scripts/`(Node 22 기준), Worker 테스트는 `worker/`의 `npm test`다.

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
| `static_src/`, `static-web/`, `scripts/build_static_web.py`, `scripts/validate_static_web.py` | 정적 웹 소스, Pages 배포 폴더, 빌더, Python–JS 동등성 검증(D-030). `static-web/data/t04/`에 T04 공개 자산, `daily.json`, `business_days.json`이 있다. |
| `scripts/t04_daily_record.mjs`, `scripts/utils/backfill_subway.py`, `scripts/utils/backfill_weather.py` | 수동 일별 기록, 운행일 이력 생성, 과거 승하차·날씨 백필. §12 참고. |
| `scripts/sync_static_data.mjs`, `run_static.bat`, `.github/workflows/pages.yml` | 공개용 데이터 생성, 로컬 정적 웹 실행, GitHub Pages 배포. |
| `worker/`, `scripts/check_map_proxy.mjs`, `scripts/validate_map_projection.js` | Kakao REST 지도 이미지 프록시 Worker와 정렬 검증 도구. [worker/README](../worker/README.md). |
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

## 12. 외부 과제 요구: ALEPH T04 외부 데이터 모니터링 대시보드 (2026-11-23 정리)

출처는 ALEPH 학생 대시보드(`aleph-omega.vercel.app/cortex?panel=tasks`)의 "과제 4. 외부 데이터 모니터링 대시보드 개발" 안내 카드 1~5와 제출 양식이다(화면을 그대로 읽은 것이며 강사가 따로 알려 준 내용은 반영하지 않았다). 사용자 말에 따르면 이 저장소의 프로젝트는 이 과제를 위해 시작했다(2026-11-23). 계획시간 6~7h, 실제 날짜 2일이며 날짜가 바뀔 때까지 기다리는 시간은 작업시간에 넣지 않는다.

### 현행 구현 2026-11-24

T04의 대상은 Open-Meteo 대전 오늘 예보의 **평균기온**이다. 승하차 정보판 탭을 제거하고 추천 경로의 기존 날씨 접이식 영역에 통합했다. 평균은 KST 00~23시 기온 24개의 산술 평균이며, 같은 시간별 응답으로 최저·최고기온과 강수·적설 합계를 계산한다. 출처 시각은 예보 적용 구간, 조회 시각은 응답 본문을 받은 시각으로 표시한다. 선정 과정은 [D-033](DECISIONS.md)에 있다.

`node scripts/t04_weather_record.mjs`로 당일 예보를 실제 조회해 `static-web/data/t04/weather-daily.json`에 원본과 요약을 저장한다. 같은 KST 날짜에는 한 행을 갱신한다. 첫 실제 기록은 2026-11-24 KST이며, 평균 2.1°C·최저 −1.8°C·최고 9.0°C·강수 0.1 mm·적설 0.0 cm를 원본 및 화면과 대조했다. 다른 실제 날짜의 두 번째 조회와 변경 버전의 Pages 검증이 남았다.

`#t04-lab`은 기존 날씨 카드에 공개 fixture 재생 조작을 추가한다. 실패하는 동안 모든 시간별 값과 요약값을 유지하고, 다시 시도하면 복구 fixture를 시간별 날씨에 적용해 같은 카드의 값과 합성 날짜별 기록을 갱신한다. 합성 값은 실서비스 기록이나 경로 추천 계산에 들어가지 않는다.

### 이전 승하차 버전 작업 기록

- **기록 대상** — 대전교통공사의 공공데이터포털 `getTicketTypeTraffic01`에서 얻는 1호선 실측 총 승하차(명)로 전환했다. 운행일 D의 모든 역·승하차·티켓 구분을 합산하되, D일 05~23시와 D+1일 00시를 사용한다. D일 00~04시는 집계 범위에서 빠진다. `record_date`는 작업을 실행한 KST 날짜 T이고 `business_day`는 T−2일이다. 같은 신호와 조회 날짜에 다시 기록하면 그 행을 갱신한다. 원본 두 날짜의 자료가 준비되지 않았으면 미집계로 처리한다. `source_time`에는 마지막 집계 구간의 끝(D+1 00:59:59 KST), `fetched_at`에는 정제 실행 시각을 저장한다. 출처 URL에는 서비스 키를 넣지 않는다.
- **정보판** — `#t04`의 날짜 선택은 기준일을 포함한 7일 그래프와 표에 적용된다. 최신 완성 운행일 뒤의 날짜는 미집계로 표시한다. 05~23시의 과거 날씨에서 강수(mm)·적설(cm)을 요약해 함께 보여 준다. 대표값, 두 기록의 차이, 시간·역별 합계와 원본 XML 대조는 `daily.json`을 사용한다. 추천 화면에서는 Open-Meteo 날씨를 계속 사용한다. 실패 5종·마지막 정상값·다시 시도·복구의 합성 재생은 `#t04-lab`에서 열리며 실제 기록과 별도다.
- **로컬 데이터(전환 작업 직후)** — `data/raw/subway/`와 `data/raw/weather/`에 각각 2024-11-01~2026-11-22의 752일치 원본이 있다. 11월 3~22일의 승하차·Open-Meteo Archive 날씨를 백필했다. `business_days.json`은 2024-11-01~2026-11-21의 완성 운행일 751건이다. 사용자 승인으로 기존 날씨 행 두 건을 삭제한 뒤 `daily.json`은 0건이다. 백필과 합성 재생은 C22~C24에서 요구하는 서로 다른 실제 KST 날짜의 두 조회 기록과 별개다.
- **배포 상태** — 기존 날씨 버전은 Pages에서 HTTP 200으로 확인한 이력이 있다([D-031](DECISIONS.md)). 승하차 전환과 사본 정리는 로컬 변경 단계에서 확인했다. 새 버전 GitHub Pages 실행, 브라우저에서 승하차 기록 2건의 XML·저장값·화면 대조, 제출 글(C27·C28), 기존 Kakao JS 키 폐기 여부 확인이 남았다.

#### 수동 수집과 검증

프로젝트 루트에서 Node 22를 사용한다. 로컬 `.env`에 `SUBWAY_API_KEY`가 설정돼 있으면 다음 명령으로 읽을 수 있다. 이미 환경변수로 주입한 경우 `--env-file=.env`를 생략한다.

```powershell
node --env-file=.env scripts/t04_daily_record.mjs all
node scripts/sync_static_data.mjs
```

- `all`은 `collect`와 `refine`으로 승하차 기록을 만들고, Open-Meteo Archive의 최근 누락 날씨를 채운 뒤 `history`로 `business_days.json`을 다시 만든다. 승하차 원본을 기다리는 상태는 `PENDING`, 기록 완료는 `RECORDED`로 출력한다. `refine`은 기존 XML만 정제하고 `history`는 저장된 원본만 집계한다. `weather`는 Archive에서 자료가 아직 없을 때 다음 수집까지 비워 두며, 예보로 채우지 않는다.
- **실제 조회 증거** — `collect`는 대상 날짜 XML이 이미 있으면 그 파일을 재사용한다. `fetched_at`은 정제 시각이므로 기존 XML을 사용한 `RECORDED` 출력만으로 당일 API 호출을 확인할 수 없다. 과제 증거를 만들 때는 실행 전 해당 날짜 원본의 유무와 새로 수집된 파일을 확인하고, 서로 다른 KST 날짜의 실제 조회 결과와 화면값을 대조한다.
- **백필 도구** — `scripts/utils/backfill_subway.py`와 `scripts/utils/backfill_weather.py`에서 날짜 범위를 지정할 수 있다. 승하차 Python 백필은 `totalCount`가 비어 있는 응답을 처리하고 일시적 503을 재시도하도록 보완했다. 백필 뒤 `node scripts/t04_daily_record.mjs history`로 그래프 데이터를 갱신한다.
- **정적 데이터와 Pages** — `run_static.bat`과 `pages.yml`은 `sync_static_data.mjs`로 `static-web/data/weather/`와 `daily.json`이 참조하는 `static-web/data/t04/raw/` XML을 생성한다. 이 사본 디렉터리는 Git에서 제외한다. `daily.json`과 `business_days.json`, `data/raw/` 원본은 커밋 대상이다. 일일 수집 워크플로는 삭제하고 `pages.yml`이 `static-web/`을 게시한다. Pages는 `main`의 `static-web/**`, `data/raw/weather/**`, `scripts/sync_static_data.mjs` 변경 또는 수동 실행으로 시작한다. 승하차 원본만 바뀐 경우에는 수동 배포가 필요하다. 로컬 배치는 Node가 없으면 동기화를 건너뛰고, 동기화 오류가 나도 파일 서버를 계속 시작한다. 공개 사본을 확인할 때는 `node scripts/sync_static_data.mjs`의 종료 코드도 확인한다.
- **검증 기록** — Claude 세션에서 Node 테스트 4개 파일 통과, `sync` 두 번 실행, 날씨 사본 752개와 Python 빌더 결과의 바이트 일치, 임시 폴더의 참조 XML 복사·미참조 XML 정리·원본 누락 오류를 보고했다. 승하차 전환 버전의 공개 배포와 실제 2일 기록 검증은 별도로 남아 있다.

### 과제 요구와 초기 날씨 구현 기록

아래의 기온·예보·일일 Actions 관련 구현 내용은 전환 전의 이력이다. 사용자 지시에 따라 카드 원문과 직접 합의한 내용을 작업 기준으로 삼았다. 외부 패키지는 스키마와 합성 재생 자산 확인에 사용했고, 패키지 문서의 ‘봉인 영수증’과 ‘조건 35개’ 해석은 작업 기준에서 제외했다.
- **과제:** 날씨·환율·교통·게임 상태 등 공개 동적 데이터 하나를 조회·저장하고 일별 변화량을 비교하는 대시보드. 응답 실패 시 오류 유형과 마지막 정상값을 보이는 폴백을 구현한다.
- **제출(필수):** 결과물 URL(공개 심사 화면), 소스 URL(40/64자리 소문자 full commit이 든 HTTPS 고정 URL, 브랜치·저장소 첫 화면은 불가). 권장: "재현·통과 확인 4가지"(어디로 가나 / 3단계 이내 무엇을 하나 / 무엇이 보이면 통과 / 안 될 때 무엇이 보이나)와 "AI와 내 판단 3줄"(AI에게 맡긴 일 / 내가 판단한 일 / 따르지 않은 AI 제안, 없으면 그 이유). 각 6,000자까지이며 비워도 제출은 막히지 않지만 후행 채점에 '기록 없음'으로 반영된다. 파일은 선택(10개·합계 8MB). 날짜·해시·과제 버전은 플랫폼이 기록하고, 제출 뒤 강사 승인→마스터 승인 순서다.
- **모든 제출 URL:** 계정 생성·로그인·인증·초대·비밀번호·OAuth·CAPTCHA 없이 새 시크릿 창에서 열려야 한다(T04-C01).

| 카드 | 하는 일 | 통과 기준 | 남길 것 |
|---|---|---|---|
| 1 값 선정 | 개인과 무관한 공개 소스에서 실제로 변하는 값 하나 선택. 비밀키 없는 소스이거나 서버 환경변수로만 호출 | C03 실제로 변하는 값 조회. C04~C09 화면에 값·단위·출처·출처 시각·조회 시각·기준 시간대 표시. C10 정상 응답 1건의 원본 응답·저장값·화면값 일치 | 공개 화면 URL, 원본/저장/화면 3자 대조 |
| 2 비밀키 | 브라우저·배포 파일·네트워크 응답·Git 기록에 키 원문을 남기지 않음 | C11 위 네 곳에 비밀키 원문 0건 | 클라이언트·네트워크·저장소 검색 결과 |
| 3 실패 재현 | 지연, 401/403, 호출 제한, 오프라인, 응답 형식(스키마) 변경을 합성 fixture로 재현하고 유형별 상태·다음 조치를 구분 표시 | C12~C16 다섯 유형 각각 별도 실패 상태. C17 실패 뒤 마지막 정상값 유지. C18 stale 표시. C19 재시도 동작 + 공개 asset `T04-RECOVER-D2` 재생 시 상태 fresh·error_code none 복구, 다음 날짜의 일별 기록이 정확히 1건 추가(사용자가 전문 확인) | 공개 package ID·파일 hash 대조, 실패 상태 5종, 마지막 정상값·stale·재시도·복구 |
| 4 일별 기록 | 기준 시간대 날짜를 고유키로 같은 날 중복 기록 방지. mock clock으로 같은 날 3회+다음 날 1회 테스트 | C20 같은 날짜 여러 번 성공해도 1건. C21 다음 날짜 성공 시 새 기록 | 같은 날짜 재실행 전후 행 수 |
| 5 실제 2일 | 첫날 값 저장, 다른 KST 날짜에 재조회, 두 값으로 전일 대비 변화 재계산 | C22 서로 다른 Asia/Seoul 실제 날짜의 실제 기록 정확히 2건. C23 각 기록의 URL·관측 시각·정규화 값·단위가 저장값·화면값과 일치. C24 전일 대비 변화 재계산이 화면값과 일치. C27 확인 방법 4구분. C28 AI·내 판단 3구분 | 실제 기록 2건, 출처·시각·값·단위 대조, 변화 재계산 |

- **기준 목록 전체:** C01, C03~C28 중 화면에 있는 것은 위 표와 같고, 공통으로 C25(공개 화면·제출 파일에 실제 개인정보·개인 기록 0건)와 C26(실패 재생은 합성 테스트 데이터만 사용)이 카드 1에 붙어 있다. C02는 화면에 없었다.
- **지켜야 할 금지:** 합성 D1/D2 기록으로 실제 공개 데이터 기록 2건을 대신하지 않는다. 둘째 날 기록이 없으면 임의 생성·수정하지 않고 다음 실제 날짜에 다시 확인한다. 노출된 키는 폐기(revoke)하고 재발급 키는 서버 환경변수에만 둔다.
- **고정 자산:** 카드 3의 `assets/studio-task-assets/t04-real-information-board/`(README·public-contract.json·asset-manifest 등)와 "T04 공개 합성 테스트 패키지 ZIP(fixtures 9종·criterion-registry·schema)"을 받아 쓴다. 받지 않았고 내용은 읽지 않았다.
- **검수(2026-11-23 오후, 푸시 전 시점의 기록; 모델 정확도는 검수 대상 아님):** 이 웹은 혼잡 추천 도구이고 과제는 '값 하나를 매일 추적'하는 모니터링이다. 현재 충족 근거가 있는 것은 Open-Meteo 시간별 날씨 조회(`static_src/static-engine.js` 96~97행, 기준 시간대 Asia/Seoul 지정)와 날씨 재시도 버튼(`static_src/app.js` 636~641행)뿐이다.
  - 없음: 일별 기록 저장소·날짜 고유키(C20·C21·C22~C24), 원본·저장·화면 3자 대조(C10), 실패 5유형 합성 fixture·유형별 상태(C12~C16), 마지막 정상값 stale 표시(C17·C18; `setStale`은 추천 결과 화면용), `T04-RECOVER-D2` 복구(C19), 확인 방법 4구분·AI 판단 3구분 글(C27·C28), 출처 시각·조회 시각 표시(C07·C08는 확인 못함).
  - 막힘: 공개 결과물 URL이 없다(`huigeun6011-prog.github.io`와 `/T04-API/` 모두 404). 소스 URL용 full commit에는 `static_src/`·`static-web/`·`worker/`가 없다(미추적, 마지막 커밋 `c786ca4`). 공개 저장소 이력(`a3b6bc9`)에 Kakao JS 키가 있어 C11 위반이다(키는 재발급됐다고 기록돼 있으나 폐기 여부는 확인하지 못함). 현재 작업 트리의 `web/config.local.js`는 gitignore되어 있다.
  - 지도 Worker는 REST 키를 Worker Secret에만 두므로 C11 방향과 맞고, 브라우저에는 키가 가지 않는다(2026-11-23 실제 응답으로 확인).
  - 둘째 실제 KST 날짜 기록(C22)은 날짜가 바뀌어야 얻을 수 있어 기록 저장 장치를 오늘 중 만들어야 내일 2건이 된다.
- **사용자 답변(2026-11-23):** 승하차·날짜 자료는 2024-11~2026-11-01까지 일별로 있으나 그 이후는 매일 기록하지 않았다(이 자료는 과거 일괄 수집이라 C22의 '서로 다른 실제 날짜에 조회한 기록 2건'에 해당하는지 불확실, 문구상은 해당하지 않는 것으로 읽힘). 확인 방법·AI 판단 글은 사용자가 직접 쓴다. 공개 배포와 소스 푸시는 구현이 끝난 뒤에 하고, 이력의 Kakao JS 키는 사용자가 폐기하며 이후 REST 키를 쓴다(구 `web/`은 JS 키를 쓰므로 폐기하면 동작하지 않는다). 추적할 값(날씨 등)과 실패 fixture 구현 범위는 아직 정하지 않았다.
- **고정 자산 확인(2026-11-23):** ZIP은 `data/external/t04_assets/`(gitignore)에 있고 `extracted/`에 풀었으며 asset-manifest의 17개 해시가 모두 일치한다. 위 '기준 목록 전체' 서술은 화면 기준이라 부정확했다. 정본 `criterion-registry.json`은 **T04-C01~C35의 35개**이고, C02 로그인 없음·C29~C33 인증·초대·비밀번호·OAuth·CAPTCHA 없음(공개 접근, 결과물·소스 URL 모두), C34 결과물 URL 필드에 HTTPS URL 1개, C35 소스 URL에 40/64자리 commit 포함이 추가돼 있다. C19 복구는 `T04-TIMEOUT` 직후(stale/timeout, 행 1, 마지막 정상값 105, 2026-08-24)에서 재시도 뒤 `T04-RECOVER-D2`로 fresh/none, 행 2, 2026-08-25 행 1건 추가, 저장값 120이다.
- **정규화 형식(`normalized-reading.schema.json`):** `signal_id`, `normalized_value`, `unit`, `source_name`, `source_url`(HTTPS), `source_time`(null 가능), `fetched_at`, `record_timezone`('Asia/Seoul' 고정), `record_date`(fetched_at의 KST 날짜와 일치) 아홉 개만 허용한다. 같은 `signal_id+record_date`는 원자적 갱신, 오류 코드는 `timeout|auth|rate_limit|offline|schema_error`, 상태는 `fresh/none` 또는 `stale/오류`다. fixture 9개는 `virtual_now`·`transport`·`payload`·`expected`를 갖는 결정론 재생 입력이다.
- **C22~C24의 증거:** 앱이 직접 만드는 기록이 아니라 ALEPH가 봉인하는 `t04_day` 영수증 정확히 2건(`server_created_at`의 KST 날짜가 서로 다름)과 앱에 **보존된 일별 저장값·화면값**을 대조한다. 영수증을 언제·어떻게 받는지(제출 양식의 '선택 과정 기록 남기기'와 관련 있어 보이나 확인 못함)는 사용자가 확인해야 한다. 따라서 일별 저장값은 다른 브라우저에서 심사해도 보여야 하므로 브라우저 localStorage만으로는 부족하다.
- **결정(2026-11-23):** 추적 값은 대전 Open-Meteo 날씨로 한다.
- **일별 기록 구현(2026-11-23, 푸시·실행 전):** 저장은 Worker KV가 아니라 GitHub Actions로 정했다. `scripts/t04_daily_record.mjs`가 Open-Meteo 대전 현재 기온 1건을 조회해 `{reading(아홉 필드), raw(응답 원본)}`을 `static-web/data/t04/daily.json`에 KST 날짜 키로 갱신·추가한다(조회 실패·형식 오류 시 파일 불변, 임시 파일 후 교체). `.github/workflows/t04-daily-record.yml`이 매일 03:10 UTC(12:10 KST)와 수동 실행으로 돌려 커밋한다. 테스트 `scripts/t04_daily_record.test.mjs` 1건 통과, 실제 API 1회 시험 성공(저장소 파일에는 쓰지 않음). 당시에는 푸시 전이라 워크플로가 돌지 않았고 `daily.json`이 없었다(현재는 위 현재 상태 요약 참고). 화면 표시(C04~C10)와 fixture 재생(C12~C19)은 이 항목 시점에는 미구현이었고 바로 아래 항목에서 구현했다.
- **T04 화면·재생 구현(2026-11-23, 푸시 전):** 기존 웹에 탭 '오늘의 정보판'(`data-tab="t04"`, 공개 주소 `…/#t04`)을 추가했다. 새 파일 `static_src/t04-core.js`(참조 어댑터를 옮긴 순수 로직, `T04Core`), `t04-board.js`, `t04-board.css`와 `index.html`의 탭·로드 줄만 바꿨고 `app.js`는 그대로다. 탭은 ① 실제 기록(`data/t04/daily.json`: 값·단위·출처·출처 시각·조회 시각·KST·전일 대비·원본/저장/화면 3자 대조, 이틀 이상 지나면 안내)과 ② 합성 재생(fixture 9종, 실패 5유형 별도 상태·마지막 정상값 보존·다시 시도·복구, 메모리 상태만 사용)으로 나뉜다. `scripts/build_static_web.py`가 외부 공개 패키지(`data/external/t04_assets/extracted/…`, gitignore)의 17개 해시를 검증해 12개를 `static-web/data/t04/`로 복사하며 `daily.json`은 건드리지 않는다. 검증: `node --test scripts/t04_core.test.mjs scripts/t04_daily_record.test.mjs` 20건 통과, 임시 폴더 빌드와 로컬 정적 서버에서 브라우저로 확인(탭 진입, 실제 기록 3자 일치 11.1°C, 정상·실패(429)·다시 시도로 stale/rate_limit 행 1 → fresh/none 행 2·2026-08-25·120·+15 전이). 독립 검토(Reviewer)의 심각도 1 지적은 없었고, 2 지적(쓰기 전 검증 통일, push 재시도, 자동 재생 실패 시 상태 초기화, 포커스·라이브 영역, 오래됨 안내)은 반영했다.
  - **미확인·남은 것:** 이 수정 뒤 브라우저 확인은 합성 영역 위주이며 좁은 화면·스크린리더·`daily.json` 오래됨 안내는 직접 보지 않았다. 워크플로(`.github/workflows/t04-daily-record.yml`)는 GitHub에서 한 번도 실행하지 않았고, `daily.json`은 아직 없다. **`t04_daily_record.mjs`가 `../static_src/t04-core.js`를 불러오므로 워크플로만 먼저 푸시하면 Actions가 실패한다. `static_src/t04-core.js`(와 스크립트·워크플로)를 함께 올려야 한다.** C22~C24 실제 2일 증거, 공개 URL·소스 commit(C01·C02·C29~C35), 글(C27·C28), Kakao JS 키 폐기는 그대로 남았다. 모델 패리티 전체 검증(`validate_static_web.py`)은 돌리지 않았다.
- **Pages 배포 준비(2026-11-23, 푸시 전):** `static-web/`을 `.venv/Scripts/python.exe scripts/build_static_web.py`로 재빌드해 적용했다(적용 전 백업: `outputs/backup_before_rebuild_t04_static/`, gitignore 대상. 바뀐 것은 `index.html`과 새 파일 15개뿐이고 `validate_static_web.py` 전체 검증 통과: 14,296행 오차 0, 66개 추천 일치, 하위 경로 URL 확인). `.github/workflows/pages.yml`은 `static-web/`을 Actions 방식으로 배포하고(push 경로 `static-web/**`, 수동 실행, `workflow_call`), `t04-daily-record.yml`은 기록·커밋 뒤 같은 실행에서 `pages.yml`을 호출한다(`GITHUB_TOKEN` 푸시는 다른 워크플로를 깨우지 않기 때문). 액션 버전(checkout v7.0.1, setup-node v7.1.0, configure-pages v6.0.0, upload-pages-artifact v5.0.0, deploy-pages v5.0.1)은 Implementer가 공식 릴리스를 확인했다고 보고했고 root는 확인하지 못했다. 둘 다 GitHub에서 실행해 본 적 없다. **사용자가 할 설정:** 저장소 Settings → Pages → Source를 'GitHub Actions'로, 정책이 막으면 Settings → Actions → General의 쓰기 권한. `.gitignore`에 `outputs/map-proxy-qa/`(자동화 스크립트·탭 정보), `.env.*`, `.dev.vars`, `.wrangler/`, `node_modules/`, `artifacts/`, `*.pem`, `*.key`를 추가했다.
- **일별 기록 형식 변경(2026-11-23): 현재 기온 1건 → 내일 24시간 예보.** 사용자 요청으로 추천 웹의 시간별 날씨(기온·강수·적설)와 연결하고 24시간 전체를 비교한다. `scripts/t04_daily_record.mjs`는 조회한 날(KST)의 다음 날 하루 24시간 예보를 가져와 `{reading, target_date, hourly, hourly_units, raw}` 행으로 저장한다. `reading`은 아홉 필드를 유지하고 `signal_id`는 `daejeon-forecast-mean-temp-2m`, `normalized_value`는 대상일 24시간 기온 평균(소수 첫째 자리, `T04Core.roundToTenth`, half away from zero), `source_time`은 예보 대상일 00:00 KST, `record_date`는 조회 날짜다. 24칸 중 하나라도 비거나 숫자가 아니면 저장하지 않는다. 같은 `signal_id`+`record_date`만 갱신하며 **옛 신호(`daejeon-temperature-2m`, 2026-11-23 현재 기온 10.9 °C 1건)는 삭제하지 않고 남겼다**(ALEPH 영수증이 그 값을 참조했을 수 있어서, 지울지는 사용자가 정한다). 화면은 마지막 행의 `signal_id`와 같은 행만 쓰고, 옛 형식이 마지막이면 '이 기록에는 시간별 예보가 없습니다'로 표시한다. `T04Core.compareHourly/previousRow/latestSignalRows/hasCompleteHourly/roundToTenth`가 추가됐고 화면은 이전 예보와 24시간(기온·강수·적설) 시각별 차이, '시간별 차이의 평균'과 '저장 대표값(소수 첫째 자리) 차이'를 구분해 보이며, 3자 대조는 원본 24칸 평균(반올림)·저장값·화면값과 저장한 24칸·원본 같은 날짜 칸을 대조한다. 검증: Node 테스트 45건 통과, `validate_static_web.py` 전체 통과, 가짜 2일치+옛 행으로 브라우저 확인(임시 폴더, 저장소 `daily.json`은 손대지 않음). 아직 GitHub Actions에서 새 형식 첫 기록을 만든 적 없다.
- **추적 값과 추천 웹의 관계:** 일별 기록의 시간별 예보는 `data/raw/weather`(과거 날짜 보관 자료)를 대체하지 않고, 추천 화면의 날씨 조회(과거=보관 파일, 오늘·미래=브라우저 직접 조회)와도 아직 연결되지 않았다(조회 실패 시 저장 예보로 대신 보여 주는 안은 보류).

