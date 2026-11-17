"""Step 3: 라벨 방식이 바뀌면 추천이 달라지는가 (후보 OD 모델 vs production).

모델마다 별도 프로세스로 질의를 돌려 JSON으로 저장하고(run), 두 JSON을 비교한다(compare).
  python compare_od_vs_production_recommend.py run --model <joblib> --out <json>
  python compare_od_vs_production_recommend.py compare --a <production.json> --b <candidate.json> --out <report.json>
질의 묶음과 판정 기준은 실행 전에 고정한 값이며 결과를 보고 바꾸지 않는다.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATES = ["2026-10-21", "2026-10-24"]
ORIGINS = ["반석", "시청", "대전", "판암", "유성온천"]
HOURS = [(7, 9), (12, 14), (17, 19)]
QUIET_WEIGHT, CATEGORY, LIMIT = 50, "all", 20
THRESH_SAME, THRESH_PART = 0.8, 0.5


def poi_key(r):
    p = r["poi"]
    return str(p.get("id")) if p.get("id") not in (None, "") else f"{p.get('name')}|{p.get('address')}"


def run(model, out):
    import prediction_api as api
    api.MODEL_PATH = Path(model)
    st = {s["name"]: s for s in api.stations()}
    queries = []
    for d in DATES:
        for o in ORIGINS:
            for s, e in HOURS:
                payload = dict(date=d, start_hour=s, end_hour=e, quiet_weight=QUIET_WEIGHT, category=CATEGORY,
                               origin=dict(lat=st[o]["lat"], lng=st[o]["lng"]), limit=LIMIT)
                top = api.recommend(payload)["results"]
                wide = api.recommend({**payload, "limit": 200})["results"]  # 점수 Spearman용(전체 장소)
                slim = lambda rs: [dict(key=poi_key(r), score=r["score"], hour=r["hour"], mean_load=r["mean_load"], no_train=r["no_train"]) for r in rs]
                queries.append(dict(date=d, origin=o, start=s, end=e, top=slim(top), wide=slim(wide)))
    # 모델 수준: 역·시간·방향 평균 예측 (두 날짜의 날씨, 운행 열차가 지나는 조합)
    cells = {}
    for d in DATES:
        trains = api.schedule(d)
        hrs = set()
        for t in trains:
            for s in t["stops"][:-1]:
                hrs.add(int(s["time"].split(":")[0]) or 24)
        weather, _ = api.weather_profile(d, hrs)
        keys, feats = [], []
        for t in trains:
            for s in t["stops"][:-1]:
                h = int(s["time"].split(":")[0]) or 24
                k = (s["station"], h, t["direction"])
                if k in keys or h not in weather:
                    continue
                keys.append(k)
                feats.append([api.STATION_NAMES.index(s["station"]), h, 0 if t["direction"] == "상행" else 1,
                              int(api.holiday(d)), *weather[h], int(d >= api.CHANGE)])
        pred = np.maximum(api.get_model().predict(pd.DataFrame(feats, columns=api.FEATURES)), 0)
        for k, v in zip(keys, pred):
            cells[f"{d}|{k[0]}|{k[1]}|{k[2]}"] = float(v)
    Path(out).write_text(json.dumps(dict(model=str(model), queries=queries, cells=cells), ensure_ascii=False), encoding="utf-8")
    print("saved", out, len(queries), "queries", len(cells), "cells")


def spearman(a, b):
    if len(a) < 3:
        return None
    r = pd.Series(a).rank().corr(pd.Series(b).rank())
    return None if pd.isna(r) else float(r)


def compare(a_path, b_path, out):
    A = json.loads(Path(a_path).read_text(encoding="utf-8"))
    B = json.loads(Path(b_path).read_text(encoding="utf-8"))
    rows = []
    for qa, qb in zip(A["queries"], B["queries"]):
        assert (qa["date"], qa["origin"], qa["start"]) == (qb["date"], qb["origin"], qb["start"])
        ta, tb = [x["key"] for x in qa["top"][:10]], [x["key"] for x in qb["top"][:10]]
        sa, sb = set(ta), set(tb)
        jac = len(sa & sb) / len(sa | sb) if sa | sb else None
        wa, wb = {x["key"]: x["score"] for x in qa["wide"]}, {x["key"]: x["score"] for x in qb["wide"]}
        common = sorted(set(wa) & set(wb))
        rho = spearman([wa[k] for k in common], [wb[k] for k in common])
        walk_a = float(np.mean([x["no_train"] for x in qa["top"]])) if qa["top"] else None
        walk_b = float(np.mean([x["no_train"] for x in qb["top"]])) if qb["top"] else None
        ha = {x["key"]: x["hour"] for x in qa["top"] if x["hour"] is not None}
        hb = {x["key"]: x["hour"] for x in qb["top"] if x["hour"] is not None}
        hc = [abs(ha[k] - hb[k]) for k in set(ha) & set(hb)]
        rows.append(dict(date=qa["date"], origin=qa["origin"], hours=f"{qa['start']}-{qa['end']}", jaccard_top10=jac,
                         spearman_all_scores=rho, walk_only_prod=walk_a, walk_only_cand=walk_b,
                         mean_abs_hour_diff=float(np.mean(hc)) if hc else None))
    df = pd.DataFrame(rows)
    ca, cb = A["cells"], B["cells"]
    keys = sorted(set(ca) & set(cb))
    va, vb = np.array([ca[k] for k in keys]), np.array([cb[k] for k in keys])
    mean_j = float(df.jaccard_top10.mean())
    verdict = "추천이 거의 같다" if mean_j >= THRESH_SAME else ("부분적으로 다르다" if mean_j >= THRESH_PART else "크게 다르다")
    summary = dict(n_queries=len(df), mean_jaccard_top10=mean_j, min_jaccard=float(df.jaccard_top10.min()),
                   mean_spearman_scores=float(df.spearman_all_scores.mean()),
                   mean_walk_only_prod=float(df.walk_only_prod.mean()), mean_walk_only_cand=float(df.walk_only_cand.mean()),
                   mean_abs_hour_diff=float(df.mean_abs_hour_diff.mean()),
                   model_cells=len(keys), model_spearman=spearman(va, vb),
                   model_ratio_mean_cand_over_prod=float(vb.mean() / va.mean()), prod_mean=float(va.mean()), cand_mean=float(vb.mean()),
                   thresholds=dict(same=THRESH_SAME, partial=THRESH_PART), verdict=verdict)
    Path(out).with_suffix(".csv").write_text(df.to_csv(index=False), encoding="utf-8-sig")
    Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--model", required=True); r.add_argument("--out", required=True)
    c = sub.add_parser("compare"); c.add_argument("--a", required=True); c.add_argument("--b", required=True); c.add_argument("--out", required=True)
    args = ap.parse_args()
    run(args.model, args.out) if args.cmd == "run" else compare(args.a, args.b, args.out)
