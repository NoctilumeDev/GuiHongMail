"""Seal and execute the finite Go/RocketMQ M1G compatibility preflight."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json

import apps
import lab
import resource_guard

ROOT = lab.ROOT
GO = Path(r'D:\DevTools\Go\go1.27.2\bin\go.exe')
RUN_PATTERN = re.compile(r'^guihong-m1g-[0-9a-f]{32}$')
GO_CLIENT = 'github.com/apache/rocketmq-client-go/v2'
GO_CLIENT_VERSION = 'v2.1.2'
GO_CLIENT_COMMIT = '7eedaf948c6076c716972724782f4837e1f9caa6'
GO_ARCHIVE_SHA256 = '1314008898bd40df77af4b014f777f08873dbdfbcd3d92308728ee03304fe04f'
PROBE_RSS_LIMIT = 384 * 1024**2
HOST_LIMIT = 14 * 1024**3


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def command_environment(offline=True):
    env = dict(os.environ)
    for name in list(env):
        if name.lower() in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'gopath', 'goroot'}:
            env.pop(name, None)
    env.update(
        CGO_ENABLED='0',
        GOCACHE=str(ROOT / '.artifacts' / 'go-cache'),
        GOMODCACHE=str(ROOT / '.artifacts' / 'go-mod'),
        GOPROXY='off' if offline else 'https://proxy.golang.org,direct',
        NO_PROXY='127.0.0.1,localhost',
    )
    return env


def logged(command, log_path, *, timeout=180, check=True, env=None):
    with log_path.open('x', encoding='utf-8', newline='\n') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'command failed with code {result.returncode}; original log retained at {log_path.name}')
    return result.returncode


def payload(run, kind):
    return json.dumps({'run': run, 'kind': kind}, ensure_ascii=False,
                      separators=(',', ':'), sort_keys=False).encode('utf-8')


def message_key(run, kind):
    return f'{run}-{kind}'


def build_probe(out):
    if not GO.is_file():
        raise RuntimeError('pinned Go executable is missing')
    binary = out / 'mqprobe.exe'
    env = command_environment()
    logged([str(GO), 'test', './...'], out / 'go-test.log', env=env)
    logged([str(GO), 'vet', './...'], out / 'go-vet.log', env=env)
    logged([str(GO), 'build', '-trimpath', '-ldflags', '-s -w', '-o', str(binary), './cmd/mqprobe'],
           out / 'go-build.log', env=env)
    module_raw = subprocess.check_output([str(GO), 'list', '-m', '-json', GO_CLIENT], cwd=ROOT,
                                         env=env, text=True, encoding='utf-8')
    module = json.loads(module_raw)
    version_output = subprocess.check_output([str(GO), 'version', '-m', str(binary)], cwd=ROOT,
                                             env=env, text=True, encoding='utf-8')
    go_env = subprocess.check_output([str(GO), 'env', 'GOVERSION', 'GOOS', 'GOARCH', 'GOROOT'], cwd=ROOT,
                                     env=env, text=True, encoding='utf-8').splitlines()
    facts = {
        'version': subprocess.check_output([str(GO), 'version'], cwd=ROOT, env=env,
                                           text=True, encoding='utf-8').strip(),
        'goversion': go_env[0], 'goos': go_env[1], 'goarch': go_env[2], 'goroot': go_env[3],
        'archive_sha256': GO_ARCHIVE_SHA256,
        'environment_lock_sha256': sha_file(ROOT / 'docs' / 'go-environment-lock.json'),
        'client_module': module['Path'], 'client_version': module['Version'], 'client_sum': module['Sum'],
        'client_tag_commit': GO_CLIENT_COMMIT,
        'binary_sha256': sha_file(binary), 'binary_bytes': binary.stat().st_size,
        'binary_build_info': version_output.splitlines(),
    }
    if facts['client_module'] != GO_CLIENT or facts['client_version'] != GO_CLIENT_VERSION:
        raise RuntimeError('resolved RocketMQ module does not match the sealed selection')
    if not any(f'dep\t{GO_CLIENT}\t{GO_CLIENT_VERSION}\t' in line for line in facts['binary_build_info']):
        raise RuntimeError('built binary does not bind the selected RocketMQ module')
    return binary, facts


def probe_command(binary, command, binding, output, timeout='90s'):
    return [str(binary), command, '--run', binding['run'], '--topic', binding['topic'],
            '--group', binding['group'], '--namesrv', '127.0.0.1:19876', '--broker', '127.0.0.1:20911',
            '--timeout', timeout, '--out', str(output)]


def run_probe(binary, command, binding, out, stem, extra=None, timeout=120):
    evidence_path = out / f'{stem}.json'
    command_line = probe_command(binary, command, binding, evidence_path)
    if extra:
        command_line.extend(extra)
    logged(command_line, out / f'{stem}.log', timeout=timeout, env=command_environment())
    return json.loads(evidence_path.read_text(encoding='utf-8'))


def owned_container(service, *, all_states=True):
    state = lab.load()
    command = [lab.docker(), 'ps']
    if all_states:
        command.append('-a')
    command.extend(['-q', '--filter', f'label=com.docker.compose.project={state["id"]}',
                    '--filter', f'label=com.docker.compose.service={service}'])
    identities = subprocess.check_output(command, text=True, encoding='utf-8').split()
    if len(identities) != 1:
        raise RuntimeError(f'exact owned {service} container is unavailable')
    return identities[0]


def inspect_container(identity):
    return json.loads(subprocess.check_output([lab.docker(), 'inspect', identity],
                                              text=True, encoding='utf-8'))[0]


def wait_mq(out, stem, timeout=60):
    broker = owned_container('broker')
    deadline = time.monotonic() + timeout
    attempts = []
    while time.monotonic() < deadline:
        result = subprocess.run(
            [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin',
             'clusterList', '-n', 'namesrv:9876'], capture_output=True, text=True, encoding='utf-8', timeout=15)
        combined = result.stdout + result.stderr
        attempts.append({'at': datetime.now(timezone.utc).isoformat(), 'exit_code': result.returncode,
                         'output_sha256': sha_bytes(combined.encode('utf-8')), 'output_bytes': len(combined.encode('utf-8'))})
        if result.returncode == 0 and lab.load()['id'] in combined:
            save(out / f'{stem}.json', attempts)
            return
        time.sleep(1)
    save(out / f'{stem}.json', attempts)
    raise RuntimeError('RocketMQ did not become ready before the bounded deadline')


def mqadmin(out, stem, action, binding):
    if action not in {'updateSubGroup', 'deleteSubGroup'}:
        raise RuntimeError('unsupported owned mqadmin action')
    broker = owned_container('broker')
    command = [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin', action,
               '-n', 'namesrv:9876', '-b', '127.0.0.1:20911', '-g', binding['group']]
    logged(command, out / f'{stem}.log', timeout=30)


def inventory():
    state = lab.load()
    result = {'owner': state['id']}
    for kind, command in {
        'containers': [lab.docker(), 'ps', '-aq', '--filter', f'label=guihong.owner={state["id"]}'],
        'volumes': [lab.docker(), 'volume', 'ls', '-q', '--filter', f'label=guihong.owner={state["id"]}'],
        'networks': [lab.docker(), 'network', 'ls', '-q', '--filter', f'label=guihong.owner={state["id"]}'],
    }.items():
        result[kind] = sorted(subprocess.check_output(command, text=True, encoding='utf-8').split())
    return result


def running_topology(binary, probe_identity=None):
    state = lab.load()
    ids = subprocess.check_output(
        [lab.docker(), 'ps', '-q', '--filter', f'label=com.docker.compose.project={state["id"]}'],
        text=True, encoding='utf-8').split()
    inspected = json.loads(subprocess.check_output([lab.docker(), 'inspect', *ids],
                                                   text=True, encoding='utf-8')) if ids else []
    services = sorted((row['Config'].get('Labels') or {}).get('com.docker.compose.service') for row in inspected)
    expected = sorted(resource_guard.INFRASTRUCTURE)
    result = {'running_services': services, 'expected_services': expected,
              'only_expected_services': services == expected, 'proxy_present': 'proxy' in services}
    if probe_identity is not None:
        current = apps.process_identity(probe_identity['pid'])
        result['probe_identity_matches'] = current == {k: probe_identity[k] for k in ('creation_ticks', 'executable')}
        result['probe_executable_matches'] = (current is not None and
                                               Path(current['executable']).resolve() == binary.resolve())
    return result


def capture_resource_window(process, binary, out):
    identity = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and process.poll() is None:
        identity = apps.process_identity(process.pid)
        if identity is not None:
            break
        time.sleep(.05)
    if identity is None or Path(identity['executable']).resolve() != binary.resolve():
        raise RuntimeError('cannot bind the owned Go probe process')
    owned = {'pid': process.pid, **identity}
    contracts = resource_guard.container_contract()
    target = out / 'resource-window.jsonl'
    samples = []
    consecutive_high = 0
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        while process.poll() is None:
            memory = lab.memory()
            containers = resource_guard.container_snapshot(contracts)
            reason = resource_guard.container_violation(containers)
            current = apps.process_identity(process.pid)
            process_row = None
            if current == identity:
                value = resource_guard.rss(process.pid)
                process_row = {'role': 'mqprobe', 'pid': process.pid, 'rss_bytes': value,
                               'creation_ticks': identity['creation_ticks'], 'executable': identity['executable']}
                if value > PROBE_RSS_LIMIT:
                    reason = reason or 'APPLICATION_RSS_STOP_LINE'
            else:
                reason = reason or 'PROBE_IDENTITY_CHANGED'
            consecutive_high = consecutive_high + 1 if memory['used_bytes'] > HOST_LIMIT else 0
            if consecutive_high >= 3:
                reason = reason or 'HOST_MEMORY_STOP_LINE'
            topology = running_topology(binary, owned)
            full = topology['only_expected_services'] and topology.get('probe_identity_matches', False)
            row = {'utc_epoch': time.time(), 'memory': memory, 'process': process_row,
                   'containers': containers, 'topology': topology, 'full_topology': full,
                   'consecutive_high': consecutive_high, 'stop_reason': reason}
            samples.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            if reason:
                if apps.process_identity(process.pid) == identity:
                    process.terminate()
                lab.compose(['stop', '--timeout', '20'])
                raise RuntimeError(f'resource stop line: {reason}')
            for _ in range(25):
                if process.poll() is not None:
                    break
                time.sleep(.2)
    return owned, samples


def summarize_resources(samples):
    running = [container for sample in samples for container in sample['containers'] if container['running']]
    per_service = {}
    for service in resource_guard.INFRASTRUCTURE:
        rows = [row for row in running if row['service'] == service]
        per_service[service] = {
            'samples': len(rows),
            'memory_limit_bytes': rows[0]['memory_limit_bytes'] if rows else None,
            'max_memory_usage_bytes': max((row['memory_usage_bytes'] for row in rows), default=None),
            'minimum_memory_headroom_ratio': min((row['memory_headroom_ratio'] for row in rows), default=None),
            'pids_limit': rows[0]['pids_limit'] if rows else None,
            'maximum_pids': max((row['pids'] for row in rows), default=None),
            'minimum_pid_headroom': min((row['pid_headroom'] for row in rows), default=None),
            'oom_free': bool(rows) and all(not row['oom_killed'] for row in rows),
        }
    return {
        'samples': len(samples), 'full_topology_samples': sum(1 for row in samples if row['full_topology']),
        'stop_reasons': [row['stop_reason'] for row in samples if row['stop_reason']],
        'max_host_used_bytes': max((row['memory']['used_bytes'] for row in samples), default=0),
        'max_probe_rss_bytes': max((row['process']['rss_bytes'] for row in samples if row['process']), default=0),
        'container_memory_headroom_ok': bool(running) and all(
            row['memory_headroom_ratio'] >= resource_guard.MIN_CONTAINER_MEMORY_HEADROOM_RATIO for row in running),
        'container_pid_headroom_ok': bool(running) and all(
            row['pid_headroom'] >= resource_guard.MIN_CONTAINER_PID_HEADROOM for row in running),
        'container_oom_free': bool(running) and all(not row['oom_killed'] for row in running),
        'per_service': per_service,
    }


def lifecycle_summary(binding, prepare, consume):
    expected = {}
    for kind in ('stored-before-restart', 'sent-after-consumer'):
        key = message_key(binding['run'], kind)
        expected[key] = sha_bytes(payload(binding['run'], kind))
    sends = {row['key']: row for row in prepare.get('sends', []) + consume.get('sends', [])}
    facts = {row['key']: row for row in consume.get('facts', [])}
    retry_key = message_key(binding['run'], 'stored-before-restart')
    retry_attempts = [row for row in consume.get('attempts', []) if row['key'] == retry_key]
    return {
        'expected': expected,
        'sent_keys': sorted(sends),
        'send_statuses': {key: sends[key]['send_status'] for key in sorted(sends)},
        'send_hashes_match': all(sends.get(key, {}).get('body_sha256') == digest for key, digest in expected.items()),
        'fact_keys': sorted(facts),
        'fact_hashes_match': all(facts.get(key, {}).get('body_sha256') == digest for key, digest in expected.items()),
        'business_fact_count': len(consume.get('facts', [])),
        'retry_attempt_count': len(retry_attempts),
        'retry_first_decision': retry_attempts[0]['decision'] if retry_attempts else None,
        'retry_first_reason': retry_attempts[0]['reason'] if retry_attempts else None,
        'retry_later_success': any(row['decision'] == 'SUCCESS' for row in retry_attempts[1:]),
        'complete': bool(consume.get('complete')),
    }


def remove_lab_directory():
    expected = (ROOT / '.artifacts' / 'lab').resolve()
    candidate = lab.LAB.resolve()
    if candidate != expected or not candidate.is_relative_to(ROOT.resolve()):
        raise RuntimeError('lab cleanup target escaped the worktree')
    if lab.LAB.is_symlink():
        raise RuntimeError('lab cleanup target is linked')
    shutil.rmtree(lab.LAB)


def capture_failure_logs(out):
    if not lab.LAB.exists():
        return
    try:
        for service in ('namesrv', 'broker'):
            identity = owned_container(service)
            logged([lab.docker(), 'logs', '--timestamps', identity], out / f'failure-{service}.log',
                   timeout=30, check=False)
    except Exception as error:
        save(out / 'failure-log-capture-error.json', {'type': type(error).__name__, 'message': str(error)})


def cleanup_lab(out):
    result = {'attempted': False, 'resources_after': None, 'lab_directory_removed': False}
    if not lab.LAB.exists():
        return result
    result['attempted'] = True
    result['resources_before'] = inventory()
    try:
        lab.compose(['down', '--volumes', '--timeout', '20'], timeout=180, capture=True)
        result['resources_after'] = inventory()
        result['owned_resources_removed'] = all(not result['resources_after'][kind]
                                                for kind in ('containers', 'volumes', 'networks'))
        if not result['owned_resources_removed']:
            raise RuntimeError('owned Docker resources remain after down --volumes')
        remove_lab_directory()
        result['lab_directory_removed'] = True
    except Exception as error:
        result['error'] = {'type': type(error).__name__, 'message': str(error)}
    return result


def sealed_plan(source, request, binding, build):
    spec = {'id': 'm1g-runtime-observation', 'contract': {'id': 'guihong-m1g', 'version': '1.0'},
            'evidence_type': 'guihong.m1g', 'coordinates': request,
            'projections': ['source_sha', 'source_clean', 'build', 'binding', 'admin', 'restart', 'lifecycle',
                            'topology', 'resources', 'cleanup', 'boundary', 'control'],
            'canonicalization_profile': 'veritrail-json-c14n/1'}

    def hard(identity, path, value):
        return {'id': identity, 'severity': 'HARD', 'left': {'requirement_id': 'm1g', 'path': '/facts/' + path},
                'operator': 'eq', 'right': value}

    kinds = ('stored-before-restart', 'sent-after-consumer')
    expected_keys = sorted(message_key(binding['run'], kind) for kind in kinds)
    assertions = [
        hard('source', 'source_sha', source), hard('clean', 'source_clean', True),
        hard('go-version', 'build/goversion', 'go1.27.2'), hard('go-os', 'build/goos', 'windows'),
        hard('go-arch', 'build/goarch', 'amd64'), hard('go-archive', 'build/archive_sha256', GO_ARCHIVE_SHA256),
        hard('module', 'build/client_module', GO_CLIENT), hard('module-version', 'build/client_version', GO_CLIENT_VERSION),
        hard('module-commit', 'build/client_tag_commit', GO_CLIENT_COMMIT),
        hard('binary', 'build/binary_sha256', build['binary_sha256']),
        hard('binding', 'binding', binding),
        hard('topic-created', 'admin/topic_present', True), hard('pre-restart-send', 'admin/complete', True),
        hard('restart-same-container', 'restart/same_container', True),
        hard('restart-new-start', 'restart/started_at_changed', True),
        hard('restart-topic', 'restart/topic_present', True), hard('restart-group', 'restart/group_present', True),
        hard('sent-keys', 'lifecycle/sent_keys', expected_keys),
        hard('send-statuses', 'lifecycle/send_statuses', {key: 'SEND_OK' for key in expected_keys}),
        hard('send-hashes', 'lifecycle/send_hashes_match', True),
        hard('fact-keys', 'lifecycle/fact_keys', expected_keys),
        hard('fact-hashes', 'lifecycle/fact_hashes_match', True),
        hard('fact-count', 'lifecycle/business_fact_count', 2),
        hard('retry-count', 'lifecycle/retry_attempt_count_minimum_met', True),
        hard('retry-first', 'lifecycle/retry_first_decision', 'RETRY'),
        hard('retry-reason', 'lifecycle/retry_first_reason', 'sealed-first-attempt'),
        hard('retry-success', 'lifecycle/retry_later_success', True), hard('lifecycle-complete', 'lifecycle/complete', True),
        hard('topology', 'topology/only_expected_services', True), hard('no-proxy', 'topology/proxy_present', False),
        hard('probe-identity', 'topology/probe_identity_matches', True),
        hard('probe-executable', 'topology/probe_executable_matches', True),
        hard('resource-samples', 'resources/sample_minimum_met', True),
        hard('full-topology', 'resources/full_topology_minimum_met', True),
        hard('resource-stop', 'resources/stop_reasons', []),
        hard('host-budget', 'resources/host_under_stop_line', True),
        hard('probe-rss', 'resources/probe_under_stop_line', True),
        hard('container-memory', 'resources/container_memory_headroom_ok', True),
        hard('container-pids', 'resources/container_pid_headroom_ok', True),
        hard('container-oom', 'resources/container_oom_free', True),
        hard('topic-cleanup', 'cleanup/topic_present_after', False),
        hard('group-cleanup', 'cleanup/group_present_after', False),
        hard('owned-topic-cleanup', 'cleanup/owned_topics_after', []),
        hard('owned-group-cleanup', 'cleanup/owned_groups_after', []),
        hard('docker-cleanup', 'cleanup/owned_resources_removed', True),
        hard('lab-cleanup', 'cleanup/lab_directory_removed', True),
        hard('research-cleanup', 'cleanup/research_directory_absent', True),
        hard('boundary', 'boundary', 'GO_RUNTIME_PREFLIGHT_ONLY'),
    ]
    plan = seal_acceptance_plan({
        'plan_kind': 'ACCEPTANCE', 'schema_version': '0.1', 'plan_id': 'guihong-m1g', 'version': 1,
        'subject': {'id': 'guihong-go-runtime-preflight', 'version': source,
                    'source_ref': 'github:NoctilumeDev/GuiHongMail'},
        'question': 'Does the pinned Go remoting client satisfy the finite M1G lifecycle on the current RocketMQ topology?',
        'governance': {'claim_owner_ref': 'human:repository-owner', 'drafter_ref': 'guihong:m1g-collector',
                       'seal_authority_ref': 'human:repository-owner:guihong-go-or-java-20261013',
                       'seal_decision': 'CONFIRMED'},
        'observation_specs': [spec],
        'evidence_requirements': [{'id': 'm1g', 'observation_spec_id': spec['id'], 'cardinality': 'EXACTLY_ONE'}],
        'sufficiency_rules': [{'id': 'coverage', 'left': {'requirement_id': 'm1g',
                              'path': '/metadata/veritrail_observation/coverage'}, 'operator': 'eq', 'right': 'COMPLETE'}],
        'integrity_rules': [], 'assertions': assertions,
        'resource_budget': {'max_artifact_bytes': 4194304, 'max_probe_seconds': 600},
        'change_scope': {'level': 'L2_CONTRACT', 'owner': 'GuiHongMail M1G',
                         'consumers': ['go-runtime-selection']},
        'reproduction_steps': ['Build the probe from this exact clean source using the pinned Go toolchain and local verified module cache.',
                               'Use a fresh owned lab and execute the fixed topic, send, restart, retry, cleanup sequence.'],
        'cleanup_steps': ['Remove only the exact owned topic/group/internal retry topics and shut down clients.',
                          'Remove this run owned Docker resources and temporary lab/research directories; retain evidence and failures.'],
    })
    return plan, spec


def collect_actual(binary, binding, out):
    facts = {'binding': binding, 'boundary': 'GO_RUNTIME_PREFLIGHT_ONLY', 'control': 'none'}
    lab.init()
    lab.compose(['up', '-d'], timeout=300, capture=True)
    wait_mq(out, 'startup-readiness')
    facts['topology_before'] = running_topology(binary)
    prepare = run_probe(binary, 'prepare', binding, out, 'prepare')
    facts['admin'] = prepare
    mqadmin(out, 'create-group', 'updateSubGroup', binding)
    before = inspect_container(owned_container('broker'))
    lab.compose(['restart', '--timeout', '20', 'broker'], timeout=120, capture=True)
    wait_mq(out, 'restart-readiness')
    after = inspect_container(owned_container('broker'))
    restarted = run_probe(binary, 'inspect', binding, out, 'after-restart-inspect')
    facts['restart'] = {
        'container_before': before['Id'], 'container_after': after['Id'],
        'same_container': before['Id'] == after['Id'],
        'started_at_before': before['State']['StartedAt'], 'started_at_after': after['State']['StartedAt'],
        'started_at_changed': before['State']['StartedAt'] != after['State']['StartedAt'],
        'topic_present': restarted['topic_present'], 'group_present': restarted['group_present'],
        'oom_killed': after['State']['OOMKilled'],
    }
    consume_path = out / 'consume.json'
    command = probe_command(binary, 'consume', binding, consume_path, timeout='90s') + ['--min-live', '35s']
    with (out / 'consume.log').open('x', encoding='utf-8', newline='\n') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=command_environment(), stdout=log,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        _, samples = capture_resource_window(process, binary, out)
        exit_code = process.wait(timeout=10)
    if exit_code:
        raise RuntimeError(f'consume probe failed with code {exit_code}; original log retained')
    consume = json.loads(consume_path.read_text(encoding='utf-8'))
    facts['lifecycle'] = lifecycle_summary(binding, prepare, consume)
    facts['lifecycle']['retry_attempt_count_minimum_met'] = facts['lifecycle']['retry_attempt_count'] >= 2
    resources = summarize_resources(samples)
    resources['sample_minimum_met'] = resources['samples'] >= 6
    resources['full_topology_minimum_met'] = resources['full_topology_samples'] >= 6
    resources['host_under_stop_line'] = resources['max_host_used_bytes'] <= HOST_LIMIT
    resources['probe_under_stop_line'] = resources['max_probe_rss_bytes'] <= PROBE_RSS_LIMIT
    facts['resources'] = resources
    facts['topology'] = samples[-1]['topology']
    before_cleanup = run_probe(binary, 'inspect', binding, out, 'before-cleanup-inspect')
    mqadmin(out, 'delete-group', 'deleteSubGroup', binding)
    deleted = run_probe(binary, 'delete-topic', binding, out, 'delete-topics')
    after_cleanup = run_probe(binary, 'inspect', binding, out, 'after-cleanup-inspect')
    facts['cleanup'] = {
        'topic_present_before': before_cleanup['topic_present'],
        'group_present_before': before_cleanup['group_present'],
        'owned_topics_before': before_cleanup.get('owned_topics', []),
        'owned_groups_before': before_cleanup.get('owned_groups', []),
        'deleted_topics': deleted.get('deleted_topics', []),
        'topic_present_after': after_cleanup['topic_present'],
        'group_present_after': after_cleanup['group_present'],
        'owned_topics_after': after_cleanup.get('owned_topics', []),
        'owned_groups_after': after_cleanup.get('owned_groups', []),
    }
    return facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', choices=['none', 'wrong-hash'], default='none')
    parser.add_argument('--source-run')
    args = parser.parse_args()
    if version('veritrail') != '0.13.0':
        raise RuntimeError('Use locked public VeriTrail Core 0.13.0')
    if git('status', '--porcelain'):
        raise RuntimeError('Exact clean source required before Plan')
    if args.control == 'none' and args.source_run:
        raise RuntimeError('source-run is only valid for a negative control')
    if args.control != 'none' and (not args.source_run or not RUN_PATTERN.fullmatch(args.source_run)):
        raise RuntimeError('negative control requires an exact M1G source run')
    if args.control == 'none' and lab.LAB.exists():
        raise RuntimeError('M1G requires a fresh lab; preserve or clean the existing owner explicitly')

    source = git('rev-parse', 'HEAD')
    identity = 'guihong-m1g-' + uuid.uuid4().hex
    out = lab.local_run(identity, create=True)
    binary, build = build_probe(out)
    source_facts = None
    if args.control == 'none':
        binding = {'run': identity, 'topic': identity + '-topic', 'group': identity + '-group'}
    else:
        source_run = lab.local_run(args.source_run)
        source_facts = json.loads((source_run / 'facts.json').read_text(encoding='utf-8'))
        if source_facts['source_sha'] != source:
            raise RuntimeError('negative control source differs from current exact source')
        binding = source_facts['binding']
    request = {'source_sha': source, 'control': args.control, 'binding': binding,
               'binary_sha256': build['binary_sha256'], 'client_module': GO_CLIENT,
               'client_version': GO_CLIENT_VERSION, 'client_tag_commit': GO_CLIENT_COMMIT,
               'contract_sha256': sha_file(ROOT / 'docs' / 'm1g-preflight.md'),
               'source_run': args.source_run}
    plan, spec = sealed_plan(source, request, binding, build)
    save(out / 'sealed-plan.json', plan)
    save(out / 'request.json', request)
    status = 'COMPLETED'
    facts = {'source_sha': source, 'source_clean': True, 'build': build, 'binding': binding,
             'boundary': 'GO_RUNTIME_PREFLIGHT_ONLY', 'control': args.control}
    try:
        if args.control == 'none':
            runtime = collect_actual(binary, binding, out)
            facts.update(runtime)
        else:
            for key in ('admin', 'restart', 'lifecycle', 'topology', 'resources', 'cleanup'):
                facts[key] = source_facts[key]
            facts['binding'] = source_facts['binding']
            facts['lifecycle'] = dict(facts['lifecycle'])
            facts['lifecycle']['fact_hashes_match'] = False
    except Exception as error:
        status = 'ERROR'
        save(out / 'collection-error.json', {'type': type(error).__name__, 'message': str(error)})
        capture_failure_logs(out)
    finally:
        if args.control == 'none':
            cleanup = cleanup_lab(out)
            facts.setdefault('cleanup', {}).update(cleanup)
            facts['cleanup']['research_directory_absent'] = not (
                ROOT / '.artifacts' / 'research' / 'rocketmq-client-go-v2.1.2').exists()

    facts['source_sha'] = git('rev-parse', 'HEAD')
    facts['source_clean'] = not bool(git('status', '--porcelain'))
    save(out / 'facts.json', facts)
    metadata = {
        'schema_version': '0.1', 'canonicalization_profile': 'veritrail-json-c14n/1',
        'plan_digest': plan['seal']['digest'], 'observation_spec_digest': observation_spec_digest(spec),
        'request_seal_digest': sha256_json(request), 'collection_session_id': identity,
        'collector_role': 'guihong-m1g-collector', 'coverage': 'COMPLETE' if status == 'COMPLETED' else 'ERROR',
        'normalization_semantics_version': 'guihong-m1g/1.0', 'facts_digest': sha256_json(facts),
    }
    evidence = {'schema_version': '0.1', 'evidence_type': spec['evidence_type'], 'source': 'guihong-m1g/1.0',
                'captured_at': datetime.now(timezone.utc).isoformat(), 'facts': facts,
                'metadata': {'veritrail_observation': metadata}}
    save(out / 'evidence.json', evidence)
    report = create_acceptance_bundle(plan=plan, evidence_paths=[out / 'evidence.json'], output=out / 'bundle',
                                      acceptance_id=identity, execution_status=status)
    expected = 'PASS' if args.control == 'none' else 'FAIL'
    summary = {'identity': identity, 'source_sha': source, 'execution_status': report['execution_status'],
               'verdict': report['verdict'], 'expected': expected, 'control': args.control,
               'boundary': 'GO_RUNTIME_PREFLIGHT_ONLY', 'bundle': str((out / 'bundle').relative_to(ROOT)),
               'public_core_version': version('veritrail')}
    save(out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report['verdict'] == expected else 1


if __name__ == '__main__':
    sys.exit(main())
