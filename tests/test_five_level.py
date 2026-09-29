import unittest
from dfm_bench.five_level import (hypothesis_metrics,transition_metrics,select_paths,orient_pairs,
 validate_hypotheses,validate_transitions,validate_families,discovery_metrics,path_arithmetic)

class FiveLevelTests(unittest.TestCase):
 def test_tie_adjusted_win_and_abstention(self):
  ps=[{"id":str(i),"child_side":"A" if i%2==0 else "B"} for i in range(4)]
  js=[{"id":"0","winner":"A"},{"id":"1","winner":"A"},{"id":"2","winner":"tie"},{"id":"3","winner":"insufficient_evidence"}]
  r=hypothesis_metrics(js,ps)
  self.assertEqual(r["tie_adjusted_preference"]["value"],.5)
  self.assertEqual(r["counts"]["win"],1);self.assertEqual(r["counts"]["loss"],1)
  self.assertEqual(r["insufficient_evidence"]["value"],.25)
 def test_all_abstain_is_not_zero_score(self):
  r=hypothesis_metrics([{"id":"p","winner":"insufficient_evidence"}],[{"id":"p","child_side":"A"}])
  self.assertIsNone(r["tie_adjusted_preference"]["value"])
  self.assertIsNone(transition_metrics([{"verdict":"insufficient_evidence"}])["useful_step"]["value"])
 def test_progress_repair_separated(self):
  js=[{"verdict":v} for v in ["substantive_progress","necessary_repair","marginal_repetition","insufficient_evidence"]]
  r=transition_metrics(js)
  self.assertAlmostEqual(r["substantive_progress"]["value"],1/3)
  self.assertAlmostEqual(r["useful_step"]["value"],2/3)
  self.assertEqual(r["insufficient_evidence"]["value"],.25)
 def test_invalid_preference_and_coverage(self):
  with self.assertRaises(ValueError):validate_hypotheses({"comparisons":[{"id":"p","winner":"C","reason":"x"}]},["p"])
  with self.assertRaises(ValueError):validate_hypotheses({"comparisons":[]},["p"])
 def test_transition_known_refs(self):
  with self.assertRaises(ValueError):validate_transitions({"transitions":[{"id":"p","verdict":"necessary_repair","reason":"x","refs":["absent"]}]},["p"],{"p":{"N1"}})
 def test_paths_one_per_leaf_not_all_crossover_paths(self):
  ns=[{"id":"a","parents":[],"dataset":"d"},{"id":"b","parents":["a"],"dataset":"d"},
      {"id":"c","parents":["a"],"dataset":"d"},{"id":"d","parents":["b","c"],"dataset":"d"},
      {"id":"singleton","parents":[],"dataset":"d"}]
  paths,m=select_paths(ns)
  self.assertEqual(m["all_root_to_leaf_paths"],3)
  self.assertEqual(m["selected_paths"],2)
  self.assertEqual(m["singleton_paths"],1)
  p=next(x for x in paths if len(x["path_ids"])>1)
  self.assertEqual(p["path_ids"],["a","b","d"]);self.assertEqual(p["context_parent_ids"],["c"])
 def test_pair_orientation_reproducible(self):
  edges=[{"parent_id":"a","child_id":"b"},{"parent_id":"a","child_id":"c"}]
  self.assertEqual(orient_pairs(edges,"snap"),orient_pairs(edges[::-1],"snap"))
 def test_trajectory_uses_distinct_weights(self):
  ds=[{"id":f"L{i}","status":"scored","score":4 if i==2 else 0} for i in range(1,8)]
  self.assertEqual(path_arithmetic({"dimensions":ds,"review_status":"complete"})["complete_full_scope_composite"],30)
  self.assertIsNone(path_arithmetic({"dimensions":ds,"review_status":"partial"})["complete_full_scope_composite"])
 def family(self):
  return {"candidate_ids":["N1"],"question":"q","contribution":"c","limits":"uncertain novelty","importance":"consequential",
   "increment_beyond_start":"yes","evidence_maturity":"diagnostically_examined","disposition":"inconclusive","evidence_refs":["A1"]}
 def test_discovery_partition_and_evidence(self):
  f=self.family();validate_families({"families":[f]},["N1"],{"A1"})
  with self.assertRaises(ValueError):validate_families({"families":[f,f]},["N1"],{"A1"})
  with self.assertRaises(ValueError):validate_families({"families":[f]},["N1","N2"],{"A1"})
 def test_discovery_does_not_count_plan_as_executed(self):
  f=self.family();g=self.family();g["candidate_ids"]=["N2"];g["evidence_maturity"]="proposed"
  r=discovery_metrics([f,g],20)
  self.assertEqual(r["proposed_contribution_families"],2)
  self.assertEqual(r["provisional_consequential_evidence_advances"],1)
  self.assertEqual(r["provisional_advance_yield_per_100_started_episodes"],5)
  self.assertIsNone(r["expert_adjudicated_discoveries"])

 def test_part_references_are_allowed_only_within_object(self):
  from dfm_bench.five_level import evidence_ids
  self.assertEqual(evidence_ids({"A1":[{"id":"A1:part:0"}]}),{"A1","A1:part:0"})
  validate_transitions({"transitions":[{"id":"p","verdict":"necessary_repair","reason":"repair","refs":["A1:part:0"]}]},["p"],{"p":{"A1:part:0"}})
 def test_not_applicable_normalizes_but_unknown_does_not(self):
  ds=[{"id":f"L{i}","status":"scored","score":2} for i in range(1,8)]
  ds[0].update(status="not_applicable",score=None)
  r=path_arithmetic({"dimensions":ds,"review_status":"complete"})
  self.assertEqual(r["applicable_weight"],95)
  self.assertEqual(r["complete_scope_adjusted_composite"],50)
  ds[1].update(status="unknown",score=None)
  self.assertIsNone(path_arithmetic({"dimensions":ds,"review_status":"complete"})["scope_adjusted_profile"])
 def test_merge_cannot_drop_or_duplicate_families(self):
  from dfm_bench.five_level import validate_family_merge
  a={"id":"f1",**self.family()}
  b={"id":"f2",**self.family()};b["candidate_ids"]=["N2"]
  group={k:v for k,v in self.family().items() if k!="candidate_ids"};group["source_family_ids"]=["f1","f2"]
  self.assertEqual(validate_family_merge({"groups":[group]},[a,b])[0]["candidate_ids"],["N1","N2"])
  group["source_family_ids"]=["f1"]
  with self.assertRaises(ValueError):validate_family_merge({"groups":[group]},[a,b])
 def test_scoped_packet_reuses_actual_accepted_request(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  from dfm_bench.five_level import scoped_packet
  from dfm_bench.pilot import SYSTEM,MODEL
  from dfm_bench.common import canonical,digest
  payload={"x":1};instruction="judge";allowed={"p":{"N1"}}
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/"calls").mkdir()
   with patch("dfm_bench.five_level.ROOT",root):
    new,newinst=scoped_packet(payload,instruction,allowed,20000)
    self.assertIn("allowed_evidence_refs_by_object",new)
    messages=[{"role":"system","content":SYSTEM},{"role":"user","content":instruction+"\n\nEVIDENCE_JSON:\n"+canonical(payload)}]
    body={"model":MODEL,"messages":messages,"temperature":0,"max_tokens":20000,"response_format":{"type":"json_object"}}
    (root/"calls"/(digest(body)+".json")).write_text("{}")
    self.assertEqual(scoped_packet(payload,instruction,allowed,20000),(payload,instruction))


 def test_trajectory_rejects_neighbor_and_fabricated_na_citations(self):
  from dfm_bench.five_level import validate_trajectories
  rows={"trajectories":[{"id":"P1","review_status":"complete","dimensions":[
    {"id":f"L{i}","status":"scored","score":2,"rationale":"Evidence-based judgment","refs":["N1"]} for i in range(1,8)]}]}
  validate_trajectories(rows,["P1"],{"P1":{"N1","A1"}})
  for invalid in ("N2","A1_NA","A1:part:9"):
   rows["trajectories"][0]["dimensions"][0]["refs"]=[invalid]
   with self.assertRaises(ValueError):validate_trajectories(rows,["P1"],{"P1":{"N1","A1"}})
 def test_trajectory_unknown_cannot_hide_numeric_score(self):
  from dfm_bench.five_level import validate_trajectories
  rows={"trajectories":[{"id":"P1","review_status":"partial","dimensions":[
    {"id":f"L{i}","status":"scored","score":2,"rationale":"Evidence-based judgment","refs":["N1"]} for i in range(1,8)]}]}
  rows["trajectories"][0]["dimensions"][0]["status"]="unknown"
  with self.assertRaises(ValueError):validate_trajectories(rows,["P1"],{"P1":{"N1"}})


 def test_merge_cannot_upgrade_evidence_maturity(self):
  from dfm_bench.five_level import validate_family_merge
  source={"id":"f1",**self.family()}
  group={k:v for k,v in self.family().items() if k!="candidate_ids"}
  group.update(source_family_ids=["f1"],evidence_maturity="independently_checked")
  with self.assertRaises(ValueError):validate_family_merge({"groups":[group]},[source])

if __name__=="__main__":unittest.main()
