"""Offline rejection controls; synthetic findings are not a vulnerability scan."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dependency_gate', Path(__file__).parents[1] / 'dependency_gate.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
ROOT = 'github.com/NoctilumeDev/GuiHongMail'


def fixture():
    inventory = {ROOT: '', 'example.org/lib': 'v1.0.0', 'stdlib': 'v1.27.2'}
    roots = {ROOT + '/cmd/example'}
    records = [
        {'config': {'protocol_version': 'v1.0.0', 'scanner_name': 'govulncheck',
                    'scanner_version': d.GOVULNCHECK, 'go_version': d.GO_VERSION,
                    'scan_level': 'symbol', 'scan_mode': 'source', 'db': 'https://vuln.go.dev'}},
        {'SBOM': {'go_version': d.GO_VERSION, 'roots': sorted(roots),
                  'modules': [{'path': k, 'version': v} for k, v in inventory.items()]}},
        {'osv': {'id': 'GO-2099-0001', 'summary': 'synthetic control'}},
        {'finding': {'osv': 'GO-2099-0001', 'trace': [{'module': 'example.org/lib', 'version': 'v1.0.0'}]}},
    ]
    return records, inventory, roots


def npm_fixture():
    lock = {'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/example': {'version': '1.0.0'}}}
    finding = {'name': 'example', 'severity': 'high', 'nodes': ['node_modules/example'],
               'via': [{'source': 123, 'title': 'synthetic control', 'url': 'https://example.invalid/advisory'}],
               'effects': [], 'fixAvailable': False}
    report = {'auditReportVersion': 2, 'vulnerabilities': {'example': finding},
              'metadata': {'dependencies': {'total': 1},
                           'vulnerabilities': {'info': 0, 'low': 0, 'moderate': 0, 'high': 1, 'critical': 0, 'total': 1}}}
    return report, lock


class DependencyTests(unittest.TestCase):
    def test_stream_rejects_empty_duplicate_truncated_and_non_object(self):
        self.assertEqual(d.stream('{"a":1}\n {"b":2}'), [{'a': 1}, {'b': 2}])
        for value in ('', '   ', '{"a":1,"a":2}', '{} trailing', '[]', '{'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.stream(value)

    def test_go_complete_scope_and_identical_cross_module_advisory(self):
        records, inventory, roots = fixture()
        expected = d.go_findings(records, inventory, roots, 0)
        self.assertEqual(len(expected), 1)
        records.append(deepcopy(records[2]))
        self.assertEqual(d.go_findings(records, inventory, roots, 0), expected)
        records[-1]['osv']['summary'] = 'conflict'
        with self.assertRaises(ValueError):
            d.go_findings(records, inventory, roots, 0)

    def test_go_config_scope_and_tool_failures(self):
        for field, bad in [('protocol_version', 'v0'), ('scanner_version', 'latest'),
                           ('go_version', 'go1.0'), ('scan_level', 'module'),
                           ('scan_mode', 'binary'), ('db', 'https://example.invalid')]:
            records, inventory, roots = fixture()
            records[0]['config'][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                d.go_findings(records, inventory, roots, 0)
        records, inventory, roots = fixture()
        for code in (1, 2, 3):
            with self.assertRaises(ValueError):
                d.go_findings(records, inventory, roots, code)

    def test_go_missing_extra_and_mismatched_evidence(self):
        def mutations(records):
            yield records[:1]
            yield records[1:]
            yield records + [deepcopy(records[0])]
            yield records + [deepcopy(records[1])]
            yield records[:2] + records[3:]
            yield records + [{'unknown': {}}]
            changed = deepcopy(records)
            changed[1]['SBOM']['modules'].pop()
            yield changed
            changed = deepcopy(records)
            changed[1]['SBOM']['roots'] = []
            yield changed
            changed = deepcopy(records)
            changed[1]['SBOM']['modules'].append({'path': 'foreign', 'version': 'v1'})
            yield changed
            changed = deepcopy(records)
            changed[3]['finding']['trace'][0]['version'] = 'v2.0.0'
            yield changed
            changed = deepcopy(records)
            changed[3]['finding']['trace'] = []
            yield changed
        records, inventory, roots = fixture()
        for index, changed in enumerate(mutations(records)):
            with self.subTest(index=index), self.assertRaises(ValueError):
                d.go_findings(changed, inventory, roots, 0)

    def test_go_graph_error_replacement_and_test_root_normalization(self):
        modules = [{'Main': True, 'Path': ROOT}, {'Path': 'example.org/lib', 'Version': 'v1.0.0'}]
        inventory = d.go_inventory(modules)
        for field in ('Error', 'Replace'):
            changed = deepcopy(modules)
            changed[1][field] = {'Path': 'other'}
            with self.assertRaises(ValueError):
                d.go_inventory(changed)
        package = {'ImportPath': ROOT + '/internal/p [' + ROOT + '/internal/p.test]', 'Module': modules[0]}
        imported, roots = d.imported_inventory([package], inventory)
        self.assertEqual(roots, {ROOT + '/internal/p'})
        self.assertEqual(imported, {'stdlib': 'v1.27.2', ROOT: ''})
        for field in ('Error', 'DepsErrors', 'Incomplete'):
            changed = dict(package, **{field: True})
            with self.assertRaises(ValueError):
                d.imported_inventory([changed], inventory)

    def test_npm_report_and_exit_denominator_controls(self):
        report, lock = npm_fixture()
        self.assertEqual(len(d.npm_findings(report, lock, 1)), 1)
        for code in (0, 2):
            with self.assertRaises(ValueError):
                d.npm_findings(report, lock, code)
        mutations = []
        changed = deepcopy(report); changed['error'] = {'message': 'offline'}; mutations.append(changed)
        changed = deepcopy(report); changed['metadata']['dependencies']['total'] = 0; mutations.append(changed)
        changed = deepcopy(report); changed['metadata']['vulnerabilities']['high'] = 0; mutations.append(changed)
        changed = deepcopy(report); changed['vulnerabilities']['example']['nodes'] = ['node_modules/foreign']; mutations.append(changed)
        changed = deepcopy(report); changed['vulnerabilities']['example']['via'] = ['missing']; mutations.append(changed)
        changed = deepcopy(report); changed['vulnerabilities']['example']['via'] = [{}]; mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(ValueError):
                d.npm_findings(changed, lock, 1)

    def test_npm_recommendation_not_risk_identity_but_advisory_is(self):
        report, lock = npm_fixture()
        original = d.npm_findings(report, lock, 1)
        report['vulnerabilities']['example']['fixAvailable'] = {'version': '9.0.0'}
        self.assertEqual(d.npm_findings(report, lock, 1), original)
        report['vulnerabilities']['example']['via'][0]['title'] = 'changed'
        self.assertNotEqual(d.npm_findings(report, lock, 1), original)

    def test_review_rejects_change_missing_risk_and_acceptance(self):
        observation = {'inputs': {'go.mod': 'synthetic'}, 'sources': {
            'test': {'inventory_sha256': 'fixture', 'package_count': 2, 'findings': {'id': {'fact': 1}}}}}
        policy = {'schema': 'guihong-dependency-review/1', 'source_revision': 'a' * 40,
                  'owner': 'NoctilumeDev/GuiHongMail maintainers', 'risk_accepted': False,
                  'inputs': observation['inputs'], 'sources': {'test': {
                      'inventory_sha256': 'fixture', 'package_count': 2,
                      'findings': {'id': {'sha256': d.digest({'fact': 1}), 'status': 'UNRESOLVED', 'next_action': 'Review separately'}}}}}
        self.assertEqual(d.review(observation, policy), 1)
        for key, value in [('status', 'PASS'), ('status', 'NOT_APPLICABLE'), ('next_action', ''),
                           ('next_action', '\ufffd'), ('sha256', 'wrong')]:
            changed = deepcopy(policy); changed['sources']['test']['findings']['id'][key] = value
            with self.assertRaises(ValueError):
                d.review(observation, changed)
        for mutate in [lambda p: p.update(risk_accepted=True), lambda p: p.update(owner=''),
                       lambda p: p.update(inputs={}), lambda p: p.update(sources={}),
                       lambda p: p['sources']['test'].update(package_count=1),
                       lambda p: p['sources']['test'].update(findings={})]:
            changed = deepcopy(policy); mutate(changed)
            with self.assertRaises(ValueError):
                d.review(observation, changed)
        for fact in ({'fact': 2}, {}):
            changed = deepcopy(observation); changed['sources']['test']['findings']['id'] = fact
            with self.assertRaises(ValueError):
                d.review(changed, policy)

    def test_command_failure_retained_and_no_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(d.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2)):
                with self.assertRaises(ValueError):
                    d.command(['synthetic'], output, output, 'failure')
            self.assertEqual(d.read(output / 'failure.exit.json'), {'exit_code': 2})
            self.assertTrue((output / 'failure.stderr').exists())
            with patch.object(d.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic', 600)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    d.command(['synthetic'], output, output, 'timeout')
            self.assertTrue((output / 'timeout.stdout').exists())
            self.assertFalse((output / 'timeout.exit.json').exists())


if __name__ == '__main__':
    unittest.main()
