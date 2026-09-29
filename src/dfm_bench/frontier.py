"""Frozen-rating archive frontiers with coverage, baseline and family controls."""
import math
from .common import digest

def frontier(records,inventory,episodes,k=3,validity_events=None):
    if k<1:raise ValueError("k must be positive")
    if len({r["id"] for r in records})!=len(records):raise ValueError("Duplicate candidate")
    if len({r["id"] for r in inventory})!=len(inventory):raise ValueError("Duplicate inventory candidate")
    inv={r["id"]:r for r in inventory}
    for r in records:
        if r["id"] not in inv:raise ValueError("Unknown candidate")
        if (r["dataset"],r["episode"])!=(inv[r["id"]]["dataset"],inv[r["id"]]["episode"]):raise ValueError("Episode mismatch")
        if r["score"] is not None and (type(r["score"]) not in (int,float) or not math.isfinite(r["score"]) or not 1<=r["score"]<=10):raise ValueError("Invalid score")
        if r.get("validity") not in ("eligible","rejected","uncertain"):raise ValueError("Invalid validity")
        if not r.get("family_id"):raise ValueError("Family ID required")
        if r.get("evidence_mode")=="as_of" and r.get("evidence_latest_episode",r["episode"])>r["episode"]:raise ValueError("Future evidence leakage")
    events=validity_events or []
    for e in events:
        if e["id"] not in inv or e["episode"]<inv[e["id"]]["episode"] or e["status"] not in ("eligible","rejected","uncertain"):raise ValueError("Invalid validity event")
    rows=[]
    for dataset in sorted({e["dataset"] for e in episodes}):
        last=max(e["episode"] for e in episodes if e["dataset"]==dataset)
        previous=None
        for t in range(last+1):
            available=[r for r in records if r["dataset"]==dataset and r["episode"]<=t]
            universe=[r for r in inventory if r["dataset"]==dataset and r["episode"]<=t]
            eligible=[r for r in available if r["validity"]=="eligible" and r["score"] is not None]
            families={}
            for r in sorted(eligible,key=lambda x:(-x["score"],x["id"])):
                families.setdefault(r["family_id"],r)
            leaders=sorted(families.values(),key=lambda r:(-r["score"],r["id"]))
            best=leaders[0]["score"] if leaders else None
            accepted={r["id"]:r["validity"] for r in available}
            for e in sorted(events,key=lambda e:e["episode"]):
                if e["episode"]<=t and e["id"] in accepted:accepted[e["id"]]=e["status"]
            warranted=[r for r in eligible if accepted[r["id"]]=="eligible"]
            known={r["id"] for r in available if (r["score"] is not None and r["validity"]=="eligible") or r["validity"]=="rejected"}
            complete=all(r["id"] in known for r in universe)
            sampled=len(available)
            rows.append({"dataset":dataset,"episode":t,"best_so_far":best,
              "top_k":sum(r["score"] for r in leaders[:k])/k if len(leaders)>=k else None,
              "k":k,"distinct_scored_families":len(leaders),"leader_id":leaders[0]["id"] if leaders else None,
              "leader_is_seed":leaders[0].get("imported_seed",False) if leaders else None,
              "frontier_gain":best-previous if best is not None and previous is not None else None,
              "currently_warranted":max((r["score"] for r in warranted),default=None) if validity_events is not None else None,
              "current_validity_events_available":validity_events is not None,
              "known_candidate_count":len(universe),"reviewed_candidate_count":sampled,
              "coverage_complete":complete,"frontier_status":"archive_complete" if complete else "observed_lower_bound",
              "new_candidate_count":sum(r["episode"]==t for r in universe),
              "new_reviewed_count":sum(r["episode"]==t for r in available),
              "expert_calibration_status":"pending","temporal_mode":"retrospective_final_snapshot"})
            previous=best
    return {"rows":rows,"score_fingerprint":digest(records),"family_fingerprint":digest(sorted((r["id"],r["family_id"]) for r in inventory)),
       "metric_owner":"campaign","input_level":"hypothesis","new_evaluation_level":False,
       "claim":"Sampled uncalibrated archive frontier; not an as-of or validated scientific-progress claim"}

def gate_counts(families):
    counts={"qualifying":0,"not_qualifying":0,"unresolved":0}
    mature={"diagnostically_examined","study_completed","independently_checked"}
    uncertain_components=0
    for f in families:
        i=f.get("importance");inc=f.get("increment_beyond_start");m=f.get("evidence_maturity")
        uncertain=i in (None,"uncertain") or inc in (None,"uncertain") or m in (None,"unknown")
        uncertain_components+=uncertain
        if i=="limited" or inc=="no" or m in ("proposed","source_grounded"):
            counts["not_qualifying"]+=1
        elif uncertain:counts["unresolved"]+=1
        elif i=="consequential" and inc=="yes" and m in mature:counts["qualifying"]+=1
        else:raise ValueError("Invalid contribution-gate labels")
    return {**counts,"families_with_uncertain_components":uncertain_components,
      "expert_confirmed_discoveries":None,"scope":"Existing provisional evidence-advance gate, not the full Discovery ontology"}
