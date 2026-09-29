import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from dfm_bench.pilot import Reviewer,validate_items,validate_campaign,campaign_arithmetic,split_text,batches,clean,MODEL

class Response:
 def __init__(self,result):self.data=json.dumps(result).encode()
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,*args):return self.data
class PilotTests(unittest.TestCase):
 def test_split_has_no_loss(self):
  text="éabcdef"*10000
  parts=split_text("A",text,101)
  self.assertEqual("".join(p["text"] for p in parts),text)
  self.assertEqual(parts[-1]["char_end"],len(text))
 def test_coverage_ids_exact(self):
  with self.assertRaises(ValueError):validate_items({"items":[{"id":"a","summary":"x"}]},["a","b"])
  with self.assertRaises(ValueError):validate_items({"items":[{"id":"a","summary":"x"},{"id":"a","summary":"x"}]},["a"])
 def test_batch_no_sampling(self):
  items=[{"id":str(i),"text":"x"*100} for i in range(100)]
  self.assertEqual([x for b in batches(items,500,3) for x in b],items)
 def review(self):
  return {"review_status":"complete","dimensions":[{"id":f"T{i}","status":"scored","score":2,"rationale":"bounded","evidence_refs":["N1"]} for i in range(1,8)]}
 def test_weighted_arithmetic(self):
  r=self.review();validate_campaign(r,{"N1"})
  self.assertEqual(campaign_arithmetic(r)["composite"],50)
 def test_partial_withholds_full(self):
  self.assertIsNone(campaign_arithmetic(self.review(),True)["composite"])
 def test_unknown_not_zero(self):
  r=self.review();r["dimensions"][0].update(status="unknown",score=None)
  a=campaign_arithmetic(r);self.assertIsNone(a["composite"]);self.assertEqual(a["score_bounds"],[37.5,62.5])
 def test_invalid_reference(self):
  with self.assertRaises(ValueError):validate_campaign(self.review(),{"N2"})
 def test_boolean_score_invalid(self):
  r=self.review();r["dimensions"][0]["score"]=True
  with self.assertRaises(ValueError):validate_campaign(r,{"N1"})
 def test_clean_secrets_and_paths(self):
  self.assertNotIn("/data_storage",clean("/data_storage/private/source.txt"))
  self.assertNotIn("x"*25,clean("sk_"+"x"*25))
 def test_budget_blocks_before_network(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   r=Reviewer(root,key,budget=0)
   with self.assertRaises(RuntimeError):r.call("t",{},"Return JSON",lambda v:None,128)
 def test_cache_and_billing_and_no_secret_in_request(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic-secret")
   r=Reviewer(root,key)
   result={"model":MODEL,"usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":"stop","message":{"content":"{\"ok\":true}"}}]}
   with patch("urllib.request.build_opener") as mock:
    mock.return_value.open.return_value=Response(result)
    self.assertTrue(r.call("t",{},"Return JSON",lambda v:None,128)["ok"])
    r.call("t",{},"Return JSON",lambda v:None,128)
    self.assertEqual(mock.return_value.open.call_count,1)
   self.assertEqual(len(r.entries),1)
   self.assertAlmostEqual(r.spent(),.0000196)
   for p in (root/"requests").iterdir():self.assertNotIn("synthetic-secret",p.read_text())
 def test_missing_usage_stops_and_reserves(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   r=Reviewer(root,key)
   with patch("urllib.request.build_opener") as mock:
    mock.return_value.open.return_value=Response({})
    with self.assertRaises(RuntimeError):r.call("t",{},"Return JSON",lambda v:None,128)
    self.assertEqual(mock.return_value.open.call_count,1)
   self.assertGreater(r.spent(),0)

 def test_supplement_all_bytes_and_reference(self):
  from test_foundations import fixture
  from dfm_bench.snapshot import import_run
  from dfm_bench.pilot import prepare_domain
  import hashlib
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source=root/"source";db=fixture(source);db.close()
   snap=root/"snapshot";import_run(source,"battery",snap,max_bytes=2)
   data=json.loads((snap/"snapshot.json").read_text())
   artifact=data["artifacts"][0]
   base=root/"pilot";out=base/"battery";out.mkdir(parents=True)
   supp=base/"battery-supplement";supp.mkdir()
   raw=(source/"evidence.md").read_bytes();path=supp/"support";path.write_bytes(raw)
   (supp/"manifest.json").write_text(json.dumps({"source_ref":artifact["id"],"path":str(path),
      "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}))
   data,nodes,decisions,parts,coverage=prepare_domain("battery",snap,out)
   self.assertEqual(coverage["unavailable_artifact_references"],0)
   self.assertEqual(coverage["unique_available_artifacts"],1)
   self.assertEqual("".join(p["text"] for p in parts),raw.decode())
   self.assertIn("AX0001",nodes[-1]["artifact_refs"])


 def test_targeted_token_override_reuses_completed_call(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   (root/"request-overrides.json").write_text(json.dumps({"t":{"max_tokens":24000}}))
   r=Reviewer(root,key)
   result={"model":MODEL,"usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":"stop","message":{"content":"{\"ok\":true}"}}]}
   with patch("urllib.request.build_opener") as mock:
    mock.return_value.open.return_value=Response(result)
    r.call("t",{},"Return JSON",lambda v:None,128)
    request=mock.return_value.open.call_args.args[0]
    self.assertEqual(json.loads(request.data)["max_tokens"],24000)
    r.call("t",{},"Return JSON",lambda v:None,128)
    self.assertEqual(mock.return_value.open.call_count,1)


 def test_budget_waits_for_active_reservation_to_settle(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   r=Reviewer(root,key,budget=.001)
   r.entries=[{"fingerprint":"other","state":"reserved","charged_usd":.0009}]
   def settle(_):
    r.entries[0].update(state="accepted",charged_usd=.00001)
   result={"model":MODEL,"usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}
   with patch("urllib.request.build_opener") as mock,patch("dfm_bench.pilot.time.sleep",side_effect=settle) as sleep:
    mock.return_value.open.return_value=Response(result)
    r.call("t",{},"Return JSON",lambda v:None,128)
    sleep.assert_called_once()
   self.assertLessEqual(r.spent(),.001)
 def test_measured_tokens_only_for_identical_request(self):
  from dfm_bench.pilot import SYSTEM
  from dfm_bench.common import canonical,digest
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   r=Reviewer(root,key,budget=.001)
   payload={"text":"x"*50000};instruction="Return JSON"
   messages=[{"role":"system","content":SYSTEM},{"role":"user","content":instruction+"\n\nEVIDENCE_JSON:\n"+canonical(payload)}]
   body={"model":MODEL,"messages":messages,"temperature":0,"max_tokens":128,"response_format":{"type":"json_object"}}
   r.entries=[{"task":"t","fingerprint":digest(body),"state":"failed","charged_usd":.00002,"usage":{"prompt_tokens":100,"completion_tokens":20}}]
   result={"model":MODEL,"usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}
   with patch("urllib.request.build_opener") as mock:
    mock.return_value.open.return_value=Response(result)
    r.call("t",payload,instruction,lambda v:None,128)
    with self.assertRaises(RuntimeError):r.call("different",{"text":"y"*50000},instruction,lambda v:None,128)
    self.assertEqual(mock.return_value.open.call_count,1)
   self.assertEqual(r.entries[-1]["input_reservation_basis"],"same-request measured tokens + 4096")


 def test_verified_cache_pricing_uses_reported_tokens_only(self):
  from dfm_bench.pilot import priced_usage
  u={"prompt_tokens":100,"completion_tokens":20,"prompt_tokens_details":{"cached_tokens":80}}
  v=priced_usage(u,.028)
  self.assertAlmostEqual(v["charged_usd"],.00001064)
  self.assertAlmostEqual(v["uncached_upper_estimate_usd"],.0000196)
  self.assertEqual(v["cache_read_tokens_priced"],80)
 def test_unknown_or_invalid_cache_tokens_get_no_discount(self):
  from dfm_bench.pilot import priced_usage
  for details in (None,{},{"cached_tokens":200},{"cached_tokens":-1},{"cached_tokens":True}):
   u={"prompt_tokens":100,"completion_tokens":20,"prompt_tokens_details":details}
   self.assertAlmostEqual(priced_usage(u,.028)["charged_usd"],.0000196)
 def test_wrong_model_pricing_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);key=root/"key";key.write_text("synthetic")
   (root/"pricing-policy.json").write_text(json.dumps({"model":"different","input_usd_per_m":.14,"output_usd_per_m":.28,"cache_read_usd_per_m":.028}))
   with self.assertRaises(ValueError):Reviewer(root,key)

if __name__=="__main__":unittest.main()
