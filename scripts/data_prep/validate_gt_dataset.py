"""Audit a generated dataset against raw arithmetic and station/hour budgets."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import generate_ground_truth as gt


def qs(values):
    return {str(q): float(np.quantile(values,q)) for q in (.5,.9,.95,.99,1)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    cols=["date","train_id","station_idx","hour","time","board","alight","raw_load","load_correction","terminal_raw_residual","load","is_origin","is_destination"]
    frame=pd.read_csv(args.dataset,usecols=cols,dtype={"date":"category","train_id":"category","time":"category","station_idx":"int16","hour":"int16","is_origin":"int8","is_destination":"int8"})
    group=frame.groupby(["date","train_id"],observed=True,sort=False)
    previous=group.raw_load.shift(fill_value=0)
    error=frame.raw_load-previous-frame.board+frame.alight
    raw_error_max=float(error.abs().max())
    projected_error=(frame.load-frame.raw_load-frame.load_correction).abs()
    first=group.cumcount()==0;last=group.cumcount(ascending=False)==0
    # Arrival times are service-day HH:MM (including 24:xx).
    minute=frame.time.astype(str).str.split(":",expand=True).astype(int)
    time_value=minute[0]*60+minute[1]
    time_diff=time_value.groupby([frame.date,frame.train_id],observed=True).diff()
    report={"rows":len(frame),"trains":int(first.sum()),"service_days":frame.date.nunique(),
            "raw_conservation_tolerance":1.6e-6,"raw_conservation_error_max":raw_error_max,
            "raw_conservation_violations":int((error.abs()>1.6e-6).sum()),
            "projection_identity_violations":int((projected_error>1.1e-6).sum()),
            "nonfinite_counts":{key:int((~np.isfinite(frame[key])).sum()) for key in ("board","alight","raw_load","load_correction","load")},
            "negative_board":int((frame.board<0).sum()),"negative_alight":int((frame.alight<0).sum()),"negative_load":int((frame.load<0).sum()),
            "raw_negative_stops":int((frame.raw_load<-.015).sum()),"raw_load_min":float(frame.raw_load.min()),
            "load_correction_count":int((frame.load_correction>0).sum()),"load_correction_total":float(frame.load_correction.sum()),
            "first_not_origin":int((first&(frame.is_origin!=1)).sum()),"last_not_terminal":int((last&(frame.is_destination!=1)).sum()),
            "first_preboarding_nonzero":int((first&((frame.raw_load-frame.board+frame.alight).abs()>1.6e-6)).sum()),
            "origin_alight_nonzero":int(((frame.is_origin==1)&(frame.alight!=0)).sum()),
            "terminal_board_nonzero":int(((frame.is_destination==1)&(frame.board!=0)).sum()),
            "nonincreasing_time_steps":int((time_diff<=0).sum()),
            "terminal_abs_quantiles":qs(frame.loc[frame.is_destination==1,"raw_load"].abs()),
            "terminal_positive_load_count":int(((frame.is_destination==1)&(frame.load>.015)).sum()),
            "label_policy":"load=max(raw cumulative board-alight,0); no terminal overwrite; correction retained; residual constraints soft"}
    aggregate=frame.groupby(["date","station_idx","hour"],observed=True)[["board","alight"]].sum().reset_index()
    if "boarding_sources" in pd.read_csv(args.dataset,nrows=0).columns:
        # Boarding gate-hour and train stop-hour can differ in headway mode.
        # Validate the original gate-hour budget using emitted provenance.
        source_groups=[]
        for chunk in pd.read_csv(args.dataset,usecols=["date","station_idx","boarding_sources"],chunksize=100000):
            source_rows=[]
            for date,station,encoded in chunk.itertuples(index=False,name=None):
                source_rows.extend((date,station,hour,amount) for hour,amount in json.loads(encoded))
            if source_rows:
                source_groups.append(pd.DataFrame(source_rows,columns=["date","station_idx","hour","board"]).groupby(["date","station_idx","hour"]).board.sum())
        boarding=pd.concat(source_groups).groupby(level=[0,1,2]).sum().reset_index()
        aggregate=aggregate.drop(columns="board").merge(boarding,how="outer",on=["date","station_idx","hour"]).fillna(0)
        report["boarding_budget_clock"]="gate source hour from boarding_sources, not train stop hour"
    else:
        report["boarding_budget_clock"]="same source and stop hour (uniform-per-train baseline)"
    raw=[]
    for date in sorted(frame.date.unique()):
        tomorrow=(pd.Timestamp(date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        curr=json.loads((gt.SUBWAY_DIR/f"{date}.json").read_text(encoding="utf-8"))["stations"]
        nxt=json.loads((gt.SUBWAY_DIR/f"{tomorrow}.json").read_text(encoding="utf-8"))["stations"]
        for sid in range(101,123):
            for hour in range(5,25):
                source=(nxt if hour==24 else curr)[str(sid)]
                key="0" if hour==24 else str(hour)
                raw.append((date,sid-101,hour,source["boardings"].get(key,0),source["alightings"].get(key,0)))
    budget=pd.DataFrame(raw,columns=["date","station_idx","hour","board_obs","alight_obs"]).merge(aggregate,how="left",on=["date","station_idx","hour"]).fillna(0)
    slack=pd.read_csv(args.dataset.with_suffix(".unallocated.csv"))
    for kind in ("board","alight"):
        unallocated=slack[slack.kind==kind].rename(columns={"unallocated":kind+"_slack"})
        budget=budget.merge(unallocated[["date","station_idx","hour",kind+"_slack"]],how="left",on=["date","station_idx","hour"]).fillna(0)
        residual=budget[kind+"_obs"]-budget[kind]-budget[kind+"_slack"]
        report[kind+"_budget"]={"cells":len(budget),"observed_total":float(budget[kind+"_obs"].sum()),"allocated_total":float(budget[kind].sum()),"explicit_unallocated_total":float(budget[kind+"_slack"].sum()),"unallocated_cells":len(unallocated),"unexplained_error_abs_max":float(residual.abs().max()),"unexplained_error_abs_quantiles":qs(residual.abs()),"unexplained_over_0_001_count":int((residual.abs()>.001).sum()),"tolerance":.001}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert raw_error_max<1.6e-6
    assert report["projection_identity_violations"]==0
    assert all(value==0 for value in report["nonfinite_counts"].values())
    assert all(report[key]==0 for key in ("negative_board","negative_alight","negative_load","first_not_origin","last_not_terminal","first_preboarding_nonzero","origin_alight_nonzero","terminal_board_nonzero","nonincreasing_time_steps"))
    assert all(report[kind+"_budget"]["unexplained_over_0_001_count"]==0 for kind in ("board","alight"))


if __name__=="__main__":
    main()
