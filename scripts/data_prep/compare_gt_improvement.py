"""Compare solver changes without touching production GT/model artifacts."""
import ast
import inspect
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import generate_ground_truth as gt
from diagnose_gt_convergence import collect_diagnostics

CASES = {
    "2025-01-16": "before_weekday",
    "2025-01-18": "before_holiday",
    "2026-04-01": "after_weekday",
    "2026-04-04": "after_holiday",
    "2026-10-21": "ordinary_weekday_not_selected_from_peak_measurements",
    "2025-08-14": "midnight_allocation_anomaly_selected_from_gate_conservation_audit",
}


def old_solver():
    archive=gt.ROOT/"outputs/diagnostics/gt_solver_before_improvement.py"
    text=archive.read_text(encoding="utf-8")
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=="process_single_date")
    source=ast.get_source_segment(text,node)
    source=source.replace("weather_file, device):", "weather_file, device, epochs=200):",1)
    source=source.replace("for _ in range(200):", "for _ in range(epochs):",1)
    source=source.split("    # 날씨 파싱")[0]+"    return collect_diagnostics(locals())\n"
    ns=dict(gt.__dict__,collect_diagnostics=collect_diagnostics)
    exec(compile(source,"<archived_gt_solver>","exec"),ns)
    return ns["process_single_date"]


def main():
    torch.set_num_threads(1)
    old=old_solver()
    results=[]
    for date,case in CASES.items():
        next_date=(pd.Timestamp(date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        args=(date,gt.SUBWAY_DIR/f"{date}.json",gt.SUBWAY_DIR/f"{next_date}.json",gt.WEATHER_DIR/f"{date}.json",torch.device("cpu"))
        for version,epochs,seed in (("old",200,None),("old",1000,None),("improved",200,None),("improved",1000,None),("improved",1000,11),("improved",1000,29)):
            started=time.perf_counter()
            if version=="old":
                diag=old(*args,epochs=epochs)
            else:
                diag={}
                rows=gt.process_single_date(*args,epochs=epochs,init_seed=seed,diagnostics=diag)
                slack=diag.pop("unallocated")
                for kind in ("board","alight"):
                    diag[kind+"_unallocated_total"]=sum(x["unallocated"] for x in slack if x["kind"]==kind)
                    diag[kind+"_unallocated_cells"]=sum(x["kind"]==kind for x in slack)
                    diag[kind+"_allocation_numeric_error"]=diag[kind+"_allocated_total"]-(diag[kind+"_observed_total"]-diag[kind+"_unallocated_total"])
                # Every emitted correction is reproducible from the stored raw
                # trajectory, rather than being silently added per stop.
                frame=pd.DataFrame(rows)
                group=frame.groupby("train_id",sort=False)
                prev=group.raw_load.shift(fill_value=0)
                local_error=frame.raw_load-prev-frame.board+frame.alight
                assert local_error.abs().max()<1.6e-6
                assert np.allclose(frame.load,frame.raw_load+frame.load_correction,atol=1.1e-6)
                assert (frame.load>=0).all()
                assert (frame.loc[frame.is_origin==1,"alight"]==0).all()
                diag["row_raw_conservation_error_max"]=float(local_error.abs().max())
                diag["visible_terminal_positive_count"]=int(((frame.is_destination==1)&(frame.load>.015)).sum())
            result=dict(version=version,service_date=date,case=case,epochs=epochs,init_seed=seed,seconds=time.perf_counter()-started,**diag)
            results.append(result)
            print(json.dumps({k:result[k] for k in ("version","service_date","epochs","init_seed","seconds","terminal_loss","negative_loss","raw_load_min","board_unallocated_total","alight_unallocated_total")}),flush=True)
    out=gt.ROOT/"outputs/diagnostics"
    (out/"gt_improvement_comparison.json").write_text(json.dumps({"purpose":"Conservation and convergence comparison; actual peak measurements not read or used", "runs":results},ensure_ascii=False,indent=2),encoding="utf-8")
    flat=[]
    for result in results:
        item={k:v for k,v in result.items() if not isinstance(v,dict)}
        item.update({key+"_q"+q:value for key,entry in result.items() if isinstance(entry,dict) for q,value in entry.items()})
        flat.append(item)
    pd.DataFrame(flat).to_csv(out/"gt_improvement_comparison.csv",index=False,encoding="utf-8-sig")


if __name__=="__main__":
    main()
