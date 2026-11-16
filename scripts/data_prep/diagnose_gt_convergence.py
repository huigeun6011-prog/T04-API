"""Small, non-destructive convergence experiment using the production GT solver.

Only iteration count and a seeded perturbation of the initial logits change.
The production function is instrumented in memory; models/GT are never saved.
"""
import argparse
import hashlib
import inspect
import ast
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import generate_ground_truth as gt

CASES = {
    "2025-01-16": "before_weekday",
    "2025-01-18": "before_holiday",
    "2026-04-01": "after_weekday",
    "2026-04-04": "after_holiday_uses_old_holiday_schedule",
    "2026-10-20": "ordinary_weekday_with_peak_case",
    "2025-08-14": "large_midnight_gate_counts_schedule_exception_possible",
}


def quantiles(values):
    return {str(q): float(np.quantile(values, q)) for q in (0, .5, .9, .95, .99, 1)}


def collect_diagnostics(context):
    b, a = context["b_stops"], context["a_stops"]
    terminals, paths = [], []
    for start, end, _ in context["train_slices"]:
        path = np.cumsum((b[start:end] - a[start:end]).astype(np.float64))
        paths.extend(path)
        terminals.append(path[-1])
    terminals, paths = np.asarray(terminals), np.asarray(paths)
    p, q = context["get_full_pq"]()
    p, q = p.detach().cpu().numpy(), q.detach().cpu().numpy()
    prior = np.mean((p[1:-1]-context["p_prior"][1:-1])**2) + np.mean((q[1:-1]-context["q_prior"][1:-1])**2)
    term_loss = float(np.mean(terminals**2))
    negative_loss = float(np.mean(np.minimum(paths, 0)**2))
    s, h = np.asarray(context["all_s_idx"]), np.asarray(context["all_h_idx"])
    b_alloc = np.zeros_like(context["B_obs"], dtype=np.float64)
    a_alloc = np.zeros_like(context["A_obs"], dtype=np.float64)
    np.add.at(b_alloc, (s, h), b)
    np.add.at(a_alloc, (s, h), a)
    result = {
        "n_trains": len(terminals), "n_stops": len(paths),
        "terminal_loss": term_loss, "negative_loss": negative_loss,
        "prior_loss_unweighted": float(prior), "prior_loss_weighted": float(2*prior),
        "total_loss": float(term_loss + negative_loss + 2*prior),
        "terminal_abs_quantiles": quantiles(np.abs(terminals)),
        "terminal_signed_quantiles": quantiles(terminals),
        "terminal_nonzero_gt_0_015": int((np.abs(terminals) > .015).sum()),
        "negative_stop_count_gt_0_015": int((paths < -.015).sum()),
        "raw_load_min": float(paths.min()),
        "negative_stop_abs_max": float(-min(paths.min(),0)),
    }
    for name, obs, alloc in (("board", context["B_obs"], b_alloc), ("alight", context["A_obs"], a_alloc)):
        diff = obs-alloc
        result[name+"_observed_total"] = float(obs.sum())
        result[name+"_unallocated_total"] = float(diff.sum())
        result[name+"_unallocated_abs_max"] = float(np.abs(diff).max())
        result[name+"_unallocated_cells_gt_0_01"] = int((np.abs(diff)>.01).sum())
        result[name+"_unallocated_abs_quantiles"] = quantiles(np.abs(diff).ravel())
        result[name+"_midnight_unallocated_total"] = float(diff[:, -1].sum())
    return result


def instrument_solver():
    baseline = gt.ROOT/"outputs/diagnostics/gt_solver_before_improvement.py"
    if not baseline.exists():
        raise FileNotFoundError("이 비교는 개선 전 solver 보관본이 필요합니다: "+str(baseline))
    archived_source = baseline.read_text(encoding="utf-8")
    node = next(node for node in ast.parse(archived_source).body if isinstance(node, ast.FunctionDef) and node.name=="process_single_date")
    source = ast.get_source_segment(archived_source, node)
    source = source.replace("weather_file, device):", "weather_file, device, epochs=200, init_seed=None):", 1)
    source = source.replace("for _ in range(200):", "for _ in range(epochs):", 1)
    needle = "    p_logits = torch.nn.Parameter(torch.tensor(p_logit_init, device=device))"
    assert needle in source
    source = source.replace(needle, "    if init_seed is not None:\n        rng = np.random.default_rng(init_seed)\n        p_logit_init += rng.normal(0, .25, p_logit_init.shape).astype(np.float32)\n        q_logit_init += rng.normal(0, .25, q_logit_init.shape).astype(np.float32)\n" + needle, 1)
    needle = "    # 날씨 파싱"
    assert needle in source
    source = source.split(needle)[0] + "    return collect_diagnostics(locals())\n"
    namespace = dict(gt.__dict__, collect_diagnostics=collect_diagnostics)
    exec(compile(source, "<instrumented_production_gt>", "exec"), namespace)
    return namespace["process_single_date"]


def run_one(solver, date, epochs, seed):
    next_date = (pd.Timestamp(date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    started=time.perf_counter()
    result=solver(date, gt.SUBWAY_DIR/f"{date}.json", gt.SUBWAY_DIR/f"{next_date}.json", gt.WEATHER_DIR/f"{date}.json", torch.device("cpu"), epochs, seed)
    return dict(service_date=date, case=CASES[date], epochs=epochs, init_seed=seed,
                init_logit_noise_std=0 if seed is None else .25,
                seconds=time.perf_counter()-started, **result)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--benchmark-only", action="store_true")
    args=parser.parse_args()
    torch.set_num_threads(1)
    solver=instrument_solver()
    first=run_one(solver,next(iter(CASES)),200,None)
    print(json.dumps({"benchmark_seconds_200":first["seconds"], "estimated_full_experiment_seconds":first["seconds"]*(6*3700/200)}, ensure_ascii=False),flush=True)
    if args.benchmark_only:
        return
    rows=[]
    for date in CASES:
        for epochs,seed in ((200,None),(500,None),(1000,None),(1000,11),(1000,29)):
            row=first if date==first["service_date"] and epochs==200 and seed is None else run_one(solver,date,epochs,seed)
            rows.append(row)
            print(json.dumps({k:row[k] for k in ("service_date","epochs","init_seed","seconds","total_loss","terminal_loss","negative_loss","raw_load_min","board_unallocated_total","alight_unallocated_total")}),flush=True)
    output=gt.ROOT/"outputs/diagnostics"
    output.mkdir(parents=True,exist_ok=True)
    payload={"purpose":"Convergence diagnostic only; no fitting to actual peak measurements and no production artifacts replaced", "source_sha256":hashlib.sha256((gt.ROOT/"outputs/diagnostics/gt_solver_before_improvement.py").read_bytes()).hexdigest(), "learning_rate":.1,"loss_weights":{"terminal":1,"negative":1,"prior":2},"runs":rows}
    (output/"gt_convergence.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    flat=[]
    for row in rows:
        item={k:v for k,v in row.items() if not isinstance(v,dict)}
        item.update({key+"_q"+q:value for key,v in row.items() if isinstance(v,dict) for q,value in v.items()})
        flat.append(item)
    pd.DataFrame(flat).to_csv(output/"gt_convergence.csv",index=False,encoding="utf-8-sig")


if __name__=="__main__":
    main()
