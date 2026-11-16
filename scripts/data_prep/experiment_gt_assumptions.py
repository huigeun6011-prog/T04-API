"""Causal ablations of temporal, weekday-pooling and boarding-headway assumptions.

Actual peak passenger measurements are never read by this experiment.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
import torch
import generate_ground_truth as gt
import gt_assumptions
from gt_assumptions import AssumptionConfig, WeekdayTemplates

CASES={
    "2025-01-16":"before_weekday",
    "2025-01-18":"before_saturday",
    "2026-05-13":"after_weekday_with_past_same_weekday",
    "2026-05-16":"after_saturday_with_past_same_weekday",
    "2026-10-21":"ordinary_after_weekday",
    "2025-08-14":"midnight_gate_schedule_mismatch_possible",
}
VARIANTS={
    "baseline":AssumptionConfig(),
    "temporal":AssumptionConfig(temporal_weight=1000),
    "weekday_pooling":AssumptionConfig(pooling_weight=1000),
    "boarding_headway":AssumptionConfig(boarding_headway=True),
    "all":AssumptionConfig(temporal_weight=1000,pooling_weight=1000,boarding_headway=True),
}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--epochs",type=int,default=1000)
    parser.add_argument("--template-source",type=Path,default=gt.ROOT/"outputs/diagnostics/candidate_training/ground_truth_train_loads.csv")
    parser.add_argument("--output-dir",type=Path,default=gt.ROOT/"outputs/diagnostics/assumption_ablation")
    parser.add_argument("--seeds",default="none,11")
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    bank_path=args.output_dir/"weekday_observations.npz"
    if bank_path.exists():
        bank=WeekdayTemplates.load(bank_path)
        with args.template_source.open("rb") as source:
            current_hash=hashlib.file_digest(source,"sha256").hexdigest()
        if current_hash!=bank.source_hash:
            raise ValueError("template cache와 source SHA256이 다릅니다. 새 output-dir에서 추출하세요.")
    else:
        started=time.perf_counter()
        bank=WeekdayTemplates.from_dataset(args.template_source,gt.HOLIDAYS)
        bank.save(bank_path)
        print(json.dumps({"template_extraction_seconds":time.perf_counter()-started,"n_independent_dates":len(bank.dates)}),flush=True)
    seed_values=[None if value=="none" else int(value) for value in args.seeds.split(",")]
    rows=[]
    (args.output_dir/"runs.jsonl").write_text("",encoding="utf-8")
    started_all=time.perf_counter()
    for date,case in CASES.items():
        tomorrow=(pd.Timestamp(date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        snapshot=bank.snapshot(date,gt.HOLIDAYS,exclude_dates=CASES)
        for variant,config in VARIANTS.items():
            for seed in seed_values:
                started=time.perf_counter()
                diag={}
                records=gt.process_single_date(date,gt.SUBWAY_DIR/f"{date}.json",gt.SUBWAY_DIR/f"{tomorrow}.json",gt.WEATHER_DIR/f"{date}.json",torch.device("cpu"),epochs=args.epochs,patience=0,init_seed=seed,diagnostics=diag,assumptions=config,weekday_template=snapshot if config.pooling_weight else None,capture_ratios=True)
                p=np.asarray(diag.pop("p_values"));q=np.asarray(diag.pop("q_values"))
                frame=pd.DataFrame(records)
                previous=frame.groupby("train_id",sort=False).raw_load.shift(fill_value=0)
                raw_error=(frame.raw_load-previous-frame.board+frame.alight).abs()
                assert raw_error.max()<1.6e-6
                assert (frame.load>=0).all()
                assert (frame.loc[frame.is_origin==1,"alight"]==0).all()
                assert np.allclose(frame.load,frame.raw_load+frame.load_correction,atol=1.1e-6)
                if config.boarding_headway:
                    emitted=np.array([sum(amount for _,amount in json.loads(item)) for item in frame.boarding_sources])
                    assert np.max(np.abs(emitted-frame.board.to_numpy()))<3e-6
                slack=diag.pop("unallocated")
                for kind in ("board","alight"):
                    unallocated=sum(item["unallocated"] for item in slack if item["kind"]==kind)
                    diag[kind+"_unallocated_total"]=unallocated
                    diag[kind+"_allocation_numeric_error"]=diag[kind+"_observed_total"]-diag[kind+"_allocated_total"]-unallocated
                    assert abs(diag[kind+"_allocation_numeric_error"])<.1
                pool_dist=[]
                for name,value in (("p",p),("q",q)):
                    confidence=snapshot[name+"_confidence"][1:-1]
                    if (confidence>0).any():
                        pool_dist.extend(((value[1:-1]-snapshot[name][1:-1])**2)[confidence>0])
                row=dict(variant=variant,service_date=date,case=case,seed=seed,seconds=time.perf_counter()-started,
                         raw_conservation_error_max=float(raw_error.max()),
                         ratio_adjacent_abs_mean=float((np.abs(np.diff(p[1:-1],axis=1)).mean()+np.abs(np.diff(q[1:-1],axis=1)).mean())/2),
                         same_weekday_template_mse=float(np.mean(pool_dist)) if pool_dist else None,
                         template_training_dates=snapshot["n_dates"],template_last_training_date=snapshot["last_training_date"],
                         template_key=snapshot["group"],config=asdict(config),**diag)
                rows.append(row)
                print(json.dumps({k:row[k] for k in ("variant","service_date","seed","seconds","terminal_loss","negative_loss","board_unallocated_total","alight_unallocated_total")}),flush=True)
                # Write incrementally so an interrupted run remains reviewable.
                with (args.output_dir/"runs.jsonl").open("a",encoding="utf-8") as stream:
                    stream.write(json.dumps(row,ensure_ascii=False)+"\n")
    result={"purpose":"Causal assumption ablations; no actual peak passenger measurements used", "same_iteration_budget":args.epochs,"patience":0,"initial_logit_noise_std":.25,"seeds":seed_values,"elapsed_seconds":time.perf_counter()-started_all,"template_source":str(args.template_source),"template_source_sha256":bank.source_hash,"evaluation_dates_excluded_from_templates":list(CASES),"template_window_days":112,"weekday_definition":"0=Monday..6=Sunday; listed public holidays=7; plan versions separate","boarding_definition":"uniform within-hour arrivals integrated over preceding scheduled departure interval; first train uses 05:00 opening; midnight continuous; after both last departures explicit unallocated; alighting unchanged","n_parameters_per_day":800,"variants":{key:asdict(config) for key,config in VARIANTS.items()},"source_sha256":{str(Path(module.__file__).name):hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (gt,)},"runs":rows}
    result["source_sha256"][Path(gt_assumptions.__file__).name]=hashlib.sha256(Path(gt_assumptions.__file__).read_bytes()).hexdigest()
    result["runner_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.output_dir/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    scalar_rows=[{key:value for key,value in row.items() if not isinstance(value,dict)} for row in rows]
    pd.DataFrame(scalar_rows).to_csv(args.output_dir/"results.csv",encoding="utf-8-sig",index=False)
    print(json.dumps({"completed_runs":len(rows),"elapsed_seconds":result["elapsed_seconds"]}),flush=True)


if __name__=="__main__":
    main()
