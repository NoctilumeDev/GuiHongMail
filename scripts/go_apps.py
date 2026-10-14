"""Build and own the three native Go services without touching global tool state."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid

import apps
import lab

GO = Path('D:/DevTools/Go/go1.27.2/bin/go.exe')
PYTHON = Path('D:/python-3.10.6/python.exe')
NPM = Path('D:/Node.js/current/npm.cmd')
PORTS = {'mailbox': 18080, 'ingress': 18081, 'delivery': 18082}
COMMANDS = {'mailbox': './cmd/mailbox', 'ingress': './cmd/ingress', 'delivery': './cmd/delivery'}
TOPICS = ('guihong_mail_send_v1', 'guihong_ingress_accepted_v1')
CONSUMER_GROUPS = ('guihong_mailbox_import_v1', 'guihong_delivery_v1')
PROCESSES = lab.LAB / 'go-applications'
process_identity = apps.process_identity
tcp_server_owners = apps.tcp_server_owners


def environment(network=False):
    env = dict(os.environ)
    for name in list(env):
        if name.lower() in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'pythonpath', 'github_token', 'gh_token'}:
            env.pop(name, None)
    env.update(GOCACHE=str(lab.ROOT / '.artifacts/go-cache'),
               GOMODCACHE=str(lab.ROOT / '.artifacts/go-mod'),
               CGO_ENABLED='0', GOFLAGS='-buildvcs=false', NO_PROXY='127.0.0.1,localhost')
    if network:
        env.update(HTTP_PROXY='http://127.0.0.1:7897', HTTPS_PROXY='http://127.0.0.1:7897',
                   GOPROXY='https://proxy.golang.org,direct')
    else:
        env['GOPROXY'] = 'off'
    return env


def private():
    return json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))


def source_sha():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=lab.ROOT, text=True).strip()


def prepare():
    import pymysql
    lab.assert_owned()
    credentials = private()
    observations = []
    for role in lab.SERVICES:
        root = lab.LAB / 'witness' / role
        if root.exists():
            raise RuntimeError('Witness already exists; no reset or implicit adoption')
        database = credentials['database'][role]
        deadline = time.monotonic() + 60
        while True:
            try:
                with pymysql.connect(host='127.0.0.1', port=13306, user=database['user'],
                                     password=database['password'], database=database['schema'], connect_timeout=5) as connection:
                    with connection.cursor() as query:
                        query.execute('SHOW TABLES')
                        tables = query.fetchall()
                        query.execute('SELECT DATABASE(),CURRENT_USER(),VERSION()')
                        binding = query.fetchone()
                break
            except pymysql.err.OperationalError as failure:
                code = failure.args[0] if failure.args else None
                if code not in {2003, 2013} or time.monotonic() >= deadline:
                    raise
                time.sleep(.5)
        if tables:
            raise RuntimeError('Bootstrap refused for a non-virgin schema')
        observations.append({'service': role, 'schema': binding[0], 'database_identity': binding[1],
                             'version': binding[2], 'tables': []})
    for row in observations:
        root = lab.LAB / 'witness' / row['service']
        root.mkdir()
        lab.write_new(root / 'generation.txt', str(uuid.uuid4()) + '\n')
        lab.write_new(root / 'virgin-observation.json', json.dumps(row, indent=2) + '\n')
        lab.write_new(root / 'bootstrap-permit', 'virgin schema observed by explicit owned lab preparation\n')
    print(json.dumps({'prepared': list(PORTS), 'schemas_virgin': True}))


def build():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=lab.ROOT):
        raise RuntimeError('Build identity requires committed clean source')
    source = source_sha()
    root = lab.ROOT / '.artifacts/go-build' / source
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'receipt.json').exists():
        raise RuntimeError('Exact source already has a qualifying immutable Go build receipt')
    attempt = root / ('attempt-' + uuid.uuid4().hex)
    attempt.mkdir()
    log_path = attempt / 'build.log'
    artifacts = []
    with log_path.open('xb') as output:
        frontend = lab.ROOT / 'frontend/web'
        for command in (['ci', '--ignore-scripts', '--proxy', 'http://127.0.0.1:7897',
                         '--https-proxy', 'http://127.0.0.1:7897'], ['test'], ['run', 'build']):
            result = subprocess.run([str(NPM), *command], cwd=frontend, env=environment(network=True),
                                    stdout=output, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode:
                raise RuntimeError('Frontend build gate failed; retained ' + str(log_path))
        result = subprocess.run([str(GO), 'mod', 'download'], cwd=lab.ROOT, env=environment(network=True),
                                stdout=output, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode:
            raise RuntimeError('Go dependency fetch failed; retained ' + str(log_path))
        result = subprocess.run([str(PYTHON), '-B', 'scripts/test_classifier.py'], cwd=lab.ROOT,
                                env=environment(), stdout=output, stderr=subprocess.STDOUT, timeout=30)
        if result.returncode:
            raise RuntimeError('Classifier contract gate failed; retained ' + str(log_path))
        for command in (['test', './...'], ['vet', './...']):
            result = subprocess.run([str(GO), *command], cwd=lab.ROOT, env=environment(),
                                    stdout=output, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode:
                raise RuntimeError('Go build gate failed; retained ' + str(log_path))
        for role, package in COMMANDS.items():
            executable = attempt / (role + '.exe')
            result = subprocess.run([str(GO), 'build', '-trimpath', '-ldflags',
                                     '-s -w -X github.com/NoctilumeDev/GuiHongMail/internal/platform.BuildSource=' + source,
                                     '-o', str(executable), package], cwd=lab.ROOT, env=environment(),
                                    stdout=output, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode:
                raise RuntimeError('Go build failed; retained ' + str(log_path))
            artifacts.append({'role': role, 'path': executable.relative_to(lab.ROOT).as_posix(),
                              'bytes': executable.stat().st_size,
                              'sha256': hashlib.sha256(executable.read_bytes()).hexdigest()})
    static = lab.ROOT / 'backend/mailbox-service/src/main/resources/static'
    frontend_assets = [{'path': path.relative_to(lab.ROOT).as_posix(), 'bytes': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in sorted(static.rglob('*')) if path.is_file()]
    if not frontend_assets:
        raise RuntimeError('Frontend production build emitted no assets')
    receipt = {'schema': 'GuiHongGoBuildReceipt/1.0', 'source_sha': source, 'exit_code': 0,
               'go_version': subprocess.check_output([str(GO), 'version'], text=True).strip(),
               'go_sum_sha256': hashlib.sha256((lab.ROOT / 'go.sum').read_bytes()).hexdigest(),
               'frontend_lock_sha256': hashlib.sha256((lab.ROOT / 'frontend/web/package-lock.json').read_bytes()).hexdigest(),
               'frontend_assets': frontend_assets, 'log': log_path.relative_to(lab.ROOT).as_posix(),
               'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest(), 'artifacts': artifacts}
    receipt_path = root / 'receipt.json'
    lab.write_new(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt))


def verified_build(source):
    root = lab.ROOT / '.artifacts/go-build' / source
    receipt_path = root / 'receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('schema') != 'GuiHongGoBuildReceipt/1.0' or receipt.get('source_sha') != source or receipt.get('exit_code') != 0:
        raise RuntimeError('Go build receipt does not bind exact source')
    if receipt.get('go_sum_sha256') != hashlib.sha256((lab.ROOT / 'go.sum').read_bytes()).hexdigest():
        raise RuntimeError('Go dependency lock changed after build')
    if receipt.get('frontend_lock_sha256') != hashlib.sha256((lab.ROOT / 'frontend/web/package-lock.json').read_bytes()).hexdigest():
        raise RuntimeError('Frontend dependency lock changed after build')
    for row in receipt.get('frontend_assets', []):
        path = (lab.ROOT / row.get('path', '')).resolve()
        static = (lab.ROOT / 'backend/mailbox-service/src/main/resources/static').resolve()
        if (not path.is_relative_to(static) or path.stat().st_size != row.get('bytes')
                or hashlib.sha256(path.read_bytes()).hexdigest() != row.get('sha256')):
            raise RuntimeError('Frontend asset binding mismatch')
    actual_frontend = {path.relative_to(lab.ROOT).as_posix() for path in static.rglob('*') if path.is_file()}
    receipted_frontend = {row.get('path') for row in receipt.get('frontend_assets', [])}
    if actual_frontend != receipted_frontend or not actual_frontend:
        raise RuntimeError('Frontend asset set mismatch')
    log_path = lab.ROOT / receipt['log']
    if hashlib.sha256(log_path.read_bytes()).hexdigest() != receipt['log_sha256']:
        raise RuntimeError('Go build log digest mismatch')
    artifacts = {}
    for row in receipt.get('artifacts', []):
        role = row.get('role')
        path = (lab.ROOT / row.get('path', '')).resolve()
        if (role not in COMMANDS or role in artifacts or not path.is_relative_to(root.resolve())
                or path.name != str(role) + '.exe' or path.stat().st_size != row.get('bytes')):
            raise RuntimeError('Unexpected Go artifact binding')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row.get('sha256'):
            raise RuntimeError('Go artifact digest mismatch')
        artifacts[role] = {'path': path, 'sha256': digest}
    if set(artifacts) != set(COMMANDS):
        raise RuntimeError('Go artifact set mismatch')
    return receipt_path, artifacts


def archive_inactive(record, role):
    previous = json.loads(record.read_text(encoding='utf-8'))
    if previous.get('lab_id') != lab.load()['id'] or previous.get('role') != role:
        raise RuntimeError('Prior process record ownership changed')
    current = apps.process_identity(previous['pid'])
    expected = {key: previous[key] for key in ('creation_ticks', 'executable')}
    if current == expected:
        raise RuntimeError('Prior exact owned PID remains active')
    record.rename(PROCESSES / (role + '-inactive-' + uuid.uuid4().hex + '.json'))


def owned_process(role):
    record = PROCESSES / (role + '.json')
    if not record.is_file():
        raise RuntimeError('No owned Go process record for ' + role)
    owned = json.loads(record.read_text(encoding='utf-8'))
    current = apps.process_identity(owned['pid'])
    executable = (lab.ROOT / owned['artifact']).resolve()
    if (owned.get('lab_id') != lab.load()['id'] or owned.get('role') != role or current is None
            or current != {key: owned[key] for key in ('creation_ticks', 'executable')}
            or Path(current['executable']).resolve() != executable):
        raise RuntimeError('Go application process ownership is not current')
    return owned


def owned_http(role, path, method='GET', body=None, headers=None, internal=False, max_bytes=7 * 1024 * 1024):
    owned = owned_process(role)
    connection = http.client.HTTPConnection('127.0.0.1', PORTS[role], timeout=10)
    try:
        connection.connect()
        client_port = connection.sock.getsockname()[1]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            owners = apps.tcp_server_owners(PORTS[role], client_port)
            if owners == {owned['pid']}:
                break
            if owners and owners != {owned['pid']}:
                raise RuntimeError('Connected listener is not the owned Go application')
            time.sleep(.02)
        else:
            raise RuntimeError('Cannot bind connected listener to owned Go application')
        outbound = dict(headers or {})
        if internal:
            outbound.update(Authorization='Bearer ' + private()['internal'][role], **{'X-GuiHong-Service': 'lab'})
        connection.request(method, path, body=body, headers=outbound)
        response = connection.getresponse()
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise RuntimeError('Go application response exceeded limit')
        return response.status, response.headers, raw
    finally:
        connection.close()


def request(role, path, method='GET'):
    status, _, body = owned_http(role, path, method=method, internal=True, max_bytes=1024 * 1024)
    if status < 200 or status >= 300:
        raise RuntimeError('Owned internal request returned HTTP ' + str(status))
    return json.loads(body)


def ensure_mq_bindings():
    state = lab.load()
    candidates = subprocess.check_output(
        [lab.docker(), 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + state['id'],
         '--filter', 'label=com.docker.compose.service=broker'], text=True, encoding='utf-8').split()
    if len(candidates) != 1:
        raise RuntimeError('Exact owned running RocketMQ broker is unavailable')
    broker = candidates[0]
    inspected = json.loads(subprocess.check_output(
        [lab.docker(), 'inspect', broker], text=True, encoding='utf-8'))[0]
    labels = inspected['Config'].get('Labels') or {}
    if labels.get('guihong.owner') != state['id'] or labels.get('com.docker.compose.service') != 'broker':
        raise RuntimeError('RocketMQ broker ownership changed before group provisioning')
    log_path = PROCESSES / ('mq-bindings-' + uuid.uuid4().hex + '.log')
    with log_path.open('xb') as output:
        for topic in TOPICS:
            result = subprocess.run(
                [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin',
                 'updateTopic', '-n', 'namesrv:9876', '-b', '127.0.0.1:20911', '-t', topic,
                 '-r', '1', '-w', '1'], stdout=output, stderr=subprocess.STDOUT, timeout=30)
            if result.returncode:
                raise RuntimeError('RocketMQ topic provisioning failed; retained ' + str(log_path))
            result = subprocess.run(
                [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin',
                 'topicRoute', '-n', 'namesrv:9876', '-t', topic],
                stdout=output, stderr=subprocess.STDOUT, timeout=30)
            if result.returncode:
                raise RuntimeError('RocketMQ topic route readback failed; retained ' + str(log_path))
        for group in CONSUMER_GROUPS:
            result = subprocess.run(
                [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin',
                 'updateSubGroup', '-n', 'namesrv:9876', '-b', '127.0.0.1:20911', '-g', group],
                stdout=output, stderr=subprocess.STDOUT, timeout=30)
            if result.returncode:
                raise RuntimeError('RocketMQ consumer group provisioning failed; retained ' + str(log_path))
    return log_path


def start(database_ports=None, roles=None):
    lab.assert_owned()
    roles = tuple(roles or lab.SERVICES)
    if not roles or len(set(roles)) != len(roles) or any(role not in lab.SERVICES for role in roles):
        raise RuntimeError('Invalid Go application role selection')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=lab.ROOT):
        raise RuntimeError('Application startup requires committed clean source')
    if lab.memory()['used_bytes'] > 14 * 1024 ** 3:
        raise RuntimeError('Host memory stop line reached before app startup')
    source = source_sha()
    receipt_path, artifacts = verified_build(source)
    credentials = private()
    database_ports = database_ports or {}
    PROCESSES.mkdir(exist_ok=True)
    group_log = ensure_mq_bindings()
    print(json.dumps({'topics': list(TOPICS), 'consumer_groups': list(CONSUMER_GROUPS), 'log': str(group_log)}))
    for role in roles:
        record = PROCESSES / (role + '.json')
        if record.exists():
            archive_inactive(record, role)
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', PORTS[role])) == 0:
                raise RuntimeError('Unknown listener on required Go application port')
        database = credentials['database'][role]
        storage = credentials['storage'][role]
        env = environment()
        env.update(GUIHONG_WITNESS_ROOT=str(lab.LAB / 'witness' / role),
                   GUIHONG_INTERNAL_TOKEN=credentials['internal'][role],
                   GUIHONG_INTERNAL_MAILBOX_TOKEN=credentials['internal']['mailbox'],
                   GUIHONG_INTERNAL_INGRESS_TOKEN=credentials['internal']['ingress'],
                   GUIHONG_INTERNAL_DELIVERY_TOKEN=credentials['internal']['delivery'],
                   GUIHONG_DB_DSN=f"{database['user']}:{database['password']}@tcp(127.0.0.1:{database_ports.get(role, 13306)})/{database['schema']}?parseTime=true&timeout=3s&readTimeout=10s&writeTimeout=10s&interpolateParams=true",
                   GUIHONG_S3_ENDPOINT='http://127.0.0.1:19833', GUIHONG_S3_BUCKET=storage['bucket'],
                   GUIHONG_S3_KEY=storage['access_key'], GUIHONG_S3_SECRET=storage['secret_key'],
                   GUIHONG_NAMESRV='127.0.0.1:19876', GUIHONG_BROKER='127.0.0.1:20911')
        if role == 'mailbox':
            env.update(GUIHONG_CLASSIFIER_PYTHON=str(PYTHON.resolve()),
                       GUIHONG_CLASSIFIER_SCRIPT=str((lab.ROOT / 'algorithm/classifier.py').resolve()))
        log_path = PROCESSES / (role + '-' + uuid.uuid4().hex + '.log')
        with log_path.open('xb') as output:
            process = subprocess.Popen([str(artifacts[role]['path'])], cwd=lab.ROOT, env=env,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        identity = apps.process_identity(process.pid)
        if identity is None:
            raise RuntimeError('Go application exited before PID binding')
        lab.write_new(record, json.dumps({'lab_id': lab.load()['id'], 'role': role, 'pid': process.pid, **identity,
                                          'source_sha': source, 'build_receipt': str(receipt_path),
                                          'artifact': artifacts[role]['path'].relative_to(lab.ROOT).as_posix(),
                                          'artifact_sha256': artifacts[role]['sha256'], 'log': str(log_path)}, indent=2) + '\n')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if apps.process_identity(process.pid) != identity:
                raise RuntimeError('Go application exited; original log retained')
            try:
                status, _, raw = owned_http(role, '/internal/identity', internal=True)
                actual = json.loads(raw)
                if status != 200 or actual.get('source_sha') != source or actual.get('service') != role:
                    raise RuntimeError('Installed Go application/source binding mismatch')
                print(json.dumps({'started': role, 'pid': process.pid, 'identity': actual}))
                break
            except (OSError, http.client.HTTPException):
                time.sleep(.5)
        else:
            raise RuntimeError('Go application did not become identifiable within 60s')


def stop(roles=None):
    if not PROCESSES.exists():
        return
    roles = tuple(roles or lab.SERVICES)
    if not roles or len(set(roles)) != len(roles) or any(role not in lab.SERVICES for role in roles):
        raise RuntimeError('Invalid Go application role selection')
    for role in reversed(lab.SERVICES):
        if role not in roles:
            continue
        record = PROCESSES / (role + '.json')
        if not record.exists():
            continue
        try:
            owned = owned_process(role)
        except RuntimeError:
            continue
        graceful = True
        try:
            owned_http(role, '/internal/drain', method='POST', internal=True)
            owned_http(role, '/internal/shutdown', method='POST', internal=True)
        except Exception:
            graceful = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if apps.process_identity(owned['pid']) is None:
                print(json.dumps({'stopped': role, 'pid': owned['pid'], 'mode': 'graceful' if graceful else 'exited'}))
                break
            if not graceful:
                break
            time.sleep(.25)
        else:
            graceful = False
        if apps.process_identity(owned['pid']) is not None:
            current = owned_process(role)
            os.kill(current['pid'], signal.SIGTERM)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if apps.process_identity(current['pid']) is None:
                    print(json.dumps({'stopped': role, 'pid': current['pid'], 'mode': 'forced-owned-pid'}))
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('Exact owned Go PID did not exit after cleanup')


def status():
    for role in lab.SERVICES:
        try:
            code, _, raw = owned_http(role, '/health/ready')
            print(json.dumps({'role': role, 'status': code, 'readiness': json.loads(raw)}))
        except Exception as failure:
            print(json.dumps({'role': role, 'error': type(failure).__name__}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'build', 'start', 'stop', 'status'])
    parser.add_argument('--role', action='append', choices=lab.SERVICES)
    arguments = parser.parse_args()
    if arguments.action in {'start', 'stop'}:
        globals()[arguments.action](roles=arguments.role)
    elif arguments.role:
        raise RuntimeError('--role is only valid for start or stop')
    else:
        globals()[arguments.action]()
