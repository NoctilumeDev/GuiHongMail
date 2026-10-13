"""Collect and seal the finite Go M3 SMTP and delivery candidate evidence."""
import argparse
import base64
from datetime import datetime, timezone
from email import policy as email_policy
from email.parser import BytesParser
import hashlib
import http.client
import json
from pathlib import Path
import smtplib
import socket
import subprocess
import threading
import time
import uuid
from http.cookies import SimpleCookie

import boto3
from botocore.config import Config
import pymysql
from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json

import go_apps
import lab

ROOT = lab.ROOT
ORIGIN = 'http://127.0.0.1:18080'
PYTHON = ROOT / '.artifacts/lab-env/Scripts/python.exe'


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def wait_until(label, predicate, timeout=30, interval=.2):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (ConnectionError, OSError, pymysql.MySQLError, http.client.HTTPException, KeyError, TypeError) as failure:
            last = type(failure).__name__ + ': ' + str(failure)
        time.sleep(interval)
    raise RuntimeError(f'timed out waiting for {label}; last={last!r}')


class API:
    def __init__(self):
        self.cookie = ''
        self.csrf = ''

    def request(self, method, path, value=None, *, headers=None, content_type='application/json', raw=None, timeout=20):
        outbound = dict(headers or {})
        if self.cookie:
            outbound['Cookie'] = 'guihong_session=' + self.cookie
        if method not in {'GET', 'HEAD'}:
            outbound['Origin'] = ORIGIN
            if self.csrf:
                outbound['X-GuiHong-CSRF'] = self.csrf
        body = raw
        if value is not None:
            body = json.dumps(value).encode()
        if body is not None:
            outbound['Content-Type'] = content_type
        connection = http.client.HTTPConnection('127.0.0.1', 18080, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=outbound)
            response = connection.getresponse()
            data = response.read(7 * 1024 * 1024)
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def login(self, address, password):
        status, headers, raw = self.request('POST', '/api/auth/login', {'address': address, 'password': password})
        if status != 200:
            raise RuntimeError(f'login failed: {status} {raw.decode(errors="replace")}')
        cookie = SimpleCookie(); cookie.load(headers['Set-Cookie'])
        self.cookie = cookie['guihong_session'].value
        body = json.loads(raw); self.csrf = body['csrf']
        return body['user']

    def json(self, method, path, value=None, *, expected=(200,), headers=None):
        status, response_headers, raw = self.request(method, path, value, headers=headers)
        body = json.loads(raw) if raw else None
        if status not in expected:
            raise RuntimeError(f'{method} {path} returned {status}: {body}')
        return status, response_headers, body

    def upload(self, path, filename, data, media='text/plain'):
        boundary = 'GuiHong' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: {media}\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', path, content_type='multipart/form-data; boundary=' + boundary, raw=body)


def internal(role, method, path, body=None, expected=(200,)):
    raw = json.dumps(body).encode() if body is not None else None
    status, headers, data = go_apps.owned_http(role, path, method=method, body=raw,
        headers={'Content-Type': 'application/json'}, internal=True)
    parsed = json.loads(data) if data else None
    if status not in expected:
        raise RuntimeError(f'{role} internal {method} {path}: {status} {parsed}')
    return status, headers, parsed


def connect(role, *, root=False, port=13306):
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    if root:
        return pymysql.connect(host='127.0.0.1', port=port, user='root',
            password=(lab.LAB / 'mysql-root').read_text(encoding='utf-8').strip(),
            database=secrets['database'][role]['schema'], connect_timeout=5, autocommit=True)
    database = secrets['database'][role]
    return pymysql.connect(host='127.0.0.1', port=port, user=database['user'], password=database['password'],
        database=database['schema'], connect_timeout=5, autocommit=True)


def rows(role, statement, arguments=()):
    with connect(role) as connection, connection.cursor(pymysql.cursors.DictCursor) as query:
        query.execute(statement, arguments)
        result = []
        for row in query.fetchall():
            result.append({key: (value.isoformat() if hasattr(value, 'isoformat') else
                                 value.decode() if isinstance(value, bytes) else value)
                           for key, value in row.items()})
        return result


def execute(role, statement, arguments=()):
    with connect(role) as connection, connection.cursor() as query:
        return query.execute(statement, arguments)


def scalar(role, statement, arguments=()):
    result = rows(role, statement, arguments)
    return next(iter(result[0].values())) if result else None


def account(name, address, password, display, *, enabled=True):
    _, _, body = internal('mailbox', 'POST', '/internal/accounts',
        {'address': address, 'password': password, 'displayName': display})
    if not enabled:
        execute('mailbox', 'UPDATE accounts SET enabled=0,auth_epoch=auth_epoch+1 WHERE account_id=%s', (body['account_id'],))
    return body['account_id']


def draft(api, subject, to, *, cc=None, bcc=None, text='归鸿 M3 正文', html='<p>归鸿 M3 正文</p>', mode='COMPOSE', source=None):
    _, _, value = api.json('POST', '/api/mailbox/drafts', {'subject': subject, 'textBody': text,
        'htmlBody': html, 'to': to, 'cc': cc or [], 'bcc': bcc or [], 'mode': mode,
        'sourceContentId': source}, expected=(201,))
    return value


def send(api, value, key, *, expected=(202,)):
    return api.json('POST', f"/api/mailbox/drafts/{value['id']}/send", {'version': value['version']},
                    headers={'Idempotency-Key': key}, expected=expected)[2]


def send_status(api, intent):
    return api.json('GET', '/api/mailbox/send-intents/' + intent)[2]


def wait_scope(api, intent, predicate, label, timeout=40):
    return wait_until(label, lambda: (lambda value: value if value.get('delivery') and predicate(value['delivery']) else None)(send_status(api, intent)), timeout)


def inbox_subject(api, subject, folder='INBOX', timeout=40):
    def find():
        page = api.json('GET', f'/api/mailbox/messages?folder={folder}&size=50')[2]
        return next((item for item in page['items'] if item['subject'] == subject), None)
    return wait_until('mailbox subject ' + subject, find, timeout)


def container(service):
    state = lab.load()
    result = subprocess.check_output([lab.docker(), 'ps', '-aq',
        '--filter', 'label=com.docker.compose.project=' + state['id'],
        '--filter', 'label=com.docker.compose.service=' + service], text=True).split()
    if len(result) != 1:
        raise RuntimeError('expected one owned ' + service + ' container')
    inspected = json.loads(subprocess.check_output([lab.docker(), 'inspect', result[0]], text=True))[0]
    if (inspected['Config'].get('Labels') or {}).get('guihong.owner') != state['id']:
        raise RuntimeError('container ownership mismatch')
    return result[0]


def docker_container(action, service):
    identity = container(service)
    subprocess.run([lab.docker(), action, identity], check=True, timeout=30, capture_output=True)
    return identity


def mq_send(payload, key, out):
    broker = container('broker')
    command = [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin',
               'sendMessage', '-n', 'namesrv:9876', '-t', 'guihong_mail_send_v1', '-k', key,
               '-p', payload]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
    save(out, {'command': command[3:7] + ['<bound-payload>'], 'exit_code': result.returncode,
               'stdout': result.stdout, 'stderr': result.stderr, 'payload_sha256': hashlib.sha256(payload.encode()).hexdigest()})
    if result.returncode:
        raise RuntimeError('mqadmin replay failed; retained ' + str(out))


def smtp_transaction(raw, recipients, *, sender='outside@example.test', port=12525):
    result = {'mail': None, 'rcpt': [], 'data': None, 'exception': None}
    client = smtplib.SMTP('127.0.0.1', port, timeout=15)
    try:
        client.ehlo()
        result['mail'] = client.mail(sender)[0]
        for recipient in recipients:
            code, message = client.rcpt(recipient)
            result['rcpt'].append([recipient, code, message.decode(errors='replace')])
        if any(item[1] == 250 for item in result['rcpt']):
            code, message = client.data(raw)
            result['data'] = [code, message.decode(errors='replace')]
    except (smtplib.SMTPException, OSError) as failure:
        result['exception'] = type(failure).__name__ + ': ' + str(failure)
    finally:
        try: client.close()
        except OSError: pass
    return result


def smtp_open(recipients, *, sender='outside@example.test'):
    client = smtplib.SMTP('127.0.0.1', 12525, timeout=15)
    client.ehlo(); mail = client.mail(sender)
    rcpt = [(recipient, *client.rcpt(recipient)) for recipient in recipients]
    return client, {'mail': mail[0], 'rcpt': [[address, code, message.decode(errors='replace')] for address, code, message in rcpt]}


def raw_message(subject, marker='M3', size=0):
    body = marker + ' 中文正文\r\n' + ('x' * size)
    return (f'From: outside@example.test\r\nTo: alice@guihong.test\r\nSubject: {subject}\r\n'
            f'Message-ID: <{uuid.uuid4()}@example.test>\r\nMIME-Version: 1.0\r\n'
            f'Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n').encode()


def start_controlled(out, policy):
    policy_path = out / 'smtp-policy.json'; transcript = out / 'smtp-transcript.jsonl'
    save(policy_path, policy)
    process = subprocess.Popen([str(PYTHON), '-B', str(ROOT / 'scripts/controlled_smtp.py'),
        '--policy', str(policy_path), '--output', str(transcript)], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    line = wait_until('controlled SMTP', lambda: process.stdout.readline().strip() if process.stdout else None, 10)
    if not json.loads(line).get('ready'):
        raise RuntimeError('controlled SMTP failed readiness')
    return process, transcript


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


def snapshots():
    result = {}
    result['mailbox'] = {
        'intents': rows('mailbox', 'SELECT intent_id,dispatch_scope_id,raw_sha256,raw_size,state FROM send_intents ORDER BY intent_id'),
        'imports': rows('mailbox', 'SELECT spool_id,recipient_account_id,raw_sha256,entry_id FROM ingress_import_receipts ORDER BY spool_id,recipient_account_id'),
        'entries': rows('mailbox', 'SELECT account_id,content_id,folder FROM mailbox_entries ORDER BY account_id,content_id')}
    result['ingress'] = {
        'spools': rows('ingress', 'SELECT spool_id,raw_sha256,raw_size,state FROM accepted_spools ORDER BY spool_id'),
        'outbox': rows('ingress', 'SELECT aggregate_id,message_key,published_at FROM ingress_outbox ORDER BY aggregate_id')}
    result['delivery'] = {
        'scopes': rows('delivery', 'SELECT scope_id,source_intent_id,state,ever_started FROM dispatch_scopes ORDER BY scope_id'),
        'jobs': rows('delivery', 'SELECT job_id,scope_id,recipient,state,attempt_count FROM delivery_jobs ORDER BY job_id'),
        'attempts': rows('delivery', 'SELECT attempt_id,job_id,epoch_no,last_stage,data_submitted,smtp_code,outcome,evidence_sha256,duplicate_risk_ack,prior_attempt_id FROM delivery_attempts ORDER BY job_id,epoch_no')}
    return result


def collect(out):
    source = git('rev-parse', 'HEAD')
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    facts = {'source_sha': source, 'cases': {}, 'http': {}, 'smtp': {}, 'database': {}, 'storage': {},
             'mq': {}, 'browser': {}, 'restart': {}, 'resource': {}, 'boundary': 'M3_SMTP_AND_DELIVERY_ONLY'}
    ids = {}
    for name, display in [('alice', '甲用户'), ('bob', '乙用户')]:
        ids[name] = account(name, secrets['accounts'][name]['address'], secrets['accounts'][name]['password'], display)
    ids['carol'] = account('carol', 'carol@guihong.test', 'Carol-M3-password', '丙用户')
    ids['disabled'] = account('disabled', 'disabled@guihong.test', 'Disabled-M3-password', '停用用户', enabled=False)
    extras = []
    for index in range(11):
        address = f'limit{index:02d}@guihong.test'; extras.append(address)
        ids['limit' + str(index)] = account('limit' + str(index), address, f'Limit-{index}-password', f'限额{index}')

    alice, bob, carol = API(), API(), API()
    alice.login(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
    bob.login(secrets['accounts']['bob']['address'], secrets['accounts']['bob']['password'])
    carol.login('carol@guihong.test', 'Carol-M3-password')

    # M3-04: a committed outbox survives broker unavailability and publishes after restart.
    docker_container('pause', 'broker')
    recovery_subject = 'M3 Outbox 恢复 ' + uuid.uuid4().hex[:8]
    recovery_draft = draft(alice, recovery_subject, ['bob@guihong.test'])
    recovery_intent = send(alice, recovery_draft, 'm3-outbox-' + uuid.uuid4().hex)
    recovery_pending = scalar('mailbox', 'SELECT published_at IS NULL FROM mailbox_outbox WHERE aggregate_id=%s', (recovery_intent['id'],)) == 1
    go_apps.stop(roles=['mailbox']); docker_container('unpause', 'broker'); go_apps.start(roles=['mailbox'])
    recovery = wait_scope(alice, recovery_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'outbox recovery', 50)
    recovery_jobs = scalar('delivery', 'SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=%s', (recovery_intent['dispatchScopeId'],))
    recovery_payload = rows('mailbox', 'SELECT payload,message_key FROM mailbox_outbox WHERE aggregate_id=%s', (recovery_intent['id'],))[0]
    before_replay = scalar('delivery', 'SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=%s', (recovery_intent['dispatchScopeId'],))
    mq_send(recovery_payload['payload'], recovery_payload['message_key'], out / 'send-outbox-replay.json')
    time.sleep(2)
    after_replay = scalar('delivery', 'SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=%s', (recovery_intent['dispatchScopeId'],))

    # M3-01/02/03/05: immutable send, idempotency, BCC and full local closed loop.
    subject = 'M3 闭环 ' + uuid.uuid4().hex[:8]
    original = draft(alice, subject, ['bob@guihong.test'], bcc=['carol@guihong.test'],
        text='中文正文 M3-IMMUTABLE', html='<p>中文正文 <b>M3-IMMUTABLE</b></p>')
    attachment_bytes = '归鸿附件-M3'.encode()
    upload_status, _, upload_raw = alice.upload(f"/api/mailbox/drafts/{original['id']}/attachments?version={original['version']}",
                                                '归鸿证据.txt', attachment_bytes)
    attached = json.loads(upload_raw)
    if upload_status != 201:
        raise RuntimeError('M3 attachment upload failed')
    send_key = 'm3-send-' + uuid.uuid4().hex
    receipts = [send(alice, attached, send_key) for _ in range(10)]
    intent = receipts[0]
    immutable_conflict = alice.request('POST', f"/api/mailbox/drafts/{recovery_draft['id']}/send",
        {'version': recovery_draft['version']}, headers={'Idempotency-Key': send_key})
    closed = wait_scope(alice, intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'closed loop delivery', 60)
    bob_entry = inbox_subject(bob, subject, timeout=60); carol_entry = inbox_subject(carol, subject, timeout=60)
    alice_sent = inbox_subject(alice, subject, folder='SENT')
    bob_detail = bob.json('GET', '/api/mailbox/messages/' + bob_entry['entryId'])[2]
    carol_detail = carol.json('GET', '/api/mailbox/messages/' + carol_entry['entryId'])[2]
    alice_detail = alice.json('GET', '/api/mailbox/messages/' + alice_sent['entryId'])[2]
    raw_status, raw_headers, raw = go_apps.owned_http('mailbox', '/internal/send-intents/' + intent['id'] + '/raw', internal=True)
    parsed = BytesParser(policy=email_policy.default).parsebytes(raw)
    raw_digest = hashlib.sha256(raw).hexdigest()
    message_attachment = next(parsed.iter_attachments()).get_payload(decode=True)
    draft_missing = alice.request('GET', '/api/mailbox/drafts/' + original['id'])[0]

    # Bob replies through the same real path; wire threading headers are read back from S3-backed raw.
    reply = bob.json('POST', f"/api/mailbox/messages/{bob_entry['entryId']}/drafts?mode=REPLY", expected=(201,))[2]
    reply_key = 'm3-reply-' + uuid.uuid4().hex
    reply_intent = send(bob, reply, reply_key)
    wait_scope(bob, reply_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'reply delivery', 60)
    reply_entry = inbox_subject(alice, reply['subject'], timeout=60)
    _, _, reply_raw = go_apps.owned_http('mailbox', '/internal/send-intents/' + reply_intent['id'] + '/raw', internal=True)
    reply_parsed = BytesParser(policy=email_policy.default).parsebytes(reply_raw)

    # M3-06: responsibility boundaries reject before durable side effects.
    before_rejects = {'spools': scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools'),
                      'entries': scalar('mailbox', 'SELECT COUNT(*) FROM mailbox_entries')}
    relay = smtp_transaction(raw_message('relay'), ['outside@example.test'])
    unknown_local = smtp_transaction(raw_message('unknown'), ['nobody@guihong.test'])
    disabled = smtp_transaction(raw_message('disabled'), ['disabled@guihong.test'])
    client, limit = smtp_open(extras)
    try: client.rset(); client.quit()
    except (smtplib.SMTPException, OSError): client.close()
    oversized = smtp_transaction(raw_message('oversized', size=5 * 1024 * 1024 + 1024), ['alice@guihong.test'])
    after_rejects = {'spools': scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools'),
                     'entries': scalar('mailbox', 'SELECT COUNT(*) FROM mailbox_entries')}

    # M3-07a: S3 disappears after RCPT; DATA must not receive 250.
    s3_client, s3_prefix = smtp_open(['alice@guihong.test'])
    s3_spools_before = scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools')
    docker_container('pause', 'seaweedfs')
    try:
        try:
            code, message = s3_client.data(raw_message('s3-failure'))
            s3_failure = {'prefix': s3_prefix, 'data': [code, message.decode(errors='replace')]}
        except (smtplib.SMTPException, OSError) as failure:
            s3_failure = {'prefix': s3_prefix, 'exception': type(failure).__name__ + ': ' + str(failure)}
    finally:
        try: s3_client.close()
        except OSError: pass
        docker_container('unpause', 'seaweedfs')
    def storage_ready():
        with socket.create_connection(('127.0.0.1', 19833), timeout=1):
            return True
    wait_until('SeaweedFS recovery', storage_ready, 20)
    s3_spools_after = scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools')

    # M3-08: accepted spool remains while Mailbox is down, imports once after recovery, and replay is idempotent.
    retained_client, retained_prefix = smtp_open(['alice@guihong.test'])
    go_apps.stop(roles=['mailbox'])
    retained_subject = 'M3 保留 ' + uuid.uuid4().hex[:8]
    try:
        code, message = retained_client.data(raw_message(retained_subject, 'RETAINED'))
        retained = {'prefix': retained_prefix, 'data': [code, message.decode(errors='replace')]}
    except (smtplib.SMTPException, OSError) as failure:
        retained = {'prefix': retained_prefix, 'exception': type(failure).__name__ + ': ' + str(failure)}
    finally:
        try: retained_client.close()
        except OSError: pass
    retained_spool = wait_until('retained accepted spool', lambda: (lambda item: item if item and item['state'] == 'ACCEPTED' else None)(
        next(iter(rows('ingress', 'SELECT spool_id,state,raw_sha256 FROM accepted_spools ORDER BY accepted_at DESC LIMIT 1')), None)), 20)
    go_apps.start(roles=['mailbox'])
    inbox_subject(alice, retained_subject, timeout=60)
    wait_until('retained spool ack', lambda: scalar('ingress', 'SELECT state FROM accepted_spools WHERE spool_id=%s', (retained_spool['spool_id'],)) == 'GC_ELIGIBLE', 40)
    retained_event = rows('ingress', 'SELECT payload,message_key FROM ingress_outbox WHERE aggregate_id=%s', (retained_spool['spool_id'],))[0]
    retained_counts_before = {'receipts': scalar('mailbox', 'SELECT COUNT(*) FROM ingress_import_receipts WHERE spool_id=%s', (retained_spool['spool_id'],)),
                              'members': scalar('mailbox', 'SELECT COUNT(*) FROM mailbox_entries e JOIN ingress_import_receipts r ON r.entry_id=e.entry_id WHERE r.spool_id=%s', (retained_spool['spool_id'],))}
    broker = container('broker')
    replay_command = [lab.docker(), 'exec', broker, '/home/rocketmq/rocketmq-5.5.0/bin/mqadmin', 'sendMessage',
                      '-n', 'namesrv:9876', '-t', 'guihong_ingress_accepted_v1', '-k', retained_event['message_key'], '-p', retained_event['payload']]
    replay_result = subprocess.run(replay_command, capture_output=True, text=True, timeout=30)
    save(out / 'ingress-event-replay.json', {'exit_code': replay_result.returncode, 'stdout': replay_result.stdout,
         'stderr': replay_result.stderr, 'payload_sha256': hashlib.sha256(retained_event['payload'].encode()).hexdigest()})
    if replay_result.returncode: raise RuntimeError('ingress event replay failed')
    time.sleep(2)
    retained_counts_after = {'receipts': scalar('mailbox', 'SELECT COUNT(*) FROM ingress_import_receipts WHERE spool_id=%s', (retained_spool['spool_id'],)),
                             'members': scalar('mailbox', 'SELECT COUNT(*) FROM mailbox_entries e JOIN ingress_import_receipts r ON r.entry_id=e.entry_id WHERE r.spool_id=%s', (retained_spool['spool_id'],))}

    # M3-07b: drop the armed COMMIT response after it reached MySQL; SMTP must withhold 250 and restart must reconcile.
    go_apps.stop(roles=['ingress'])
    proxy_root = lab.LAB / ('m3-commit-proxy-' + uuid.uuid4().hex)
    proxy = subprocess.Popen([str(PYTHON), '-B', str(ROOT / 'scripts/mysql_commit_proxy.py'), '--port', '23306', '--root', str(proxy_root)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    wait_until('commit proxy readiness', lambda: (proxy_root / 'ready').is_file(), 10)
    go_apps.start(database_ports={'ingress': 23306}, roles=['ingress'])
    commit_client, commit_prefix = smtp_open(['alice@guihong.test'])
    commit_raw = raw_message('M3 COMMIT UNKNOWN', 'COMMIT-UNKNOWN')
    commit_digest = hashlib.sha256(commit_raw).hexdigest()
    commit_spools_before = scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools')
    (proxy_root / 'arm').write_text('armed\n', encoding='utf-8')
    try:
        try:
            code, message = commit_client.data(commit_raw)
            commit_failure = {'prefix': commit_prefix, 'data': [code, message.decode(errors='replace')]}
        except (smtplib.SMTPException, OSError) as failure:
            commit_failure = {'prefix': commit_prefix, 'exception': type(failure).__name__ + ': ' + str(failure)}
    finally:
        try: commit_client.close()
        except OSError: pass
    wait_until('commit fault firing', lambda: (proxy_root / 'fired').is_file(), 15)
    go_apps.stop(roles=['ingress']); (proxy_root / 'stop').write_text('stop\n', encoding='utf-8'); stop_process(proxy)
    go_apps.start(roles=['ingress'])
    commit_reconciled = wait_until('commit-unknown spool reconciliation', lambda: scalar('ingress',
        'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (commit_digest,)), 30)
    commit_spools_after = scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools')
    commit_fault_files = {path.name: json.loads(path.read_text(encoding='utf-8')) for path in proxy_root.glob('*.json')}

    # Switch the delivery next hop to a policy-controlled server.
    go_apps.stop(roles=['ingress'])
    policy = {'default': {'mode': 'accept'}, 'recipients': {
        'accept@test.invalid': {'mode': 'accept'},
        'temp@test.invalid': {'mode': 'temporary_data', 'failures': 2},
        'perm@test.invalid': {'mode': 'permanent_rcpt'},
        'unknown@test.invalid': {'mode': 'unknown'},
        'hold@test.invalid': {'mode': 'hold', 'seconds': 5},
        'unknown-browser@test.invalid': {'mode': 'unknown'}}}
    controlled = None
    try:
        controlled, transcript_path = start_controlled(out, policy)
        mixed_draft = draft(alice, 'M3 混合结果 ' + uuid.uuid4().hex[:8],
            ['accept@test.invalid', 'temp@test.invalid', 'perm@test.invalid', 'unknown@test.invalid'])
        mixed_intent = send(alice, mixed_draft, 'm3-mixed-' + uuid.uuid4().hex)
        mixed = wait_scope(alice, mixed_intent['id'], lambda scope: all(item['state'] in
            {'NEXT_HOP_ACCEPTED','PERMANENT_FAILURE','UNKNOWN'} for item in scope['recipients']), 'mixed delivery results', 60)
        mixed_scope = mixed['delivery']
        jobs = {item['recipient']: item for item in mixed_scope['recipients']}
        unknown_attempt = jobs['unknown@test.invalid']['attempts'][0]
        observation_start = time.monotonic(); time.sleep(4)
        unknown_stable = send_status(alice, mixed_intent['id'])['delivery']

        unconfirmed = alice.request('POST', '/api/mailbox/send-intents/' + mixed_intent['id'] + '/retry-unknown',
            {'confirmDuplicateRisk': False, 'recipient': 'unknown@test.invalid'}, headers={'Idempotency-Key': 'm3-unconfirmed'})
        retry_key = 'm3-risk-' + uuid.uuid4().hex
        retry_one = alice.json('POST', '/api/mailbox/send-intents/' + mixed_intent['id'] + '/retry-unknown',
            {'confirmDuplicateRisk': True, 'recipient': 'unknown@test.invalid'}, headers={'Idempotency-Key': retry_key})[2]
        retry_two = alice.json('POST', '/api/mailbox/send-intents/' + mixed_intent['id'] + '/retry-unknown',
            {'confirmDuplicateRisk': True, 'recipient': 'unknown@test.invalid'}, headers={'Idempotency-Key': retry_key})[2]
        retried = wait_scope(alice, mixed_intent['id'], lambda scope: next(item for item in scope['recipients'] if item['recipient']=='unknown@test.invalid')['attemptCount'] == 2,
                             'explicit unknown retry', 30)

        # Cancel-before-claim and duplicate/restart/replay isolation.
        docker_container('pause', 'broker')
        cancel_draft = draft(alice, 'M3 取消 ' + uuid.uuid4().hex[:8], ['cancel@test.invalid'])
        cancel_intent = send(alice, cancel_draft, 'm3-cancel-' + uuid.uuid4().hex)
        cancel_one = alice.json('POST', '/api/mailbox/send-intents/' + cancel_intent['id'] + '/cancel')[2]
        cancel_two = alice.json('POST', '/api/mailbox/send-intents/' + cancel_intent['id'] + '/cancel')[2]
        docker_container('unpause', 'broker')
        time.sleep(3)
        go_apps.stop(roles=['delivery']); go_apps.start(roles=['delivery'])
        cancel_after_restart = send_status(alice, cancel_intent['id'])['delivery']
        cancel_attempts = scalar('delivery', 'SELECT COUNT(*) FROM delivery_attempts a JOIN delivery_jobs j ON j.job_id=a.job_id WHERE j.scope_id=%s', (cancel_intent['dispatchScopeId'],))

        # Worker-first decision.
        hold_draft = draft(alice, 'M3 Worker first ' + uuid.uuid4().hex[:8], ['hold@test.invalid'])
        hold_intent = send(alice, hold_draft, 'm3-hold-' + uuid.uuid4().hex)
        wait_scope(alice, hold_intent['id'], lambda scope: scope['everStarted'], 'worker-first claim', 20)
        worker_cancel = alice.request('POST', '/api/mailbox/send-intents/' + hold_intent['id'] + '/cancel')
        hold_final = wait_scope(alice, hold_intent['id'], lambda scope: scope['recipients'][0]['state']=='NEXT_HOP_ACCEPTED', 'held delivery finish', 20)

        # Real race: the broker resumes while cancellation contends with the first event/claim.
        docker_container('pause', 'broker')
        race_draft = draft(alice, 'M3 Race ' + uuid.uuid4().hex[:8], ['race@test.invalid'])
        race_intent = send(alice, race_draft, 'm3-race-' + uuid.uuid4().hex)
        race_result = {}
        barrier = threading.Barrier(2)
        def cancel_race():
            barrier.wait()
            status, _, raw_value = alice.request('POST', '/api/mailbox/send-intents/' + race_intent['id'] + '/cancel')
            race_result.update(status=status, body=json.loads(raw_value))
        racer = threading.Thread(target=cancel_race); racer.start(); barrier.wait(); docker_container('unpause', 'broker'); racer.join(20)
        if racer.is_alive(): raise RuntimeError('cancel race thread did not finish')
        race_final = wait_until('race terminal observation', lambda: (lambda value: value if value.get('delivery') and
            (value['delivery']['state']=='CANCELLED' or value['delivery']['everStarted']) else None)(send_status(alice, race_intent['id'])), 30)
        race_attempts = scalar('delivery', 'SELECT COUNT(*) FROM delivery_attempts a JOIN delivery_jobs j ON j.job_id=a.job_id WHERE j.scope_id=%s', (race_intent['dispatchScopeId'],))

        # Browser witnesses use the same real UI and state machine.
        docker_container('pause', 'broker')
        cancel_browser_dir = out / 'browser-cancel'
        cancel_browser = subprocess.run(['D:/python-3.10.6/python.exe', '-B', str(ROOT / 'scripts/browser_m3.py'),
            '--output', str(cancel_browser_dir), '--mode', 'cancel'], cwd=ROOT, capture_output=True, text=True, timeout=120)
        docker_container('unpause', 'broker')
        if cancel_browser.returncode: raise RuntimeError('cancel browser failed: ' + cancel_browser.stdout + cancel_browser.stderr)
        unknown_browser_dir = out / 'browser-unknown'
        unknown_browser = subprocess.run(['D:/python-3.10.6/python.exe', '-B', str(ROOT / 'scripts/browser_m3.py'),
            '--output', str(unknown_browser_dir), '--mode', 'unknown'], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if unknown_browser.returncode: raise RuntimeError('unknown browser failed: ' + unknown_browser.stdout + unknown_browser.stderr)
        browser_facts = {'cancel': json.loads((cancel_browser_dir/'browser.json').read_text(encoding='utf-8')),
                         'unknown': json.loads((unknown_browser_dir/'browser.json').read_text(encoding='utf-8'))}
    finally:
        try:
            inspected = json.loads(subprocess.check_output([lab.docker(), 'inspect', container('broker')], text=True))[0]
            if inspected['State'].get('Paused'): docker_container('unpause', 'broker')
        except Exception: pass
        stop_process(controlled)
    go_apps.start(roles=['ingress'])

    transcript = [json.loads(line) for line in transcript_path.read_text(encoding='utf-8').splitlines()]
    controlled_counts = {}
    for event in transcript:
        if event.get('direction') == 'data':
            controlled_counts[event['recipient']] = controlled_counts.get(event['recipient'], 0) + 1

    before_restart = snapshots()
    go_apps.stop(); go_apps.start()
    after_restart = snapshots()

    resource_process = subprocess.run([str(PYTHON), '-B', str(ROOT/'scripts/resource_guard.py'), '--duration', '65', '--runtime', 'go'],
        cwd=ROOT, capture_output=True, text=True, timeout=100)
    if resource_process.returncode:
        raise RuntimeError('resource guard stopped M3 run: ' + resource_process.stdout + resource_process.stderr)
    resource_line = json.loads(resource_process.stdout.strip().splitlines()[-1])
    resource_path = Path(resource_line['evidence'])
    resource_rows = [json.loads(line) for line in resource_path.read_text(encoding='utf-8').splitlines() if line]

    delivery_rows = rows('delivery', 'SELECT j.recipient,j.state,j.attempt_count,a.epoch_no,a.started_at,a.completed_at,a.last_stage,a.data_submitted,a.smtp_code,a.outcome,a.evidence_sha256,a.duplicate_risk_ack,a.prior_attempt_id FROM delivery_jobs j JOIN delivery_attempts a ON a.job_id=j.job_id WHERE j.scope_id=%s ORDER BY j.recipient,a.epoch_no', (mixed_intent['dispatchScopeId'],))
    intent_rows = rows('mailbox', 'SELECT intent_id,draft_id,draft_version,request_key,payload_sha256,dispatch_scope_id,raw_sha256,raw_size,envelope_json FROM send_intents WHERE intent_id=%s', (intent['id'],))
    scope_count = scalar('delivery', 'SELECT COUNT(*) FROM dispatch_scopes WHERE source_intent_id=%s', (intent['id'],))
    job_count = scalar('delivery', 'SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=%s', (intent['dispatchScopeId'],))
    parsed_envelope = json.loads(intent_rows[0]['envelope_json'])
    storage_secret = secrets['storage']['mailbox']
    s3 = boto3.client('s3', endpoint_url='http://127.0.0.1:19833', aws_access_key_id=storage_secret['access_key'],
        aws_secret_access_key=storage_secret['secret_key'], region_name='us-east-1', config=Config(signature_version='s3v4'))
    object_key = scalar('mailbox', 'SELECT o.object_key FROM send_intents s JOIN stored_objects o ON o.object_id=s.raw_object_id WHERE s.intent_id=%s', (intent['id'],))
    stored_raw = s3.get_object(Bucket=storage_secret['bucket'], Key=object_key)['Body'].read()

    facts['http'] = {'idempotent_receipts': receipts, 'immutable_conflict': [immutable_conflict[0], json.loads(immutable_conflict[2])],
        'draft_after_send_status': draft_missing, 'closed_scope': closed['delivery'], 'alice_sent': alice_detail,
        'bob_received': bob_detail, 'carol_received': carol_detail, 'reply_entry': reply_entry,
        'unconfirmed_retry': [unconfirmed[0], json.loads(unconfirmed[2])], 'retry_one': retry_one, 'retry_two': retry_two,
        'cancel': {'first': cancel_one, 'second': cancel_two, 'after_restart': cancel_after_restart},
        'worker_cancel': [worker_cancel[0], json.loads(worker_cancel[2])], 'race': {'decision': race_result, 'final': race_final['delivery'], 'attempts': race_attempts}}
    facts['smtp'] = {'relay': relay, 'unknown_local': unknown_local, 'disabled': disabled, 'limit': limit,
        'oversized': oversized, 's3_failure': s3_failure, 'retained': retained, 'commit_failure': commit_failure,
        'commit_fault_files': commit_fault_files, 'controlled_counts': controlled_counts,
        'unknown_observation_seconds': time.monotonic()-observation_start, 'transcript_file': transcript_path.name,
        'transcript_events': len(transcript)}
    facts['database'] = {'intent': intent_rows[0], 'scope_count': scope_count, 'job_count': job_count,
        'delivery_attempts': delivery_rows, 'recovery': {'pending': recovery_pending, 'jobs': recovery_jobs,
        'before_replay': before_replay, 'after_replay': after_replay, 'scope': recovery['delivery']},
        'rejection_counts': {'before': before_rejects, 'after': after_rejects},
        'retained_spool': retained_spool, 'retained_counts': {'before': retained_counts_before, 'after': retained_counts_after},
        'commit_reconciled': commit_reconciled, 'commit_spools': [commit_spools_before, commit_spools_after],
        's3_failure_spools': [s3_spools_before, s3_spools_after], 'cancel_attempts': cancel_attempts}
    facts['storage'] = {'http_raw_status': raw_status, 'http_raw_digest': raw_headers.get('X-GuiHong-SHA256'),
        'computed_digest': raw_digest, 'stored_digest': hashlib.sha256(stored_raw).hexdigest(),
        'stored_exact': stored_raw == raw, 'attachment_exact': message_attachment == attachment_bytes}
    facts['mq'] = {'send_replay': 'send-outbox-replay.json', 'ingress_replay': 'ingress-event-replay.json'}
    facts['browser'] = browser_facts
    facts['restart'] = {'before_digest': sha256_json(before_restart), 'after_digest': sha256_json(after_restart),
                        'equal': before_restart == after_restart}
    facts['resource'] = {'file': resource_path.name, 'samples': len(resource_rows),
        'full_topology_samples': sum(bool(row['full_topology']) for row in resource_rows),
        'stop_reasons': [row['stop_reason'] for row in resource_rows if row['stop_reason']],
        'max_host_used_bytes': max(row['memory']['used_bytes'] for row in resource_rows),
        'min_container_memory_headroom_ratio': min(c['memory_headroom_ratio'] for row in resource_rows for c in row['containers'] if c['running']),
        'min_container_pid_headroom': min(c['pid_headroom'] for row in resource_rows for c in row['containers'] if c['running'])}

    recipient_kinds_sender = {item['kind'] for item in alice_detail['recipients']}
    recipient_kinds_bob = {item['kind'] for item in bob_detail['recipients']}
    recipient_kinds_carol = {item['kind'] for item in carol_detail['recipients']}
    delivery_by_recipient = {}
    for item in delivery_rows: delivery_by_recipient.setdefault(item['recipient'], []).append(item)
    temp_times = [datetime.fromisoformat(item['started_at']).timestamp() for item in delivery_by_recipient['temp@test.invalid']]
    unknown_rows = delivery_by_recipient['unknown@test.invalid']
    race = race_final['delivery']
    race_valid = ((race['state'] == 'CANCELLED' and race_attempts == 0) or (race['everStarted'] and race_result['status'] == 409))
    facts['cases'] = {
        'M3-01': len({row['id'] for row in receipts}) == 1 and scope_count == 1 and job_count == 2 and immutable_conflict[0] == 409,
        'M3-02': draft_missing == 404 and stored_raw == raw and raw_digest == intent['rawSha256'] and message_attachment == attachment_bytes,
        'M3-03': 'BCC' in recipient_kinds_sender and 'BCC' not in recipient_kinds_bob and 'BCC' not in recipient_kinds_carol and parsed.get('Bcc') is None and any(item['kind']=='BCC' for item in parsed_envelope),
        'M3-04': recovery_pending and recovery_jobs == before_replay == after_replay == 1 and recovery['delivery']['state'] == 'COMPLETED',
        'M3-05': bob_entry and carol_entry and reply_entry and parsed.get_body(('plain',)).get_content().find('M3-IMMUTABLE') >= 0 and reply_parsed.get('In-Reply-To') == parsed.get('Message-ID') and reply_parsed.get('References') == parsed.get('Message-ID'),
        'M3-06': relay['rcpt'][0][1] == 550 and unknown_local['rcpt'][0][1] == 550 and disabled['rcpt'][0][1] == 550 and [item[1] for item in limit['rcpt']] == [250]*10+[452] and oversized.get('data',[0])[0] == 552 and before_rejects == after_rejects,
        'M3-07': s3_failure.get('data',[0])[0] != 250 and s3_spools_before == s3_spools_after and commit_failure.get('data',[0])[0] != 250 and (proxy_root/'fired').is_file() and bool(commit_reconciled) and commit_spools_after == commit_spools_before + 1,
        'M3-08': retained.get('data',[0])[0] == 250 and retained_counts_before == retained_counts_after == {'receipts':1,'members':1} and scalar('ingress','SELECT state FROM accepted_spools WHERE spool_id=%s',(retained_spool['spool_id'],)) == 'GC_ELIGIBLE',
        'M3-09': jobs['accept@test.invalid']['state']=='NEXT_HOP_ACCEPTED' and jobs['temp@test.invalid']['state']=='NEXT_HOP_ACCEPTED' and jobs['perm@test.invalid']['state']=='PERMANENT_FAILURE' and jobs['unknown@test.invalid']['state']=='UNKNOWN',
        'M3-10': len(delivery_by_recipient['temp@test.invalid']) == 3 and len(delivery_by_recipient['perm@test.invalid']) == 1 and temp_times[1]-temp_times[0] >= .8 and temp_times[2]-temp_times[1] >= 1.8,
        'M3-11': len(unknown_rows) == 2 and unknown_rows[0]['outcome']=='UNKNOWN' and bool(unknown_rows[0]['data_submitted']) and unknown_rows[0]['last_stage']=='DATA_SUBMITTED' and unknown_rows[0]['evidence_sha256'] and next(item for item in unknown_stable['recipients'] if item['recipient']=='unknown@test.invalid')['attemptCount'] == 1,
        'M3-12': unconfirmed[0] == 400 and len(unknown_rows) == 2 and bool(unknown_rows[1]['duplicate_risk_ack']) and unknown_rows[1]['prior_attempt_id'] == unknown_rows[0]['attempt_id'],
        'M3-13': cancel_one['state']==cancel_two['state']==cancel_after_restart['state']=='CANCELLED' and cancel_attempts == 0,
        'M3-14': worker_cancel[0] == 409 and hold_final['delivery']['everStarted'] and hold_final['delivery']['recipients'][0]['attemptCount'] == 1,
        'M3-15': race_valid,
        'M3-16': browser_facts['cancel']['submitted_local'] and browser_facts['cancel']['cancelled'] and browser_facts['unknown']['unknown_copy'] and '尝试 2 次' in browser_facts['unknown']['attempts_after'] and not browser_facts['cancel']['external_requests'] and not browser_facts['unknown']['external_requests'],
        'M3-17': before_restart == after_restart,
        'M3-18': len(resource_rows) >= 12 and sum(bool(row['full_topology']) for row in resource_rows) >= 12 and not facts['resource']['stop_reasons'] and facts['resource']['max_host_used_bytes'] < 14*1024**3 and facts['resource']['min_container_memory_headroom_ratio'] >= .10 and facts['resource']['min_container_pid_headroom'] >= 16,
    }
    return facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', choices=['none','wrong-binding','missing-evidence'], default='none')
    parser.add_argument('--facts-from')
    args = parser.parse_args()
    if git('status','--porcelain'):
        raise RuntimeError('M3 evidence requires committed clean source')
    if args.facts_from and args.control == 'none':
        raise RuntimeError('Reusing facts is limited to negative controls')
    source = git('rev-parse','HEAD'); run = 'guihong-m3-' + uuid.uuid4().hex; out = lab.local_run(run, create=True)
    request = {'source_sha': source,
        'contract_sha256': hashlib.sha256((ROOT/'docs/m3-plan.md').read_bytes()).hexdigest(),
        'amendment_sha256': hashlib.sha256((ROOT/'docs/m3-plan-1.1.md').read_bytes()).hexdigest(),
        'control': args.control, 'facts_from': args.facts_from}
    spec = {'id':'m3-runtime','contract':{'id':'guihong-m3-local','version':'1.1'},'evidence_type':'guihong.m3',
        'coordinates':request,'projections':['source_sha','cases','http','smtp','database','storage','mq','browser','restart','resource','boundary'],
        'canonicalization_profile':'veritrail-json-c14n/1'}
    assertions = [{'id':case.lower(),'severity':'HARD','left':{'requirement_id':'m3','path':'/facts/cases/'+case},'operator':'eq','right':True}
                  for case in [f'M3-{number:02d}' for number in range(1,19)]]
    plan = seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m3-local','version':1,
        'subject':{'id':'guihong-m3-candidate','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the exact Go source satisfy the finite M3 SMTP, delivery, retry and cancellation contract?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:m3-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'m3','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'m3','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':30*1024*1024,'max_probe_seconds':600},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M3','consumers':['m3-stage-gate']},
        'reproduction_steps':['Start the exact immutable Go build in a fresh owned lab.','Run this collector and inspect retained SMTP, SQL, S3, MQ, browser, restart and resource facts.'],
        'cleanup_steps':['Stop exact owned application PIDs and remove only the owned lab after evidence retention.']})
    save(out/'sealed-plan.json', plan); save(out/'request.json', request)
    status='COMPLETED'; error=None
    try:
        if args.facts_from:
            source_path=(ROOT/args.facts_from).resolve(); local_root=(ROOT/'artifacts/local').resolve()
            if not source_path.is_file() or not source_path.is_relative_to(local_root):
                raise RuntimeError('Control facts must come from retained local evidence')
            facts=json.loads(source_path.read_text(encoding='utf-8'))['facts']
            if facts.get('source_sha') != source or not all(facts.get('cases',{}).values()):
                raise RuntimeError('Control facts are not a same-source complete PASS candidate')
        else:
            facts=collect(out)
    except Exception as failure:
        status='ERROR'; error={'exception_type':type(failure).__name__,'message':str(failure)}
        facts={'source_sha':source,'cases':{},'boundary':'M3_SMTP_AND_DELIVERY_ONLY'}
        save(out/'collection-error.json',error)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
        'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(request),
        'collection_session_id':run,'collector_role':'guihong-m3-collector','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR',
        'normalization_semantics_version':'guihong-m3/1.1','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding': metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-m3/1.1',
        'captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],
        output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],
        'expected':expected,'control':args.control,'bundle':(out/'bundle').relative_to(ROOT).as_posix()}
    save(out/'summary.json',summary); print(json.dumps(summary))
    return 0 if report['verdict']==expected and status=='COMPLETED' else 1


if __name__=='__main__':
    raise SystemExit(main())
