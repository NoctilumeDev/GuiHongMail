"""Create one independent M6 round receipt from retained runtime evidence."""
import argparse
import hashlib
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import re
import socket
import subprocess
import uuid

from veritrail.canonical import sha256_json

from evidence_summary import is_completed
import lab

ROOT = lab.ROOT


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def child(relative, expected_type, source):
    path = (ROOT / relative).resolve()
    local = (ROOT / 'artifacts/local').resolve()
    if not path.is_file() or not path.is_relative_to(local) or path.name != 'evidence.json':
        raise RuntimeError('Round child must be a retained local evidence.json')
    evidence = read_json(path)
    summary = read_json(path.parent / 'summary.json')
    facts = evidence.get('facts', {})
    observed = evidence.get('metadata', {}).get('veritrail_observation', {})
    if evidence.get('evidence_type') != expected_type:
        raise RuntimeError('Unexpected M6 child evidence type')
    if facts.get('source_sha') != source or summary.get('source_sha') != source:
        raise RuntimeError('M6 child source mismatch')
    if summary.get('verdict') != 'PASS' or not is_completed(summary):
        raise RuntimeError('M6 child is not a completed PASS')
    if observed.get('facts_digest') != sha256_json(facts):
        raise RuntimeError('M6 child facts digest mismatch')
    return {'path': path, 'evidence': evidence, 'summary': summary, 'facts': facts,
            'evidence_sha256': digest(path), 'facts_digest': observed['facts_digest']}


def verified_build(source):
    path = ROOT / '.artifacts/go-build' / source / 'receipt.json'
    receipt = read_json(path)
    if receipt.get('schema') != 'GuiHongGoBuildReceipt/1.0' or receipt.get('source_sha') != source:
        raise RuntimeError('M6 build receipt is not bound to exact source')
    if receipt.get('go_sum_sha256') != digest(ROOT / 'go.sum'):
        raise RuntimeError('M6 Go lock differs from build receipt')
    if receipt.get('frontend_lock_sha256') != digest(ROOT / 'frontend/web/package-lock.json'):
        raise RuntimeError('M6 frontend lock differs from build receipt')
    artifacts = []
    for row in receipt.get('artifacts', []):
        candidate = (ROOT / row['path']).resolve()
        if not candidate.is_file() or not candidate.is_relative_to((ROOT / '.artifacts/go-build').resolve()):
            raise RuntimeError('M6 build artifact escaped owned build root')
        if candidate.stat().st_size != row['bytes'] or digest(candidate) != row['sha256']:
            raise RuntimeError('M6 build artifact hash mismatch')
        artifacts.append({'role': row['role'], 'bytes': row['bytes'], 'sha256': row['sha256']})
    frontend = []
    for row in receipt.get('frontend_assets', []):
        candidate = (ROOT / row['path']).resolve()
        if not candidate.is_file() or candidate.stat().st_size != row['bytes'] or digest(candidate) != row['sha256']:
            raise RuntimeError('M6 frontend asset hash mismatch')
        frontend.append({'path': row['path'], 'bytes': row['bytes'], 'sha256': row['sha256']})
    if {item['role'] for item in artifacts} != {'mailbox', 'ingress', 'delivery'} or not frontend:
        raise RuntimeError('M6 build receipt is incomplete')
    return path, receipt, artifacts, frontend


def screenshot(parent, relative):
    path = (parent / relative).resolve()
    if not path.is_file() or not path.is_relative_to(parent.resolve()) or path.stat().st_size == 0:
        raise RuntimeError('M6 screenshot is missing or empty')
    return {'name': Path(relative).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def owned_absent(identity):
    if re.fullmatch(r'guihong-local-[a-f0-9]{12}', identity) is None:
        raise RuntimeError('Invalid M6 lab identity')
    docker = lab.docker()
    commands = {
        'containers': [docker, 'ps', '-aq', '--filter', 'label=guihong.owner=' + identity],
        'volumes': [docker, 'volume', 'ls', '-q', '--filter', 'label=guihong.owner=' + identity],
        'networks': [docker, 'network', 'ls', '-q', '--filter', 'label=guihong.owner=' + identity],
    }
    remaining = {name: subprocess.check_output(command, text=True, encoding='utf-8').split()
                 for name, command in commands.items()}
    return {'id': identity, 'remaining': remaining, 'clean': not any(remaining.values())}


def port_free(port):
    with socket.socket() as probe:
        probe.settimeout(.5)
        return probe.connect_ex(('127.0.0.1', port)) != 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--m3', required=True)
    parser.add_argument('--m4', required=True)
    parser.add_argument('--resilience', required=True)
    parser.add_argument('--lab-id', action='append', required=True)
    args = parser.parse_args()
    if git('status', '--porcelain'):
        raise RuntimeError('M6 round requires committed clean exact source')
    if lab.LAB.exists():
        raise RuntimeError('M6 round cleanup must finish before reconciliation')
    source = git('rev-parse', 'HEAD')
    children = {
        'm3': child(args.m3, 'guihong.m3', source),
        'm4': child(args.m4, 'guihong.m4', source),
        'resilience': child(args.resilience, 'guihong.m5.resilience', source),
    }
    receipt_path, receipt, artifacts, frontend = verified_build(source)
    m3, m4, resilience = (children[name]['facts'] for name in ('m3', 'm4', 'resilience'))
    cleanup = [owned_absent(identity) for identity in args.lab_id]
    if len(cleanup) != 3 or len({item['id'] for item in cleanup}) != 3:
        raise RuntimeError('M6 round requires three distinct fresh labs')
    ports = {str(port): port_free(port) for port in (18080, 18081, 18082, 2526)}
    screenshots = [
        screenshot(children['m3']['path'].parent,
                   Path('browser-cancel') / m3['browser']['cancel']['screenshot']),
        screenshot(children['m3']['path'].parent,
                   Path('browser-unknown') / m3['browser']['unknown']['screenshot']),
        screenshot(children['m4']['path'].parent,
                   Path('browser') / m4['browser']['desktop']['screenshot']),
        screenshot(children['m4']['path'].parent,
                   Path('browser') / m4['browser']['mobile']['screenshot']),
    ]
    resources = [m3['resource'], m4['resource'], resilience['resource']]
    resource_ok = all(row['full_topology_samples'] >= (18 if index == 2 else 12) and
                      not row['stop_reasons'] and row['max_host_used_bytes'] < 14 * 1024**3 and
                      row['min_container_memory_headroom_ratio'] >= .10 and
                      row['min_container_pid_headroom'] >= 16
                      for index, row in enumerate(resources))
    versions = {name: importlib_metadata.version(name) for name in ('veritrail', 'boto3', 'PyMySQL')}
    cases = {
        'R-01': versions == {'veritrail': '0.13.0', 'boto3': '1.43.112', 'PyMySQL': '1.2.3'} and
                receipt.get('go_version') == 'go version go1.27.2 windows/amd64',
        'R-02': all(all(item['facts']['cases'].values()) for item in children.values()),
        'R-03': all(m3['cases'][case] for case in ('M3-02', 'M3-03', 'M3-05', 'M3-11', 'M3-13', 'M3-16')),
        'R-04': all(m4['cases'][case] for case in ('M4-13', 'M4-14', 'M4-16')) and
                not m3['browser']['cancel']['external_requests'] and not m3['browser']['unknown']['external_requests'],
        'R-05': all(m4['cases'][case] for case in ('M4-03', 'M4-06', 'M4-07', 'M4-09', 'M4-11', 'M4-12')),
        'R-06': m3['cases']['M3-17'] and m4['cases']['M4-15'] and m3['restart']['equal'] and m4['restart']['equal'],
        'R-07': all(resilience['cases'][case] for case in ('M5R-06', 'M5R-07', 'M5R-08', 'M5R-09', 'M5R-10')),
        'R-08': resource_ok and all(item['clean'] for item in cleanup) and all(ports.values()),
    }
    run = 'guihong-m6round-' + uuid.uuid4().hex
    output = lab.local_run(run, create=True)
    record = {
        'schema': 'GuiHongM6Round/1.0', 'identity': run, 'source_sha': source,
        'checkout_identity': str(ROOT.resolve()), 'verdict': 'PASS' if all(cases.values()) else 'FAIL',
        'cases': cases, 'versions': versions,
        'build': {'receipt': receipt_path.relative_to(ROOT).as_posix(), 'receipt_sha256': digest(receipt_path),
                  'artifacts': artifacts, 'frontend_assets': frontend},
        'children': {name: {'identity': item['summary']['identity'], 'evidence_sha256': item['evidence_sha256'],
                            'facts_digest': item['facts_digest']} for name, item in children.items()},
        'product': {'screenshots': screenshots, 'browser_version': m4['browser']['browser_version'],
                    'desktop': m4['browser']['desktop'], 'mobile': m4['browser']['mobile'],
                    'm4_external_requests': m4['browser']['external_requests'],
                    'cancel': m3['browser']['cancel'], 'unknown': m3['browser']['unknown'],
                    'classification_cases': {case: m4['cases'][case] for case in ('M4-03','M4-06','M4-07','M4-09','M4-11','M4-12')}},
        'recovery': {'m3_restart': m3['restart'], 'm4_restart': m4['restart'],
                     'snapshot_cases': {case: resilience['cases'][case] for case in ('M5R-06','M5R-07','M5R-08','M5R-09','M5R-10')}},
        'resource': {'windows': resources, 'max_host_used_bytes': max(row['max_host_used_bytes'] for row in resources),
                     'min_container_memory_headroom_ratio': min(row['min_container_memory_headroom_ratio'] for row in resources),
                     'min_container_pid_headroom': min(row['min_container_pid_headroom'] for row in resources)},
        'cleanup': {'labs': cleanup, 'ports_free': ports},
        'operator_guide_sha256': digest(ROOT / 'docs/operator-guide.md'),
        'boundary': 'M6_FRESH_ROUND_ONLY',
    }
    lab.write_new(output / 'round.json', json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'identity': run, 'source_sha': source, 'verdict': record['verdict'],
                      'record': (output / 'round.json').relative_to(ROOT).as_posix()}))
    return 0 if record['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
