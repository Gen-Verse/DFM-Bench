import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from . import __version__
from .adapters import decode,read_source
from .common import canonical,digest,file_hash,private_dir,write_json
from .contracts import validate_record
from .graph import audit
from .registry import get_rubrics

STATE_MAP={"succeeded":"passed","failed":"failed","cancelled":"cancelled","queued":"pending",
 "running":"pending","deferred":"pending","blocked":"blocked"}
SENSITIVE=re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}|(?:api[_-]?key|access[_-]?token|password|secret)[\"\']?\s*[=:]\s*[\"']?[A-Za-z0-9_./+-]{16,})",re.I)

def source_hashes(path):
    return {p.name:file_hash(p) for p in (path,Path(str(path)+"-wal")) if p.is_file()}

def safe_result(result):
    allowed=("state","validation_mode","task_readiness","reference_status","scientific_result",
        "positive_fixture_status","validator_version","elapsed_seconds","category","stage","error_type","retryable")
    return {k:result[k] for k in allowed if k in result and (result[k] is None or type(result[k]) in (str,bool,int,float))}

def package_identity(result):
    manifest=result.get("manifest")
    if not isinstance(manifest,dict) or not isinstance(manifest.get("files"),dict): return None
    return digest({"candidate_hash":manifest.get("candidate_hash"),"files":manifest["files"]})

def freeze_artifact(record,root,output,max_bytes):
    expected=record.get("sha256")
    result={"source_sha256":expected,"source_path":record.get("path"),"status":"unavailable","reason":None}
    if record.get("dataset_source"):
        result.update(status="dataset_binding",reason="Source data remains read-only; not copied")
        return result
    if not isinstance(expected,str) or not re.fullmatch("[0-9a-f]{64}",expected):
        result["reason"]="missing_or_invalid_hash"; return result
    root_input=Path(os.path.abspath(root));root=root_input.resolve()
    raw=Path(record.get("path") or "")
    if not raw.is_absolute(): raw=root_input/raw
    raw=Path(os.path.abspath(raw))
    try:
        # macOS /var and /tmp aliases are outside the trusted run boundary.
        if raw.is_relative_to(root_input):raw=root/raw.relative_to(root_input)
        if not raw.is_relative_to(root):
            aliases=[parent for parent in raw.parents if parent.resolve()==root]
            if not aliases:raise ValueError("outside_run_root")
            raw=root/raw.relative_to(aliases[0])
        if any(p.is_symlink() for p in [raw,*raw.parents] if p.is_relative_to(root) and p!=root):raise ValueError("symlink")
        if not raw.resolve().is_relative_to(root): raise ValueError("outside_run_root")
        if raw.name != expected and raw.suffix.lower() not in (".md",".txt",".json",".jsonl",".csv",".py",".sh",".toml",".yaml",".yml"):
            raise ValueError("unsupported_type")
        if any(x.lower() in (".credentials",".env","credentials") for x in raw.parts): raise ValueError("sensitive_path")
        fd=os.open(raw,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,"rb") as stream:
            s=os.fstat(stream.fileno())
            if not stat.S_ISREG(s.st_mode): raise ValueError("not_regular")
            if s.st_size>max_bytes: raise ValueError("oversized")
            data=stream.read(max_bytes+1)
        if len(data)>max_bytes: raise ValueError("oversized")
        if hashlib.sha256(data).hexdigest()!=expected: raise ValueError("hash_mismatch")
        data.decode("utf-8")
        if b"\x00" in data: raise ValueError("binary_content")
        if SENSITIVE.search(data): raise ValueError("suspected_secret")
        dest=output/"artifacts"/expected
        dest.parent.mkdir(exist_ok=True,mode=0o700)
        dest.write_bytes(data);dest.chmod(0o600)
        result.update(status="frozen_private",reason=None,relative_path="artifacts/"+expected,bytes=len(data))
    except (OSError,UnicodeError,ValueError) as exc:
        result["reason"]=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    return result

def build_snapshot(rows,provenance,domain,source_root,output,max_bytes=1048576):
    provenance["implementation_sha256"]=digest({p.name:file_hash(p) for p in Path(__file__).parent.glob("*.py")})
    namespace=domain+":"+provenance["run_id"]
    def ident(kind,value): return namespace+":"+kind+":"+str(value) if value else None
    hypotheses=[];artifacts=[];edges=[];decisions=[];episodes=[]
    for row in rows["candidates"]:
        cid=ident("hypothesis",row["id"]); refs=[]
        for index,record in enumerate(decode(row["files"],[])):
            ref=cid+":artifact:"+str(index);refs.append(ref)
            artifacts.append({"id":ref,"candidate_id":cid,**freeze_artifact(record,source_root,output,max_bytes)})
        node={"id":cid,"source_id":row["id"],"episode_id":ident("episode",row["episode_id"]),
            "domain":domain,"dataset":row["dataset"],"proposal":row["proposal"],"change_note":row["change_note"],
            "parents":[ident("hypothesis",p) for p in decode(row["parents"],[])],"imported_seed":row["origin"] is not None,
            "created_at":row["created_at"],"content_hash":row["content_hash"],"artifact_refs":refs,"scientific_assessment":None}
        validate_record("hypothesis",node);hypotheses.append(node)
        for parent in node["parents"]: edges.append({"id":digest([parent,cid]),"parent_id":parent,"child_id":cid,"kind":"derivation"})
    graph=audit(hypotheses)
    for row in rows["episodes"]:
        eid=ident("episode",row["id"])
        episodes.append({"id":eid,"source_id":row["id"],"dataset":row["dataset"],"ordinal":row["ordinal"],
            "closed_at":row["closed_at"],"selected_id":ident("hypothesis",row["selected_id"]),"outcome":row["outcome"]})
        for index,work in enumerate(decode(row["work_history"],[])):
            decisions.append({"id":eid+":decision:"+str(index),"episode_id":eid,"operation":work.get("operation","unknown"),
                "time":work.get("time"),"parents":[ident("hypothesis",p) for p in work.get("parents",[])],
                "context_ids":[ident("hypothesis",p) for p in work.get("context_candidate_ids",[])],
                "goal":work.get("goal",""),"reason":work.get("reason",""),
                "provenance":{"source":"episodes.work_history","source_index":index,"seq":work.get("seq"),"board_revision":work.get("board_revision")}})
        if row["closed_at"] is not None:
            decisions.append({"id":eid+":closure","episode_id":eid,"operation":"episode_close","time":row["closed_at"],
                "parents":[],"context_ids":[ident("hypothesis",row["selected_id"])] if row["selected_id"] else [],
                "goal":"","reason":row["reason"] or "","provenance":{"source":"episodes","outcome":row["outcome"]}})
    jobs={j["id"]:j for j in rows["jobs"]}; package_paths={}; delivery=[]
    # Resolve exact package receipts, including successful retry attempts.
    for raw in [*rows["jobs"],*rows["attempts"]]:
        result=decode(raw["result"],{}); version=package_identity(result)
        if version and result.get("package"): package_paths[result["package"]]=version
    compile_receipts={}
    for raw in rows["attempts"]:
        if jobs[raw["job_id"]]["operation"]=="compile" and raw["state"]=="succeeded":
            compile_receipts.setdefault(raw["job_id"],[]).append((raw["ended_at"],package_identity(decode(raw["result"],{}))))
    for record_type,raw_records in [("job",rows["jobs"]),("attempt",rows["attempts"])]:
        for raw in raw_records:
            job=raw if record_type=="job" else jobs[raw["job_id"]]
            inputs=decode(job["inputs"],{});result=decode(raw["result"],{})
            candidate=job["candidate_id"] or inputs.get("candidate_id")
            compile_job=jobs.get(inputs.get("compile_job"))
            if not candidate and compile_job:
                candidate=compile_job["candidate_id"] or decode(compile_job["inputs"],{}).get("candidate_id")
            version=package_identity(result) or package_paths.get(result.get("package"))
            version_origin="receipt" if version else "unknown"
            if not version and compile_job and raw.get("started_at") is not None:
                prior=[(t,v) for t,v in compile_receipts.get(compile_job["id"],[]) if t is not None and t<=raw["started_at"]]
                if prior:
                    _,version=max(prior,key=lambda x:x[0])
                    if version: version_origin="latest_prior_compile_attempt_receipt"
            evidence=safe_result(result)
            evidence["package_version_origin"]=version_origin
            evidence["compile_job_id"]=ident("job",inputs.get("compile_job"))
            evidence["version_status"]="identified" if version else "unknown"
            event={"id":ident(record_type,raw["id"]),"source_id":raw["id"],"job_id":ident("job",job["id"]),
                "episode_id":ident("episode",job["episode_id"]),"candidate_id":ident("hypothesis",candidate),
                "record_type":record_type,"stage":job["operation"] if job["operation"] in ("compile","validate","science","compute") else "other",
                "status":STATE_MAP.get(raw["state"],"unknown"),"source_state":raw["state"],
                "attempt_number":raw["number"] if record_type=="attempt" else None,
                "started_at":raw.get("started_at"),"ended_at":raw.get("ended_at"),"created_at":job["created_at"],
                "package_version":version,"evidence":evidence}
            validate_record("delivery_event",event);delivery.append(event)
    active=sum(j["state"] in ("queued","running","deferred") and j["operation"] in ("science","compute") for j in rows["jobs"])
    active+=sum(bool(a["active"]) and a["role"] in ("lead","generation","evolution","critique","progress") for a in rows["actors"])
    unclosed=sum(e["closed_at"] is None for e in episodes)
    status="open" if active else ("quiescent_unclosed" if unclosed else "closed")
    campaign={"id":namespace,"domain":domain,"hypothesis_ids":[n["id"] for n in hypotheses],
      "decision_ids":[d["id"] for d in decisions],"status":status,
      "end_reason":"operator_stopped" if provenance["operator_stopped"] else "unknown","review_coverage":"not_reviewed"}
    from importlib.resources import files
    rubric_entries=get_rubrics(domain)
    for entry in rubric_entries:
        entry["frozen_path"]="rubrics/"+entry["path"]
        target=output/entry["frozen_path"]
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        target.write_bytes(files("dfm_bench").joinpath("rubrics",entry["path"]).read_bytes())
        target.chmod(0o600)
    data={"schema_version":"1.0","package_version":__version__,"source":provenance,"campaign":campaign,
        "hypotheses":hypotheses,"edges":edges,"decisions":decisions,"episodes":episodes,"delivery":delivery,
        "artifacts":artifacts,"rubrics":rubric_entries,"graph":graph,
        "accounting":{"candidates":len(rows["candidates"]),"episodes":len(rows["episodes"]),"jobs":len(rows["jobs"]),
            "attempts":len(rows["attempts"]),"actors":len(rows["actors"]),"active_discovery_records":active,
            "source_metadata_policy":"allowlist_only; config, authorizations, native traces and raw datasets not exported"},
        "trajectories":[],"contributions":[],"reviews":[]}
    validate_snapshot(data)
    return data

def validate_snapshot(data):
    if data.get("schema_version")!="1.0": raise ValueError("Unsupported snapshot version")
    for name,key in [("hypothesis","hypotheses"),("derivation_edge","edges"),("decision_event","decisions"),
        ("delivery_event","delivery"),("trajectory","trajectories"),("contribution","contributions"),("review","reviews")]:
        for record in data[key]: validate_record(name,record)
        ids=[r["id"] for r in data[key]]
        if len(ids)!=len(set(ids)): raise ValueError("Duplicate "+key+" identity")
    validate_record("campaign",data["campaign"])
    actual=audit(data["hypotheses"])
    if actual!=data["graph"]: raise ValueError("Graph audit mismatch")
    expected={(p,n["id"]) for n in data["hypotheses"] for p in n["parents"]}
    if expected!={(e["parent_id"],e["child_id"]) for e in data["edges"]} or len(expected)!=len(data["edges"]):
        raise ValueError("Edge mismatch")
    candidates={n["id"] for n in data["hypotheses"]}; episodes={e["id"] for e in data["episodes"]}
    if len(episodes)!=len(data["episodes"]): raise ValueError("Duplicate episode")
    jobs={e["id"] for e in data["delivery"] if e["record_type"]=="job"}
    for n in data["hypotheses"]:
        if n["episode_id"] not in episodes and not (n["episode_id"] is None and n["imported_seed"]): raise ValueError("Dangling hypothesis episode")
    for d in data["decisions"]:
        if d["episode_id"] not in episodes or not set(d["parents"]+d["context_ids"])<=candidates:
            raise ValueError("Dangling decision reference")
    for e in data["episodes"]:
        if e["selected_id"] is not None and e["selected_id"] not in candidates: raise ValueError("Dangling selection")
    for e in data["delivery"]:
        if e["episode_id"] not in episodes or e["job_id"] not in jobs: raise ValueError("Dangling delivery reference")
        if e["candidate_id"] is not None and e["candidate_id"] not in candidates: raise ValueError("Dangling delivery candidate")
    for key,records in [("candidates","hypotheses"),("episodes","episodes")]:
        if data["accounting"][key]!=len(data[records]): raise ValueError("Source accounting mismatch")
    for kind,key in [("job","jobs"),("attempt","attempts")]:
        if sum(e["record_type"]==kind for e in data["delivery"])!=data["accounting"][key]: raise ValueError("Delivery accounting mismatch")

    validate_record("run_snapshot",data)
    if set(data["campaign"]["hypothesis_ids"]) != candidates or set(data["campaign"]["decision_ids"]) != {d["id"] for d in data["decisions"]}:
        raise ValueError("Campaign membership mismatch")
    artifact_ids={a["id"] for a in data["artifacts"]}
    if len(artifact_ids)!=len(data["artifacts"]): raise ValueError("Duplicate artifact identity")
    for a in data["artifacts"]:
        if a["candidate_id"] not in candidates: raise ValueError("Dangling artifact candidate")
    for n in data["hypotheses"]:
        if set(n["artifact_refs"]) != {a["id"] for a in data["artifacts"] if a["candidate_id"]==n["id"]}:
            raise ValueError("Artifact membership mismatch")
    from .graph import trajectory
    for t in data["trajectories"]:
        verified=trajectory(data["hypotheses"],t["path_ids"])
        if verified["context_parent_ids"]!=t["context_parent_ids"] or verified["scope"]!=t["scope"]:
            raise ValueError("Trajectory context mismatch")
    for contribution in data["contributions"]:
        if not set(contribution["candidate_ids"])<=candidates: raise ValueError("Dangling contribution candidate")
    return data

def import_run(source,domain,output,max_bytes=1048576):
    source=Path(source).resolve(strict=True)
    if source.is_dir(): source=source/"state.sqlite"
    if not source.is_file(): raise ValueError("Source database missing")
    output=Path(output).absolute()
    if output.resolve().is_relative_to(source.parent): raise ValueError("Output cannot be inside source run")
    if output.exists(): raise ValueError("Output already exists; verify it or use a new path")
    private_dir(output.parent)
    before=source_hashes(source);rows,provenance=read_source(source,domain)
    staging=Path(tempfile.mkdtemp(prefix=".dfm-import-",dir=output.parent));staging.chmod(0o700)
    try:
        data=build_snapshot(rows,provenance,domain,source.parent,staging,max_bytes)
        sid=digest(data); write_json(staging/"snapshot.json",data)
        after=source_hashes(source)
        manifest={"snapshot_id":sid,"snapshot_file_sha256":file_hash(staging/"snapshot.json"),
            "source_path":str(source),"captured_at":datetime.now(timezone.utc).isoformat(),
            "source_files_before":before,"source_files_after":after,"source_files_unchanged":before==after,
            "consistency":"SQLite read-only backup to memory includes committed WAL",
            "privacy":"private unredacted evidence; not an M4 reviewer packet or public export"}
        write_json(staging/"manifest.json",manifest)
        os.rename(staging,output)
        return manifest
    except BaseException:
        shutil.rmtree(staging);raise

def load_snapshot(path):
    path=Path(path)
    data=json.loads((path/"snapshot.json").read_text());manifest=json.loads((path/"manifest.json").read_text())
    if digest(data)!=manifest["snapshot_id"] or file_hash(path/"snapshot.json")!=manifest["snapshot_file_sha256"]:
        raise ValueError("Snapshot integrity mismatch")
    validate_snapshot(data)
    for artifact in data["artifacts"]:
        if artifact["status"]=="frozen_private":
            p=path/artifact["relative_path"]
            if p.is_symlink() or not p.resolve().is_relative_to(path.resolve()) or file_hash(p)!=artifact["source_sha256"]:
                raise ValueError("Artifact integrity mismatch")
    for rubric in data["rubrics"]:
        p=path/rubric["frozen_path"]
        if p.is_symlink() or not p.resolve().is_relative_to(path.resolve()) or file_hash(p)!=rubric["sha256"]:
            raise ValueError("Frozen rubric integrity mismatch")
    return data,manifest
