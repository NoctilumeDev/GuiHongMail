"""Seal and reconcile the finite M1 local gates without claiming protected-merge authority."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distribution, version
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json

import go_apps as apps
import lab
import resource_guard

ROOT = lab.ROOT
RUN_PATTERN = re.compile(r'guihong-[a-z0-9-]{1,100}')
RESOURCE_PATTERN = re.compile(r'resource-[0-9a-f]{32}\.jsonl')
CHILDREN = ('foundation', 'storage', 'objects')


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(path.read_bytes())


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def safe_run_path(identity):
    if RUN_PATTERN.fullmatch(identity) is None:
        raise RuntimeError('Invalid child run identity')
    return lab.local_run(identity)


def safe_resource_path(name):
    if RESOURCE_PATTERN.fullmatch(name) is None:
        raise RuntimeError('Invalid resource evidence identity')
    path = (lab.LAB / name).resolve()
    if path.parent != lab.LAB.resolve():
        raise RuntimeError('Resource evidence escaped the owned lab')
    return path


def inspect_bundle(identity, expected_source):
    run = safe_run_path(identity)
    bundle = run / 'bundle'
    manifest_path = bundle / 'acceptance-bundle-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    verified = []
    for entry in manifest['files']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe child bundle manifest path')
        target = (bundle / relative).resolve()
        if bundle.resolve() not in target.parents:
            raise RuntimeError('Child bundle entry escaped bundle root')
        verified.append(target.is_file() and target.stat().st_size == entry['size'] and sha_file(target) == entry['sha256'])
    report_path = bundle / 'acceptance-report.json'
    plan_path = bundle / 'sealed-acceptance-plan.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    sealed_plan = json.loads(plan_path.read_text(encoding='utf-8'))
    summary = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
    summary_identity = summary.get('identity', summary.get('run_id'))
    summary_execution = summary.get('execution_status', summary.get('execution'))
    evidence_clean = all(not row.get('redacted') and row.get('redacted_fields') == 0 for row in report['evidence'])
    return {
        'run_id': identity,
        'manifest_sha256': sha_file(manifest_path),
        'manifest_file_count': len(manifest['files']),
        'manifest_verified': bool(verified) and all(verified),
        'plan_sha256_verified': report['plan']['sha256'] == sealed_plan['seal']['digest'],
        'acceptance_id_verified': manifest['acceptance_id'] == identity == report['acceptance_id'] == summary_identity,
        'execution_status': report['execution_status'],
        'verdict': report['verdict'],
        'summary_matches': summary_execution == report['execution_status'] and summary['verdict'] == report['verdict'],
        'subject_source': report['subject']['version'],
        'source_matches': report['subject']['version'] == expected_source == summary['source_sha'],
        'evidence_unredacted': evidence_clean,
        'captured_epochs': [datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00')).timestamp() for row in report['evidence']],
    }


def inspect_resource(name, child_epochs):
    path = safe_resource_path(name)
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        raise RuntimeError('Empty resource evidence')
    epochs = [row['utc_epoch'] for row in rows]
    rss_values = [process['rss_bytes'] for row in rows for process in row['processes']]
    containers = [container for row in rows for container in row.get('containers', [])]
    running_containers = [container for container in containers if container['running']]
    consecutive_full = maximum_full = 0
    for row in rows:
        consecutive_full = consecutive_full + 1 if row.get('full_topology') else 0
        maximum_full = max(maximum_full, consecutive_full)
    peaks = {}
    for service in resource_guard.INFRASTRUCTURE:
        observed = [row for row in running_containers if row['service'] == service]
        peaks[service] = {
            'samples': len(observed),
            'memory_limit_bytes': observed[0]['memory_limit_bytes'] if observed else None,
            'max_memory_usage_bytes': max((row['memory_usage_bytes'] for row in observed), default=None),
            'max_memory_utilization_ratio': max((row['memory_usage_bytes'] / row['memory_limit_bytes'] for row in observed), default=None),
            'pids_limit': observed[0]['pids_limit'] if observed else None,
            'max_pids': max((row['pids'] for row in observed), default=None),
            'min_pid_headroom': min((row['pid_headroom'] for row in observed), default=None),
        }
    return {
        'file': name,
        'sha256': sha_file(path),
        'samples': len(rows),
        'stop_reasons': [row['stop_reason'] for row in rows if row['stop_reason'] is not None],
        'max_host_used_bytes': max(row['memory']['used_bytes'] for row in rows),
        'max_application_rss_bytes': max(rss_values, default=0),
        'application_roles_seen': sorted({process['role'] for row in rows for process in row['processes']}),
        'container_roles_seen': sorted({container['service'] for container in running_containers}),
        'container_peaks': peaks,
        'container_memory_headroom_ok': bool(running_containers) and all(
            row['memory_headroom_ratio'] >= resource_guard.MIN_CONTAINER_MEMORY_HEADROOM_RATIO for row in running_containers),
        'container_pid_headroom_ok': bool(running_containers) and all(
            row['pid_headroom'] >= resource_guard.MIN_CONTAINER_PID_HEADROOM for row in running_containers),
        'container_oom_free': bool(containers) and all(not row['oom_killed'] for row in containers),
        'max_consecutive_full_topology_samples': maximum_full,
        'covers_child_evidence': bool(child_epochs) and min(epochs) <= min(child_epochs) and max(child_epochs) <= max(epochs) + 10,
    }


def inspect_build(source):
    receipt_path, verified = apps.verified_build(source)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    return {
        'receipt': receipt_path.relative_to(ROOT).as_posix(),
        'receipt_sha256': sha_file(receipt_path),
        'source_sha': receipt['source_sha'],
        'go_version': receipt['go_version'],
        'exit_code': receipt['exit_code'],
        'log_verified': True,
        'artifact_count': len(receipt['artifacts']),
        'artifacts_verified': len(verified) == 3,
    }


def run_gate(command, target):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lab.write_new(target, result.stdout)
    return {'exit_code': result.returncode, 'output': target.relative_to(ROOT).as_posix(), 'output_sha256': sha_file(target)}


def applications_stopped():
    result = {}
    for role in lab.SERVICES:
        path = apps.PROCESSES / (role + '.json')
        if not path.exists():
            result[role] = True
            continue
        owner = json.loads(path.read_text(encoding='utf-8'))
        result[role] = apps.process_identity(owner['pid']) is None
    return result


def main():
    parser = argparse.ArgumentParser()
    for child in CHILDREN:
        parser.add_argument('--' + child, required=True)
        parser.add_argument('--' + child + '-resource', required=True)
    parser.add_argument('--mode', choices=['candidate', 'exact-main'], default='candidate')
    parser.add_argument('--control', choices=['none', 'wrong-hash', 'wrong-binding', 'missing-evidence'], default='none')
    args = parser.parse_args()
    if git('status', '--porcelain'):
        raise RuntimeError('Exact clean source required before Plan')
    if version('veritrail') != '0.13.0':
        raise RuntimeError('Use locked public VeriTrail Core 0.13.0')
    source = git('rev-parse', 'HEAD')
    run = 'guihong-m1-' + uuid.uuid4().hex
    out = lab.local_run(run, create=True)
    child_ids = {name: getattr(args, name) for name in CHILDREN}
    resource_ids = {name: getattr(args, name + '_resource') for name in CHILDREN}
    request = {
        'source_sha': source,
        'mode': args.mode,
        'control': args.control,
        'children': child_ids,
        'resource_evidence': resource_ids,
        'contracts': {name: sha_file(ROOT / path) for name, path in {
            'm1_plan': 'docs/m1-plan.md', 'm1_components': 'docs/m1-components.md',
            'm1_resource_contract': 'docs/m1-resource-contract-1.1.md',
            'go_runtime_contract': 'docs/m0.1-go-runtime.md', 'go_environment_lock': 'docs/go-environment-lock.json',
            'environment_lock': 'docs/environment-lock.json', 'ci': '.github/workflows/ci.yml'}.items()},
    }
    spec = {'id': 'm1-local-observation', 'contract': {'id': 'guihong-m1-local', 'version': '1.2'},
            'evidence_type': 'guihong.m1', 'coordinates': request,
            'projections': ['source_sha', 'contracts', 'core', 'children', 'resources', 'build', 'gates', 'cleanup', 'boundary'],
            'canonicalization_profile': 'veritrail-json-c14n/1'}

    def hard(identity, path, value):
        return {'id': identity, 'severity': 'HARD', 'left': {'requirement_id': 'm1', 'path': '/facts/' + path},
                'operator': 'eq', 'right': value}

    assertions = [
        hard('source', 'source_sha', source), hard('clean', 'source_clean', True), hard('mode', 'mode', args.mode),
        hard('core-version', 'core/version', '0.13.0'), hard('core-lock', 'core/locked_wheel_sha256', '95cb00c08fa4a29c21c798c7ca5a8200bb83f71cd11b31b1dea01c19ec5a8a04'),
        hard('build-source', 'build/source_sha', source), hard('build-exit', 'build/exit_code', 0),
        hard('build-go-version', 'build/go_version', 'go version go1.27.2 windows/amd64'),
        hard('build-log', 'build/log_verified', True), hard('build-artifacts', 'build/artifacts_verified', True),
        hard('build-count', 'build/artifact_count', 3), hard('static-gate', 'gates/static/exit_code', 0),
        hard('proxy-parser-tests', 'gates/proxy_parser/exit_code', 0),
        hard('apps-stopped', 'cleanup/applications_stopped', {'delivery': True, 'ingress': True, 'mailbox': True}),
    ]
    if args.mode == 'exact-main':
        assertions.append(hard('exact-origin-main', 'head_matches_origin_main', True))
    for name in request['contracts']:
        assertions.append(hard('contract-' + name.replace('_', '-'), 'contracts/' + name, request['contracts'][name]))
    for name in CHILDREN:
        base = 'children/' + name
        assertions.extend([
            hard(name + '-run', base + '/run_id', child_ids[name]), hard(name + '-manifest', base + '/manifest_verified', True),
            hard(name + '-plan', base + '/plan_sha256_verified', True), hard(name + '-identity', base + '/acceptance_id_verified', True),
            hard(name + '-execution', base + '/execution_status', 'COMPLETED'), hard(name + '-verdict', base + '/verdict', 'PASS'),
            hard(name + '-summary', base + '/summary_matches', True), hard(name + '-source', base + '/source_matches', True),
            hard(name + '-privacy', base + '/evidence_unredacted', True),
            hard(name + '-resource-file', 'resources/' + name + '/file', resource_ids[name]),
            hard(name + '-resource-stop', 'resources/' + name + '/stop_reasons', []),
            hard(name + '-resource-host', 'resources/' + name + '/host_under_stop_line', True),
            hard(name + '-resource-rss', 'resources/' + name + '/applications_under_stop_line', True),
            hard(name + '-container-roles', 'resources/' + name + '/container_roles_seen', list(resource_guard.INFRASTRUCTURE)),
            hard(name + '-container-memory', 'resources/' + name + '/container_memory_headroom_ok', True),
            hard(name + '-container-pids', 'resources/' + name + '/container_pid_headroom_ok', True),
            hard(name + '-container-oom', 'resources/' + name + '/container_oom_free', True),
            hard(name + '-resource-time', 'resources/' + name + '/covers_child_evidence', True),
        ])
    assertions.append(hard('application-resource-witness', 'resources/application_roles_seen', sorted(lab.SERVICES)))
    assertions.append(hard('infrastructure-resource-witness', 'resources/infrastructure_roles_seen', list(resource_guard.INFRASTRUCTURE)))
    assertions.append(hard('sustained-full-topology', 'resources/full_topology_sustained', True))
    plan = seal_acceptance_plan({
        'plan_kind': 'ACCEPTANCE', 'schema_version': '0.1', 'plan_id': 'guihong-m1-local', 'version': 3,
        'subject': {'id': 'guihong-m1-' + args.mode, 'version': source, 'source_ref': 'github:NoctilumeDev/GuiHongMail'},
        'question': 'Do all finite M1 local child, build, architecture, resource and public-Core gates reconcile for the exact source?',
        'governance': {'claim_owner_ref': 'human:repository-owner', 'drafter_ref': 'guihong:m1-reconciler',
                       'seal_authority_ref': 'human:repository-owner:guihong-m1-m6-20261013', 'seal_decision': 'CONFIRMED'},
        'observation_specs': [spec], 'evidence_requirements': [{'id': 'm1', 'observation_spec_id': spec['id'], 'cardinality': 'EXACTLY_ONE'}],
        'sufficiency_rules': [{'id': 'coverage', 'left': {'requirement_id': 'm1', 'path': '/metadata/veritrail_observation/coverage'},
                               'operator': 'eq', 'right': 'COMPLETE'}],
        'integrity_rules': [], 'assertions': assertions,
        'resource_budget': {'max_artifact_bytes': 4194304, 'max_probe_seconds': 120},
        'change_scope': {'level': 'L2_CONTRACT', 'owner': 'GuiHongMail M1 local qualification', 'consumers': ['m1-stage-gate']},
        'reproduction_steps': ['Build and run all three child collectors at one clean exact source under independent watchdog windows.',
                               'Run this reconciler with the exact child and resource evidence identities using locked public Core.'],
        'cleanup_steps': ['Retain all child and aggregate evidence, including non-PASS controls.',
                          'Application shutdown must already be proven; infrastructure cleanup remains an explicit owned-lab action.'],
    })
    save(out / 'sealed-plan.json', plan)
    save(out / 'request.json', request)
    status = 'COMPLETED'
    error_record = None
    facts = {'source_sha': source, 'source_clean': not bool(git('status', '--porcelain')), 'mode': args.mode,
             'head_matches_origin_main': source == git('rev-parse', 'origin/main'), 'contracts': {}, 'children': {},
             'resources': {}, 'boundary': 'M1_LOCAL_' + args.mode.upper().replace('-', '_') + '_ONLY'}
    try:
        facts['contracts'] = {name: sha_file(ROOT / path) for name, path in {
            'm1_plan': 'docs/m1-plan.md', 'm1_components': 'docs/m1-components.md',
            'm1_resource_contract': 'docs/m1-resource-contract-1.1.md',
            'go_runtime_contract': 'docs/m0.1-go-runtime.md', 'go_environment_lock': 'docs/go-environment-lock.json',
            'environment_lock': 'docs/environment-lock.json', 'ci': '.github/workflows/ci.yml'}.items()}
        dist = distribution('veritrail')
        record = Path(dist.locate_file('veritrail-0.13.0.dist-info/RECORD'))
        lock = json.loads((ROOT / 'docs/environment-lock.json').read_text(encoding='utf-8'))
        facts['core'] = {'version': version('veritrail'), 'distribution_record_sha256': sha_file(record),
                         'locked_wheel_sha256': lock['collector']['veritrail_wheel_sha256']}
        for name in CHILDREN:
            facts['children'][name] = inspect_bundle(child_ids[name], source)
            resource = inspect_resource(resource_ids[name], facts['children'][name]['captured_epochs'])
            resource['host_under_stop_line'] = resource['max_host_used_bytes'] <= 14 * 1024**3
            resource['applications_under_stop_line'] = resource['max_application_rss_bytes'] <= 384 * 1024**2
            facts['resources'][name] = resource
            del facts['children'][name]['captured_epochs']
        facts['resources']['application_roles_seen'] = sorted({role for name in CHILDREN for role in facts['resources'][name]['application_roles_seen']})
        facts['resources']['infrastructure_roles_seen'] = sorted({role for name in CHILDREN for role in facts['resources'][name]['container_roles_seen']})
        facts['resources']['full_topology_sustained'] = max(
            facts['resources'][name]['max_consecutive_full_topology_samples'] for name in CHILDREN) >= 6
        facts['build'] = inspect_build(source)
        facts['gates'] = {
            'static': run_gate([sys.executable, '-B', str(ROOT / 'scripts/check.py'), 'all'], out / 'static-gate.log'),
            'proxy_parser': run_gate([sys.executable, '-B', str(ROOT / 'scripts/test_mysql_commit_proxy.py')], out / 'proxy-parser-tests.log'),
        }
        facts['cleanup'] = {'applications_stopped': applications_stopped()}
    except Exception as error:
        status = 'ERROR'
        error_record = {'exception_type': type(error).__name__, 'message': str(error)}
        save(out / 'collection-error.json', error_record)
    facts['source_sha'] = git('rev-parse', 'HEAD')
    facts['source_clean'] = not bool(git('status', '--porcelain'))
    if args.control == 'wrong-hash' and facts.get('children'):
        first = next(iter(facts['children'].values()))
        first['manifest_verified'] = False
    metadata = {'schema_version': '0.1', 'canonicalization_profile': 'veritrail-json-c14n/1',
                'plan_digest': plan['seal']['digest'], 'observation_spec_digest': observation_spec_digest(spec),
                'request_seal_digest': sha256_json(request), 'collection_session_id': run,
                'collector_role': 'guihong-m1-reconciler', 'coverage': 'COMPLETE' if status == 'COMPLETED' else 'ERROR',
                'normalization_semantics_version': 'guihong-m1/1.2', 'facts_digest': sha256_json(facts)}
    if args.control == 'wrong-binding':
        metadata['plan_digest'] = '0' * 64
    evidence = {'schema_version': '0.1', 'evidence_type': spec['evidence_type'], 'source': 'guihong-m1/1.2',
                'captured_at': datetime.now(timezone.utc).isoformat(), 'facts': facts,
                'metadata': {'veritrail_observation': metadata}}
    save(out / 'evidence.json', evidence)
    report = create_acceptance_bundle(plan=plan, evidence_paths=[] if args.control == 'missing-evidence' else [out / 'evidence.json'],
                                      output=out / 'bundle', acceptance_id=run, execution_status=status)
    expected = {'none': 'PASS', 'wrong-hash': 'FAIL', 'wrong-binding': 'INCONCLUSIVE', 'missing-evidence': 'PENDING'}[args.control]
    summary = {'identity': run, 'source_sha': source, 'execution_status': report['execution_status'], 'verdict': report['verdict'],
               'expected': expected, 'control': args.control, 'mode': args.mode, 'boundary': facts['boundary'],
               'bundle': (out / 'bundle').relative_to(ROOT).as_posix()}
    save(out / 'summary.json', summary)
    print(json.dumps(summary))
    return 0 if status == 'COMPLETED' and report['verdict'] == expected else 1


if __name__ == '__main__':
    raise SystemExit(main())
