import argparse
import json
from .snapshot import import_run,load_snapshot
from .registry import registry
from .report import make_report,write_report
from .contracts import json_schemas
from .common import write_json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description="DFM-Bench: read-only scientific evaluation foundations; no model calls")
    commands=p.add_subparsers(dest="command",required=True)
    imp=commands.add_parser("import-run");imp.add_argument("--source",required=True);imp.add_argument("--domain",choices=["clinical","battery"],required=True)
    imp.add_argument("--output",required=True);imp.add_argument("--max-artifact-bytes",type=int,default=1048576)
    for name in ("verify","report"):
        cmd=commands.add_parser(name);cmd.add_argument("snapshot")
    commands.add_parser("rubrics")
    sc=commands.add_parser("schemas");sc.add_argument("--output",required=True)
    cal=commands.add_parser("calibration-report",help="Compare model judgments with registered, adjudicated expert references")
    for name in ("cases","predictions","human-reviews","reviewer-registry","adjudications","output"):cal.add_argument("--"+name,required=True)
    cal.add_argument("--level-acceptances")
    fr=commands.add_parser("frontier",help="Compute archive/frontier curves from fixed candidate scores")
    for name in ("records","inventory","episodes","output"):fr.add_argument("--"+name,required=True)
    fr.add_argument("--validity-events");fr.add_argument("--top-k",type=int,default=3)
    ingest=commands.add_parser("calibration-import",help="Import completed independent human CSV ratings; blank rows stay pending")
    for name in ("csv","cases","reviewer-registry","output"):ingest.add_argument("--"+name,required=True)
    args=p.parse_args()
    try:
        if args.command=="import-run":
            if args.max_artifact_bytes<1: raise ValueError("Artifact limit must be positive")
            m=import_run(args.source,args.domain,args.output,args.max_artifact_bytes)
            print(json.dumps({"snapshot_id":m["snapshot_id"],"source_files_unchanged":m["source_files_unchanged"],"output":args.output}))
        elif args.command in ("verify","report"):
            data,m=load_snapshot(args.snapshot)
            if args.command=="report":
                r=make_report(data,m);write_report(args.snapshot,r)
                print(json.dumps({"snapshot_id":m["snapshot_id"],"report":str(Path(args.snapshot)/"report.md")}))
            else: print(json.dumps({"verified":True,"snapshot_id":m["snapshot_id"],"graph":data["graph"]}))
        elif args.command=="calibration-import":
            from .calibration import import_human_csv
            rows=import_human_csv(args.csv,json.loads(Path(args.cases).read_text()),json.loads(Path(args.reviewer_registry).read_text()))
            output=Path(args.output)
            existing=json.loads(output.read_text()) if output.exists() else []
            merged={(r["case_id"],r["reviewer_id"]):r for r in existing}
            for row in rows:
                key=(row["case_id"],row["reviewer_id"])
                if key in merged and merged[key]!=row:raise ValueError("Existing independent judgment is immutable; use a new version or adjudication")
                merged[key]=row
            write_json(output,list(merged.values()));print(json.dumps({"imported":len(rows),"total_retained":len(merged),"output":args.output}))
        elif args.command=="calibration-report":
            from .calibration import calibration_report
            def read(path):return json.loads(Path(path).read_text())
            result=calibration_report(read(args.cases),read(args.predictions),read(args.human_reviews),
                read(args.reviewer_registry),read(args.adjudications),read(args.level_acceptances) if args.level_acceptances else None)
            write_json(Path(args.output),result);print(json.dumps({"output":args.output,"levels":list(result["levels"]),"headline_release_approved":False}))
        elif args.command=="frontier":
            from .frontier import frontier
            def read(path):return json.loads(Path(path).read_text())
            result=frontier(read(args.records),read(args.inventory),read(args.episodes),args.top_k,read(args.validity_events) if args.validity_events else None)
            write_json(Path(args.output),result);print(json.dumps({"output":args.output,"rows":len(result["rows"]),"new_evaluation_level":False}))
        elif args.command=="rubrics":print(json.dumps(registry(),indent=2))
        elif args.command=="schemas":
            for name,s in json_schemas().items():write_json(Path(args.output)/(name+".json"),s)
            print(json.dumps({"schemas":len(json_schemas())}))
    except (ValueError,OSError,KeyError) as exc:
        p.exit(2,"DFM-Bench error: "+str(exc)+"\n")

if __name__=="__main__":main()
