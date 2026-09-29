"""Five-level calibration contracts. No model calls; no synthetic human gold."""
import math
from collections import Counter
from .common import digest

LEVELS=("hypothesis","transition","trajectory","campaign","discovery")
H_WEIGHTS={"importance":20,"novelty":20,"grounding":15,"falsifiability":10,
 "data_resolvability":10,"feasibility":10,"alternatives":10,"actionability":5}
T_WEIGHTS=[5,30,20,20,10,10,5]
C_WEIGHTS=[25,15,15,20,10,10,5]
CARD_FIELDS=("claim","increment","evidence","decisive_test","alternatives","limitations")

def protocol():
    body={"version":"dfm-calibration-development-v1","levels":list(LEVELS),
      "hypothesis_dimensions":H_WEIGHTS,"weight_status":"trial_not_expert_approved",
      "hypothesis_scale":[1,10],"trajectory_weights":T_WEIGHTS,"campaign_weights":C_WEIGHTS,
      "expert_calibration_status":"pending","required_experts":2,
      "time_mode":"retrospective_final_snapshot","novelty_scope":"supplied_evidence_only",
      "family_policy":"frozen prior proposed family mapping; no rescoring during consolidation",
      "human_gate":"Registered independent expert judgments, adjudication and held-out acceptance are required",
      "verbal_bands":{"1-2":"Uninterpretable or severe unresolved scientific defects",
       "3-4":"Material omissions or weak scientific warrant",
       "5-6":"Coherent incremental proposal with bounded limitations",
       "7-8":"Strong, grounded scientific opportunity with a discriminating test",
       "9-10":"Exceptional scientifically consequential opportunity; proposal-stage evidence sufficient"},
      "score_meaning":"Scientific proposal merit conditional on supplied evidence, not truth or verified novelty",
      "forbidden_claims":["expert_calibrated","online_as_of_progress","confirmed_discovery","system_superiority"]}
    return {**body,"protocol_hash":digest(body)}

def normalize(text):
    return " ".join(text.split())

def validate_card(value,source):
    if set(value)!=set(CARD_FIELDS):raise ValueError("Card fields mismatch")
    source=normalize(source)
    for field,quotes in value.items():
        if quotes is None:continue
        if not isinstance(quotes,list) or not 1<=len(quotes)<=2:raise ValueError("Quote list required")
        for quote in quotes:
            if not isinstance(quote,str) or not quote.strip() or len(quote)>1200:raise ValueError("Invalid quote")
            if normalize(quote) not in source:raise ValueError("Unsupported card quote")
    if not value["claim"]:raise ValueError("Missing central claim")

def validate_rating(value,allowed):
    if value.get("validity") not in ("eligible","rejected","uncertain"):raise ValueError("Invalid validity")
    ds=value.get("dimensions")
    if not isinstance(ds,dict) or set(ds)!=set(H_WEIGHTS):raise ValueError("Invalid dimensions")
    if value.get("novelty_scope")!="supplied_evidence_only":raise ValueError("Unsupported novelty scope")
    for key,d in ds.items():
        if not isinstance(d,dict) or d.get("status") not in ("scored","unknown"):raise ValueError("Invalid dimension")
        if d["status"]=="scored":
            if type(d.get("score")) is not int or not 1<=d["score"]<=10:raise ValueError("Score must be integer 1–10")
        elif d.get("score") is not None:raise ValueError("Unknown must be null")
        if not isinstance(d.get("rationale"),str) or not d["rationale"].strip():raise ValueError("Rationale required")
        refs=d.get("refs")
        if not isinstance(refs,list) or any(not isinstance(r,str) for r in refs) or not set(refs)<=set(allowed):raise ValueError("Invalid evidence reference")
        if d["status"]=="scored" and not refs:raise ValueError("Unreferenced rating")

def composite(value,weights=None):
    weights=weights or H_WEIGHTS
    if value["validity"]!="eligible":return None
    ds=value["dimensions"]
    if any(ds[k]["status"]!="scored" for k in weights):return None
    return sum(weights[k]*ds[k]["score"] for k in weights)/sum(weights.values())

def calibration_report(cases,predictions,human_reviews,registry,approvals=None,level_acceptances=None):
    """Only explicitly adjudicated references with two registered humans enter metrics."""
    approvals=approvals or {}
    level_acceptances=level_acceptances or {}
    if len({c["id"] for c in cases})!=len(cases):raise ValueError("Duplicate case ID")
    if any(c["level"] not in LEVELS or c["split"] not in ("development","validation","audit") for c in cases):raise ValueError("Invalid case level/split")
    if any(digest({k:v for k,v in c.items() if k!="packet_hash"})!=c["packet_hash"] for c in cases):raise ValueError("Corrupted case packet")
    by={c["id"]:c for c in cases};registered={r["id"]:r for r in registry}
    if any(not isinstance(r.get("id"),str) or not r["id"].strip() or not isinstance(r.get("domains"),list) or not r["domains"] for r in registry):raise ValueError("Registry needs identified domain experts")
    if len(registered)!=len(registry):raise ValueError("Duplicate expert registry ID")
    pred={p["case_id"]:p for p in predictions}
    if len(pred)!=len(predictions):raise ValueError("Duplicate prediction")
    grouped={}
    for r in human_reviews:
        if r.get("origin")!="human" or r.get("synthetic",False):raise ValueError("Human reviews cannot be model/fixture labels")
        if r["case_id"] not in by:raise ValueError("Unknown case")
        case=by[r["case_id"]];expert=registered.get(r["reviewer_id"])
        if not expert or case["domain"] not in expert.get("domains",[]):raise ValueError("Unregistered domain expert")
        if r.get("packet_hash")!=case["packet_hash"]:raise ValueError("Wrong packet version")
        if r.get("independent") is not True or not r.get("rationale"):raise ValueError("Independent reasoned judgment required")
        if not isinstance(r.get("judgment"),dict) or (r["judgment"].get("category") is None and not r["judgment"].get("dimensions") and not r["judgment"].get("labels")):raise ValueError("Expert judgment required")
        judgment=r["judgment"]
        if not isinstance(judgment.get("dimensions",{}),dict):raise ValueError("Expert dimensions must be an object")
        if judgment.get("category") is not None and (not isinstance(judgment["category"],str) or not judgment["category"].strip()):raise ValueError("Invalid expert category")
        if not isinstance(judgment.get("labels",{}),dict) or any(v is not None and not isinstance(v,str) for v in judgment.get("labels",{}).values()):raise ValueError("Expert labels must be strings or null")
        maximum=4 if case["level"] in ("trajectory","campaign") else 10
        minimum=1 if case["level"]=="hypothesis" else 0
        for value in judgment.get("dimensions",{}).values():
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum):
                raise ValueError("Expert dimension outside level scale")
        group=grouped.setdefault(r["case_id"],[])
        if any(x["reviewer_id"]==r["reviewer_id"] for x in group):raise ValueError("Duplicate reviewer")
        group.append(r)
    result={}
    for level in LEVELS:
        lc=[c for c in cases if c["level"]==level];matched=[];pending=0;validation=[];matched_by_case={}
        for case in lc:
            reviews=grouped.get(case["id"],[]);a=approvals.get(case["id"])
            if len(reviews)<2 or not a or a.get("approved") is not True or a.get("adjudicator_id") not in registered:
                pending+=1;continue
            if a.get("origin")!="human":raise ValueError("Adjudication must be human")
            if case["domain"] not in registered[a["adjudicator_id"]].get("domains",[]):raise ValueError("Adjudicator domain mismatch")
            if a.get("packet_hash")!=case["packet_hash"]:raise ValueError("Adjudication version mismatch")
            if case["id"] not in pred:continue
            pair=(pred[case["id"]]["judgment"],a["judgment"]);matched.append(pair);matched_by_case[case["id"]]=pair
            if case["split"]=="validation" and case.get("validation_eligible",True):validation.append(pair)
        def metrics(pairs):
            errors=[];agree=0;categories=0;confusion=Counter();label_n=0;label_agree=0;label_confusion=Counter();maturity_n=0;overclaims=0;expert_known_model_unknown=0;expert_unknown_model_scored=0
            for predicted,reference in pairs:
                if reference.get("category") is not None and predicted.get("category") is not None:
                    categories+=1;agree+=predicted["category"]==reference["category"]
                    confusion[(reference["category"],predicted["category"])]+=1
                for key,expected in reference.get("labels",{}).items():
                    actual=predicted.get("labels",{}).get(key)
                    if expected is not None and actual is not None:
                        label_n+=1;label_agree+=actual==expected;label_confusion[(key,expected,actual)]+=1
                        stages=["proposed","source_grounded","diagnostically_examined","study_completed","independently_checked"]
                        if key=="evidence_maturity" and expected in stages and actual in stages:
                            maturity_n+=1;overclaims+=stages.index(actual)>stages.index(expected)
                for key,expected in reference.get("dimensions",{}).items():
                    actual=predicted.get("dimensions",{}).get(key)
                    if expected is None and type(actual) in (int,float):expert_unknown_model_scored+=1
                    if type(expected) in (int,float) and actual is None:expert_known_model_unknown+=1
                    if type(actual) in (int,float) and type(expected) in (int,float) and math.isfinite(actual) and math.isfinite(expected):
                        errors.append(abs(actual-expected))
            return {"matched_cases":len(pairs),"categorical_n":categories,"categorical_agreement":agree/categories if categories else None,
              "label_comparisons":label_n,"label_agreement":label_agree/label_n if label_n else None,
              "label_confusion":[{"field":k,"expert":a,"model":b,"count":n} for (k,a,b),n in sorted(label_confusion.items())],
              "evidence_maturity_comparisons":maturity_n,"maturity_overclaim_rate":overclaims/maturity_n if maturity_n else None,
              "expert_known_model_unknown":expert_known_model_unknown,"expert_unknown_model_scored":expert_unknown_model_scored,
              "dimension_comparisons":len(errors),"dimension_mae":sum(errors)/len(errors) if errors else None,
              "confusion":[{"expert":a,"model":b,"count":n} for (a,b),n in sorted(confusion.items())]}
        domains={}
        for domain in sorted({c["domain"] for c in lc}):
            subset=[c for c in lc if c["domain"]==domain]
            evaluated=[matched_by_case[c["id"]] for c in subset if c["id"] in matched_by_case]
            validation_ids=[c["id"] for c in subset if c["split"]=="validation" and c.get("validation_eligible",True) and c["id"] in matched_by_case]
            vm=metrics([matched_by_case[cid] for cid in validation_ids])
            acceptance=level_acceptances.get(domain+"/"+level)
            accepted=False
            if acceptance and acceptance.get("approved") is True:
                expert=registered.get(acceptance.get("approver_id"))
                if acceptance.get("origin")!="human" or not expert or domain not in expert.get("domains",[]):
                    raise ValueError("Invalid expert acceptance")
                if set(acceptance.get("validation_case_ids",[]))!=set(validation_ids):raise ValueError("Acceptance validation set mismatch")
                hashes={c.get("protocol_hash") for c in subset}
                if hashes!={acceptance.get("protocol_hash")}:raise ValueError("Acceptance protocol mismatch")
                minimum=acceptance.get("minimum_validation_cases")
                if type(minimum) is not int or minimum<2:raise ValueError("Acceptance needs a prospective minimum >=2")
                for key,upper in (("maximum_dimension_mae",10),("minimum_categorical_agreement",1),("minimum_label_agreement",1)):
                    if key in acceptance:
                        value=acceptance[key]
                        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=upper:raise ValueError("Invalid acceptance threshold")
                checks=[len(validation_ids)>=minimum]
                if "maximum_dimension_mae" in acceptance:
                    checks.append(vm["dimension_mae"] is not None and vm["dimension_mae"]<=acceptance["maximum_dimension_mae"])
                if "minimum_categorical_agreement" in acceptance:
                    checks.append(vm["categorical_agreement"] is not None and vm["categorical_agreement"]>=acceptance["minimum_categorical_agreement"])
                if "minimum_label_agreement" in acceptance:
                    checks.append(vm["label_agreement"] is not None and vm["label_agreement"]>=acceptance["minimum_label_agreement"])
                if len(checks)==1:raise ValueError("Explicit measurement threshold required")
                accepted=all(checks)
            domains[domain]={"cases":len(subset),"all_adjudicated":metrics(evaluated),"validation_only":vm,
                "scientific_calibration_status":"expert_accepted_within_declared_scope" if accepted else "pending_expert_acceptance"}
        measures={}
        for measure in sorted({c.get("measurement",level) for c in lc}):
            ids=[c["id"] for c in lc if c.get("measurement",level)==measure and c["id"] in matched_by_case]
            measures[measure]=metrics([matched_by_case[cid] for cid in ids])
        result[level]={"by_measurement":measures,"cases":len(lc),"pending_expert_adjudication":pending,"all_adjudicated":metrics(matched),
           "validation_only":metrics(validation),"by_domain":domains,
           "scientific_calibration_status":"expert_accepted_within_declared_scope" if domains and all(x["scientific_calibration_status"]=="expert_accepted_within_declared_scope" for x in domains.values()) else "pending_expert_acceptance"}
    return {"levels":result,"registered_experts":len(registry),"human_reviews":len(human_reviews),
      "headline_release_approved":False,"status":"development_only",
      "reason":"Agreement statistics alone never auto-approve scientific release; explicit level-specific acceptance remains required."}

def import_human_csv(path,cases,registry):
    """Blank rows remain pending; import only actual registered human judgments."""
    import csv,json
    records=[]
    with open(path,newline="") as f:
        for row in csv.DictReader(f):
            populated=bool(row.get("reviewer_id","").strip() or row.get("category","").strip() or row.get("rationale","").strip() or row.get("dimensions_json","").strip() not in ("","{}","null") or row.get("labels_json","").strip() not in ("","{}","null"))
            populated=populated or any(v and v.strip() for k,v in row.items() if k.startswith("score_") or k.startswith("label_"))
            if not populated:continue
            dimensions=json.loads(row.get("dimensions_json") or "{}")
            labels=json.loads(row.get("labels_json") or "{}")
            for key,value in row.items():
                if not value or not value.strip():continue
                if key.startswith("score_"):
                    dimension=key[6:];parsed=None if value.strip().lower() in ("unknown","null","na","n/a") else float(value)
                    if dimension in dimensions and dimensions[dimension]!=parsed:raise ValueError("Conflicting JSON and column rating")
                    dimensions[dimension]=parsed
                elif key.startswith("label_"):
                    label=key[6:]
                    if label in labels and labels[label]!=value.strip():raise ValueError("Conflicting label values")
                    labels[label]=value.strip()
            record={"case_id":row["case_id"],"packet_hash":row["packet_hash"],"reviewer_id":row["reviewer_id"],
              "origin":row.get("origin"),"independent":row.get("independent","").strip().lower() in ("true","yes","1"),
              "rationale":row.get("rationale",""),"evidence_refs":json.loads(row["evidence_refs_json"]) if row.get("evidence_refs_json") else [v.strip() for v in row.get("evidence_refs","").split(";") if v.strip()],
              "judgment":{"category":row.get("category") or None,"dimensions":dimensions,"labels":labels}}
            records.append(record)
    calibration_report(cases,[],records,registry)
    return records


def case_bank_hash(cases):
    return digest(sorted((c["id"],c["packet_hash"]) for c in cases))

def verify_case_bank(cases,lock):
    if case_bank_hash(cases)!=lock["case_bank_hash"]:
        raise ValueError("Published review packets changed; create a new version instead of overwriting expert inputs")
