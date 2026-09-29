import hashlib
import json
from importlib.resources import files

def registry():
    root=files("dfm_bench").joinpath("rubrics")
    entries=json.loads(root.joinpath("registry.json").read_text())
    for entry in entries:
        content=root.joinpath(entry["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest()!=entry["sha256"]:
            raise ValueError("Rubric hash mismatch: "+entry["rubric_id"])
        if sum(entry["weights"])!=100: raise ValueError("Invalid rubric weights")
    return entries

def get_rubrics(domain):
    return [e for e in registry() if e["domain"]==domain]
