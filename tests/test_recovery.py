import json,tempfile,unittest
from pathlib import Path
from dfm_bench.five_level import run_transition

class RecoveryTests(unittest.TestCase):
 def test_retains_final_valid_rows_and_recovers_only_bad_edge(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/"calls").mkdir();out=root/"domain";out.mkdir()
   good={"id":"P1","verdict":"necessary_repair","reason":"final response retained","refs":["n1"]}
   bad={"id":"P2","verdict":"substantive_progress","reason":"wrong evidence","refs":["absent"]}
   (root/"calls/f.attempt-2.response.json").write_text(json.dumps({"content":json.dumps({"transitions":[good,bad]})}))
   (root/"calls/f.attempt-1.response.json").write_text(json.dumps({"content":json.dumps({"transitions":[{**good,"verdict":"substantive_progress"},bad]})}))
   class FakeReviewer:
    def __init__(self):
     self.out=root;self.entries=[{"task":"test/transition/000","fingerprint":"f"} for _ in range(2)];self.called=[]
    def call(self,name,payload,prompt,validator,tokens):
     self.called.append(name)
     if "/isolated/" not in name:raise RuntimeError("Retry allowance exhausted")
     result={"transitions":[{"id":"P2","verdict":"marginal_repetition","reason":"isolated review","refs":["n2"]}]}
     validator(result);return result
   ctx={"domain":"test","transition_rubric":"original",
    "pairs":[{"id":"P1","parent":"n1","child":"n2"},{"id":"P2","parent":"n2","child":"n3"}],
    "nodes":{"n1":{"id":"n1","parents":[],"artifact_refs":[]},"n2":{"id":"n2","parents":["n1"],"artifact_refs":[]},
    "n3":{"id":"n3","parents":["n2"],"artifact_refs":[]}},"support":{}}
   reviewer=FakeReviewer();result=run_transition(ctx,reviewer,out)
   self.assertEqual(reviewer.called,["test/transition/000","test/transition/000/isolated/P2"])
   self.assertEqual(result["counts"]["necessary_repair"],1)
   self.assertEqual(result["counts"]["substantive_progress"],0)
   self.assertEqual(json.loads((out/"transition-reviews.json").read_text())[0],good)
   self.assertEqual(len(json.loads((out/"transition-recovery-000.json").read_text())),2)

 def test_trajectory_recovery_keeps_final_valid_score(self):
  from dfm_bench.five_level import run_trajectory
  import copy
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/"calls").mkdir();out=root/"domain";out.mkdir()
   def row(pid,ref,score=2):
    return {"id":pid,"review_status":"complete","dimensions":[{"id":f"L{i}","status":"scored",
      "score":score,"rationale":"frozen evidence","refs":[ref]} for i in range(1,8)]}
   good=row("PATH1","n1");bad=row("PATH2","absent")
   for attempt,first in [(1,row("PATH1","n1",4)),(2,good)]:
    (root/f"calls/f.attempt-{attempt}.response.json").write_text(json.dumps({"content":json.dumps({"trajectories":[first,bad]})}))
   class FakeReviewer:
    def __init__(self):
     self.out=root;self.entries=[{"task":"test/trajectory/000","fingerprint":"f"} for _ in range(2)];self.called=[]
    def call(self,name,payload,prompt,validator,tokens):
     self.called.append(name)
     if "/isolated/" not in name:raise RuntimeError("Retry allowance exhausted")
     result={"trajectories":[row("PATH2","n2")]}
     validator(result);return result
   ctx={"domain":"test","trajectory_rubric":"original","opportunity_map":{},"decisions":[],"support":{},
     "nodes":{n:{"id":n,"parents":[],"artifact_refs":[]} for n in ("n1","n2","n3")},
     "paths":[{"id":"PATH1","path_ids":["n1","n2"],"context_parent_ids":[]},{"id":"PATH2","path_ids":["n2","n3"],"context_parent_ids":[]}],
     "path_manifest":{}}
   reviewer=FakeReviewer();result=run_trajectory(ctx,reviewer,out)
   self.assertEqual(reviewer.called,["test/trajectory/000","test/trajectory/000/isolated/PATH2"])
   self.assertEqual(result["mean_complete_full_scope_score"],50)
   rows=json.loads((out/"trajectory-reviews.json").read_text())
   self.assertEqual(rows[0]["dimensions"],good["dimensions"])
