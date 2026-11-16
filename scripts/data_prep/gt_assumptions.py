"""Optional, explicitly assumed structure for the latent boarding split.

No passenger waiting times or actual peak passenger counts are read here.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AssumptionConfig:
    temporal_weight: float = 0.0
    temporal_huber_delta: float = 0.15
    pooling_weight: float = 0.0
    boarding_headway: bool = False


def boarding_exposures(stops, n_stations=22, hours=tuple(range(5,25))):
    """Integrate uniform within-hour gate arrivals to the next departure.

    Waiting interval = (previous departure, current departure], clipped to the
    service opening at 05:00. For a station/direction's first train the unknown
    previous departure is replaced by service opening, not by observed wait.
    Stops after midnight use 24:xx on the same continuous minute axis.

    Counts arriving after both directions' last departure are not assigned to
    an already departed train: they become explicit unallocated source mass.
    Equal-time departures divide the interval equally. Alighting is untouched.
    """
    groups={}
    for index,stop in enumerate(stops):
        if stop["is_destination"]:
            continue
        hour,minute=map(int,stop["time"].split(":"))
        if hour==0:
            hour=24
        departure=hour*60+minute
        groups.setdefault((stop["station_idx"],stop["dir_code"]),{}).setdefault(departure,[]).append(index)
    final={key:max(times) for key,times in groups.items()}
    edges=[]
    coverage=np.zeros((n_stations,len(hours)),np.float32)
    both_coverage=np.zeros_like(coverage)
    for station in range(n_stations):
        up_end=final.get((station,0),5*60)
        down_end=final.get((station,1),5*60)
        for h_idx,hour in enumerate(hours):
            coverage[station,h_idx]=max(0,min((hour+1)*60,max(up_end,down_end))-hour*60)/60
            both_coverage[station,h_idx]=max(0,min((hour+1)*60,min(up_end,down_end))-hour*60)/60
    for (station,direction),departures in groups.items():
        previous=5*60
        other_end=final.get((station,1-direction),5*60)
        for departure,indices in sorted(departures.items()):
            for h_idx,hour in enumerate(hours):
                left=max(previous,hour*60)
                right=min(departure,(hour+1)*60)
                if right<=left:
                    continue
                both=max(0,min(right,other_end)-left)
                only=(right-left)-both
                for index in indices:
                    edges.append((index,station,h_idx,direction,both/(60*len(indices)),only/(60*len(indices))))
            previous=departure
    return edges,coverage,both_coverage


def day_group(date,public_holidays):
    """Monday..Sunday are distinct; listed public holidays are an eighth group."""
    return 7 if date in public_holidays else pd.Timestamp(date).weekday()


class WeekdayTemplates:
    """Causal partial-pooling targets extracted from independent daily fits.

    Observation arrays may include later dates on disk, but snapshot() strictly
    filters date<current service date and excludes declared evaluation dates.
    A 112-day window bounds drift. At least two observed same-group days are
    needed per cell; n/(n+4) scales confidence without hard tying daily ratios.
    """
    def __init__(self, dates, groups, plans, p, q, source_hash=""):
        self.dates=np.asarray(dates).astype("U10")
        self.groups=np.asarray(groups)
        self.plans=np.asarray(plans)
        self.p=np.asarray(p,dtype=np.float32)
        self.q=np.asarray(q,dtype=np.float32)
        self.source_hash=source_hash

    @classmethod
    def from_dataset(cls,path,public_holidays):
        if "boarding_sources" in pd.read_csv(path,nrows=0).columns:
            raise ValueError("headway 자료의 stop-hour 합으로 template를 역산할 수 없습니다. 독립 uniform-baseline 자료를 사용하세요.")
        columns=["date","station_idx","hour","dir_code","board","alight","is_origin","is_destination"]
        frame=pd.read_csv(path,usecols=columns)
        frame["eligible_board"]=(frame.is_destination==0).astype(int)
        frame["eligible_alight"]=(frame.is_origin==0).astype(int)
        grouped=frame.groupby(["date","station_idx","hour","dir_code"])[["board","alight","eligible_board","eligible_alight"]].sum()
        dates=sorted(frame.date.unique())
        p=np.full((len(dates),22,20),np.nan,np.float32)
        q=p.copy()
        wide=grouped.unstack("dir_code").fillna(0)
        date_index=pd.Index(dates).get_indexer(wide.index.get_level_values("date"))
        station_index=wide.index.get_level_values("station_idx").to_numpy(dtype=int)
        hour_index=wide.index.get_level_values("hour").to_numpy(dtype=int)-5
        for target,value,count in ((p,"board","eligible_board"),(q,"alight","eligible_alight")):
            up=wide[(value,0)].to_numpy()
            down=wide[(value,1)].to_numpy()
            total=up+down
            identified=(wide[(count,0)].to_numpy()>0)&(wide[(count,1)].to_numpy()>0)&(total>0)
            ratio=np.divide(up,total,out=np.full(len(up),np.nan),where=identified)
            target[date_index,station_index,hour_index]=ratio
        with open(path,"rb") as source:
            digest=hashlib.file_digest(source,"sha256").hexdigest()
        return cls(dates,[day_group(date,public_holidays) for date in dates],[int(date>="2026-03-30") for date in dates],p,q,digest)

    def save(self,path):
        np.savez_compressed(path,dates=self.dates,groups=self.groups,plans=self.plans,p=self.p,q=self.q,source_hash=np.asarray(self.source_hash))

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as item:
            return cls(item["dates"],item["groups"],item["plans"],item["p"],item["q"],str(item["source_hash"]))

    def snapshot(self,date,public_holidays,exclude_dates=(),window_days=112,fit_through=None):
        history_end=min(pd.Timestamp(date),pd.Timestamp(fit_through)+pd.Timedelta(days=1)) if fit_through else pd.Timestamp(date)
        cutoff=(history_end-pd.Timedelta(days=window_days)).strftime("%Y-%m-%d")
        mask=(self.dates<date)&(self.dates>=cutoff)&(self.groups==day_group(date,public_holidays))&(self.plans==int(date>="2026-03-30"))&~np.isin(self.dates,list(exclude_dates))
        if fit_through:
            mask &= self.dates<=fit_through
        selected=self.dates[mask]
        result={"n_dates":int(mask.sum()),"last_training_date":max(selected.tolist()) if len(selected) else None,"group":int(day_group(date,public_holidays)),"window_days":window_days,"fit_through":fit_through,"source_sha256":self.source_hash}
        for key,values in (("p",self.p),("q",self.q)):
            observations=values[mask]
            count=np.isfinite(observations).sum(axis=0)
            total=np.nansum(observations,axis=0)
            mean=np.divide(total,count,out=np.full((22,20),.5),where=count>0).astype(np.float32)
            confidence=np.where(count>=2,count/(count+4),0).astype(np.float32)
            result[key]=mean
            result[key+"_confidence"]=confidence
        assert result["last_training_date"] is None or result["last_training_date"]<date
        return result
