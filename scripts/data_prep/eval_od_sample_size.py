"""표본 크기 점검 평가: 61일·122일 OD 라벨 모델을 홀드아웃 31일의 OD 라벨에 대조. 기준: outputs/diagnostics/od_labels/size_check_criteria.md"""
import json
import sys
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
B = ROOT / "outputs/diagnostics/od_labels"
models = {"m61": joblib.load(B / "sample61/od_predictor.joblib"), "m122": joblib.load(B / "sample122/od_predictor.joblib")}
h = pd.read_csv(B / "holdout31/dataset.csv")
feats = list(models["m61"].feature_names_in_)
assert feats == list(models["m122"].feature_names_in_)
for k, m in models.items():
    h[k] = np.maximum(m.predict(h[feats]), 0)
cells = h.groupby(["date", "station_idx", "dir_code", "hour"])[["load", "m61", "m122"]].mean().reset_index()


def sp(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or a.std() == 0 or b.std() == 0:
        return np.nan
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


res = {"holdout_days": int(h.date.nunique()), "rows": int(len(h)), "cells": int(len(cells))}
for k in ("m61", "m122"):
    res[k] = dict(row_mae=float((h[k] - h["load"]).abs().mean()), cell_mae=float((cells[k] - cells["load"]).abs().mean()),
                  cell_rel_mae=float((cells[k] - cells["load"]).abs().sum() / cells["load"].sum()), sum_ratio=float(cells[k].sum() / cells["load"].sum()),
                  cell_spearman=sp(cells["load"], cells[k]))
rows = []
g = cells[(cells.hour >= 7) & (cells.hour <= 22)]
for (d, s, dr), x in g.groupby(["date", "station_idx", "dir_code"]):
    if len(x) < 14 or x["load"].max() < 20:
        continue
    tr = x["load"].rank(method="first").to_numpy()
    row = dict(date=d, s=int(s), dir=int(dr))
    for k in ("m61", "m122"):
        er = x[k].rank(method="first").to_numpy(); diff = np.abs(tr - er)
        row[f"{k}_sp"] = sp(x["load"], x[k])
        for c in (0, 1, 2):
            row[f"{k}_le{c}"] = float((diff <= c).mean())
        row[f"{k}_top1"] = float(x.hour.iloc[int(np.argmin(x[k].to_numpy()))] == x.hour.iloc[int(np.argmin(x["load"].to_numpy()))])
    rows.append(row)
p = pd.DataFrame(rows)
res["orderings"] = int(len(p))
for k in ("m61", "m122"):
    res[k].update({m: float(p[f"{k}_{m}"].mean()) for m in ("sp", "le0", "le1", "le2", "top1")})
res["between_models"] = dict(cell_spearman=sp(cells.m61, cells.m122), sum_ratio=float(cells.m122.sum() / cells.m61.sum()))
better = (res["m122"]["cell_rel_mae"] <= 0.95 * res["m61"]["cell_rel_mae"]) or (res["m122"]["sp"] - res["m61"]["sp"] >= 0.01) or (res["m122"]["le2"] - res["m61"]["le2"] >= 0.02)
res["verdict"] = "122일이 눈에 띄게 낫다" if better else "61일이면 충분"
res["checks"] = dict(rel_mae_ratio_122_over_61=res["m122"]["cell_rel_mae"] / res["m61"]["cell_rel_mae"], d_sp=res["m122"]["sp"] - res["m61"]["sp"], d_le2=res["m122"]["le2"] - res["m61"]["le2"])
(B / "size_check_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
p.to_csv(B / "size_check_orderings.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
print(json.dumps(res, ensure_ascii=False, indent=1))
