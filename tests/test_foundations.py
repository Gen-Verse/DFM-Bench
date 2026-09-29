import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dfm_bench.common import digest,file_hash
from dfm_bench.contracts import validate_record,json_schemas
from dfm_bench.graph import audit,trajectory
from dfm_bench.registry import registry
from dfm_bench.snapshot import import_run,load_snapshot,freeze_artifact,validate_snapshot
from dfm_bench.report import make_report

def fixture(root,wal=False):
    root.mkdir();db=sqlite3.connect(root/"state.sqlite")
    if wal:db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA wal_autocheckpoint=0")
    db.executescript("""
    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE candidates(id TEXT,episode_id TEXT,dataset TEXT,proposal TEXT,parents TEXT,change_note TEXT,
      files TEXT,content_hash TEXT,created_at REAL,origin TEXT);
    CREATE TABLE episodes(id TEXT,dataset TEXT,ordinal INTEGER,work_history TEXT,closed_at REAL,
      selected_id TEXT,outcome TEXT,reason TEXT);
    CREATE TABLE jobs(id TEXT,operation TEXT,episode_id TEXT,candidate_id TEXT,inputs TEXT,state TEXT,result TEXT,created_at REAL);
    CREATE TABLE attempts(id TEXT,job_id TEXT,number INTEGER,state TEXT,started_at REAL,ended_at REAL,result TEXT);
    CREATE TABLE actors(active INTEGER,role TEXT);
    """)
    db.executemany("INSERT INTO meta VALUES (?,?)",[("run_id","synthetic"),("config",json.dumps({
      "runtime_version":"fixture","validation_mode":"readiness","credential_file":"DO_NOT_EXPORT","api_key":"DO_NOT_EXPORT"})),
      ("operator_stop","true")])
    evidence=root/"evidence.md";evidence.write_text("A bounded synthetic diagnostic.")
    sha=file_hash(evidence)
    for i,parents in enumerate([[],["a"],["a"],["b","c"]]):
        key="abcd"[i]
        files=[{"path":str(evidence),"sha256":sha,"dataset_source":False}] if key=="d" else []
        db.execute("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?)",
          (key,"e1","synthetic","Test hypothesis "+key,json.dumps(parents),"change",json.dumps(files),digest(key),i+1,None))
    work=[{"operation":"restart","parents":[],"context_candidate_ids":["b"],"time":10,"reason":"different question"}]
    db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)",("e1","synthetic",1,json.dumps(work),20,"d","selected","done"))
    db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)",("e2","synthetic",2,"[]",None,None,None,None))
    manifest={"candidate_hash":digest("d"),"files":{"instruction.md":sha}}
    compile_result={"state":"succeeded","package":str(root/"package"),"manifest":manifest}
    pass_result={"state":"succeeded","package":str(root/"package"),"validation_mode":"readiness",
       "task_readiness":"passed","scientific_result":"not_established"}
    for j,op,cid,inputs,state,result in [
        ("c1","compile","d",{},"succeeded",compile_result),
        ("v1","validate",None,{"compile_job":"c1"},"succeeded",pass_result),
        ("v2","validate","b",{},"cancelled",{"state":"cancelled"}),
        ("v3","validate","c",{},"queued",{}),
        ("c2","compile","c",{},"failed",{"state":"failed"})]:
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (j,op,"e1",cid,json.dumps(inputs),state,json.dumps(result),10))
    for row in [
        ("a1","c1",1,"failed",11,12,{"state":"failed"}),
        ("a2","c1",2,"succeeded",13,14,compile_result),
        ("a3","v1",1,"failed",15,16,{"state":"failed","category":"verifier"}),
        ("a4","v1",2,"succeeded",17,18,pass_result),
        ("a5","v2",1,"cancelled",19,20,{"state":"cancelled"}),
        ("a6","c2",1,"failed",19,20,{"state":"failed"})]:
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)",(*row[:-1],json.dumps(row[-1])))
    for i in (1,2):
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",(f"s{i}","science",f"e{i}",None,"{}","succeeded","{}",1))
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)",(f"sa{i}",f"s{i}",1,"succeeded",1,2,"{}"))
    db.commit()
    return db

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.run=self.root/"run"
        self.db=fixture(self.run);self.db.close();self.out=self.root/"out"
    def tearDown(self): self.temp.cleanup()
    def imported(self):
        import_run(self.run,"clinical",self.out)
        return load_snapshot(self.out)
    def test_readonly_reproducible_and_accounted(self):
        before=file_hash(self.run/"state.sqlite")
        d,m=self.imported()
        m2=import_run(self.run,"clinical",self.root/"out2")
        self.assertEqual(m["snapshot_id"],m2["snapshot_id"])
        self.assertEqual(before,file_hash(self.run/"state.sqlite"))
        self.assertTrue(m["source_files_unchanged"])
        self.assertEqual(d["graph"]["edges"],4)
        self.assertEqual(d["graph"]["crossovers"],1)
        self.assertEqual(d["accounting"]["jobs"],7)
        self.assertEqual(d["accounting"]["attempts"],8)
    def test_config_secrets_never_exported(self):
        d,m=self.imported()
        self.assertNotIn("DO_NOT_EXPORT",json.dumps(d))
        self.assertNotIn("credential_file",json.dumps(d))
    def test_stopped_unclosed_not_final(self):
        d,_=self.imported()
        self.assertEqual(d["campaign"]["status"],"quiescent_unclosed")
        self.assertEqual(d["campaign"]["end_reason"],"operator_stopped")
    def test_restart_does_not_add_edges(self):
        d,_=self.imported()
        r=[x for x in d["decisions"] if x["operation"]=="restart"][0]
        self.assertFalse(r["parents"]);self.assertEqual(len(r["context_ids"]),1)
        self.assertEqual(len(d["edges"]),4)
    def test_crossovers_path_scope(self):
        d,_=self.imported();q=lambda x:"clinical:synthetic:hypothesis:"+x
        t=trajectory(d["hypotheses"],[q("a"),q("b"),q("d")])
        self.assertEqual(t["context_parent_ids"],[q("c")])
        self.assertEqual(trajectory(d["hypotheses"],[q("b"),q("d")])["scope"],"segment")
        with self.assertRaises(ValueError):trajectory(d["hypotheses"],[q("b"),q("c")])
    def test_cycles_dangling_duplicate(self):
        for nodes in [[{"id":"a","parents":["b"]}],[{"id":"a","parents":["a"]}],
            [{"id":"a","parents":[]},{"id":"a","parents":[]}]]:
            with self.assertRaises(ValueError):audit(nodes)
    def test_deep_graph_iterative(self):
        nodes=[{"id":str(i),"parents":[str(i-1)] if i else [],"dataset":"d"} for i in range(3000)]
        self.assertEqual(audit(nodes)["max_depth"],2999)
    def test_frozen_artifact_survives_source_mutation(self):
        d,m=self.imported();(self.run/"evidence.md").write_text("changed")
        d2,_=load_snapshot(self.out);self.assertEqual(d,d2)
        self.assertEqual(d["artifacts"][0]["status"],"frozen_private")
    def test_snapshot_tamper_detected(self):
        self.imported();p=self.out/"snapshot.json";p.write_text(p.read_text()+" ")
        with self.assertRaises(ValueError):load_snapshot(self.out)
    def test_artifact_tamper_detected(self):
        d,_=self.imported();(self.out/d["artifacts"][0]["relative_path"]).write_text("changed")
        with self.assertRaises(ValueError):load_snapshot(self.out)
    def test_dataset_never_opened(self):
        output=self.root/"art";output.mkdir()
        r=freeze_artifact({"dataset_source":True,"path":"/does/not/exist"},self.run,output,100)
        self.assertEqual(r["status"],"dataset_binding")
    def test_artifact_escape_changed_large_and_secret(self):
        output=self.root/"art";output.mkdir()
        outside=self.root/"outside.md";outside.write_text("outside")
        link=self.run/"link.md";link.symlink_to(outside)
        for path,sha,cap,reason in [
           (outside,file_hash(outside),1000,"outside_run_root"),
           (self.run/"evidence.md","0"*64,1000,"hash_mismatch"),
           (self.run/"evidence.md",file_hash(self.run/"evidence.md"),2,"oversized")]:
            r=freeze_artifact({"path":str(path),"sha256":sha},self.run,output,cap)
            self.assertEqual(r["reason"],reason)
        secret=self.run/"secret.json";secret.write_text('{"api_key":"'+ "x"*30 +'"}')
        r=freeze_artifact({"path":str(secret),"sha256":file_hash(secret)},self.run,output,1000)
        # JSON quoting between key and colon must be detected.
        self.assertEqual(r["reason"],"suspected_secret")
    def test_delivery_retry_denominators(self):
        d,m=self.imported();r=make_report(d,m)
        c=r["delivery"]["compilation"];v=r["delivery"]["readiness"]
        self.assertEqual(c["candidate_success"]["numerator"],1);self.assertEqual(c["candidate_success"]["denominator"],2)
        self.assertEqual(c["attempt_success"]["denominator"],3)
        self.assertEqual(v["candidate_success"]["numerator"],1);self.assertEqual(v["candidate_success"]["denominator"],2)
        self.assertEqual(v["candidate_first_attempt_success"]["numerator"],0)
        self.assertEqual(v["jobs_with_no_started_attempt"],1)
        self.assertEqual(r["episodes"]["closure_rate"]["value"],.5)
        self.assertIsNone(r["scientific_metrics"]["execution_completion"])
    def test_reference_success_not_readiness(self):
        d,m=self.imported()
        for e in d["delivery"]:
            if e["stage"]=="validate":e["evidence"]["validation_mode"]="reference"
        r=make_report(d,m)
        self.assertIsNone(r["delivery"]["readiness"]["candidate_success"]["value"])
    def test_pass_without_readiness_receipt_not_scientific_success(self):
        d,m=self.imported()
        for e in d["delivery"]:e["evidence"].pop("task_readiness",None)
        self.assertEqual(make_report(d,m)["delivery"]["readiness"]["ever_passed_candidates"],0)
    def test_unknown_mode_not_assumed(self):
        d,m=self.imported();d["source"]["validation_mode"]=None
        for e in d["delivery"]:e["evidence"].pop("validation_mode",None)
        self.assertIsNone(make_report(d,m)["delivery"]["readiness"]["candidate_success"]["value"])
    def test_domain_registry(self):
        rs=registry();self.assertEqual(len(rs),4)
        self.assertEqual({r["domain"] for r in rs},{"clinical","battery"})
        self.assertEqual(len({r["sha256"] for r in rs}),4)
    def test_schemas_and_invalid_review(self):
        self.assertIn("contribution",json_schemas())
        with self.assertRaises(ValueError):validate_record("review",{"id":"x"})
    def test_contribution_maturity_independent_of_disposition(self):
        validate_record("contribution",{"id":"c","candidate_ids":[],"contribution_type":"empirical_result",
          "evidence_maturity":"study_completed","disposition":"contradicted","exposure":"uncertain","evidence_refs":[],"importance":None})
    def test_invalid_domain_and_output(self):
        with self.assertRaises(ValueError):import_run(self.run,"wrong",self.out)
        with self.assertRaises(ValueError):import_run(self.run,"clinical",self.run/"bad")
        self.imported()
        with self.assertRaises(ValueError):import_run(self.run,"clinical",self.out)
    def test_wal_committed_state(self):
        run=self.root/"wal";db=fixture(run,wal=True)
        try:
            self.assertTrue(Path(str(run/"state.sqlite")+"-wal").exists())
            dpath=self.root/"wal-out";import_run(run,"battery",dpath)
            d,m=load_snapshot(dpath);self.assertEqual(len(d["hypotheses"]),4)
            self.assertTrue(m["source_files_unchanged"])
        finally:db.close()
    def test_unsupported_schema_does_not_write_source(self):
        db=sqlite3.connect(self.run/"state.sqlite");db.execute("ALTER TABLE candidates RENAME TO unsupported");db.close()
        before=file_hash(self.run/"state.sqlite")
        with self.assertRaises(ValueError):import_run(self.run,"clinical",self.out)
        self.assertEqual(before,file_hash(self.run/"state.sqlite"))
    def test_validation_rejects_accounting_and_links(self):
        d,m=self.imported();d["accounting"]["attempts"]+=1
        with self.assertRaises(ValueError):validate_snapshot(d)
    def test_no_quality_from_proposal_existence(self):
        d,m=self.imported();r=make_report(d,m)
        self.assertEqual(r["episodes"]["proposal_availability"]["value"],.5)
        self.assertIsNone(r["scientific_metrics"]["hypothesis_quality"])


    def test_imported_seed_has_no_episode(self):
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("UPDATE candidates SET episode_id=NULL,origin='expert_seed' WHERE id='a'");db.commit();db.close()
        d,_=self.imported()
        seed=next(n for n in d["hypotheses"] if n["source_id"]=="a")
        self.assertIsNone(seed["episode_id"]);self.assertTrue(seed["imported_seed"])
    def test_hash_named_support_and_symlink(self):
        output=self.root/"art";output.mkdir()
        raw=b"Scientific support";sha=hashlib.sha256(raw).hexdigest()
        support=self.run/"support";support.mkdir();p=support/sha;p.write_bytes(raw)
        r=freeze_artifact({"path":str(p),"sha256":sha},self.run,output,1000)
        self.assertEqual(r["status"],"frozen_private")
        link=self.run/"local.md";link.symlink_to(self.run/"evidence.md")
        r=freeze_artifact({"path":str(link),"sha256":file_hash(self.run/"evidence.md")},self.run,output,1000)
        self.assertEqual(r["reason"],"symlink")
    def test_retry_history_and_current_state_separate(self):
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("UPDATE jobs SET state='cancelled',result='{}' WHERE id='c1'");db.commit();db.close()
        d,m=self.imported();r=make_report(d,m)["delivery"]["compilation"]
        self.assertEqual(r["ever_passed_candidates"],1)
        self.assertEqual(r["current_job_passed_candidates"],0)
    def test_package_identity_uses_only_prior_compile(self):
        d,m=self.imported()
        a=next(e for e in d["delivery"] if e["source_id"]=="a3" and e["record_type"]=="attempt")
        self.assertIsNotNone(a["package_version"])
        self.assertEqual(a["evidence"]["package_version_origin"],"latest_prior_compile_attempt_receipt")
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("UPDATE attempts SET started_at=1 WHERE id='a3'");db.commit();db.close()
        import_run(self.run,"clinical",self.root/"early")
        early,_=load_snapshot(self.root/"early")
        a=next(e for e in early["delivery"] if e["source_id"]=="a3" and e["record_type"]=="attempt")
        self.assertIsNone(a["package_version"])
    def test_partial_package_rate_withheld(self):
        d,m=self.imported();r=make_report(d,m)
        self.assertIsNone(r["delivery"]["compilation"]["package_version_success"]["value"])
        self.assertEqual(r["delivery"]["compilation"]["package_version_success"]["coverage"],"partial")
    def test_null_and_boolean_numeric_validation(self):
        c={"id":"c","candidate_ids":[],"contribution_type":"empirical_result","evidence_maturity":"proposed",
           "disposition":"unresolved","exposure":"uncertain","evidence_refs":[],"importance":True}
        with self.assertRaises(ValueError):validate_record("contribution",c)
    def test_active_science_and_closed_stopped_are_distinct(self):
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("UPDATE episodes SET closed_at=20 WHERE id='e2'");db.commit();db.close()
        d,m=self.imported();self.assertEqual(d["campaign"]["status"],"closed")
        self.assertEqual(d["campaign"]["end_reason"],"operator_stopped")
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("INSERT INTO actors VALUES (1,'lead')");db.commit();db.close()
        import_run(self.run,"clinical",self.root/"active")
        d,_=load_snapshot(self.root/"active");self.assertEqual(d["campaign"]["status"],"open")


    def test_frozen_rubric_tamper(self):
        d,m=self.imported()
        (self.out/d["rubrics"][0]["frozen_path"]).write_text("tampered")
        with self.assertRaises(ValueError):load_snapshot(self.out)


    def test_unstarted_episode_is_not_started_denominator(self):
        db=sqlite3.connect(self.run/"state.sqlite")
        db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)",("e3","synthetic",3,"[]",None,None,None,None))
        db.commit();db.close()
        d,m=self.imported();r=make_report(d,m)
        self.assertEqual(r["episodes"]["recorded"],3)
        self.assertEqual(r["episodes"]["started"],2)
        self.assertEqual(r["episodes"]["closure_rate"]["value"],.5)
        self.assertAlmostEqual(r["episodes"]["recorded_closure_rate"]["value"],1/3)

if __name__=="__main__":unittest.main()
