import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_foundations import fixture
from test_pilot import Response
from dfm_bench.snapshot import import_run
from dfm_bench.common import write_json, file_hash
from dfm_bench.calibration import CARD_FIELDS, H_WEIGHTS
from dfm_bench.evaluate import prepare, review, summarize, load_prepared, validate_config
from dfm_bench.pilot import Reviewer

CONFIG = {'model': 'synthetic-judge', 'endpoint': 'https://example.invalid/v1/chat/completions',
          'input_usd_per_m': 1.0, 'output_usd_per_m': 2.0, 'cache_read_usd_per_m': 0.5,
          'budget_usd': 2.0, 'request_cap': 100, 'max_output_tokens': 256}

class FakeReviewer:
    calls = 0
    def __init__(self, out, key_file, **kwargs):
        self.entries = []; self.out = out
    def save(self):
        write_json(self.out/'ledger.json', self.entries)
    def call(self, task, payload, prompt, validator, tokens):
        type(self).calls += 1
        if task.startswith('card/'):
            value = {field: None for field in CARD_FIELDS}; value['claim'] = [payload['proposal']]
        elif task.startswith('quality/'):
            value = {'validity': 'eligible', 'novelty_scope': 'supplied_evidence_only',
                     'dimensions': {k: {'status': 'scored', 'score': 5, 'rationale': 'Synthetic rating', 'refs': ['claim']} for k in H_WEIGHTS}}
        elif task.startswith('transition/'):
            value = {'transitions': [{'id': payload['edge']['id'], 'verdict': 'necessary_repair', 'reason': 'Synthetic repair', 'refs': payload['allowed_refs'][:1]}]}
        elif task.startswith('trajectory/'):
            value = {'trajectories': [{'id': payload['paths'][0]['id'], 'review_status': 'complete',
                    'dimensions': [{'id': f'L{i}', 'status': 'scored', 'score': 2, 'rationale': 'Synthetic', 'refs': payload['allowed_refs'][:1]} for i in range(1, 8)]}]}
        elif task == 'campaign':
            value = {'review_status': 'complete', 'dimensions': [{'id': f'T{i}', 'status': 'scored', 'score': 2, 'rationale': 'Synthetic', 'evidence_refs': payload['allowed_refs'][:1]} for i in range(1, 8)]}
        elif task.startswith('discovery/'):
            value = {'families': [{'candidate_ids': [n['id'] for n in payload['nodes'] if not n['imported_seed']],
                'question': 'Synthetic question', 'contribution': 'Synthetic family', 'importance': 'uncertain', 'increment_beyond_start': 'uncertain',
                'evidence_maturity': 'proposed', 'disposition': 'unresolved', 'evidence_refs': [], 'limits': 'Synthetic fixture only'}]}
        else:
            raise AssertionError(task)
        validator(value)
        return value

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.source = self.root/'run'; db = fixture(self.source); db.close()
        self.before = file_hash(self.source/'state.sqlite')
        self.snapshot = self.root/'snapshot'; import_run(self.source, 'clinical', self.snapshot)
        self.output = self.root/'review'
        self.plan = prepare(self.snapshot, self.output)
        self.config = self.root/'judge.json'; write_json(self.config, CONFIG)
        self.key = self.root/'key'; self.key.write_text('synthetic-not-a-credential'); self.key.chmod(0o600)
    def tearDown(self):
        self.temp.cleanup()
    def run_review(self, factory=FakeReviewer):
        return review(self.output, self.config, self.key, self.plan['packet_hash'], factory)
    def test_end_to_end_all_five_levels_and_resume(self):
        FakeReviewer.calls = 0
        result = self.run_review()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['hypothesis']['generated']['mean_Q'], 5)
        self.assertEqual(result['campaign']['arithmetic']['composite'], 50)
        self.assertEqual(len(result['delta_H']), 4)
        self.assertEqual([e['delta_H'] for e in result['delta_H']], [0]*4)
        self.assertEqual(result['discovery']['proposed_families'], 1)
        calls = FakeReviewer.calls
        self.run_review(); self.assertEqual(FakeReviewer.calls, calls)
        self.assertEqual(file_hash(self.source/'state.sqlite'), self.before)
    def test_prepare_and_report_make_no_network_calls(self):
        with patch('urllib.request.build_opener', side_effect=AssertionError('Network forbidden')):
            new = self.root/'offline'; prepare(self.snapshot, new)
            result = summarize(new)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['hypothesis']['generated']['mean_Q'])
        self.assertIsNone(result['campaign'])
    def test_packet_and_plan_tamper(self):
        p = self.output/'packet.json'; data = json.loads(p.read_text()); data['nodes'][0]['proposal'] = 'changed'; write_json(p, data)
        with self.assertRaises(ValueError):load_prepared(self.output)
    def test_approval_required_before_network(self):
        with self.assertRaises(ValueError):review(self.output, self.config, self.key, 'wrong', FakeReviewer)
    def test_existing_output_and_nested_output_rejected(self):
        with self.assertRaises(ValueError):prepare(self.snapshot, self.output)
        with self.assertRaises(ValueError):prepare(self.snapshot, self.snapshot/'review')
    def test_changed_config_cannot_resume(self):
        self.run_review(); changed = dict(CONFIG, model='different'); write_json(self.config, changed)
        with self.assertRaises(ValueError):self.run_review()
    def test_invalid_pricing_and_endpoint(self):
        for config in [dict(CONFIG, budget_usd=float('nan')), dict(CONFIG, input_usd_per_m=None), dict(CONFIG, endpoint='http://example.com'), dict(CONFIG, endpoint='https://secret@example.com')]:
            with self.assertRaises(ValueError):validate_config(config)
    def test_configured_reviewer_uses_exact_model_and_rates(self):
        judge = Reviewer(self.root/'custom', self.key, model=CONFIG['model'], endpoint=CONFIG['endpoint'], input_price=1, output_price=2)
        response = {'model': CONFIG['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        with patch('urllib.request.build_opener') as mock:
            mock.return_value.open.return_value = Response(response)
            judge.call('test', {}, 'JSON', lambda v: None, 128)
            request = mock.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, CONFIG['endpoint'])
            self.assertEqual(json.loads(request.data)['model'], CONFIG['model'])
        self.assertAlmostEqual(judge.spent(), .00014)
    def test_failure_retains_partial_report_and_can_resume(self):
        class FailOnce(FakeReviewer):
            def call(self, task, *args):
                if task.startswith('transition/'):raise RuntimeError('synthetic interruption')
                return super().call(task, *args)
        with self.assertRaises(RuntimeError):self.run_review(FailOnce)
        self.assertEqual(summarize(self.output)['status'], 'partial')
        self.assertTrue((self.output/'REPORT.md').exists())
        self.assertEqual(self.run_review()['status'], 'complete')

if __name__ == '__main__':unittest.main()
