from collections import Counter, deque

def topology(nodes):
    by_id = {n["id"]:n for n in nodes}
    if len(by_id)!=len(nodes): raise ValueError("Duplicate hypothesis identity")
    indegree = {}; children = {k:[] for k in by_id}
    for key,node in by_id.items():
        parents = node["parents"]
        if len(parents)!=len(set(parents)): raise ValueError("Duplicate parent")
        if any(p not in by_id for p in parents): raise ValueError("Dangling parent")
        indegree[key]=len(parents)
        for parent in parents: children[parent].append(key)
    q=deque(sorted(k for k,v in indegree.items() if not v)); order=[]
    while q:
        key=q.popleft(); order.append(key)
        for child in children[key]:
            indegree[child]-=1
            if not indegree[child]: q.append(child)
    if len(order)!=len(nodes): raise ValueError("Cyclic ancestry")
    return by_id,order,children

def audit(nodes):
    by_id,order,children=topology(nodes);depth={}
    for key in order: depth[key]=max((depth[p]+1 for p in by_id[key]["parents"]),default=0)
    return {"candidates":len(nodes),"edges":sum(len(n["parents"]) for n in nodes),
       "roots":sum(not n["parents"] for n in nodes),"crossovers":sum(len(n["parents"])>1 for n in nodes),
       "leaves":sum(not v for v in children.values()),"max_depth":max(depth.values(),default=0),
       "datasets":dict(sorted(Counter(n["dataset"] for n in nodes).items()))}

def trajectory(nodes,path_ids):
    by_id,_,_=topology(nodes)
    if not path_ids or len(set(path_ids))!=len(path_ids) or any(x not in by_id for x in path_ids):
        raise ValueError("Invalid trajectory identity")
    if any(a not in by_id[b]["parents"] for a,b in zip(path_ids,path_ids[1:])):
        raise ValueError("Trajectory is not a genuine parent-child path")
    context=sorted({p for i,x in enumerate(path_ids) for p in by_id[x]["parents"]
        if i==0 or p!=path_ids[i-1]})
    return {"path_ids":path_ids,"context_parent_ids":context,
       "scope":"segment" if by_id[path_ids[0]]["parents"] else "full_path"}
