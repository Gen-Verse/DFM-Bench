import math
from importlib.resources import files

LEVELS = ("hypothesis", "transition", "trajectory", "campaign", "discovery")
DOMAINS = ("clinical", "battery")
STATES = ("not_attempted", "pending", "passed", "failed", "blocked", "cancelled", "not_applicable", "unknown")
def field(kind, enum=None):
    result = {"type": kind}
    if enum is not None:
        result["enum"] = list(enum)
    return result

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

S = field("string")
N = field(["number", "null"])
A = {"type": "array", "items": S}
O = field("object")
CONTRACTS = {
 "hypothesis": obj({"id": S, "source_id": S, "episode_id": field(["string","null"]), "domain": field("string", DOMAINS), "dataset": S,
    "proposal": S, "change_note": S, "parents": A, "imported_seed": field("boolean"), "created_at": N,
    "content_hash": S, "artifact_refs": A, "scientific_assessment": field(["object","null"])}),
 "derivation_edge": obj({"id": S, "parent_id": S, "child_id": S, "kind": field("string",["derivation"])}),
 "decision_event": obj({"id": S, "episode_id": S, "operation": S, "time": N, "parents": A,
    "context_ids": A, "goal": S, "reason": S, "provenance": O}),
 "trajectory": obj({"id": S, "path_ids": A, "context_parent_ids": A,
    "scope": field("string",["full_path","segment"]), "decision_ids": A, "evidence_refs": A}),
 "campaign": obj({"id": S, "domain": field("string",DOMAINS), "hypothesis_ids": A, "decision_ids": A,
    "status": field("string",["open","quiescent_unclosed","closed","unknown"]),
    "end_reason": field("string",["operator_stopped","planned_completion","budget_exhaustion","early_termination","unknown"]),
    "review_coverage": field("string",["not_reviewed","complete","partial","unscorable"])}),
 "contribution": obj({"id": S, "candidate_ids": A, "contribution_type": field("string",["problem","hypothesis","design","measurement_finding","empirical_result"]),
    "evidence_maturity": field("string",["proposed","source_grounded","diagnostically_examined","study_completed","independently_checked"]),
    "disposition": field("string",["supported","contradicted","inconclusive","unresolved"]), "exposure": field("string",["observed","uncertain","independently_assessed"]),
    "evidence_refs": A, "importance": field(["number","null"])}),
 "delivery_event": obj({"id": S, "source_id": S, "job_id": S, "episode_id": S, "candidate_id": field(["string","null"]),
    "record_type": field("string",["job","attempt"]), "stage": field("string",["compile","validate","science","compute","other"]),
    "status": field("string",STATES), "source_state": S, "attempt_number": field(["integer","null"]),
    "started_at": N, "ended_at": N, "created_at": N, "package_version": field(["string","null"]), "evidence": O}),
 "review": obj({"id": S, "level": field("string",LEVELS), "object_id": S, "snapshot_id": S, "rubric_id": S,
    "rubric_sha256": S, "status": field("string",["complete","partial","unscorable"]),
    "dimensions": O, "evidence_refs": A, "composite": N, "feedback_use": field("string",["development","held_out"])}),
}

def _validate(value, schema, path):
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds,list) else [kinds]
    checks = {"null":value is None, "string":isinstance(value,str), "boolean":type(value) is bool,
        "integer":type(value) is int, "number":type(value) in (int,float) and math.isfinite(value),
        "object":isinstance(value,dict), "array":isinstance(value,list)}
    if not any(checks.get(k,False) for k in kinds):
        raise ValueError(path + ": invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + ": invalid enum")
    if isinstance(value,dict):
        props = schema.get("properties",{})
        missing = set(schema.get("required",[]))-value.keys()
        if missing: raise ValueError(path + ": missing fields " + ",".join(sorted(missing)))
        if schema.get("additionalProperties") is False and set(value)-props.keys():
            raise ValueError(path + ": unexpected fields")
        for key,item in value.items():
            if key in props: _validate(item,props[key],path+"."+key)
    if isinstance(value,list) and "items" in schema:
        for i,item in enumerate(value): _validate(item,schema["items"],path+"["+str(i)+"]")

def validate_record(name,value):
    _validate(value,CONTRACTS[name],name)
    return value

def json_schemas():
    return {name: {"$schema":"https://json-schema.org/draft/2020-12/schema",
       "$id":"https://dfm-bench.local/schemas/v1/"+name, **schema} for name,schema in CONTRACTS.items()}

CONTRACTS["episode"] = obj({"id":S,"source_id":S,"dataset":S,"ordinal":field("integer"),
    "closed_at":N,"selected_id":field(["string","null"]),"outcome":field(["string","null"])})
CONTRACTS["artifact"] = {"type":"object","required":["id","candidate_id","source_sha256","source_path","status","reason"],
    "properties":{"id":S,"candidate_id":S,"source_sha256":field(["string","null"]),"source_path":field(["string","null"]),
      "status":field("string",["unavailable","dataset_binding","frozen_private"]),"reason":field(["string","null"]),
      "relative_path":S,"bytes":field("integer")},"additionalProperties":False}
CONTRACTS["run_snapshot"] = obj({
    "schema_version":field("string",["1.0"]),"package_version":S,"source":O,"campaign":CONTRACTS["campaign"],
    **{key:{"type":"array","items":CONTRACTS[name]} for key,name in [
      ("hypotheses","hypothesis"),("edges","derivation_edge"),("decisions","decision_event"),
      ("episodes","episode"),("delivery","delivery_event"),("artifacts","artifact"),
      ("trajectories","trajectory"),("contributions","contribution"),("reviews","review")]},
    "rubrics":{"type":"array","items":O},"graph":O,"accounting":O})
