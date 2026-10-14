"""Collect and seal the finite Go M4 classification evidence."""
import argparse
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email import policy
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import time
import traceback
import uuid
from http.cookies import SimpleCookie

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


def wait_until(label, predicate, timeout=40, interval=.2):
    deadline = time.monotonic() + timeout; last = None
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
    def __init__(self): self.cookie = ''; self.csrf = ''

    def request(self, method, path, value=None, *, headers=None, content_type='application/json', raw=None, timeout=20):
        outbound = dict(headers or {})
        if self.cookie: outbound['Cookie'] = 'guihong_session=' + self.cookie
        if method not in {'GET', 'HEAD'}:
            outbound['Origin'] = ORIGIN
            if self.csrf: outbound['X-GuiHong-CSRF'] = self.csrf
        body = raw if raw is not None else (json.dumps(value).encode() if value is not None else None)
        if body is not None: outbound['Content-Type'] = content_type
        connection = http.client.HTTPConnection('127.0.0.1', 18080, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=outbound)
            response = connection.getresponse(); data = response.read(7 * 1024 * 1024)
            return response.status, dict(response.getheaders()), data
        finally: connection.close()

    def login(self, address, password):
        status, headers, raw = self.request('POST', '/api/auth/login', {'address': address, 'password': password})
        if status != 200: raise RuntimeError(f'login failed: {status} {raw!r}')
        cookie = SimpleCookie(); cookie.load(headers['Set-Cookie']); self.cookie = cookie['guihong_session'].value
        body = json.loads(raw); self.csrf = body['csrf']; return body['user']

    def json(self, method, path, value=None, *, expected=(200,), headers=None):
        status, response_headers, raw = self.request(method, path, value, headers=headers)
        body = json.loads(raw) if raw else None
        if status not in expected: raise RuntimeError(f'{method} {path} returned {status}: {body}')
        return status, response_headers, body

    def upload(self, path, filename, data):
        boundary = 'GuiHong' + uuid.uuid4().hex
        raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
               'Content-Type: text/plain\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', path, content_type='multipart/form-data; boundary=' + boundary, raw=raw)


def internal(method, path, body=None, expected=(200,)):
    raw = json.dumps(body).encode() if body is not None else None
    status, _, data = go_apps.owned_http('mailbox', path, method=method, body=raw,
        headers={'Content-Type': 'application/json'}, internal=True)
    parsed = json.loads(data) if data else None
    if status not in expected: raise RuntimeError(f'internal {method} {path}: {status} {parsed}')
    return parsed


def connect():
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    database = secrets['database']['mailbox']
    return pymysql.connect(host='127.0.0.1', port=13306, user=database['user'], password=database['password'],
        database=database['schema'], connect_timeout=5, autocommit=True)


def rows(statement, arguments=()):
    with connect() as connection, connection.cursor(pymysql.cursors.DictCursor) as query:
        query.execute(statement, arguments)
        return [{key: (value.isoformat() if hasattr(value, 'isoformat') else value.decode() if isinstance(value, bytes) else value)
                 for key, value in row.items()} for row in query.fetchall()]


def scalar(statement, arguments=()):
    result = rows(statement, arguments); return next(iter(result[0].values())) if result else None


def account(address, password, display):
    return internal('POST', '/internal/accounts', {'address': address, 'password': password, 'displayName': display})['account_id']


def mime(from_address, to_address, subject, body):
    message = EmailMessage(policy=policy.SMTP)
    message['From'] = from_address; message['To'] = to_address; message['Subject'] = subject
    message['Message-ID'] = f'<{uuid.uuid4()}@m4.test>'; message.set_content(body)
    return message.as_bytes()


def import_message(account_id, address, from_address, subject, body='M4 classification body'):
    raw = mime(from_address, address, subject, body)
    value = internal('POST', '/internal/mailbox/fixtures', {'base64': base64.b64encode(raw).decode(),
        'members': [{'accountId': account_id, 'folder': 'INBOX', 'read': False}]})
    entry = rows('SELECT entry_id,version_no FROM mailbox_entries WHERE account_id=%s AND content_id=%s', (account_id, value['content_id']))[0]
    return {'entryId': entry['entry_id'], 'version': entry['version_no'], 'rawSha256': hashlib.sha256(raw).hexdigest(), 'subject': subject}


def category(api, name):
    return api.json('POST', '/api/mailbox/categories', {'name': name}, expected=(201,))[2]


def rule(api, category_id, kind, pattern, priority, auto=False):
    return api.json('POST', '/api/mailbox/classification/rules', {'categoryId': category_id, 'type': kind,
        'pattern': pattern, 'priority': priority, 'autoApply': auto, 'enabled': True}, expected=(201,))[2]


def evaluate(api, entry):
    return api.json('GET', f"/api/mailbox/messages/{entry['entryId']}/classification")[2]


def message(api, entry):
    return api.json('GET', f"/api/mailbox/messages/{entry['entryId']}")[2]


def classify_manual(api, entry, category_id):
    detail = message(api, entry)
    return api.json('PATCH', f"/api/mailbox/messages/{entry['entryId']}", {'version': detail['summary']['version'], 'categoryId': category_id})[2]


def inbox_subject(api, subject, timeout=40):
    def find():
        page = api.json('GET', '/api/mailbox/messages?folder=INBOX&size=50')[2]
        return next((item for item in page['items'] if item['subject'] == subject), None)
    return wait_until('inbox subject ' + subject, find, timeout)


def wait_delivery(api, intent, timeout=50):
    def done():
        value = api.json('GET', '/api/mailbox/send-intents/' + intent)[2]
        return value if value.get('delivery', {}).get('state') == 'COMPLETED' else None
    return wait_until('delivery ' + intent, done, timeout)


def snapshot():
    tables = ('classification_rules', 'classification_settings', 'classification_category_auto',
              'classification_feedback', 'classification_models', 'classification_suggestions', 'classification_actions')
    return {table: rows(f'SELECT * FROM {table} ORDER BY 1') for table in tables}


def collect(out):
    source = git('rev-parse', 'HEAD')
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    alice_id = account(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'], '甲用户')
    bob_id = account(secrets['accounts']['bob']['address'], secrets['accounts']['bob']['password'], '乙用户')
    carol_password = 'Carol-M4-password'; carol_id = account('carol@guihong.test', carol_password, '丙用户')
    alice, bob, carol = API(), API(), API()
    alice.login(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
    bob.login(secrets['accounts']['bob']['address'], secrets['accounts']['bob']['password'])
    carol.login('carol@guihong.test', carol_password)
    categories = {
        'alice_a': category(alice, '甲项目'), 'alice_b': category(alice, '甲行程'),
        'bob_a': category(bob, '乙项目'), 'bob_b': category(bob, '乙行程')}

    # Two disjoint account-owned training sets: six manual confirmations per class.
    training = {'alice': [], 'bob': []}
    profiles = {
        'alice': (alice, alice_id, secrets['accounts']['alice']['address'], categories['alice_a'], categories['alice_b'], 'alpha-a.test', 'beta-a.test'),
        'bob': (bob, bob_id, secrets['accounts']['bob']['address'], categories['bob_a'], categories['bob_b'], 'alpha-b.test', 'beta-b.test')}
    for owner, (api, account_id, address, cat_a, cat_b, domain_a, domain_b) in profiles.items():
        for index in range(6):
            first = import_message(account_id, address, f'reports@{domain_a}', f'alpha project brief {index}')
            second = import_message(account_id, address, f'alerts@{domain_b}', f'beta travel notice {index}')
            classify_manual(api, first, cat_a['id']); classify_manual(api, second, cat_b['id'])
            training[owner].extend([first, second])

    validation = {'alice': [], 'bob': []}; predictions = []
    for owner, (api, account_id, address, cat_a, cat_b, domain_a, domain_b) in profiles.items():
        fixtures = [(f'reports@{domain_a}', f'alpha project review {index}', cat_a['id']) for index in range(2)] + [
                    (f'alerts@{domain_b}', f'beta travel update {index}', cat_b['id']) for index in range(2)]
        for from_address, subject, expected in fixtures:
            entry = import_message(account_id, address, from_address, subject)
            result = evaluate(api, entry); validation[owner].append(entry)
            predictions.append({'owner': owner, 'entry': entry['entryId'], 'expected': expected, 'result': result})
    model_before_decisions = rows('SELECT account_id,model_version,sample_digest,sample_count,category_counts FROM classification_models ORDER BY account_id')

    cold = import_message(carol_id, 'carol@guihong.test', 'new@cold.test', 'cold start')
    cold_result = evaluate(carol, cold)
    low = import_message(alice_id, secrets['accounts']['alice']['address'], 'mixed@mixed.test', 'alpha beta project travel brief notice')
    low_result = evaluate(alice, low)

    # Decide algorithm suggestions before rule mutations intentionally withdraw and recompute pending suggestions.
    accept_prediction, reject_prediction, override_prediction = predictions[0], predictions[1], predictions[2]
    accepted = alice.json('POST', f"/api/mailbox/messages/{accept_prediction['entry']}/classification/decision",
        {'suggestionId': accept_prediction['result']['suggestion']['id'], 'decision': 'ACCEPT',
         'version': accept_prediction['result']['suggestion']['entryVersion']})[2]
    rejected = alice.json('POST', f"/api/mailbox/messages/{reject_prediction['entry']}/classification/decision",
        {'suggestionId': reject_prediction['result']['suggestion']['id'], 'decision': 'REJECT',
         'version': reject_prediction['result']['suggestion']['entryVersion']})[2]
    override_entry = {'entryId': override_prediction['entry']}
    overridden = classify_manual(alice, override_entry, categories['alice_a']['id'])

    # Rule CRUD, conflict, manual precedence, default suggestion and explicit auto application.
    address_rule = rule(alice, categories['alice_a']['id'], 'FROM_ADDRESS', 'boss@rules.test', 600)
    domain_rule = rule(alice, categories['alice_a']['id'], 'FROM_DOMAIN', 'auto.rules', 850, True)
    subject_rule = rule(alice, categories['alice_a']['id'], 'SUBJECT_CONTAINS', 'invoice', 500)
    conflict_a = rule(alice, categories['alice_a']['id'], 'SUBJECT_CONTAINS', 'conflictmark', 700)
    conflict_b = rule(alice, categories['alice_b']['id'], 'SUBJECT_CONTAINS', 'conflictmark', 700)
    stale_rule = dict(address_rule, priority=601)
    update_ok = alice.json('PUT', '/api/mailbox/classification/rules/' + address_rule['id'], stale_rule)[2]
    stale_status = alice.request('PUT', '/api/mailbox/classification/rules/' + address_rule['id'], stale_rule)[0]
    foreign = dict(update_ok, categoryId=categories['bob_a']['id'])
    foreign_status = bob.request('PUT', '/api/mailbox/classification/rules/' + address_rule['id'], foreign)[0]

    suggested = import_message(alice_id, secrets['accounts']['alice']['address'], 'boss@rules.test', 'rule suggestion')
    invariant_before = message(alice, suggested); suggested_result = evaluate(alice, suggested); invariant_after = message(alice, suggested)
    conflict = import_message(alice_id, secrets['accounts']['alice']['address'], 'nobody@other.test', 'conflictmark now')
    conflict_result = evaluate(alice, conflict)
    manual_rule = rule(alice, categories['alice_b']['id'], 'FROM_ADDRESS', 'reports@alpha-a.test', 900, True)
    manual_result = evaluate(alice, training['alice'][0])
    auto_rule_entry = import_message(alice_id, secrets['accounts']['alice']['address'], 'worker@auto.rules', 'automatic rule')
    auto_rule_result = evaluate(alice, auto_rule_entry); auto_rule_detail = message(alice, auto_rule_entry)
    stale_undo_status = alice.request('POST', f"/api/mailbox/messages/{auto_rule_entry['entryId']}/classification/undo",
        {'actionId': auto_rule_result['suggestion']['actionId'], 'version': auto_rule_detail['summary']['version'] - 1})[0]
    auto_rule_undone = alice.json('POST', f"/api/mailbox/messages/{auto_rule_entry['entryId']}/classification/undo",
        {'actionId': auto_rule_result['suggestion']['actionId'], 'version': auto_rule_detail['summary']['version']})[2]

    # Algorithm auto authorization.
    settings = alice.json('GET', '/api/mailbox/classification/settings')[2]
    auto_settings = alice.json('PUT', '/api/mailbox/classification/category-auto/' + categories['alice_a']['id'], {'enabled': True})[2]
    # The manual-precedence address rule would win for reports@alpha-a.test; disable it before algorithm-auto proof.
    manual_rule_disabled = dict(manual_rule, enabled=False)
    alice.json('PUT', '/api/mailbox/classification/rules/' + manual_rule['id'], manual_rule_disabled)
    algorithm_auto_entry = import_message(alice_id, secrets['accounts']['alice']['address'], 'reports@alpha-a.test', 'alpha project automatic')
    algorithm_auto_result = evaluate(alice, algorithm_auto_entry)
    algorithm_auto_detail = message(alice, algorithm_auto_entry)
    algorithm_stale_undo = alice.request('POST', f"/api/mailbox/messages/{algorithm_auto_entry['entryId']}/classification/undo",
        {'actionId': algorithm_auto_result['suggestion']['actionId'], 'version': algorithm_auto_detail['summary']['version'] - 1})[0]
    algorithm_auto_undone = alice.json('POST', f"/api/mailbox/messages/{algorithm_auto_entry['entryId']}/classification/undo",
        {'actionId': algorithm_auto_result['suggestion']['actionId'], 'version': algorithm_auto_detail['summary']['version']})[2]

    feedback = rows('SELECT account_id,entry_id,category_id,decision,suggestion_id,features_json FROM classification_feedback ORDER BY created_at,feedback_id')
    training_after = {owner: scalar("SELECT COUNT(*) FROM classification_feedback WHERE account_id=%s AND decision='CONFIRMED' AND category_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM classification_feedback n WHERE n.account_id=classification_feedback.account_id AND n.entry_id=classification_feedback.entry_id AND (n.created_at>classification_feedback.created_at OR (n.created_at=classification_feedback.created_at AND n.feedback_id>classification_feedback.feedback_id)))", (account_id,))
                      for owner, account_id in [('alice', alice_id), ('bob', bob_id)]}

    bob_pending = predictions[4]['result']['suggestion']['id']
    bob_settings = bob.json('GET', '/api/mailbox/classification/settings')[2]
    disabled_settings = bob.json('PUT', '/api/mailbox/classification/settings', {'version': bob_settings['version'], 'algorithmEnabled': False})[2]
    withdrawn = scalar("SELECT COUNT(*) FROM classification_suggestions WHERE account_id=%s AND source_kind='ALGORITHM' AND status_value='WITHDRAWN'", (bob_id,))
    disabled_entry = import_message(bob_id, secrets['accounts']['bob']['address'], 'fresh@none.test', 'algorithm disabled')
    disabled_result = evaluate(bob, disabled_entry)
    bob_rule = rule(bob, categories['bob_a']['id'], 'FROM_ADDRESS', 'rule@bob.test', 500)
    bob_rule_entry = import_message(bob_id, secrets['accounts']['bob']['address'], 'rule@bob.test', 'rule while disabled')
    bob_rule_result = evaluate(bob, bob_rule_entry)

    wrong_message_status = bob.request('GET', f"/api/mailbox/messages/{suggested['entryId']}/classification")[0]
    feature_plaintext = any('reports@' in str(row['features_json']) or 'alpha project' in str(row['features_json']) for row in feedback)

    # Missing algorithm file degrades only algorithm decisions; Go rules remain live.
    missing_rule = rule(alice, categories['alice_a']['id'], 'FROM_ADDRESS', 'missing-rule@rules.test', 650)
    missing_algorithm_entry = import_message(alice_id, secrets['accounts']['alice']['address'], 'missing@algorithm.test', 'algorithm file missing probe')
    missing_rule_entry = import_message(alice_id, secrets['accounts']['alice']['address'], 'missing-rule@rules.test', 'rule file missing probe')
    script = ROOT / 'algorithm/classifier.py'; hidden = ROOT / '.artifacts/lab/classifier-temporarily-missing.py'
    script.replace(hidden)
    try:
        missing_algorithm_result = evaluate(alice, missing_algorithm_entry)
        missing_rule_result = evaluate(alice, missing_rule_entry)
    finally:
        hidden.replace(script)
    if git('status', '--porcelain'):
        raise RuntimeError('algorithm missing-file probe did not restore exact clean source')

    # Real browser probes are last so their suggestions remain in the first mailbox page.
    browser_rule = rule(alice, categories['alice_a']['id'], 'SUBJECT_CONTAINS', 'browser-probe', 800)
    suffix = uuid.uuid4().hex[:8]
    desktop_subject = 'browser-probe desktop ' + suffix; mobile_subject = 'browser-probe mobile ' + suffix
    stale_subject = 'browser-probe stale-alice ' + suffix
    browser_entries = [import_message(alice_id, secrets['accounts']['alice']['address'], 'browser@rules.test', value)
                       for value in (desktop_subject, mobile_subject, stale_subject)]
    browser_dir = out / 'browser'
    browser_run = subprocess.run(['D:/python-3.10.6/python.exe', '-B', str(ROOT/'scripts/browser_m4.py'),
        '--output', str(browser_dir), '--desktop-subject', desktop_subject, '--mobile-subject', mobile_subject,
        '--stale-subject', stale_subject], cwd=ROOT, capture_output=True, text=True, timeout=150)
    if browser_run.returncode: raise RuntimeError('M4 browser failed: ' + browser_run.stdout + browser_run.stderr)
    browser = json.loads((browser_dir/'browser.json').read_text(encoding='utf-8'))

    # M3 closed-loop regression on the changed source, including attachment and reply.
    send_subject = 'M4 regression send ' + suffix
    draft = alice.json('POST', '/api/mailbox/drafts', {'subject': send_subject, 'textBody': 'M4 regression', 'htmlBody': '<p>M4 regression</p>',
        'to': [secrets['accounts']['bob']['address']], 'cc': [], 'bcc': [], 'mode': 'COMPOSE', 'sourceContentId': None}, expected=(201,))[2]
    upload_status, _, upload_raw = alice.upload(f"/api/mailbox/drafts/{draft['id']}/attachments?version={draft['version']}", 'm4.txt', b'M4 attachment')
    attached = json.loads(upload_raw)
    intent = alice.json('POST', f"/api/mailbox/drafts/{draft['id']}/send", {'version': attached['version']},
        headers={'Idempotency-Key': 'm4-' + uuid.uuid4().hex}, expected=(202,))[2]
    delivery = wait_delivery(alice, intent['id']); bob_received = inbox_subject(bob, send_subject)
    reply = bob.json('POST', f"/api/mailbox/messages/{bob_received['entryId']}/drafts?mode=REPLY", expected=(201,))[2]
    reply_intent = bob.json('POST', f"/api/mailbox/drafts/{reply['id']}/send", {'version': reply['version']},
        headers={'Idempotency-Key': 'm4-reply-' + uuid.uuid4().hex}, expected=(202,))[2]
    reply_delivery = wait_delivery(bob, reply_intent['id']); reply_received = inbox_subject(alice, reply['subject'])

    before_restart = snapshot(); go_apps.stop(); go_apps.start(); after_restart = snapshot()
    manual_after_restart = evaluate(alice, training['alice'][0])
    classifier_processes = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*algorithm\\classifier.py*' }).Count"], text=True).strip()

    unit = subprocess.run(['D:/python-3.10.6/python.exe', '-B', str(ROOT/'scripts/test_classifier.py')],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    resource_run = subprocess.run([str(PYTHON), '-B', str(ROOT/'scripts/resource_guard.py'), '--duration', '90', '--runtime', 'go'],
        cwd=ROOT, capture_output=True, text=True, timeout=130)
    if resource_run.returncode: raise RuntimeError('resource guard stopped M4 run: ' + resource_run.stdout + resource_run.stderr)
    resource_path = Path(json.loads(resource_run.stdout.strip().splitlines()[-1])['evidence'])
    resource_rows = [json.loads(line) for line in resource_path.read_text(encoding='utf-8').splitlines() if line]
    resource = {'file': resource_path.name, 'samples': len(resource_rows),
        'full_topology_samples': sum(bool(row['full_topology']) for row in resource_rows),
        'stop_reasons': [row['stop_reason'] for row in resource_rows if row['stop_reason']],
        'max_host_used_bytes': max(row['memory']['used_bytes'] for row in resource_rows),
        'min_container_memory_headroom_ratio': min(c['memory_headroom_ratio'] for row in resource_rows for c in row['containers'] if c['running']),
        'min_container_pid_headroom': min(c['pid_headroom'] for row in resource_rows for c in row['containers'] if c['running'])}

    prediction_ok = all(item['result']['state'] == 'SUGGESTED' and item['result']['suggestion']['categoryId'] == item['expected'] for item in predictions)
    isolation_models = len(model_before_decisions) == 2 and {row['account_id'] for row in model_before_decisions} == {alice_id, bob_id}
    invariants = all(invariant_before[key] == invariant_after[key] for key in ('textBody', 'safeHtml', 'rawSha256', 'rawSize', 'attachments', 'recipients')) and invariant_before['summary']['folder'] == invariant_after['summary']['folder'] and invariant_before['summary']['read'] == invariant_after['summary']['read']
    facts = {'source_sha': source, 'boundary': 'M4_CLASSIFICATION_ONLY', 'predictions': predictions,
        'rules': {'address': update_ok, 'domain': domain_rule, 'subject': subject_rule, 'conflicts': [conflict_a, conflict_b],
                  'stale_status': stale_status, 'foreign_status': foreign_status, 'suggested': suggested_result,
                  'conflict_result': conflict_result, 'manual_result': manual_result, 'auto_result': auto_rule_result,
                  'auto_undone': auto_rule_undone, 'stale_undo_status': stale_undo_status},
        'algorithm': {'models': model_before_decisions, 'cold': cold_result, 'low': low_result,
                      'auto_settings': auto_settings, 'auto_result': algorithm_auto_result,
                      'auto_stale_undo': algorithm_stale_undo, 'auto_undone': algorithm_auto_undone,
                      'missing': missing_algorithm_result, 'missing_rule': missing_rule_result,
                      'unit_exit': unit.returncode, 'unit_stdout': unit.stdout, 'classifier_processes': classifier_processes},
        'feedback': {'rows': feedback, 'training_after': training_after, 'accepted': accepted, 'rejected': rejected,
                     'overridden': overridden, 'feature_plaintext': feature_plaintext},
        'disabled': {'settings': disabled_settings, 'withdrawn': withdrawn, 'pending_id': bob_pending,
                     'algorithm': disabled_result, 'rule': bob_rule_result, 'rule_id': bob_rule['id']},
        'isolation': {'wrong_message_status': wrong_message_status, 'models': isolation_models},
        'invariants': {'equal': invariants, 'before': invariant_before, 'after': invariant_after},
        'browser': browser, 'restart': {'equal': before_restart == after_restart, 'manual': manual_after_restart,
                    'before_digest': sha256_json(before_restart), 'after_digest': sha256_json(after_restart)},
        'regression': {'upload_status': upload_status, 'delivery': delivery, 'bob_received': bob_received,
                       'reply_delivery': reply_delivery, 'reply_received': reply_received},
        'resource': resource}
    facts['cases'] = {
        'M4-01': stale_status == 409 and foreign_status == 404 and len(alice.json('GET','/api/mailbox/classification/rules')[2]) >= 7,
        'M4-02': suggested_result['state'] == 'SUGGESTED' and update_ok['id'][:8] in suggested_result['suggestion']['reason'] and conflict_result['state'] == 'RULE_CONFLICT' and '规则冲突' in conflict_result['suggestion']['reason'],
        'M4-03': manual_result['state'] == 'MANUAL_LOCKED' and manual_after_restart['state'] == 'MANUAL_LOCKED',
        'M4-04': suggested_result['suggestion']['status'] == 'PENDING' and auto_rule_result['state'] == 'AUTO_APPLIED' and auto_rule_undone['summary']['categoryId'] is None and stale_undo_status == 409,
        'M4-05': unit.returncode == 0 and isolation_models and all(row['sample_count'] == 12 for row in model_before_decisions) and classifier_processes == '0',
        'M4-06': cold_result['state'] == 'COLD_START' and low_result['state'] == 'LOW_CONFIDENCE' and conflict_result['state'] == 'RULE_CONFLICT' and missing_algorithm_result['state'] == 'ALGORITHM_UNAVAILABLE',
        'M4-07': isolation_models and wrong_message_status == 404 and not feature_plaintext,
        'M4-08': prediction_ok and len(predictions) == 8 and all(row['sample_count'] == 12 for row in model_before_decisions),
        'M4-09': accepted['status'] == 'ACCEPTED' and rejected['status'] == 'REJECTED' and overridden['summary']['categorySource'] == 'MANUAL_LOCKED' and training_after == {'alice': 14, 'bob': 12},
        'M4-10': algorithm_auto_result['state'] == 'AUTO_APPLIED' and algorithm_auto_result['suggestion']['confidence'] >= .95 and algorithm_auto_result['suggestion']['margin'] >= .40 and algorithm_stale_undo == 409 and algorithm_auto_undone['summary']['categoryId'] is None,
        'M4-11': not disabled_settings['algorithmEnabled'] and withdrawn >= 1 and disabled_result['state'] == 'ALGORITHM_DISABLED' and bob_rule_result['state'] == 'SUGGESTED',
        'M4-12': invariants,
        'M4-13': browser['desktop']['accepted'] and browser['desktop']['priority_after'] == '799' and '规则' in browser['desktop']['reason'] and not browser['external_requests'],
        'M4-14': browser['mobile']['viewport'][0] == 390 and browser['mobile']['rejected'] and browser['desktop']['stale_alice_absent_after_bob_login'],
        'M4-15': before_restart == after_restart and manual_after_restart['state'] == 'MANUAL_LOCKED' and missing_rule_result['state'] == 'SUGGESTED',
        'M4-16': browser['desktop']['navigation_visible'] and browser['desktop']['search_found'] and upload_status == 201 and delivery['delivery']['state'] == 'COMPLETED' and bob_received and reply_delivery['delivery']['state'] == 'COMPLETED' and reply_received and len(resource_rows) >= 12 and resource['full_topology_samples'] >= 12 and not resource['stop_reasons'] and resource['max_host_used_bytes'] < 14*1024**3 and resource['min_container_memory_headroom_ratio'] >= .10 and resource['min_container_pid_headroom'] >= 16,
    }
    return facts


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--control', choices=['none','wrong-binding','missing-evidence'], default='none'); parser.add_argument('--facts-from'); args = parser.parse_args()
    if git('status','--porcelain'): raise RuntimeError('M4 evidence requires committed clean source')
    if args.facts_from and args.control == 'none': raise RuntimeError('Reusing facts is limited to negative controls')
    source = git('rev-parse','HEAD'); run = 'guihong-m4-' + uuid.uuid4().hex; out = lab.local_run(run, create=True)
    request = {'source_sha': source, 'contract_sha256': hashlib.sha256((ROOT/'docs/m4-plan.md').read_bytes()).hexdigest(),
               'control': args.control, 'facts_from': args.facts_from}
    spec = {'id':'m4-runtime','contract':{'id':'guihong-m4-local','version':'1.0'},'evidence_type':'guihong.m4',
        'coordinates':request,'projections':['source_sha','cases','rules','algorithm','feedback','disabled','isolation','invariants','browser','restart','regression','resource','boundary'],
        'canonicalization_profile':'veritrail-json-c14n/1'}
    assertions = [{'id':case.lower(),'severity':'HARD','left':{'requirement_id':'m4','path':'/facts/cases/'+case},'operator':'eq','right':True}
                  for case in [f'M4-{number:02d}' for number in range(1,17)]]
    plan = seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m4-local','version':1,
        'subject':{'id':'guihong-m4-candidate','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the exact Go source satisfy the finite M4 classification and product regression contract?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:m4-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'m4','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'m4','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':30*1024*1024,'max_probe_seconds':600},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M4','consumers':['m4-stage-gate']},
        'reproduction_steps':['Start the exact immutable Go build in a fresh owned lab.','Run this collector and inspect retained SQL, algorithm, browser, restart, SMTP and resource facts.'],
        'cleanup_steps':['Stop exact owned application PIDs and remove only the owned lab after evidence retention.']})
    save(out/'sealed-plan.json',plan); save(out/'request.json',request); status='COMPLETED'; error=None
    try:
        if args.facts_from:
            source_path=(ROOT/args.facts_from).resolve(); local_root=(ROOT/'artifacts/local').resolve()
            if not source_path.is_file() or not source_path.is_relative_to(local_root): raise RuntimeError('Control facts must come from retained local evidence')
            facts=json.loads(source_path.read_text(encoding='utf-8'))['facts']
            if facts.get('source_sha') != source or not all(facts.get('cases',{}).values()): raise RuntimeError('Control facts are not a same-source complete PASS candidate')
        else: facts=collect(out)
    except Exception as failure:
        status='ERROR'; error={'exception_type':type(failure).__name__,'message':str(failure),'traceback':traceback.format_exc()}
        facts={'source_sha':source,'cases':{},'boundary':'M4_CLASSIFICATION_ONLY'}; save(out/'collection-error.json',error)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
        'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(request),'collection_session_id':run,
        'collector_role':'guihong-m4-collector','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR','normalization_semantics_version':'guihong-m4/1.0','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding': metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-m4/1.0','captured_at':datetime.now(timezone.utc).isoformat(),
              'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],'expected':expected,
             'control':args.control,'bundle':(out/'bundle').relative_to(ROOT).as_posix()}
    save(out/'summary.json',summary); print(json.dumps(summary)); return 0 if report['verdict']==expected and status=='COMPLETED' else 1


if __name__=='__main__': raise SystemExit(main())
