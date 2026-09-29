import unittest
from dfm_bench.common import digest
from dfm_bench.calibration import *
from dfm_bench.frontier import frontier,gate_counts

class CalibrationTests(unittest.TestCase):
 def case(self,level="hypothesis",domain="clinical"):
  c={"id":"c","level":level,"domain":domain,"split":"validation","inputs":{"claim":"fixture"}}
  c["packet_hash"]=digest(c);return c
 def rating(self):
  return {"validity":"eligible","novelty_scope":"supplied_evidence_only","dimensions":{k:{"status":"scored","score":7,"rationale":"fixture evidence","refs":["claim"]} for k in H_WEIGHTS}}
 def test_five_levels_and_original_weights(self):
  p=protocol();self.assertEqual(len(p["levels"]),5);self.assertEqual(p["trajectory_weights"],[5,30,20,20,10,10,5]);self.assertEqual(p["campaign_weights"],[25,15,15,20,10,10,5])
 def test_source_quote_guard(self):
  c={k:None for k in CARD_FIELDS};c["claim"]=["A testable claim."]
  validate_card(c,"A testable\nclaim.")
  c["claim"]=["A novel invented claim."]
  with self.assertRaises(ValueError):validate_card(c,"A testable claim.")
 def test_score_validation_and_unknown(self):
  v=self.rating();validate_rating(v,{"claim"});self.assertEqual(composite(v),7)
  v["dimensions"]["novelty"].update(status="unknown",score=None)
  self.assertIsNone(composite(v))
  v["dimensions"]["novelty"].update(status="scored",score=True)
  with self.assertRaises(ValueError):validate_rating(v,{"claim"})
 def test_foreign_citation_rejected(self):
  v=self.rating();v["dimensions"]["grounding"]["refs"]=["foreign"]
  with self.assertRaises(ValueError):validate_rating(v,{"claim"})
 def test_no_humans_means_no_calibration(self):
  case=self.case();lock={"case_bank_hash":case_bank_hash([case])};verify_case_bank([case],lock)
  altered={**case,"packet_hash":"changed"}
  with self.assertRaises(ValueError):verify_case_bank([altered],lock)
  r=calibration_report([self.case()],[],[],[])
  self.assertFalse(r["headline_release_approved"]);self.assertEqual(set(r["levels"]),set(LEVELS))
  self.assertIsNone(r["levels"]["hypothesis"]["all_adjudicated"]["categorical_agreement"])
 def test_model_cannot_be_human_reference(self):
  with self.assertRaises(ValueError):calibration_report([self.case()],[],[{"origin":"model"}],[])
 def reviews(self,c):
  return [{"case_id":"c","packet_hash":c["packet_hash"],"reviewer_id":e,"origin":"human","independent":True,"rationale":"fixture","judgment":{"category":"eligible"}} for e in ["fixture-e1","fixture-e2"]]
 def test_registered_two_experts_and_adjudication_required(self):
  c=self.case();reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  approvals={"c":{"approved":True,"origin":"human","adjudicator_id":"fixture-e1","packet_hash":c["packet_hash"],"judgment":{"category":"eligible","dimensions":{"importance":8}}}}
  pred=[{"case_id":"c","judgment":{"category":"eligible","dimensions":{"importance":7}}}]
  r=calibration_report([c],pred,self.reviews(c),reg,approvals)
  self.assertEqual(r["levels"]["hypothesis"]["validation_only"]["categorical_agreement"],1)
  self.assertEqual(r["levels"]["hypothesis"]["validation_only"]["dimension_mae"],1)
  self.assertFalse(r["headline_release_approved"])
  r=calibration_report([c],pred,self.reviews(c)[:1],reg,approvals)
  self.assertEqual(r["levels"]["hypothesis"]["validation_only"]["matched_cases"],0)
 def test_duplicate_reviewer_and_version_mismatch(self):
  c=self.case();reg=[{"id":"fixture-e1","domains":["clinical"]}]
  rs=self.reviews(c)[:1]
  with self.assertRaises(ValueError):calibration_report([c],[],rs*2,reg)
  rs[0]["packet_hash"]="wrong"
  with self.assertRaises(ValueError):calibration_report([c],[],rs,reg)
 def test_unknown_discovery_not_counted_as_negative(self):
  x=gate_counts([{"importance":"uncertain","increment_beyond_start":"yes","evidence_maturity":"diagnostically_examined"}])
  self.assertEqual(x["unresolved"],1);self.assertEqual(x["not_qualifying"],0);self.assertIsNone(x["expert_confirmed_discoveries"])


 def test_blank_csv_is_not_human_evidence(self):
  import tempfile,csv
  from pathlib import Path
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"blank.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["case_id","packet_hash","reviewer_id","category","dimensions_json","rationale"]);w.writeheader()
    w.writerow({"case_id":"c","packet_hash":self.case()["packet_hash"],"reviewer_id":"","category":"","dimensions_json":"{}","rationale":""})
   self.assertEqual(import_human_csv(p,[self.case()],[]),[])
 def test_level_acceptance_is_explicit_scoped_and_thresholded(self):
  cases=[]
  for i in range(2):
   c=self.case();c.update(id="c"+str(i),protocol_hash="p");c["packet_hash"]=digest({k:v for k,v in c.items() if k!="packet_hash"});cases.append(c)
  reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  reviews=[];pred=[];adjudications={}
  for c in cases:
   for e in reg:
    reviews.append({"case_id":c["id"],"packet_hash":c["packet_hash"],"reviewer_id":e["id"],"origin":"human","independent":True,"rationale":"fixture","judgment":{"dimensions":{"importance":8}}})
   pred.append({"case_id":c["id"],"judgment":{"dimensions":{"importance":7}}})
   adjudications[c["id"]]={"approved":True,"origin":"human","adjudicator_id":"fixture-e1","packet_hash":c["packet_hash"],"judgment":{"dimensions":{"importance":8}}}
  acceptance={"clinical/hypothesis":{"approved":True,"origin":"human","approver_id":"fixture-e1","protocol_hash":"p","validation_case_ids":["c0","c1"],"minimum_validation_cases":2,"maximum_dimension_mae":.5}}
  r=calibration_report(cases,pred,reviews,reg,adjudications,acceptance)
  self.assertEqual(r["levels"]["hypothesis"]["by_domain"]["clinical"]["scientific_calibration_status"],"pending_expert_acceptance")
  acceptance["clinical/hypothesis"]["maximum_dimension_mae"]=1
  r=calibration_report(cases,pred,reviews,reg,adjudications,acceptance)
  self.assertEqual(r["levels"]["hypothesis"]["by_domain"]["clinical"]["scientific_calibration_status"],"expert_accepted_within_declared_scope")
  self.assertFalse(r["headline_release_approved"])
 def test_known_gate_failure_retains_other_uncertainty(self):
  g=gate_counts([{"importance":"uncertain","increment_beyond_start":"yes","evidence_maturity":"proposed"}])
  self.assertEqual(g["not_qualifying"],1);self.assertEqual(g["families_with_uncertain_components"],1)


 def test_maturity_overclaim_separate_from_other_labels(self):
  c=self.case("discovery");reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  reviews=self.reviews(c)
  for r in reviews:r["judgment"]={"labels":{"evidence_maturity":"diagnostically_examined"}}
  approval={"c":{"approved":True,"origin":"human","adjudicator_id":"fixture-e1","packet_hash":c["packet_hash"],"judgment":{"labels":{"evidence_maturity":"diagnostically_examined"}}}}
  pred=[{"case_id":"c","judgment":{"labels":{"evidence_maturity":"study_completed"}}}]
  metrics=calibration_report([c],pred,reviews,reg,approval)["levels"]["discovery"]["all_adjudicated"]
  self.assertEqual(metrics["label_agreement"],0);self.assertEqual(metrics["maturity_overclaim_rate"],1)
 def test_cli_preserves_existing_independent_judgment(self):
  import tempfile,json,csv,subprocess,sys
  from pathlib import Path
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);c=self.case();registry=[{"id":"fixture-e1","domains":["clinical"]}]
   (p/"cases.json").write_text(json.dumps([c]));(p/"registry.json").write_text(json.dumps(registry))
   old=self.reviews(c)[:1];(p/"reviews.json").write_text(json.dumps(old));original=(p/"reviews.json").read_bytes()
   with (p/"new.csv").open("w",newline="") as f:
    fields=["case_id","packet_hash","reviewer_id","origin","independent","category","dimensions_json","labels_json","rationale"]
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    w.writerow({"case_id":"c","packet_hash":c["packet_hash"],"reviewer_id":"fixture-e1","origin":"human","independent":"true","category":"rejected","dimensions_json":"{}","labels_json":"{}","rationale":"changed after discussion"})
   run=subprocess.run([sys.executable,"-m","dfm_bench","calibration-import","--csv",str(p/"new.csv"),"--cases",str(p/"cases.json"),"--reviewer-registry",str(p/"registry.json"),"--output",str(p/"reviews.json")],capture_output=True,text=True)
   self.assertEqual(run.returncode,2);self.assertEqual((p/"reviews.json").read_bytes(),original)


 def test_unknown_disagreement_is_not_hidden_or_zero_imputed(self):
  c=self.case();reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  reviews=self.reviews(c)
  approval={"c":{"approved":True,"origin":"human","adjudicator_id":"fixture-e1","packet_hash":c["packet_hash"],"judgment":{"dimensions":{"importance":8,"novelty":None,"grounding":5}}}}
  pred=[{"case_id":"c","judgment":{"dimensions":{"importance":7,"novelty":6,"grounding":None}}}]
  metrics=calibration_report([c],pred,reviews,reg,approval)["levels"]["hypothesis"]["all_adjudicated"]
  self.assertEqual(metrics["dimension_comparisons"],1);self.assertEqual(metrics["dimension_mae"],1)
  self.assertEqual(metrics["expert_known_model_unknown"],1);self.assertEqual(metrics["expert_unknown_model_scored"],1)


 def test_string_false_is_not_independent_human_review(self):
  c=self.case();reviews=self.reviews(c);reviews[0]["independent"]="false"
  reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  with self.assertRaises(ValueError):calibration_report([c],[],reviews,reg)
 def test_string_false_never_approves_reference(self):
  c=self.case();reg=[{"id":e,"domains":["clinical"]} for e in ["fixture-e1","fixture-e2"]]
  a={"c":{"approved":"false","origin":"human","adjudicator_id":"fixture-e1","packet_hash":c["packet_hash"],"judgment":{"category":"eligible"}}}
  r=calibration_report([c],[{"case_id":"c","judgment":{"category":"eligible"}}],self.reviews(c),reg,a)
  self.assertEqual(r["levels"]["hypothesis"]["all_adjudicated"]["matched_cases"],0)


 def test_plain_column_form_needs_no_json_entry(self):
  import tempfile,csv
  from pathlib import Path
  c=self.case();reg=[{"id":"fixture-e1","domains":["clinical"]}]
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"form.csv"
   columns=["case_id","packet_hash","reviewer_id","origin","independent","category","score_importance","score_novelty","evidence_refs","rationale"]
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
    w.writerow({"case_id":"c","packet_hash":c["packet_hash"],"reviewer_id":"fixture-e1","origin":"human","independent":"yes","category":"eligible","score_importance":"7","score_novelty":"unknown","evidence_refs":"A1; A2","rationale":"fixture"})
   rows=import_human_csv(p,[c],reg)
   self.assertEqual(rows[0]["judgment"]["dimensions"],{"importance":7.0,"novelty":None})
   self.assertEqual(rows[0]["evidence_refs"],["A1","A2"])

class FrontierTests(unittest.TestCase):
 def records(self):
  return [{"id":str(i),"dataset":"d","episode":i,"score":s,"validity":"eligible","family_id":f,"evidence_mode":"retrospective_final_snapshot"} for i,s,f in [(0,6,"seed"),(1,7,"a"),(2,5,"b"),(3,8,"a")]]
 def run_f(self,rs,extra=None,events=None):
  inv=[{k:r[k] for k in ("id","dataset","episode","family_id")} for r in rs]+(extra or [])
  return frontier(rs,inv,[{"dataset":"d","episode":i} for i in range(5)],validity_events=events)["rows"]
 def test_monotone_actual_archive_and_fixed_k(self):
  rows=self.run_f(self.records());self.assertEqual([r["best_so_far"] for r in rows],[6,7,7,8,8])
  self.assertIsNone(rows[1]["top_k"]);self.assertEqual(rows[2]["top_k"],6)
  self.assertAlmostEqual(rows[3]["top_k"],19/3)
  self.assertEqual(rows[4]["new_candidate_count"],0)
 def test_family_dedup_and_input_order(self):
  a=self.run_f(self.records());b=self.run_f(self.records()[::-1]);self.assertEqual(a,b)
  self.assertEqual(a[3]["distinct_scored_families"],3)
 def test_missing_scores_are_lower_bound(self):
  rows=self.run_f(self.records(),[{"id":"unscored","dataset":"d","episode":2,"family_id":"u"}])
  self.assertFalse(rows[-1]["coverage_complete"]);self.assertEqual(rows[-1]["best_so_far"],8)
 def test_refutation_does_not_rewrite_history(self):
  rows=self.run_f(self.records(),events=[{"id":"3","episode":4,"status":"rejected"}])
  self.assertEqual(rows[-1]["best_so_far"],8);self.assertEqual(rows[-1]["currently_warranted"],7)
 def test_future_evidence_and_invalid_scores(self):
  rs=self.records();rs[1].update(evidence_mode="as_of",evidence_latest_episode=3)
  with self.assertRaises(ValueError):self.run_f(rs)
  rs=self.records();rs[1]["score"]=float("nan")
  with self.assertRaises(ValueError):self.run_f(rs)
 def test_no_score_is_not_zero_and_no_new_level(self):
  r=self.records()[0];r.update(score=None,validity="uncertain")
  rows=self.run_f([r]);self.assertIsNone(rows[0]["best_so_far"]);self.assertFalse(rows[0]["coverage_complete"]);self.assertIsNone(rows[0]["currently_warranted"])

if __name__=="__main__":unittest.main()
