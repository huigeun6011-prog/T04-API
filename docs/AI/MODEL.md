# 모델과 학습 단계 개요

[인수인계](../HANDOFF.md)와 [방법론](METHODOLOGY.md)이 현재상태의 기준이다.

## 두 단계

1. `generate_ground_truth.py`: 방향없는 역별 승하차와 열차시간표로 일별p/q 분배율을 Adam으로 추정한다. 라벨은 실측정답이 아니며 물리적soft penalty를 쓴다.
2. `train_predict_model.py`: 추정라벨을 HistGradientBoostingRegressor로 학습해 역·시간·방향·요일binary·날씨·시간표버전 조건부 재차인원을 예측한다.

출력은 정차 후 재차인원으로 해석하는 작업가정이다. 실제피크 CSV의 측정시점은 아직 공식확인하지 못했다. 열차번호·출발분·월~일은 현모델 입력에 없으므로 같은역·시간·방향·날씨면 같은예측이다.

## 파일 상태

- API가 읽는 production은 `outputs/load_predictor.joblib`이다.731일·3,733,691행, 이전200회solver라벨,24시날씨수정후전체refit이다.
- `outputs/diagnostics/candidate_training/`은 feasible배분·1000회·raw잔차보존 후보다.production에 미적용이다.
- `gt_assumptions.py`의 시간/요일/headway옵션은 구현·검증했지만 기본비활성이고 전체all모델도 만들지 않았다.
- `train_load_model.py`와 `outputs/best_model.pt`는 이전PyTorch 예측모델이다. 현재HGB와혼용하지 않는다.
- `scripts/data_prep/gen_station_hourly.py` 산출물은 이전경로용이다. 현재GT는 열차별시간표JSON에서 분모를 직접센다.

## 입력과 날짜

- `data/processed/subway/{운행일}.json`의05~23시와 `{익일}.json`의00시를 사용한다.
- 시간표는2026-03-30이후평일에20260330,그외에는20250930이다. 이후휴일도이전휴일표폴백이다.
- 24시날씨는익일00시이며 달력D일00시단일요청은D−1운행일24시로변환한다.
- 원본 OD·개별승하차·전체열차실측재차는없다. 일부실제피크20사례(매칭19)는사후검증전용이다.

## 성능 해석

production 날짜holdout MAE20.14/R²0.8766과 실제피크MAE375.99는 서로다른평가다. 전자는추정라벨재현성이고 후자는선택된실제극단사례비교다. 실제정확도와추천순위는확보되지않았다. 후보별수치·hash·한계는[HANDOFF](../HANDOFF.md)를참고한다.
