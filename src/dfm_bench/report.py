from collections import Counter,defaultdict
from pathlib import Path
from .common import write_json

def ratio(numerator,denominator,unit):
    return {"numerator":numerator,"denominator":denominator,
        "value":numerator/denominator if denominator else None,"unit":unit}

def make_report(data,manifest):
    events=data["delivery"];jobs=[e for e in events if e["record_type"]=="job"]
    attempts=[e for e in events if e["record_type"]=="attempt"]
    warnings=[]
    def mode(e): return e["evidence"].get("validation_mode") or data["source"].get("validation_mode")
    def passed(e,stage):
        if e["status"]!="passed": return False
        return stage=="compile" or (mode(e)=="readiness" and e["evidence"].get("task_readiness")=="passed")
    stages={}
    for stage in ("compile","validate"):
        js=[e for e in jobs if e["stage"]==stage]
        ats=[e for e in attempts if e["stage"]==stage]
        if stage=="validate":
            unknown=sum(mode(e) not in ("readiness","reference") for e in ats)
            if unknown: warnings.append(str(unknown)+" validation attempts have unknown mode and are excluded from readiness rates")
            js=[e for e in js if mode(e)=="readiness"]
            ats=[e for e in ats if mode(e)=="readiness"]
        started=[e for e in ats if e["started_at"] is not None]
        submitted={e["candidate_id"] for e in js if e["candidate_id"]}
        attempted={e["candidate_id"] for e in started if e["candidate_id"]}
        successes={e["candidate_id"] for e in [*js,*ats] if e["candidate_id"] and passed(e,stage)}
        observed_success=successes & attempted
        if successes-attempted: warnings.append(stage+": successful candidates without started attempt evidence excluded from attempted-rate numerator")
        first={}
        for e in sorted(started,key=lambda e:(e["started_at"],e["attempt_number"],e["id"])):
            if e["candidate_id"]: first.setdefault(e["candidate_id"],e)
        versions={(e["candidate_id"],e["package_version"]) for e in started if e["package_version"] and e["candidate_id"]}
        version_pass={(e["candidate_id"],e["package_version"]) for e in started
            if e["package_version"] and e["candidate_id"] and passed(e,stage)}
        missing_versions=sum(not e["package_version"] for e in started)
        version_rate=ratio(len(version_pass),len(versions),"identified candidate/package-version pairs")
        version_rate["coverage"]="partial" if missing_versions else "complete"
        if missing_versions:
            version_rate["value"]=None
            version_rate["reason"]="Rate withheld: missing package identities could produce selection bias"
        stages["compilation" if stage=="compile" else "readiness"]={
            "submitted_candidates":len(submitted),"attempted_candidates":len(attempted),
            "ever_passed_candidates":len(successes),
            "current_job_passed_candidates":len({e["candidate_id"] for e in js if e["candidate_id"] and passed(e,stage)}),
            "candidate_success":ratio(len(successes & submitted) if stage=="compile" else len(observed_success),
                len(submitted) if stage=="compile" else len(attempted),
                "candidate; ever passed / submitted" if stage=="compile" else "candidate; ever passed / attempted"),
            "candidate_first_attempt_success":ratio(sum(passed(e,stage) for e in first.values()),len(first),"candidate; earliest started attempt"),
            "attempt_success":ratio(sum(passed(e,stage) for e in started),len(started),"started attempt"),
            "package_version_success":version_rate,
            "attempts_with_unknown_version":sum(not e["package_version"] for e in started),
            "jobs_with_no_started_attempt":sum(not any(a["job_id"]==j["id"] for a in started) for j in js),
            "attempt_state_counts":dict(sorted(Counter(e["status"] for e in ats).items())),
            "job_state_counts":dict(sorted(Counter(e["status"] for e in js).items())),
            "failure_causes":dict(sorted(Counter(e["evidence"].get("category") or "unknown"
                for e in ats if e["status"]=="failed").items())),
            "unlinked_candidate_attempts":sum(e["candidate_id"] is None for e in started),
            "evidence_mode_policy":"receipt validation_mode, otherwise source config; unknown excluded",
        }
    episodes=data["episodes"];nodes=data["hypotheses"]
    started_episodes={e["episode_id"] for e in attempts if e["stage"]=="science" and e["started_at"] is not None}
    closed_started=sum(e["closed_at"] is not None and e["id"] in started_episodes for e in episodes)
    produced={n["episode_id"] for n in nodes if not n["imported_seed"] and n["proposal"].strip()}
    selected={e["selected_id"] for e in episodes if e["selected_id"]}
    artifact_states=Counter(a["status"] for a in data["artifacts"])
    if data["campaign"]["status"]!="closed": warnings.append("Campaign has unresolved discovery state; this is an as-of snapshot, not a final completed campaign")
    if not manifest["source_files_unchanged"]: warnings.append("Source changed during capture; consistent database view retained, artifacts independently hash-checked")
    if artifact_states.get("unavailable"): warnings.append("Some supporting artifacts are unavailable; scientific review coverage has not been established")
    warnings.extend(["No hypothesis quality, discovery yield or scientific execution success was assessed in M1–M3.",
       "Readiness and synthetic fixture passes do not establish a completed scientific study.",
       "Candidate versions are not deduplicated scientific contribution families.",
       "Historical snapshots are not a controlled comparison between domains or systems."])
    return {"schema_version":"1.0","snapshot_id":manifest["snapshot_id"],"domain":data["campaign"]["domain"],
       "campaign_status":data["campaign"]["status"],"end_reason":data["campaign"]["end_reason"],
       "review_coverage":data["campaign"]["review_coverage"],"graph":data["graph"],
       "source_accounting":data["accounting"],"source_files_unchanged":manifest["source_files_unchanged"],
       "episodes":{"recorded":len(episodes),"started":len(started_episodes),"closed":sum(e["closed_at"] is not None for e in episodes),
          "closed_started":closed_started,"not_started":len(episodes)-len(started_episodes),
          "closure_rate":ratio(closed_started,len(started_episodes),"episode with started science attempt"),
          "recorded_closure_rate":ratio(sum(e["closed_at"] is not None for e in episodes),len(episodes),"recorded episode, including not started"),
          "proposal_availability":ratio(len(produced & started_episodes),len(started_episodes),"started episode with nonempty non-imported proposal; not scientific package validity"),
          "outcomes":dict(sorted(Counter(e["outcome"] or "unclosed" for e in episodes).items()))},
       "selected_candidates":len(selected),"delivery":stages,
       "decision_operations":dict(sorted(Counter(d["operation"] for d in data["decisions"]).items())),
       "artifact_statuses":dict(sorted(artifact_states.items())),
       "scientific_metrics":{"hypothesis_quality":None,"contribution_yield":None,"execution_completion":None,
           "status":"not_assessed","reason":"Requires M4–M7 and explicit scientific execution records"},
       "resources":{"cost":None,"tokens":None,"status":"not_accounted; no billing/native trace ingestion"},
       "warnings":warnings}

def markdown(report):
    lines=["# DFM-Bench M1–M3 snapshot report","",
       "Domain: **"+report["domain"]+"**. Campaign: **"+report["campaign_status"]+"**; end reason: **"+report["end_reason"]+"**.",
       "","Scientific review: **not assessed**. All metrics below are deterministic operational observations.","",
       "| Measure | Count |","|---|---:|"]
    for key,value in report["graph"].items():
        if key!="datasets":lines.append("| "+key+" | "+str(value)+" |")
    lines += ["| Closed / recorded episodes | "+str(report["episodes"]["closed"])+" / "+str(report["episodes"]["recorded"])+" |",
       "| Closed among started / started episodes | "+str(report["episodes"]["closed_started"])+" / "+str(report["episodes"]["started"])+" |",
       "| Selected candidate versions | "+str(report["selected_candidates"])+" |","","## Delivery","",
       "| Stage | Submitted candidates | Attempted candidates | Ever passed | Candidate success | Attempt success |",
       "|---|---:|---:|---:|---|---|"]
    def render(r):
        return str(r["numerator"])+"/"+str(r["denominator"])+(" (N/A)" if r["value"] is None else " ("+format(100*r["value"],".1f")+"%)")
    for name,s in report["delivery"].items():
        lines.append("| "+name+" | "+str(s["submitted_candidates"])+" | "+str(s["attempted_candidates"])+" | "+str(s["ever_passed_candidates"])+" | "+render(s["candidate_success"])+" | "+render(s["attempt_success"])+" |")
    lines += ["","Compilation candidate rate uses submitted candidates; readiness uses attempted candidates. Attempt rate includes all started attempts, including cancelled and pending attempts.",
       "","Package-version rates are withheld when identity coverage is incomplete. Candidate ever-passed counts may exceed current job-pass counts after recovery or cancellation.",
       "","## Evidence coverage","",str(report["artifact_statuses"]),"","## Limits",""]
    lines += ["- "+x for x in report["warnings"]]
    lines += ["","Source database/WAL bytes unchanged across import: **"+str(report["source_files_unchanged"])+"**.",
        "","Snapshot ID: "+report["snapshot_id"],""
    ]
    return "\n".join(lines)

def write_report(snapshot_dir,report):
    path=Path(snapshot_dir)
    write_json(path/"report.json",report)
    out=path/"report.md";out.write_text(markdown(report));out.chmod(0o600)
