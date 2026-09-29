import hashlib
import json
import sqlite3
from pathlib import Path
from .common import digest
from .contracts import DOMAINS

REQUIRED = {
 "candidates":{"id","episode_id","dataset","proposal","parents","change_note","files","content_hash","created_at","origin"},
 "episodes":{"id","dataset","ordinal","work_history","closed_at","selected_id","outcome","reason"},
 "jobs":{"id","operation","episode_id","candidate_id","inputs","state","result","created_at"},
 "attempts":{"id","job_id","number","state","started_at","ended_at","result"},
 "actors":{"active","role"}, "meta":{"key","value"},
}
ADAPTERS={"clinical":"ehr-thin-pairwise-v1","battery":"battery-discovery-pairwise-v1"}

def decode(value,default):
    return json.loads(value) if value else default

def read_source(path,domain):
    if domain not in DOMAINS: raise ValueError("Unsupported domain")
    path=Path(path).resolve(strict=True)
    source=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10)
    memory=sqlite3.connect(":memory:"); memory.row_factory=sqlite3.Row
    try:
        source.execute("PRAGMA query_only=ON")
        # SQLite backup reads a consistent committed view including WAL. No source checkpoint or migration.
        source.backup(memory,pages=512,sleep=0.01)
    finally:
        source.close()
    try:
        if memory.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity check failed")
        schema={}
        for table,columns in REQUIRED.items():
            found={r[1] for r in memory.execute("PRAGMA table_info("+table+")")}
            if not columns <= found: raise ValueError("Unsupported schema: "+table)
            schema[table]=sorted(found)
        rows={t:[dict(r) for r in memory.execute("SELECT * FROM "+t+" ORDER BY "+("key" if t=="meta" else "rowid"))]
              for t in REQUIRED}
        meta={r["key"]:r["value"] for r in rows.pop("meta")}
        config=decode(meta.get("config"),{})
        run_id=meta.get("run_id")
        if not run_id: raise ValueError("Missing run identity")
        # Deliberate allowlist: never export credentials, environment, URLs, prompts or native traces.
        provenance={k:config.get(k) for k in ("runtime_version","compiler_version","rubric_version","validation_mode","knowledge_policy")}
        provenance={k:(v if isinstance(v,(str,int,float,bool)) or v is None else "unavailable_structured") for k,v in provenance.items()}
        provenance.update({"adapter":ADAPTERS[domain],"source_schema_sha256":digest(schema),
          "consistent_database_sha256":hashlib.sha256(memory.serialize()).hexdigest(),
          "run_id":run_id,"operator_stopped":"operator_stop" in meta})
        return rows,provenance
    finally:
        memory.close()
