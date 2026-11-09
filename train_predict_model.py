"""
train_predict_model.py
1단계에서 물리적으로 복원된 열차 재차인원 정답 데이터(ground_truth_train_loads.csv)를 학습하여,
미래 임의의 조건(날짜, 역, 시간대, 상/하행, 날씨 등)에서
열차 재차인원(Load)을 초고속으로 정확하게 예측하는 모델을 훈련합니다.
"""

import sys
import json
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib

DATASET_PATH = Path("./outputs/ground_truth_train_loads.csv")
MODEL_OUT_PATH = Path("./outputs/load_predictor.joblib")
METRICS_OUT_PATH = Path("./outputs/model_metrics.json")

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]

def train_model():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"학습용 정답 데이터셋이 없습니다: {DATASET_PATH}\n먼저 generate_ground_truth.py를 실행하세요.")

    print(f"데이터셋 로딩 중: {DATASET_PATH}")
    df = pd.read_csv(DATASET_PATH)
    print(f"  총 샘플 수: {len(df):,}건, 기간: {df['date'].min()} ~ {df['date'].max()}")

    # 피처 정의
    feature_cols = [
        "station_idx", "hour", "dir_code", "is_weekend",
        "temp", "precip", "snow", "plan_version"
    ]
    target_col = "load"

    X = df[feature_cols]
    y = df[target_col]

    # 날짜 기준 시간 순 분할 (마지막 20%를 테스트/검증셋으로 사용)
    dates = sorted(df["date"].unique())
    split_idx = int(len(dates) * 0.8)
    if split_idx >= len(dates):
        split_idx = len(dates) - 1

    train_dates = set(dates[:split_idx])
    val_dates = set(dates[split_idx:])

    if not val_dates:
        # 날짜 수가 너무 적을 경우 인덱스 기준 분할
        train_mask = np.random.rand(len(df)) < 0.8
        X_train, y_train = X[train_mask], y[train_mask]
        X_val, y_val = X[~train_mask], y[~train_mask]
        print(f"  단기 데이터로 인덱스 기준 분할: Train {len(X_train):,}, Val {len(X_val):,}")
    else:
        train_mask = df["date"].isin(train_dates)
        val_mask = df["date"].isin(val_dates)
        X_train, y_train = X[train_mask], y[train_mask]
        X_val, y_val = X[val_mask], y[val_mask]
        print(f"  시간 분할: Train {len(X_train):,} ({len(train_dates)}일), Val {len(X_val):,} ({len(val_dates)}일)")

    # HistGradientBoostingRegressor 모델 학습 (LightGBM 호환 알고리즘)
    print("모델 학습 시작 (HistGradientBoostingRegressor)...")
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        categorical_features=[0, 2, 3, 7], # station_idx, dir_code, is_weekend, plan_version
        max_iter=300,
        learning_rate=0.08,
        max_leaf_nodes=31,
        min_samples_leaf=20,
        random_state=42
    )

    model.fit(X_train, y_train)

    # 평가
    y_pred_train = np.clip(model.predict(X_train), 0, None)
    y_pred_val = np.clip(model.predict(X_val), 0, None)

    tr_mae = mean_absolute_error(y_train, y_pred_train)
    tr_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
    tr_r2 = r2_score(y_train, y_pred_train)

    val_mae = mean_absolute_error(y_val, y_pred_val)
    val_rmse = np.sqrt(mean_squared_error(y_val, y_pred_val))
    val_r2 = r2_score(y_val, y_pred_val)

    print("\n" + "=" * 55)
    print(" [모델 평가 결과]")
    print("=" * 55)
    print(f" 학습 데이터  | MAE: {tr_mae:6.2f}명 | RMSE: {tr_rmse:6.2f}명 | R²: {tr_r2:6.4f}")
    print(f" 검증 데이터  | MAE: {val_mae:6.2f}명 | RMSE: {val_rmse:6.2f}명 | R²: {val_r2:6.4f}")
    print("=" * 55)

    # 주요 역별 검증 오차 확인 (상위 혼잡역)
    val_df = df[val_mask].copy() if len(val_dates) > 0 else df[~train_mask].copy()
    val_df["pred_load"] = y_pred_val
    val_df["abs_err"] = np.abs(val_df["load"] - val_df["pred_load"])

    print("\n[주요 역별 검증 MAE]")
    print(f"{'역명':<10} {'실제평균재차':>12} {'예측평균재차':>12} {'MAE':>10}")
    print("-" * 50)
    for s_idx in [10, 11, 15, 3, 0, 21]: # 시청, 정부청사, 유성온천, 대전, 판암, 반석
        s_name = STATION_NAMES[s_idx]
        sdf = val_df[val_df["station_idx"] == s_idx]
        if len(sdf) > 0:
            print(f"{s_name:<10} {sdf['load'].mean():>12.1f}명 {sdf['pred_load'].mean():>12.1f}명 {sdf['abs_err'].mean():>10.2f}명")

    # 모델 및 메타데이터 저장
    joblib.dump(model, MODEL_OUT_PATH)
    metrics = {
        "train_mae": float(tr_mae),
        "train_rmse": float(tr_rmse),
        "train_r2": float(tr_r2),
        "val_mae": float(val_mae),
        "val_rmse": float(val_rmse),
        "val_r2": float(val_r2),
        "features": feature_cols,
        "n_samples": len(df),
    }
    with open(METRICS_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"\n모델 저장 완료: {MODEL_OUT_PATH}")

if __name__ == "__main__":
    train_model()
