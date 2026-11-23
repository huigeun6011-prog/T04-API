# 재차인원 역산 실행 지침서 (다른 PC의 Claude용)

기준 2026-11-17(작성 당시). **이후 상태(2026-11-23):** 이 지침의 OD 방식은 61일 표본 라벨로 2026-11-19에 production에 적용됐고([D-027](../DECISIONS.md), [HANDOFF §4](../HANDOFF.md)), 731일 전체 재생성은 E-38에서 불필요하다고 확인됐다. 아래 본문은 당시 절차 기록이며 'production 교체는 별도 단계'라는 문구는 이미 지나간 상태다. 이 문서만 읽고 따라 할 수 있도록 썼다. 목표는 **열차 단위 OD 방식(E-16)으로 재차인원 라벨을 만들어 HGB 예측 모델 후보를 학습하고, 기존 production 모델과 추천 결과를 비교**하는 것이다. production 교체는 사용자 승인 이후의 별도 단계다.

## 0. 사용자에게 받은 지시와 이 문서를 쓰게 된 이유

- 사용자는 재차인원 역산에 오래 투자할 수 없다고 했다. "3시간 안에 끝난다는 보장이 없으면 다른 PC의 Claude에게 시키겠다"고 했고, 원래 PC에서는 전체 731일 재생성이 3시간 안에 끝난다고 보장할 수 없어서(아래 §8) 이 문서를 만들었다.
- 사용자는 한국어로 대화한다. 짧고 직설적으로 답하고, 확인하지 않은 것을 확인했다고 말하지 않는다. 모르는 것은 "모른다/확인하지 못했다"고 쓴다.
- 사용자는 "지휘자 Claude가 작업 에이전트를 만들어 시킨다"는 구조를 좋아한다. 에이전트가 가능하면 같은 에이전트를 이어서 쓰고, 에이전트의 보고는 **산출물 파일로 직접 검증한 뒤** 사용자에게 전달한다.
- 컴퓨터를 쓰는 동안 사용자가 다른 일을 할 수 있어야 한다. 오래 걸리는 계산은 병렬 프로세스 수를 제한하고(§6) 낮은 우선순위로 돌린다.

## 1. 먼저 읽을 문서 (이 순서)

1. [HANDOFF](../HANDOFF.md) §1, §3, §4: 확정 요구, 운행일 규칙, production과 후보의 구분.
2. [ROADMAP](../../ROADMAP.md): 현재 상태, 완료 기록, 사용자 결정(하지 않기로 한 것).
3. [METHODOLOGY](METHODOLOGY.md) 마지막 절 "권고하는 재차인원 역산 방식".
4. [EXPERIMENTS](../EXPERIMENTS.md) E-16(열차 단위 OD), E-17(LP 범위), E-19(합성 복원): 왜 이 방식인지와 한계.
5. [DECISIONS](../DECISIONS.md) D-007, D-008, D-009: 실측 자료 사용 규칙, 하지 않기로 한 것.

## 2. 지켜야 할 규칙 (어기면 안 됨)

- 실제 피크 19건(`data/raw/subway_time/…혼잡도 분석_20261031.csv`의 매칭 19건)은 **평가용이다**. 학습, 튜닝, 손실 가중치, 보정, 설정 선택에 쓰지 않는다. 모델과 설정을 확정한 뒤 **마지막에 한 번** 사후 비교만 한다. 보고 나서 모델을 고치지 않는다(고치고 싶으면 사용자에게 묻는다).
- 설정(λ, 시드, 표본 날짜, 판정 기준)은 **실행 전에 파일(config.json)로 고정**하고 결과를 본 뒤 바꾸지 않는다.
- `.env`와 `web/config.local.js`의 값(API 키)을 읽거나 출력하거나 문서에 쓰지 않는다. 권종(ticket type) 정보, 다른 지역 자료, 베이지안 분해는 쓰지 않는다(D-008).
- production 파일은 사용자 승인 없이 바꾸지 않는다: `outputs/load_predictor.joblib`, `outputs/model_metrics.json`, `outputs/ground_truth_train_loads.csv`(이 CSV는 git에 없음). 후보는 항상 별도 경로(`outputs/diagnostics/od_labels/` 아래)에 만든다.
- git은 사용자가 시킬 때만 커밋하고, push, 브랜치 삭제 같은 바깥에 영향을 주는 동작은 하기 전에 묻는다. 시킨 일이 아닌 파일은 수정하지 않는다.
- 낮은 내부 loss나 추정 라벨 지표(MAE, R²)만으로 "정확해졌다"고 말하지 않는다. 이 라벨은 실측 정답이 아니다.
- 재차인원은 "출발 후 값"이라는 작업가정이다(측정 시점은 미확인).

## 3. 환경 준비

저장소를 복제하면 계산에 필요한 자료는 git에 들어 있다(확인된 수): `data/processed/subway` 732개, `data/raw/weather` 732개, `data/processed/subway_time` 6개, `data/raw/subway_time`의 시간표·혼잡도 CSV, `outputs/load_predictor.joblib`. git에 **없는** 것: `outputs/ground_truth_train_loads.csv`(380MB, production 라벨), `outputs/best_model.pt`, `.venv`, `web/config.local.js`. 이 단계들에는 앞의 둘이 필요하지 않다.

**필수 스크립트가 저장소에 있어야 한다.** 아래 파일과 `scripts/data_prep/make_od_labels.py`가 저장소(GitLab, GitHub 모두)에 커밋되어 있어야 한다. 없으면 사용자에게 가져오는 방법(커밋·push 또는 복사)을 요청한다. 대신 만들어 내려고 하지 않는다(재현 숫자가 달라질 수 있다).

```
scripts/data_prep/generate_ground_truth.py     (day-type, 시간표, 날씨 규칙. 모듈 gt)
scripts/data_prep/gt_assumptions.py            (generate_ground_truth가 import)
scripts/data_prep/gt_arrival_curve.py          (load_day(date) 관측 승하차 B, A 로딩. 모듈 ac)
scripts/data_prep/gt_train_od.py               (열차 단위 OD: build_problem, base_q, fit, to_frame, marginal_stats)
scripts/data_prep/validate_train_od_peaks.py   (피크 사후 비교 참고용)
scripts/data_prep/evaluate_peak_cases.py       (피크 사후 비교 참고용)
scripts/data_prep/make_od_labels.py            (Step 1 생성기·조립기)
train_predict_model.py, prediction_api.py, predict_load.py
```

Python 환경(원래 PC에서 쓴 버전. lockfile은 없다): Python 3.12.16, numpy 2.5.5, scipy 1.18.1, pandas 3.1.1, scikit-learn 1.9.1, joblib 1.6.0, torch 2.15.0(CPU 전용. `generate_ground_truth`가 import하므로 필요하지만 GPU는 쓰지 않는다). 같은 버전이 어렵다면 가까운 버전을 설치하고 **Step 0의 재현 숫자로 확인**한다.

작업 폴더 규칙: 스크립트는 `scripts/data_prep`를 `sys.path`에 넣고 import한다(`import generate_ground_truth as gt`, `import gt_train_od as od`). 자료 경로는 파일 위치 기준 절대 경로로 잡혀 있어 작업 폴더에 덜 민감하다. Windows에서는 파일을 UTF-8로 읽고 쓴다.

## 4. 단계

### Step 0. 재현 확인 (약 5~10분)

`gt_train_od`로 2025-11-04(화) 하루를 균일 기준, λ=0.01로 푼다.

```python
import sys; sys.path.insert(0, "scripts/data_prep")
import generate_ground_truth as gt, gt_train_od as od
P = od.build_problem("2025-11-04")
q = od.base_q(P, "uniform", None, 1.0)
x, info = od.fit(P, q, 0.01)          # 약 2~3분
frame = od.to_frame(P, x)
```

원래 PC에서 얻은 값(이와 비슷해야 한다): `info["converged"]`가 True, 반복 약 1,458회, `x.sum()` ≈ 109,828명(관측 승차 합 110,086, 하차 합 109,735), 종점 재차와 음수 재차는 0, 07~09시에 하차가 가장 많은 역은 정부청사(약 3,181명), 시청(약 2,419), 대전(약 1,915). `x.sum()`은 관측 승차 합보다 약 0.2% 작다(참고: 6일 평균 합계 불일치는 0.6%, [E-16](../EXPERIMENTS.md)). 크게 다르면(합계가 관측과 ±1% 이상 차이, 미수렴 등) **여기서 멈추고 사용자에게 보고**한다.

### Step 1. 라벨 생성기와 조립기 (구현됨: `scripts/data_prep/make_od_labels.py`)

코드는 이미 있다(2026-11-17 작성, 기존 파일은 수정하지 않았다). 풀이 설정은 `gt_train_od`의 E-16 설정 그대로(균일 기준 q, L-BFGS-B, λ 기본 0.01)다.

```
# 생성 (날짜 목록 또는 간격; 이미 만든 날짜는 건너뜀, workers 최대 3)
python scripts/data_prep/make_od_labels.py --dates 2026-10-21,2026-10-24 --out-dir outputs/diagnostics/od_labels/<실행이름> --lam 0.01 --workers 2
python scripts/data_prep/make_od_labels.py --stride 12 --start 2024-11-01 --end 2026-11-01 --out-dir outputs/diagnostics/od_labels/<실행이름>
# 조립 -> <out-dir>/dataset.csv
python scripts/data_prep/make_od_labels.py --assemble --out-dir outputs/diagnostics/od_labels/<실행이름>
# 학습(별도 경로)
python train_predict_model.py --dataset <out-dir>/dataset.csv --model-output <out-dir>/od_predictor.joblib --metrics-output <out-dir>/od_metrics.json
```

- 날짜별 산출물: `labels/<date>.csv`(production과 같은 열 + `raw_load, load_correction, terminal_raw_residual`, 후보 CSV와 같은 열 순서, 날씨 포함: hour 24는 익일 00시, 날씨 파일이 없으면 그 날짜는 오류로 기록하고 건너뜀), `agg/<date>.csv`(역×시×방향 평균·최대 load), `info/<date>.json`(초 단위 시간, converged, nit, objective, proj_grad_inf, 종점 잔차, 승하차 오차, 슬랙). `progress.json`은 날짜 하나가 끝날 때마다 갱신. 익일 승하차 파일이 없는 날짜도 오류로 기록한다.
- 스레드 1, 프로세스 우선순위 BELOW_NORMAL(Windows)을 스크립트가 스스로 설정한다. 조립기는 열 이름이 정해진 열과 다르면 중단한다.
- **검증한 것 (2026-11-17, 3일, λ=0.01, 3개 병렬):** 평일 2026-10-21, 주말 2026-10-24, 공휴일 2026-10-03. 하루 31.8~36.6초(병렬 3, 저우선순위), 3일 모두 수렴(nit 1,214~1,550), 종점 재차 최대 1.8e-13, 음수 최소 -1.8e-13, 보존식 오차 최대 4e-14, 승·하차 합 오차(적격 셀 L1) 0.55~0.68%. 조립 표 14,787행, 열 이름·타입이 후보 CSV(`outputs/diagnostics/candidate_training/ground_truth_train_loads.csv`)와 같다. 24시 날씨는 익일 00시 값(2026-10-21: 8.1도, 같은 날 00시였다면 15.5도)임을 확인했다. `train_predict_model.py`가 이 조립 표로 학습·검증·재학습을 끝까지 수행한다(3일짜리 스모크 모델이며 의미 있는 성능이 아니다). production 파일은 건드리지 않았다.
- **검증하지 않은 것:** 3일을 넘는 실행, `--stride` 경로(코드는 같은 함수), 중단 후 재개(건너뛰기 코드만 있음, 실제 중단 시험은 안 함), 자정 이후 운행 가능일(2025-08-14 등)의 수렴, Step 0의 2025-11-04 재현 숫자와의 대조, 61일/731일 총 시간. 이 PC의 하루 시간(약 35초)은 원래 PC 측정(약 154초)보다 훨씬 짧으므로 이 PC에서 Step 2 시간을 다시 추정해야 한다.
- 시험 산출물은 `outputs/diagnostics/od_labels/step1_validation/`에 있다(dataset.csv, 스모크 모델 포함, 삭제해도 된다).

### Step 2. 표본 라벨, 후보 모델 학습 (하루 약 35초 기준 라벨 약 15분 + 학습)

1. **표본 날짜를 실행 전에 고정**한다. `make_od_labels.py`에는 `--sample` 옵션이 없고 `--dates`(쉼표 구분)나 `--stride/--start/--end`만 있다. 따라서 직접 날짜 목록을 만든다: 운행일 전체(2024-11-01 ~ 2026-11-01, 731일)를 정렬해 **간격 12일로 뽑아 약 61일**을 만들고, 휴일(`gt.get_day_type(date) == "휴일"`, 라벨의 `is_weekend == 1`과 같다)이 15일 미만이면 가장 가까운 휴일 날짜를 더해 15일 이상으로 한다. 개편 전후(2026-03-30)가 모두 들어가야 한다. 목록을 `outputs/diagnostics/od_labels/<실행이름>/sample_dates.json`에 저장한 뒤 실행한다.
2. `make_od_labels.py --dates <쉼표로 이은 목록> --out-dir <실행이름> --lam 0.01 --workers 3`로 생성한다. **코드가 `--workers`를 3으로 제한한다**(`min(workers, 3)`). 이 PC 측정으로 하루 약 35초(병렬 3, 저우선순위)이므로 61일은 약 12분이다(원래 PC 단일 프로세스 측정은 약 154초). 상한을 올리려면 사용자에게 먼저 묻는다.
3. 조립해 `outputs/diagnostics/od_labels/<실행이름>/dataset.csv`를 만든다.
4. 학습(별도 후보 경로, production을 덮어쓰지 않는다):
   ```
   python train_predict_model.py --dataset <dataset.csv> --model-output <후보>/od_predictor.joblib --metrics-output <후보>/od_metrics.json
   ```
   `train_predict_model.py`는 날짜순 앞 80% 학습, 뒤 20% 검증 뒤에 전체로 다시 학습한다. 라벨 정의가 달라 **MAE를 production 지표와 비교하지 않는다**. 학습 날짜가 적어 검증 구간 날씨 범위가 좁을 수 있으므로 그 사실을 보고에 적는다.

### Step 3. 추천 민감도 시험 (약 20분, 핵심 판단 단계)

질문: **라벨 방식을 바꾸면 사용자가 받는 추천이 실제로 달라지는가?**

(이 단계의 비교 스크립트 `compare_od_vs_production_recommend.py`는 아직 없다. 아래 설계대로 **새로 작성**한다. 작성한 코드는 3개 질의로 먼저 시험하고 전체 30개를 돌린다.)

- 모델마다 **별도 프로세스**로 돌린다(`prediction_api`에 날짜별 캐시와 모델 캐시가 있어 한 프로세스에서 모델을 바꾸면 결과가 섞일 수 있다). 방법: `prediction_api.MODEL_PATH`를 후보 경로로 바꾼 뒤(`api.MODEL_PATH = Path(...)`) `api.recommend(payload)`를 직접 호출한다. 서버는 필요 없다. payload 필드: `date, start_hour, end_hour, quiet_weight(0~100), category, origin{lat,lng}, limit`.
- 질의 묶음(실행 전 고정): 날짜 2개(평일 2026-10-21, 토요일 2026-10-24; 과거 날짜라 날씨는 로컬 파일을 쓴다), 출발지 5곳(반석, 시청, 대전, 판암, 유성온천 역 좌표. 좌표는 `web/app.js`의 `STATIONS`), 시간 범위 3개(07~09시, 12~14시, 17~19시), `quiet_weight` 50, `category` all, `limit` 20.
- 지표: 질의마다 상위 10곳의 겹침(Jaccard), 상위 20곳 점수의 Spearman, 도보 직행 후보 비율, 대표 시간의 평균 차이. 모델 수준에서는 역·시간·방향별 평균 예측의 Spearman과 비율(후보/production)도 낸다.
- 판정 기준(기본값, 실행 전에 사용자가 바꾸지 않으면 그대로 쓴다): 상위 10 겹침의 질의 평균 ≥ 0.8이면 "추천이 거의 같다", 0.5~0.8이면 "부분적으로 다르다", < 0.5이면 "크게 다르다".
- 피크 19건 사후 비교는 **여기서 한 번만** 한다(`scripts/data_prep/evaluate_peak_cases.py`와 `validate_train_od_peaks.py`의 방식을 읽고 후보 HGB 모델에 맞춰 적용). 추정/실제 평균과 MAE만 보고한다. 이 결과로 설정을 바꾸지 않는다.

### Step 4. 사용자에게 보고하고 결정을 받는다 (여기서 반드시 멈춘다)

보고 내용: Step 0 재현 여부, 표본 규모와 소요 시간, 미수렴 일수, 추천 민감도 결과(겹침 수치), 피크 사후 비교, 한계. 그리고 아래 선택지를 제시한다.

- **A. 교체하지 않는다:** 추천이 거의 같다면 교체 이득은 물리 일관성(보존식·종점 0 구조)과 수준 개선뿐이고 계산 비용이 크다. 기존 production을 유지한다.
- **B. 전체 731일을 재생성한다(Step 5).**

결과는 [EXPERIMENTS](../EXPERIMENTS.md)에 E-20으로(색인 표와 상세 모두) 기록하고 ROADMAP과 필요하면 DECISIONS를 갱신한다. 시도가 효과 없음이어도 기록한다.

### Step 5. 전체 재생성과 교체 (사용자가 B를 고르고, 시간 예산을 정했을 때만)

- λ 선택은 실행 전에 사용자와 정한다: **λ=0.01**(합계 불일치 약 0.6%, 하루 약 154초)와 **λ=0.1**(불일치 약 2.4%, 하루 약 73초, 피크 비교는 비슷: 0.616 vs 0.618). 후자는 계산이 절반이다. 이 값을 피크 결과로 고르지 않는다.
- `make_od_labels.py --stride 1 --start 2024-11-01 --end 2026-11-01 --out-dir <실행이름> --lam <선택값>`(`--all` 옵션은 없다)을 백그라운드로 돌린다. 워커 상한이 3이므로 12개 병렬 같은 시간 추정은 코드를 바꿔야 가능하다(사용자 승인 필요). 이 PC 기준 하루 약 35초×731일 ≈ 7시간(단일), 3개 병렬 약 2.5시간이지만 3일만 잰 값이라 Step 2의 61일 시간으로 다시 추정한다. 이어서 조립하고 학습한다.
- 교체 전 필수: 기존 `outputs/load_predictor.joblib`, `outputs/model_metrics.json`을 백업하고 SHA256을 기록한다(기존 joblib SHA256: `6a1e4ec8e1f66be5c90d865d9ef5e625768d5dcc0835f69fcd82fcc62800467a`). 날짜 holdout, 보존식·종점 감사(날짜별 0 확인), Step 3의 추천 비교(전체 모델로 다시), 피크 사후 비교(1회)를 거친다. 교체 후 API는 파일 mtime이 바뀌면 모델을 다시 읽는다. **교체는 사용자의 명시 승인 후에만 한다.**

## 5. 산출물 위치

- 코드: `scripts/data_prep/make_od_labels.py`(+ 조립기, 비교 스크립트 `compare_od_vs_production_recommend.py` 등 새 파일).
- 결과: `outputs/diagnostics/od_labels/<실행이름>/`(config.json, sample_dates.json, labels/, info/, progress.json, dataset.csv, candidate 모델, 비교 결과, report.md).
- 문서: EXPERIMENTS E-20, ROADMAP, 필요 시 DECISIONS.

## 6. 자원 사용 규칙

- 병렬 프로세스는 `make_od_labels.py`가 3개로 제한한다. 더 늘리려면 사용자에게 묻는다. 프로세스당 메모리 약 410MB.
- 시작 전 `OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=1`.
- 프로세스 우선순위 낮춤(Windows): `psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)` 또는 `ctypes.windll.kernel32.SetPriorityClass`.
- `pool.map`으로 전체를 한 번에 돌려 진행 상황이 안 보이게 하지 않는다. 날짜 하나가 끝날 때마다 파일과 `progress.json`을 남긴다.
- 한 단계가 예상보다 오래 걸리면 멈추고 보고한다(Step 2가 60분을 넘기면 중단해 상황을 보고한다).

## 7. 이미 알려진 한계 (보고에 반드시 포함)

- 이 라벨은 "열차마다·목적지마다 균일 기준에서 시간별 합계에 맞게 최소로 조정한 평균 열차"이다. 열차 하나의 재차는 자료로 식별되지 않는다(LP 범위 0 ~ 약 6,000명).
- 피크 열차 대비 추정이 약 0.6배인 수준 격차가 남는다(E-16). 이동 거리 prior가 수준을 정한다.
- 합계 불일치 0.6~2.4%(소프트 제약). 승하차 합계 = 실제 승객, 한 열차만 탄다(환승·연결 없음), 출발 후 재차라는 가정은 검증하지 않았다.
- 열차 계수, 방향 prior, headway, 정원, 도착률 곡선 방식은 시도했고 효과가 없었다(E-13~E-19). 같은 시도를 되풀이하지 않는다.

## 8. 시간 추정과 이 PC에서 3시간 보장이 안 되는 이유

| 작업 | 계산량 | 이 PC(i7-11700, 8코어/16스레드) 예상 |
|---|---|---|
| Step 0 | 하루 1회 | 2~3분(측정) |
| Step 2 표본 61일 | 하루 약 35초 → 약 2,100 CPU초(이 PC 3일 측정) | 3개 병렬 약 12분(추정; 원래 PC 154초 기준이면 약 9,400 CPU초) |
| Step 3 추천 비교 | 모델 2개 × 질의 30개 | 약 10~20분(추정, 첫 호출은 날씨 제한으로 최대 10초 더 걸림) |
| Step 5 전체 731일, λ=0.01 | 원래 PC 기준 약 112,000 CPU초(약 31 CPU시간), 이 PC 35초 기준 약 25,600 CPU초(3일 측정이라 불확실) | **12개 병렬로 약 3.4시간(측정: 72회 풀이가 1,187초), 8개 병렬 4.5~5시간, 4개 병렬 9~10시간(추정)** |
| Step 5 전체 731일, λ=0.1 | 약 53,000 CPU초 | 8개 병렬 약 2시간 안팎(추정) |

하루 풀이 시간은 PC와 날에 따라 다르다(원래 PC 70~330초, 이 PC 3일 측정 32~37초)(설정에 따라 다르고, 자정 이후 운행 가능일은 더 어렵다). 표의 "측정"은 원래 PC에서 실제로 잰 값이다. 3시간 안에 전체 재생성을 보장하려면 코어가 훨씬 많은 PC이거나 λ=0.1 설정이 필요하고, 그 경우에도 학습과 검증 시간이 더해진다.

## 9. 사용자에게 줄 첫 메시지 예시

```
docs/AI/LOAD_ESTIMATION_RUNBOOK.md를 끝까지 읽고 Step 0부터 진행해줘.
Step 4에서 멈추고 결과를 보고해줘. production 파일은 바꾸지 마.
```
