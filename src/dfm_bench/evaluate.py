"""Portable v1 scientific review: prepare offline, review explicitly, report offline."""
import argparse
from collections import Counter
import fcntl
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .common import digest, file_hash, private_dir, write_json
from .snapshot import load_snapshot, SENSITIVE
from .report import make_report
from .pilot import Reviewer, clean, validate_campaign, campaign_arithmetic
from .calibration import CARD_FIELDS, H_WEIGHTS, validate_card, validate_rating, composite
from .calibration_pilot import CARD_PROMPT, SCORE_PROMPT
from .five_level import (select_paths, validate_transitions, validate_trajectories,
                         path_arithmetic, TRAJECTORY_INSTRUCTION, validate_families,
                         transition_metrics)

PHI = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:姓名|患者姓名|身份证号|病案号)\s*[:：]|(?:patient|subject|stay|hadm)[_ -]?id\s*[:=]\s*["\x27]?\d{3,}', re.I)
SCOPE = ('Retrospective frozen final-state proposals and available scientific support. '
         'Source documents are agent-authored claims unless independently verified. '
         'Dataset bindings and native actor transcripts are excluded; attached support must be inspected for private content. '
         'Novelty is relative to supplied evidence. Human calibration remains pending.')

def read(path):
    return json.loads(Path(path).read_text())

def safe_text(text):
    text = clean(text or '')
    if SENSITIVE.search(text.encode()) or PHI.search(text):
        raise ValueError('Potential private identifier in scientific packet; inspect locally before preparing a new version')
    return text

def prepare(snapshot, output, opportunity_map=None):
    snapshot, output = Path(snapshot).resolve(), Path(output).resolve()
    if output == snapshot or output.is_relative_to(snapshot):
        raise ValueError('Review output must be outside the immutable snapshot')
    if output.exists():
        raise ValueError('Review output exists; resume review/report or use a new directory')
    data, manifest = load_snapshot(snapshot)
    domain = data['campaign']['domain']
    ordered = sorted(data['hypotheses'], key=lambda n: digest([manifest['snapshot_id'], n['id']]))
    nmap = {n['id']: f'N{i+1:04}' for i, n in enumerate(ordered)}
    amap = {a['id']: f'A{i+1:04}' for i, a in enumerate(data['artifacts'])}
    support = {}
    for a in data['artifacts']:
        support[amap[a['id']]] = {'status': a['status'], 'source_sha256': a.get('source_sha256')}
        if a['status'] == 'frozen_private':
            support[amap[a['id']]]['text'] = safe_text((snapshot/a['relative_path']).read_text())
        else:
            support[amap[a['id']]]['reason'] = a.get('reason', 'Evidence unavailable; preserve uncertainty')
    nodes = [{'id': nmap[n['id']], 'dataset': safe_text(n['dataset']),
              'proposal': safe_text(n['proposal']), 'parents': [nmap[p] for p in n['parents']],
              'change_note': safe_text(n['change_note']), 'imported_seed': n['imported_seed'],
              'artifact_refs': [amap[a] for a in n['artifact_refs']]} for n in ordered]
    if not nodes:
        raise ValueError('No registered hypotheses to evaluate')
    decisions = [{'id': f'D{i+1:04}', 'operation': safe_text(d['operation']),
                  'parents': [nmap[n] for n in d['parents']],
                  'context_ids': [nmap[n] for n in d.get('context_ids', [])],
                  'goal': safe_text(d.get('goal')), 'reason': safe_text(d.get('reason'))}
                 for i, d in enumerate(data['decisions'])]
    paths, path_policy = select_paths(nodes)
    opportunities = json.loads(safe_text(Path(opportunity_map).read_text())) if opportunity_map else {
        'status': 'not_supplied', 'instruction': 'Only infer starting opportunities supported by root proposals and decisions; otherwise mark affected dimensions unknown.'}
    if not isinstance(opportunities, dict):
        raise ValueError('Opportunity map must be a JSON object')
    packet = {'domain': domain, 'nodes': nodes, 'support': support, 'decisions': decisions,
              'edges': [{'id': f'E{i+1:04}', 'parent': nmap[e['parent_id']], 'child': nmap[e['child_id']]}
                        for i, e in enumerate(data['edges'])],
              'paths': paths, 'path_policy': path_policy, 'opportunities': opportunities,
              'rubrics': {name: (snapshot/'rubrics'/domain/name).read_text()
                          for name in ('tree-rubric.md', 'trajectory-rubric.md')},
              'scope': SCOPE}
    resources = files('dfm_bench').joinpath('protocols')
    protocol = json.loads(resources.joinpath('PROTOCOL-V1.json').read_text())
    rules = resources.joinpath('interpretation-v1.txt').read_text()
    plan = {'runner_version': 'portable-v1.0', 'snapshot_id': manifest['snapshot_id'],
            'packet_hash': digest(packet), 'protocol': protocol, 'interpretation_rules': rules,
            'effective_population': 'All registered candidates; imported seeds separate; all actual edges; one deterministic longest path per terminal node; one family partition per dataset.',
            'trajectory_scope': 'All seven dimensions fixed applicable; absent evidence is unknown. No automatic applicability exclusion or prefix-progress claim.',
            'discovery_scope': 'Fresh within-run family grouping; not the historical frozen family map and not a cross-run deduplicated yield.',
            'time_mode': 'retrospective_final_snapshot', 'human_calibration': 'pending',
            'implementation_hash': digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))})}
    plan['plan_hash'] = digest(plan)
    private_dir(output)
    write_json(output/'packet.json', packet)
    write_json(output/'plan.json', plan)
    write_json(output/'private-id-map.json', nmap)
    write_json(output/'delivery.json', make_report(data, manifest))
    write_json(output/'privacy-audit.json', {
        'packet_hash': plan['packet_hash'], 'plan_hash': plan['plan_hash'],
        'nodes': len(nodes), 'edges': len(packet['edges']), 'paths': len(paths),
        'support_status': dict(Counter(a['status'] for a in support.values())),
        'warning': 'Heuristic scanning and ID replacement are not de-identification certification. Inspect packet.json before external review; free text may still identify a run or person.',
        'external_calls': 0})
    return plan

def load_prepared(output):
    output = Path(output)
    packet, plan = read(output/'packet.json'), read(output/'plan.json')
    if digest(packet) != plan['packet_hash'] or digest({k: v for k, v in plan.items() if k != 'plan_hash'}) != plan['plan_hash']:
        raise ValueError('Prepared packet or plan changed; prepare a new version')
    return packet, plan

def validate_config(config):
    required = {'model', 'endpoint', 'input_usd_per_m', 'output_usd_per_m', 'cache_read_usd_per_m', 'budget_usd', 'request_cap', 'max_output_tokens'}
    if not required <= config.keys():
        raise ValueError('Judge configuration missing required fields')
    for field in ('input_usd_per_m', 'output_usd_per_m', 'cache_read_usd_per_m', 'budget_usd'):
        value = config[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Set finite nonnegative numeric judge pricing and budget: '+field)
    if config['budget_usd'] <= 0 or config['cache_read_usd_per_m'] > config['input_usd_per_m']:
        raise ValueError('Invalid judge budget or cache pricing')
    for field in ('request_cap', 'max_output_tokens'):
        if type(config[field]) is not int or config[field] < 1:
            raise ValueError('Positive integer required: '+field)
    u = urlsplit(config['endpoint'])
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Use an HTTPS Chat Completions endpoint without embedded credentials or query parameters')
    if not isinstance(config['model'], str) or not config['model'].strip():
        raise ValueError('Explicit external judge model required')

CAMPAIGN_PROMPT = '''Evaluate the entire supplied campaign DAG under the original T1–T7 rubric, weights 25/15/15/20/10/10/5. Never average hypothesis or trajectory scores. Include failed/no-selection directions in the supplied decisions. Do not infer quality from node count, closure, or length. Unavailable opportunity/budget evidence is unknown. All seven dimensions remain applicable; never exclude an unknown dimension. Return JSON {"review_status":"complete|partial|unscorable","dimensions":[{"id":"T1","status":"scored|unknown","score":0,"rationale":"...","evidence_refs":["allowed ID"]}, ... T1 through T7],"overall_assessment":"...","major_strengths":[],"major_weaknesses":[],"limitations":[]}. Scores 0–4; unknown=null. No scientific truth or confirmed-discovery claim.'''
DISCOVERY_PROMPT = '''Construct the broad v1 Discovery family ledger. Partition EVERY non-seed candidate exactly once by scientific question; merge revisions, extra safeguards and method swaps that do not change the question. Imported seeds are context only. Do not use a binary discovery gate as the main result. Return JSON {"families":[{"candidate_ids":["exact ID"],"question":"...","contribution":"...","importance":"consequential|limited|uncertain","increment_beyond_start":"yes|no|uncertain","evidence_maturity":"proposed|source_grounded|diagnostically_examined|study_completed|independently_checked","disposition":"supported|contradicted|inconclusive|unresolved","evidence_refs":["allowed refs"],"limits":"..."}]}. A claimed result, script, citation manifest or planned diagnostic is not verified execution. No confirmed discoveries or verified global novelty without independent evidence.'''

def full_scope_campaign(value, refs):
    validate_campaign(value, refs)
    if any(d['status'] == 'not_applicable' for d in value['dimensions']):
        raise ValueError('Frozen full scope cannot exclude dimensions')

def full_scope_path(value, pid, refs):
    validate_trajectories(value, [pid], {pid: refs})
    if any(d['status'] == 'not_applicable' for d in value['trajectories'][0]['dimensions']):
        raise ValueError('Frozen full scope cannot exclude dimensions')

def review(output, config_path, key_file, approved_packet_hash, reviewer_factory=Reviewer):
    output = Path(output)
    packet, plan = load_prepared(output)
    if approved_packet_hash != plan['packet_hash']:
        raise ValueError('Pass the exact inspected packet hash using --approve-packet-sha256')
    current_hash = digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    if plan['implementation_hash'] != current_hash:
        raise ValueError('Evaluator code changed since preparation; prepare a new version')
    config = read(config_path)
    validate_config(config)
    key_file = Path(key_file).resolve(strict=True)
    if key_file.is_relative_to(output.resolve()):
        raise ValueError('Keep the API key outside the review output')
    if key_file.stat().st_mode & 0o077:
        raise ValueError('API key file must be owner-only (chmod 600)')
    with (output/'review.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen_config = output/'judge-config.json'
        if frozen_config.exists() and read(frozen_config) != config:
            raise ValueError('Judge configuration is frozen; use a new review directory for changed model, rates or budget')
        write_json(frozen_config, config)
        judge_out = private_dir(output/'judge')
        write_json(judge_out/'pricing-policy.json', config)
        reviewer = reviewer_factory(judge_out, key_file, budget=config['budget_usd'], request_cap=config['request_cap'],
            model=config['model'], endpoint=config['endpoint'], input_price=config['input_usd_per_m'], output_price=config['output_usd_per_m'])
        # Reservations left by an interrupted process stay charged and cannot block the next run forever.
        for entry in reviewer.entries:
            if entry['state'] == 'reserved':
                entry['state'] = 'interrupted_usage_unknown'
        reviewer.save()
        result_path = output/'results.json'
        result = read(result_path) if result_path.exists() else {
            'plan_hash': plan['plan_hash'], 'hypotheses': {}, 'transitions': {}, 'trajectories': {}, 'campaign': None, 'discovery': {}, 'errors': []}
        if result['plan_hash'] != plan['plan_hash']:
            raise ValueError('Results belong to a different plan')
        result['errors'] = []
        rules = '\n'+plan['interpretation_rules']
        nodes = {n['id']: n for n in packet['nodes']}
        def context(ids):
            ids = set(ids)
            aids = {a for n in ids for a in nodes[n]['artifact_refs']}
            return {'domain': packet['domain'], 'nodes': [nodes[n] for n in sorted(ids)],
                    'support': {a: packet['support'][a] for a in sorted(aids)},
                    'allowed_refs': sorted(ids | aids), 'scope': packet['scope']}
        def call(task, payload, prompt, validator):
            return reviewer.call(task, payload, prompt+rules, validator, config['max_output_tokens'])
        stage, obj = 'initialization', None
        try:
            for nid, node in nodes.items():
                stage, obj = 'hypothesis', nid
                if nid in result['hypotheses']: continue
                card = call('card/'+nid, {'proposal': node['proposal']}, CARD_PROMPT, lambda v: validate_card(v, node['proposal']))
                refs = set(CARD_FIELDS) | set(node['artifact_refs'])
                payload = {'domain': packet['domain'], 'card': card,
                           'support_documents': {a: packet['support'][a] for a in node['artifact_refs']},
                           'allowed_refs': sorted(refs), 'scientific_contract': plan['protocol']['domain_anchors'][packet['domain']],
                           'verbal_bands': plan['protocol']['verbal_bands'], 'dimensions': list(H_WEIGHTS), 'scope': packet['scope']}
                rating = call('quality/'+nid, payload, SCORE_PROMPT, lambda v: validate_rating(v, refs))
                result['hypotheses'][nid] = {'dataset': node['dataset'], 'imported_seed': node['imported_seed'], 'card': card, 'rating': rating, 'Q': composite(rating)}
                write_json(result_path, result)
            for edge in packet['edges']:
                stage, obj = 'transition', edge['id']
                if obj in result['transitions']: continue
                payload = context({edge['parent'], edge['child'], *nodes[edge['child']]['parents']})
                payload['edge'] = edge
                prompt = 'Judge this actual derivation edge as substantive_progress, necessary_repair, marginal_repetition or insufficient_evidence. Preserve all actual parents as context; do not credit inherited work twice. Useful refutation can lower Q. Return JSON {"transitions":[{"id":"'+obj+'","verdict":"...","reason":"1–100 words","refs":["allowed ID"]}]}. Missing evidence is uncertainty.'
                value = call('transition/'+obj, payload, prompt, lambda v: validate_transitions(v, [obj], {obj: set(payload['allowed_refs'])}))
                result['transitions'][obj] = value['transitions'][0]
                write_json(result_path, result)
            for path in packet['paths']:
                stage, obj = 'trajectory', path['id']
                if obj in result['trajectories']: continue
                if len(path['path_ids']) < 2:
                    result['trajectories'][obj] = {'status': 'unscorable_singleton', 'score': None}
                else:
                    ids = set(path['path_ids']) | {p for n in path['path_ids'] for p in nodes[n]['parents']}
                    payload = context(ids)
                    payload.update(paths=[path], rubric=packet['rubrics']['trajectory-rubric.md'], opportunity_map=packet['opportunities'])
                    value = call('trajectory/'+obj, payload, TRAJECTORY_INSTRUCTION+' All seven dimensions remain applicable. Unavailable evidence is unknown; never use not_applicable.', lambda v: full_scope_path(v, obj, set(payload['allowed_refs'])))
                    value = value['trajectories'][0]
                    result['trajectories'][obj] = {'review': value, 'arithmetic': path_arithmetic(value)}
                write_json(result_path, result)
            stage, obj = 'campaign', 'whole-run'
            if result['campaign'] is None:
                payload = context(nodes)
                payload.update(decisions=packet['decisions'], rubric=packet['rubrics']['tree-rubric.md'], opportunity_map=packet['opportunities'], resource_budget=packet['opportunities'].get('resource_budget', 'not independently audited; keep affected dimensions unknown'))
                payload['allowed_refs'] += [d['id'] for d in packet['decisions']]
                value = call('campaign', payload, CAMPAIGN_PROMPT, lambda v: full_scope_campaign(v, set(payload['allowed_refs'])))
                result['campaign'] = {'review': value, 'arithmetic': campaign_arithmetic(value)}
                write_json(result_path, result)
            for dataset in sorted({n['dataset'] for n in nodes.values()}):
                stage, obj = 'discovery', dataset
                if dataset in result['discovery']: continue
                ids = {n['id'] for n in nodes.values() if n['dataset'] == dataset}
                generated = {n for n in ids if not nodes[n]['imported_seed']}
                if not generated:
                    result['discovery'][dataset] = {'families': []}
                else:
                    payload = context(ids)
                    payload['starting_opportunities'] = packet['opportunities']
                    result['discovery'][dataset] = call('discovery/'+dataset, payload, DISCOVERY_PROMPT, lambda v: validate_families(v, generated, set(payload['allowed_refs'])))
                write_json(result_path, result)
        except Exception as exc:
            result['errors'].append({'stage': stage, 'object': obj, 'error_type': type(exc).__name__})
            write_json(result_path, result)
            summarize(output)
            raise RuntimeError('Review stopped at '+stage+'; partial results retained. Inspect local judge ledger, then resume the identical command.') from exc
        write_json(result_path, result)
        return summarize(output)

def summarize(output):
    output = Path(output)
    packet, plan = load_prepared(output)
    result = read(output/'results.json') if (output/'results.json').exists() else {
        'plan_hash': plan['plan_hash'], 'hypotheses': {}, 'transitions': {}, 'trajectories': {}, 'campaign': None, 'discovery': {}, 'errors': []}
    if result['plan_hash'] != plan['plan_hash']:
        raise ValueError('Results belong to a different plan')
    hypotheses = result['hypotheses']
    hstats = {}
    for population, seed in [('generated', False), ('imported_seeds', True)]:
        ids = [n['id'] for n in packet['nodes'] if n['imported_seed'] == seed]
        values = [hypotheses[n]['Q'] for n in ids if n in hypotheses and hypotheses[n]['Q'] is not None]
        hstats[population] = {'total': len(ids), 'reviewed': sum(n in hypotheses for n in ids), 'known_Q': len(values),
                              'mean_Q': sum(values)/len(values) if values else None, 'max_observed_Q': max(values) if values else None}
    deltas = []
    for e in packet['edges']:
        parent = hypotheses.get(e['parent'], {}).get('Q'); child = hypotheses.get(e['child'], {}).get('Q')
        deltas.append({**e, 'delta_H': child-parent if parent is not None and child is not None else None})
    families = [f for v in result['discovery'].values() for f in v['families']]
    ledger = read(output/'judge/ledger.json') if (output/'judge/ledger.json').exists() else []
    expected = {'hypothesis': len(packet['nodes']), 'transition': len(packet['edges']),
                'trajectory': len(packet['paths']), 'campaign': 1, 'discovery': len({n['dataset'] for n in packet['nodes']})}
    completed = {'hypothesis': len(hypotheses), 'transition': len(result['transitions']), 'trajectory': len(result['trajectories']),
                 'campaign': int(result['campaign'] is not None), 'discovery': len(result['discovery'])}
    summary = {'plan_hash': plan['plan_hash'], 'status': 'complete' if completed == expected else 'partial',
               'meaning': SCOPE, 'coverage': {k: {'completed': completed[k], 'expected': expected[k]} for k in expected},
               'hypothesis': hstats, 'transition': transition_metrics(list(result['transitions'].values())), 'delta_H': deltas,
               'trajectory': result['trajectories'], 'campaign': result['campaign'],
               'discovery': {'proposed_families': len(families), 'maturity': dict(Counter(f['evidence_maturity'] for f in families)),
                             'disposition': dict(Counter(f['disposition'] for f in families)), 'confirmed_discoveries': None},
               'cost_usd_including_unknown_usage_reservations': sum(e['charged_usd'] for e in ledger),
               'requests': len(ledger), 'errors': result['errors'], 'human_calibration': 'pending'}
    write_json(output/'summary.json', summary)
    campaign_q = result['campaign']['arithmetic']['composite'] if result['campaign'] else None
    text = ['# DFM-Bench scientific evaluation', '', '**Status: '+summary['status']+'; AI-reviewed internal preview; human calibration pending.**', '',
            '| Level | Completed / expected |', '|---|---:|']
    text += [f'| {k.title()} | {completed[k]} / {expected[k]} |' for k in expected]
    text += ['', f"Generated hypothesis Q (1–10): {hstats['generated']['mean_Q']}; known scores {hstats['generated']['known_Q']} / {hstats['generated']['total']}.",
             f'Campaign score (0–100): {campaign_q}. Null means withheld, never zero.',
             f"Proposed contribution families: {len(families)}. Confirmed discoveries: unassessed.",
             f"Cost including unknown-usage reservations: ${summary['cost_usd_including_unknown_usage_reservations']:.6f}.", '',
             '## Detailed results', '', 'Per-node ratings, transition verdicts, path dimensions, campaign dimensions and family ledger: `results.json`.',
             'Numerical edge-by-edge ΔH, coverage and aggregate metrics: `summary.json`. Operational completion/readiness: `delivery.json`.',
             'Imported seeds are excluded from the generated mean. Every crossover parent has a separate ΔH edge. Unknown Q remains null.',
             'Trajectory paths are selected before scoring; one longest path per endpoint, not every possible crossover path. Singletons are explicitly unscorable.',
             'All seven path/campaign dimensions are fixed applicable. Missing budget/opportunity evidence can withhold the composite.',
             'Discovery families are deduplicated within this run and dataset only. No combined five-level total is defined.', '',
             '## Interpretation and privacy', '', SCOPE,
             'Scores do not establish learning, verified novelty or clinical utility. This report and accompanying JSON remain private; review before sharing.',
             'The archived v1 protocol contains historical population descriptions; plan.json explicitly defines this run’s population and scope.', '']
    report = output/'REPORT.md'; report.write_text('\n'.join(text)); report.chmod(0o600)
    return summary

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare', help='Offline, no API calls')
    prep.add_argument('--snapshot', required=True); prep.add_argument('--output', required=True); prep.add_argument('--opportunity-map')
    run = sub.add_parser('review', help='Explicit paid external judge calls; resumable')
    run.add_argument('--output', required=True); run.add_argument('--config', required=True); run.add_argument('--key-file', required=True)
    run.add_argument('--approve-packet-sha256', required=True)
    report = sub.add_parser('report', help='Offline report, including partial coverage')
    report.add_argument('--output', required=True)
    args = p.parse_args()
    try:
        if args.command == 'prepare':
            plan = prepare(args.snapshot, args.output, args.opportunity_map)
            print(json.dumps({'prepared': True, 'packet_hash': plan['packet_hash'], 'output': args.output, 'external_calls': 0}))
        elif args.command == 'review':
            summary = review(args.output, args.config, args.key_file, args.approve_packet_sha256)
            print(json.dumps({'status': summary['status'], 'report': str(Path(args.output)/'REPORT.md')}))
        else:
            summary = summarize(args.output)
            print(json.dumps({'status': summary['status'], 'report': str(Path(args.output)/'REPORT.md')}))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        # Error type only for unexpected provider/private content; no response body or credential echoed.
        p.exit(2, 'DFM review stopped: '+(str(exc) if type(exc) in (ValueError, RuntimeError) else type(exc).__name__)+'\n')

if __name__ == '__main__':
    main()
