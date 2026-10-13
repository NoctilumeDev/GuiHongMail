"""Collect and seal the finite Go M2 candidate evidence."""
import argparse
from datetime import datetime, timezone
from email.message import EmailMessage
import base64
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
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


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


class API:
    def __init__(self):
        self.cookie = ''
        self.csrf = ''

    def request(self, method, path, value=None, content_type='application/json', raw=None):
        headers = {}
        if self.cookie:
            headers['Cookie'] = 'guihong_session=' + self.cookie
        if method not in {'GET', 'HEAD'}:
            headers['Origin'] = ORIGIN
            if self.csrf:
                headers['X-GuiHong-CSRF'] = self.csrf
        body = raw
        if value is not None:
            body = json.dumps(value).encode()
        if body is not None:
            headers['Content-Type'] = content_type
        connection = http.client.HTTPConnection('127.0.0.1', 18080, timeout=20)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse(); data = response.read(7 * 1024 * 1024)
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def login(self, address, password):
        status, headers, raw = self.request('POST', '/api/auth/login', {'address': address, 'password': password})
        if status != 200:
            raise RuntimeError('login failed: ' + str(status) + ' ' + raw.decode(errors='replace'))
        cookie = SimpleCookie(); cookie.load(headers['Set-Cookie']); self.cookie = cookie['guihong_session'].value
        body = json.loads(raw); self.csrf = body['csrf']; return body['user']

    def json(self, method, path, value=None, expected=(200,)):
        status, headers, raw = self.request(method, path, value)
        body = json.loads(raw) if raw else None
        if status not in expected:
            raise RuntimeError(f'{method} {path} returned {status}: {body}')
        return status, headers, body

    def upload(self, path, filename, data, media='text/plain'):
        boundary = 'GuiHong' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: {media}\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', path, content_type='multipart/form-data; boundary=' + boundary, raw=body)


def internal(method, path, body=None):
    raw = json.dumps(body).encode() if body is not None else None
    status, headers, data = go_apps.owned_http('mailbox', path, method=method, body=raw,
                                               headers={'Content-Type': 'application/json'}, internal=True)
    parsed = json.loads(data) if data else None
    if status < 200 or status >= 300:
        raise RuntimeError(f'internal {method} {path}: {status} {parsed}')
    return status, headers, parsed


def message(subject, marker, attachment=True):
    value = EmailMessage()
    value['From'] = '寄信人 <sender@example.test>'; value['To'] = 'alice@guihong.test, bob@guihong.test'
    value['Cc'] = 'copy@example.test'; value['Subject'] = subject; value['Message-ID'] = f'<{uuid.uuid4()}@example.test>'
    value.set_content('纯文本 ' + marker + ' 可搜索正文')
    value.add_alternative(f'<p onclick="window.__guihongUnsafeExecuted=true">{marker}</p><script>window.__guihongUnsafeExecuted=true</script><img src="https://example.invalid/tracker.png"><form action="https://example.invalid/"><input></form>', subtype='html')
    if attachment:
        value.add_attachment(('附件内容-' + marker).encode(), maintype='text', subtype='plain', filename='证据.txt')
    return value.as_bytes()


def draft_payload(value, **changes):
    result = {key: value[key] for key in ('version','subject','textBody','htmlBody','to','cc','bcc','mode','sourceContentId')}
    result.update(changes)
    return result


def sql_facts(secrets, account_ids, raw_digest):
    database = secrets['database']['mailbox']
    with pymysql.connect(host='127.0.0.1', port=13306, user=database['user'], password=database['password'],
                         database=database['schema'], connect_timeout=5) as connection:
        with connection.cursor() as query:
            query.execute('SELECT account_id,folder,is_read,category_id,version_no FROM mailbox_entries ORDER BY account_id,entry_id')
            entries = [{'account_id': row[0], 'folder': row[1], 'read': bool(row[2]), 'category_id': row[3], 'version': row[4]} for row in query.fetchall()]
            query.execute('SELECT raw_object_id,raw_sha256,raw_size FROM message_contents WHERE raw_sha256=%s', (raw_digest,)); raw = query.fetchone()
            query.execute('SELECT object_key,sha256,byte_size,lifecycle FROM stored_objects WHERE object_id=%s', (raw[0],)); stored = query.fetchone()
            query.execute('SELECT COUNT(*) FROM drafts WHERE account_id=%s', (account_ids['alice'],)); draft_count = query.fetchone()[0]
            query.execute('SELECT COUNT(*) FROM object_refs WHERE ref_kind IN (\'MESSAGE_RAW\',\'MESSAGE_ATTACHMENT\',\'DRAFT_ATTACHMENT\')'); refs = query.fetchone()[0]
    return {'entries': entries, 'raw': {'object_id': raw[0], 'sha256': raw[1], 'size': raw[2],
                                        'object_key': stored[0], 'stored_sha256': stored[1], 'stored_size': stored[2], 'lifecycle': stored[3]},
            'alice_draft_count': draft_count, 'mailbox_object_reference_count': refs}


def collect(out):
    source = git('rev-parse', 'HEAD')
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    facts = {'source_sha': source, 'cases': {}, 'http': {}, 'database': {}, 'storage': {}, 'browser': {},
             'restart': {}, 'resource': {}, 'boundary': 'M2_MAILBOX_AND_WEB_ONLY'}
    accounts = {}
    for name, display in [('alice', '甲用户'), ('bob', '乙用户')]:
        _, _, body = internal('POST', '/internal/accounts', {'address': secrets['accounts'][name]['address'],
                                                             'password': secrets['accounts'][name]['password'], 'displayName': display})
        accounts[name] = body['account_id']
    shared_raw = message('共同邮件', 'SHARED-MARKER'); bob_raw = message('乙专有邮件', 'BOB-PRIVATE-MARKER')
    alice_raw = message('甲专有邮件', 'ALICE-PRIVATE-MARKER', attachment=False)
    for raw, members in [(shared_raw, [('alice', 'INBOX'), ('bob', 'INBOX')]),
                         (bob_raw, [('bob', 'INBOX')]), (alice_raw, [('alice', 'INBOX')])]:
        internal('POST', '/internal/mailbox/fixtures', {'base64': base64.b64encode(raw).decode(),
                 'members': [{'accountId': accounts[name], 'folder': folder, 'read': False} for name, folder in members]})

    alice = API(); bob = API()
    alice_user = alice.login(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
    bob_user = bob.login(secrets['accounts']['bob']['address'], secrets['accounts']['bob']['password'])
    _, _, alice_page = alice.json('GET', '/api/mailbox/messages?folder=INBOX&size=30')
    _, _, bob_page = bob.json('GET', '/api/mailbox/messages?folder=INBOX&size=30')
    by_subject_a = {row['subject']: row for row in alice_page['items']}; by_subject_b = {row['subject']: row for row in bob_page['items']}
    shared_a, shared_b = by_subject_a['共同邮件'], by_subject_b['共同邮件']; private_b = by_subject_b['乙专有邮件']
    _, _, shared_detail = alice.json('GET', '/api/mailbox/messages/' + shared_a['entryId'])
    _, _, private_b_detail = bob.json('GET', '/api/mailbox/messages/' + private_b['entryId'])
    attachment = shared_detail['attachments'][0]
    status_cross, _, cross_body = alice.request('GET', '/api/mailbox/messages/' + private_b['entryId'])
    status_attachment, _, attachment_body = alice.request('GET', f"/api/mailbox/messages/{private_b['entryId']}/attachments/{private_b_detail['attachments'][0]['id']}")
    _, _, cross_after = alice.json('GET', '/api/mailbox/messages?folder=INBOX&size=30')
    before_invalid = len(alice_page['items'])
    invalid_status, _, invalid_body = alice.request('GET', '/api/mailbox/messages?folder=INBOX&size=1&cursor=invalid')
    _, _, page_one = alice.json('GET', '/api/mailbox/messages?folder=INBOX&size=1')
    page_two = {'items': []}
    if page_one['nextCursor']:
        _, _, page_two = alice.json('GET', '/api/mailbox/messages?folder=INBOX&size=1&cursor=' + page_one['nextCursor'])
    _, _, search = alice.json('GET', '/api/mailbox/messages?folder=INBOX&size=30&q=ALICE-PRIVATE-MARKER')

    _, _, changed_a = alice.json('PATCH', '/api/mailbox/messages/' + shared_a['entryId'], {'version': shared_a['version'], 'read': True, 'folder': 'ARCHIVE'})
    _, _, unchanged_b = bob.json('GET', '/api/mailbox/messages/' + shared_b['entryId'])

    _, _, draft = alice.json('POST', '/api/mailbox/drafts', {'subject': '持久草稿', 'textBody': '初稿', 'htmlBody': '<b>初稿</b>', 'to': ['bob@guihong.test'], 'cc': [], 'bcc': [], 'mode': 'COMPOSE'}, expected=(201,))
    _, _, updated = alice.json('PUT', '/api/mailbox/drafts/' + draft['id'], draft_payload(draft,textBody='已更新'), expected=(200,))
    stale_status, _, stale_raw = alice.request('PUT', '/api/mailbox/drafts/' + draft['id'], draft_payload(draft,textBody='旧写入'))
    stale_body = json.loads(stale_raw)
    bad_name_status, _, bad_name_raw = alice.upload(f"/api/mailbox/drafts/{draft['id']}/attachments?version={updated['version']}", '../secret.txt', b'bad')
    good_status, _, good_raw = alice.upload(f"/api/mailbox/drafts/{draft['id']}/attachments?version={updated['version']}", '证据.txt', b'draft-evidence')
    attached = json.loads(good_raw)
    draft_attachment = attached['attachments'][0]
    download_status, download_headers, download_raw = alice.request('GET', f"/api/mailbox/drafts/{draft['id']}/attachments/{draft_attachment['id']}")

    derived = {}
    for mode in ('REPLY', 'REPLY_ALL', 'FORWARD'):
        _, _, derived[mode] = alice.json('POST', f"/api/mailbox/messages/{shared_a['entryId']}/drafts?mode={mode}", expected=(201,))
    _, _, category = alice.json('POST', '/api/mailbox/categories', {'name': '项目'}, expected=(201,))
    _, _, categorized = alice.json('PATCH', '/api/mailbox/messages/' + shared_a['entryId'], {'version': changed_a['summary']['version'], 'categoryId': category['id']})
    _, _, renamed = alice.json('PUT', '/api/mailbox/categories/' + category['id'], {'version': category['version'], 'name': '重要项目'})
    alice.json('DELETE', f"/api/mailbox/categories/{category['id']}?version={renamed['version']}", expected=(204,))
    _, _, after_category = alice.json('GET', '/api/mailbox/messages/' + shared_a['entryId'])
    state = after_category
    for folder in ('SPAM', 'TRASH', 'INBOX'):
        _, _, state = alice.json('PATCH', '/api/mailbox/messages/' + shared_a['entryId'], {'version': state['summary']['version'], 'folder': folder})
    _, _, counts = alice.json('GET', '/api/mailbox/folders')

    raw_digest = hashlib.sha256(shared_raw).hexdigest(); database = sql_facts(secrets, accounts, raw_digest)
    storage = secrets['storage']['mailbox']
    s3 = boto3.client('s3', endpoint_url='http://127.0.0.1:19833', aws_access_key_id=storage['access_key'],
                      aws_secret_access_key=storage['secret_key'], region_name='us-east-1', config=Config(signature_version='s3v4'))
    stored_raw = s3.get_object(Bucket=storage['bucket'], Key=database['raw']['object_key'])['Body'].read()

    resource = subprocess.Popen([str(ROOT / '.artifacts/lab-env/Scripts/python.exe'), '-B', str(ROOT / 'scripts/resource_guard.py'),
                                 '--duration', '90', '--runtime', 'go'], cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        go_apps.stop(); go_apps.start()
        restarted = API(); restarted.login(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
        _, _, draft_after_restart = restarted.json('GET', '/api/mailbox/drafts/' + draft['id'])
        _, _, message_after_restart = restarted.json('GET', '/api/mailbox/messages/' + shared_a['entryId'])
        browser_dir = out / 'browser'
        browser_run = subprocess.run(['D:/python-3.10.6/python.exe', '-B', str(ROOT / 'scripts/browser_m2.py'), '--output', str(browser_dir)],
                                     cwd=ROOT, capture_output=True, text=True, timeout=120)
        if browser_run.returncode:
            raise RuntimeError('browser observation failed: ' + browser_run.stdout + browser_run.stderr)
        browser = json.loads((browser_dir / 'browser.json').read_text(encoding='utf-8'))
        resource_stdout, _ = resource.communicate(timeout=120)
    finally:
        if resource.poll() is None:
            resource.terminate()
            resource.wait(timeout=10)
    if resource.returncode:
        raise RuntimeError('resource guard stopped M2 run: ' + resource_stdout)
    resource_line = json.loads(resource_stdout.strip().splitlines()[-1]); resource_path = Path(resource_line['evidence'])
    resource_rows = [json.loads(line) for line in resource_path.read_text(encoding='utf-8').splitlines() if line]

    bad_name_body = json.loads(bad_name_raw)
    facts['http'] = {'alice_subjects': sorted(by_subject_a), 'bob_subjects': sorted(by_subject_b),
                     'cross_owner': [status_cross, json.loads(cross_body)['code']],
                     'cross_attachment': [status_attachment, json.loads(attachment_body)['code']],
                     'independent_state': {'alice': changed_a['summary'], 'bob': unchanged_b['summary']},
                     'invalid_cursor': [invalid_status, json.loads(invalid_body)['code']],
                     'pagination_subjects': [row['subject'] for row in page_one['items'] + page_two['items']],
                     'search_subjects': [row['subject'] for row in search['items']], 'count_before_invalid': before_invalid,
                     'cross_owner_no_side_effect': cross_after == alice_page,
                     'draft': {'created_version': draft['version'], 'updated_version': updated['version'],
                               'stale_status': stale_status, 'stale': stale_body, 'after_restart': draft_after_restart},
                     'attachments': {'bad_name': [bad_name_status, bad_name_body['code']], 'good_status': good_status,
                                     'download_status': download_status, 'download_disposition': download_headers.get('Content-Disposition'),
                                     'download_sha256': hashlib.sha256(download_raw).hexdigest()},
                     'derived': {key: {'mode': value['mode'], 'subject': value['subject'], 'to': value['to'], 'cc': value['cc']} for key,value in derived.items()},
                     'category': {'assigned': categorized['summary']['categoryId'], 'renamed': renamed['name'],
                                  'after_delete_category': after_category['summary']['categoryId'], 'folder_after_delete': after_category['summary']['folder']},
                     'final_counts': counts, 'message_after_restart': message_after_restart['summary']}
    facts['database'] = database
    facts['storage'] = {'raw_sha256': hashlib.sha256(stored_raw).hexdigest(), 'raw_size': len(stored_raw),
                        'exact_raw_match': stored_raw == shared_raw}
    facts['browser'] = browser
    facts['restart'] = {'draft_body': draft_after_restart['textBody'], 'draft_attachment_count': len(draft_after_restart['attachments']),
                        'message_folder': message_after_restart['summary']['folder'], 'raw_sha256': message_after_restart['rawSha256']}
    facts['resource'] = {'file': resource_path.name, 'samples': len(resource_rows),
                         'stop_reasons': [row['stop_reason'] for row in resource_rows if row['stop_reason']],
                         'full_topology_samples': sum(bool(row['full_topology']) for row in resource_rows),
                         'max_host_used_bytes': max(row['memory']['used_bytes'] for row in resource_rows),
                         'max_application_rss_bytes': max((p['rss_bytes'] for row in resource_rows for p in row['processes']), default=0),
                         'min_container_memory_headroom_ratio': min((c['memory_headroom_ratio'] for row in resource_rows for c in row['containers'] if c['running']), default=0),
                         'min_container_pid_headroom': min((c['pid_headroom'] for row in resource_rows for c in row['containers'] if c['running']), default=0)}
    facts['cases'] = {
        'M2-01': set(by_subject_a)=={'共同邮件','甲专有邮件'} and set(by_subject_b)=={'共同邮件','乙专有邮件'},
        'M2-02': changed_a['summary']['folder']=='ARCHIVE' and changed_a['summary']['read'] and unchanged_b['summary']['folder']=='INBOX' and not unchanged_b['summary']['read'],
        'M2-03': (status_cross,status_attachment)==(404,404) and cross_after==alice_page,
        'M2-04': stale_status==409 and stale_body.get('current_version')==updated['version'] and draft_after_restart['textBody']=='已更新',
        'M2-05': set(derived)=={'REPLY','REPLY_ALL','FORWARD'} and message_after_restart['rawSha256']==raw_digest,
        'M2-06': shared_detail['summary']['subject']=='共同邮件' and len(shared_detail['attachments'])==1 and database['raw']['sha256']==raw_digest,
        'M2-07': not browser['desktop']['unsafe_script_executed'] and not browser['browser']['external_requests'],
        'M2-08': bad_name_status==400 and good_status==201 and download_status==200 and download_headers.get('Content-Disposition','').startswith('attachment'),
        'M2-09': state['summary']['folder']=='INBOX' and any(row['folder']=='INBOX' for row in counts),
        'M2-10': categorized['summary']['categoryId']==category['id'] and after_category['summary']['categoryId'] is None and after_category['summary']['folder']=='ARCHIVE',
        'M2-11': invalid_status==400 and len(page_one['items'])==1 and bool(page_one['nextCursor']) and search['items'][0]['subject']=='甲专有邮件',
        'M2-12': browser['desktop']['navigation']==browser['desktop']['expected_navigation'] and browser['desktop']['three_scroll_regions']==['auto','auto','auto'],
        'M2-13': browser['mobile']['viewport']==[390,844] and 'mobile-step-list' in browser['mobile']['step_after_browser_back'],
        'M2-14': browser['stale_response']['b_account_visible'] and browser['stale_response']['a_private_marker_absent'],
        'M2-15': attached['to']==['bob@guihong.test'] and attached['textBody']=='已更新' and len(attached['attachments'])==1,
        'M2-16': draft_after_restart['textBody']=='已更新' and message_after_restart['summary']['folder']=='INBOX' and facts['storage']['exact_raw_match'],
    }
    return facts


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--control', choices=['none','wrong-binding','missing-evidence'], default='none'); args=parser.parse_args()
    if git('status','--porcelain'):
        raise RuntimeError('M2 evidence requires committed clean source')
    source=git('rev-parse','HEAD'); run='guihong-m2-'+uuid.uuid4().hex; out=lab.local_run(run,create=True)
    request={'source_sha':source,'contract_sha256':hashlib.sha256((ROOT/'docs/m2-plan.md').read_bytes()).hexdigest(),'control':args.control}
    spec={'id':'m2-runtime','contract':{'id':'guihong-m2-local','version':'1.0'},'evidence_type':'guihong.m2',
          'coordinates':request,'projections':['source_sha','cases','http','database','storage','browser','restart','resource','boundary'],
          'canonicalization_profile':'veritrail-json-c14n/1'}
    assertions=[{'id':case.lower(),'severity':'HARD','left':{'requirement_id':'m2','path':'/facts/cases/'+case},'operator':'eq','right':True} for case in [f'M2-{n:02d}' for n in range(1,17)]]
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m2-local','version':1,
        'subject':{'id':'guihong-m2-candidate','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the exact Go source satisfy the finite M2 mailbox and web contract?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:m2-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'m2','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'m2','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':20*1024*1024,'max_probe_seconds':300},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M2','consumers':['m2-stage-gate']},
        'reproduction_steps':['Start the exact immutable Go build in a fresh owned lab.','Run this collector and inspect the retained browser, API, SQL, S3, restart and resource facts.'],
        'cleanup_steps':['Stop exact owned application PIDs and remove only the owned lab after evidence retention.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',request);status='COMPLETED';error=None
    try:facts=collect(out)
    except Exception as failure:
        status='ERROR';error={'exception_type':type(failure).__name__,'message':str(failure)};facts={'source_sha':source,'cases':{},'boundary':'M2_MAILBOX_AND_WEB_ONLY'};save(out/'collection-error.json',error)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
              'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(request),
              'collection_session_id':run,'collector_role':'guihong-m2-collector',
              'coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR','normalization_semantics_version':'guihong-m2/1.0','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding':metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-m2/1.0','captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],'expected':expected,'control':args.control,'bundle':(out/'bundle').relative_to(ROOT).as_posix()};save(out/'summary.json',summary);print(json.dumps(summary));return 0 if report['verdict']==expected and status=='COMPLETED' else 1


if __name__=='__main__':raise SystemExit(main())
