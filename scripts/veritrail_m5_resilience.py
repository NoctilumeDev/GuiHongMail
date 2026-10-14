"""Collect the M5 lease, poison-message and recovery counterexamples."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import smtplib
import subprocess
import time
import traceback
import uuid

import pymysql
from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json

import go_apps
import lab
import veritrail_m3 as m3

ROOT = lab.ROOT
PYTHON = ROOT / '.artifacts/lab-env/Scripts/python.exe'


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def readiness(role):
    status, _, raw = go_apps.owned_http(role, '/health/ready')
    return {'http': status, 'body': json.loads(raw)}


def internal_status(role, method, path, body=None):
    raw = None if body is None else json.dumps(body).encode()
    status, _, response = go_apps.owned_http(role, path, method=method, body=raw,
        headers={'Content-Type': 'application/json'}, internal=True)
    return {'http': status, 'body': json.loads(response) if response else None}


def seed_crashed_attempt(intent, *, submitted):
    row = m3.rows('mailbox', 'SELECT intent_id,dispatch_scope_id,raw_sha256,raw_size,sender_address FROM send_intents WHERE intent_id=%s', (intent['id'],))[0]
    scope, job, attempt, worker = row['dispatch_scope_id'], str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with m3.connect('delivery') as connection, connection.cursor() as query:
        query.execute('SET FOREIGN_KEY_CHECKS=0')
        query.execute('DELETE FROM delivery_retry_requests WHERE scope_id=%s', (scope,))
        query.execute('DELETE a FROM delivery_attempts a JOIN delivery_jobs j ON j.job_id=a.job_id WHERE j.scope_id=%s', (scope,))
        query.execute('DELETE FROM delivery_jobs WHERE scope_id=%s', (scope,))
        query.execute('DELETE FROM delivery_events WHERE source_intent_id=%s', (intent['id'],))
        query.execute('DELETE FROM dispatch_scopes WHERE scope_id=%s', (scope,))
        query.execute('SET FOREIGN_KEY_CHECKS=1')
        query.execute("INSERT INTO dispatch_scopes(scope_id,source_intent_id,source_service,raw_sha256,raw_size,sender_address,state,ever_started) VALUES(%s,%s,'mailbox',%s,%s,%s,'STARTED',1)",
                      (scope, intent['id'], row['raw_sha256'], row['raw_size'], row['sender_address']))
        query.execute("INSERT INTO delivery_jobs(job_id,scope_id,recipient,state,attempt_count,active_epoch,worker_id,lease_until) VALUES(%s,%s,'bob@guihong.test','STARTED',1,1,%s,DATE_SUB(CURRENT_TIMESTAMP(6),INTERVAL 2 SECOND))",
                      (job, scope, worker))
        query.execute("INSERT INTO delivery_attempts(attempt_id,job_id,epoch_no,worker_id,last_stage,data_submitted) VALUES(%s,%s,1,%s,%s,%s)",
                      (attempt, job, worker, 'DATA_SUBMITTED' if submitted else 'CLAIMED', submitted))
    return {'scope': scope, 'job': job, 'attempt': attempt, 'worker': worker, 'raw_sha256': row['raw_sha256']}


def stale_worker_cas(fixture):
    with m3.connect('delivery') as connection, connection.cursor() as query:
        attempt_rows = query.execute("UPDATE delivery_attempts SET outcome='PERMANENT_FAILURE' WHERE attempt_id=%s AND job_id=%s AND epoch_no=1 AND worker_id=%s AND completed_at IS NULL",
                                     (fixture['attempt'], fixture['job'], fixture['worker']))
        job_rows = query.execute("UPDATE delivery_jobs SET state='PERMANENT_FAILURE' WHERE job_id=%s AND state='STARTED' AND active_epoch=1 AND worker_id=%s",
                                 (fixture['job'], fixture['worker']))
    return {'attempt_rows': attempt_rows, 'job_rows': job_rows}


def mysql_dump(role, path):
    credentials = go_apps.private()
    container = m3.container('mysql')
    command = [lab.docker(), 'exec', '-e', 'MYSQL_PWD=' + (lab.LAB/'mysql-root').read_text(encoding='utf-8').strip(),
               container, 'mysqldump', '-uroot', '--single-transaction', '--skip-comments',
               '--set-gtid-purged=OFF', '--no-tablespaces', credentials['database'][role]['schema']]
    with path.open('xb') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        raise RuntimeError('mysqldump failed for ' + role + ': ' + result.stderr.decode(errors='replace'))
    return {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}


def mysql_restore(role, path):
    credentials = go_apps.private()
    container = m3.container('mysql')
    command = [lab.docker(), 'exec', '-i', '-e', 'MYSQL_PWD=' + (lab.LAB/'mysql-root').read_text(encoding='utf-8').strip(),
               container, 'mysql', '-uroot', '--binary-mode=1', credentials['database'][role]['schema']]
    with path.open('rb') as source:
        result = subprocess.run(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        raise RuntimeError('mysql restore failed for ' + role + ': ' + result.stderr.decode(errors='replace'))


def dump_all(root, label):
    result = {}
    for role in lab.SERVICES:
        path = root / f'{label}-{role}.sql'
        result[role] = {'path': path.name, **mysql_dump(role, path)}
    return result


def restore_all(root, label):
    for role in lab.SERVICES:
        mysql_restore(role, root / f'{label}-{role}.sql')


def smtp_mail_only(sender='outside@example.test'):
    client = smtplib.SMTP('127.0.0.1', 12525, timeout=15)
    try:
        client.ehlo()
        code, message = client.mail(sender)
        return [code, message.decode(errors='replace')]
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            client.close()


def collect(out):
    source = git('rev-parse', 'HEAD')
    secrets = go_apps.private()
    m3.account('alice', secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'], '甲用户')
    m3.account('bob', secrets['accounts']['bob']['address'], secrets['accounts']['bob']['password'], '乙用户')
    alice = m3.API(); alice.login(secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])

    resource = subprocess.Popen([str(PYTHON), '-B', str(ROOT/'scripts/resource_guard.py'), '--duration', '100', '--runtime', 'go'],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)

    # Durable Outbox survives a real broker pause and drains once without a second job.
    m3.docker_container('pause', 'broker')
    try:
        outbox_draft = m3.draft(alice, 'M5 Outbox ' + uuid.uuid4().hex[:8], ['bob@guihong.test'])
        outbox_intent = m3.send(alice, outbox_draft, 'm5-outbox-' + uuid.uuid4().hex)
        outbox_pending = m3.scalar('mailbox', 'SELECT published_at IS NULL FROM mailbox_outbox WHERE aggregate_id=%s', (outbox_intent['id'],)) == 1
    finally:
        m3.docker_container('unpause', 'broker')
    outbox_result = m3.wait_scope(alice, outbox_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'M5 outbox recovery', 60)
    outbox_jobs = m3.scalar('delivery', 'SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=%s', (outbox_intent['dispatchScopeId'],))

    # Re-seed the completed real intent as a dead pre-DATA worker. Recovery must
    # close epoch 1 and create a distinct worker/epoch before another SMTP action.
    lease_fixture = seed_crashed_attempt(outbox_intent, submitted=False)
    lease_final = m3.wait_until('lease takeover', lambda: (lambda rows: rows if len(rows) >= 2 and rows[-1]['outcome'] else None)(
        m3.rows('delivery', 'SELECT attempt_id,epoch_no,worker_id,last_stage,data_submitted,outcome FROM delivery_attempts WHERE job_id=%s ORDER BY epoch_no', (lease_fixture['job'],))), 50)
    stale_cas = stale_worker_cas(lease_fixture)
    lease_job = m3.rows('delivery', 'SELECT state,attempt_count,active_epoch,worker_id FROM delivery_jobs WHERE job_id=%s', (lease_fixture['job'],))[0]

    # A second real delivery supplies the independent external acceptance fact.
    unknown_draft = m3.draft(alice, 'M5 Lease UNKNOWN ' + uuid.uuid4().hex[:8], ['bob@guihong.test'])
    unknown_intent = m3.send(alice, unknown_draft, 'm5-lease-unknown-' + uuid.uuid4().hex)
    m3.wait_scope(alice, unknown_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'M5 lease unknown seed', 60)
    unknown_raw = m3.rows('mailbox', 'SELECT raw_sha256 FROM send_intents WHERE intent_id=%s', (unknown_intent['id'],))[0]['raw_sha256']
    accepted_before = m3.scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (unknown_raw,))
    unknown_fixture = seed_crashed_attempt(unknown_intent, submitted=True)
    unknown_final = m3.wait_until('submitted lease becomes unknown', lambda: (lambda rows: rows if rows and rows[0]['outcome'] == 'UNKNOWN' else None)(
        m3.rows('delivery', 'SELECT epoch_no,worker_id,last_stage,data_submitted,outcome FROM delivery_attempts WHERE job_id=%s ORDER BY epoch_no', (unknown_fixture['job'],))), 20)
    time.sleep(3)
    accepted_after = m3.scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (unknown_raw,))
    unknown_job = m3.rows('delivery', 'SELECT state,attempt_count,active_epoch FROM delivery_jobs WHERE job_id=%s', (unknown_fixture['job'],))[0]

    # Invalid MQ input reaches a persistent bounded quarantine and does not stop
    # the following valid event from completing.
    poison_payload = json.dumps({'version': 99, 'sourceService': 'mailbox'}, separators=(',', ':'))
    poison_key = 'm5-poison-' + uuid.uuid4().hex
    m3.mq_send(poison_payload, poison_key, out/'poison-send.json')
    poison_digest = sha(poison_payload.encode())
    poison = m3.wait_until('poison quarantine', lambda: (lambda rows: rows[0] if rows else None)(m3.rows('delivery',
        'SELECT payload_sha256,message_key_sha256,reason_code,byte_size,observed_count FROM delivery_quarantine WHERE payload_sha256=%s', (poison_digest,))), 30)
    valid_draft = m3.draft(alice, 'M5 Poison 后续 ' + uuid.uuid4().hex[:8], ['bob@guihong.test'])
    valid_intent = m3.send(alice, valid_draft, 'm5-after-poison-' + uuid.uuid4().hex)
    valid_after_poison = m3.wait_scope(alice, valid_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'valid event after poison', 60)

    resource_stdout, resource_stderr = resource.communicate(timeout=140)
    if resource.returncode:
        raise RuntimeError('resource guard stopped resilience run: ' + resource_stdout + resource_stderr)
    resource_result = json.loads(resource_stdout.strip().splitlines()[-1])
    resource_path = Path(resource_result['evidence'])
    resource_rows = [json.loads(line) for line in resource_path.read_text(encoding='utf-8').splitlines() if line]

    # T0 and T1 are taken with all writers stopped. Restoring only T0 databases
    # leaves the independent witness journals at T1 and must fail closed.
    go_apps.stop()
    t0 = dump_all(out, 't0')
    go_apps.start()
    effect_draft = m3.draft(alice, 'M5 旧快照外部事实 ' + uuid.uuid4().hex[:8], ['bob@guihong.test'])
    effect_intent = m3.send(alice, effect_draft, 'm5-snapshot-' + uuid.uuid4().hex)
    effect_scope = m3.wait_scope(alice, effect_intent['id'], lambda scope: scope['state'] == 'COMPLETED', 'snapshot external effect', 60)
    effect_raw = m3.rows('mailbox', 'SELECT raw_sha256 FROM send_intents WHERE intent_id=%s', (effect_intent['id'],))[0]['raw_sha256']
    effect_count = m3.wait_until('independent next-hop acceptance', lambda: m3.scalar('ingress',
        'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (effect_raw,)), 30)
    external_effect = {'raw_sha256': effect_raw, 'accepted_count': effect_count,
                       'delivery_state': effect_scope['delivery']['recipients'][0]['state']}
    save(out/'external-effect.json', external_effect)
    go_apps.stop()
    t1 = dump_all(out, 't1')
    restore_all(out, 't0')
    go_apps.start()
    old_readiness = {role: readiness(role) for role in lab.SERVICES}
    old_gc = {role: internal_status(role, 'POST', '/internal/storage/gc') for role in lab.SERVICES}
    old_delivery = internal_status('delivery', 'GET', '/internal/dispatch-scopes/' + effect_intent['dispatchScopeId'])
    old_mailbox_write = alice.request('POST', '/api/mailbox/drafts', {'subject':'blocked','textBody':'blocked','htmlBody':'',
        'to':['bob@guihong.test'],'cc':[],'bcc':[],'mode':'COMPOSE','sourceContentId':None})[0]
    old_smtp_mail = smtp_mail_only()
    time.sleep(5)
    old_effect_rows = m3.scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (effect_raw,))
    old_outbox = {role: m3.scalar(role, 'SELECT COUNT(*) FROM '+('mailbox_outbox' if role == 'mailbox' else 'ingress_outbox')+' WHERE published_at IS NULL') for role in ('mailbox','ingress')}

    go_apps.stop()
    restore_all(out, 't1')
    go_apps.start()
    restored_readiness = {role: readiness(role) for role in lab.SERVICES}
    restored_effect_rows = m3.scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (effect_raw,))

    # The current database with only one journal removed is a separate mechanism.
    witness = lab.LAB/'witness'/'mailbox'/'transactions.log'
    witness_backup = out/'mailbox-transactions.log.exact'
    go_apps.stop(roles=['mailbox'])
    shutil.copy2(witness, witness_backup)
    os.remove(witness)
    go_apps.start(roles=['mailbox'])
    missing_readiness = readiness('mailbox')
    missing_gc = internal_status('mailbox', 'POST', '/internal/storage/gc')
    go_apps.stop(roles=['mailbox'])
    shutil.copy2(witness_backup, witness)
    go_apps.start(roles=['mailbox'])
    witness_restored = readiness('mailbox')
    witness_effect_rows = m3.scalar('ingress', 'SELECT COUNT(*) FROM accepted_spools WHERE raw_sha256=%s', (effect_raw,))

    resource_facts = {'file': resource_path.name, 'samples': len(resource_rows),
        'full_topology_samples': sum(bool(row['full_topology']) for row in resource_rows),
        'stop_reasons': [row['stop_reason'] for row in resource_rows if row['stop_reason']],
        'max_host_used_bytes': max(row['memory']['used_bytes'] for row in resource_rows),
        'max_application_rss_bytes': max(p['rss_bytes'] for row in resource_rows for p in row['processes']),
        'min_container_memory_headroom_ratio': min(c['memory_headroom_ratio'] for row in resource_rows for c in row['containers'] if c['running']),
        'min_container_pid_headroom': min(c['pid_headroom'] for row in resource_rows for c in row['containers'] if c['running'])}
    facts = {'source_sha': source, 'boundary':'M5_RESILIENCE_COUNTEREXAMPLES_ONLY',
        'outbox': {'pending_during_outage':outbox_pending,'final':outbox_result['delivery'],'job_count':outbox_jobs},
        'lease': {'fixture':lease_fixture,'attempts':lease_final,'job':lease_job,'stale_cas':stale_cas},
        'lease_unknown': {'fixture':unknown_fixture,'attempts':unknown_final,'job':unknown_job,
                          'accepted_before':accepted_before,'accepted_after':accepted_after},
        'poison': {'row':poison,'valid_followup':valid_after_poison['delivery']},
        'snapshot': {'t0':t0,'t1':t1,'external_effect':external_effect,'old_readiness':old_readiness,
                     'old_gc':old_gc,'old_delivery':old_delivery,'old_mailbox_write':old_mailbox_write,
                     'old_smtp_mail':old_smtp_mail,'old_effect_rows':old_effect_rows,'old_outbox':old_outbox,
                     'restored_readiness':restored_readiness,'restored_effect_rows':restored_effect_rows},
        'missing_witness': {'backup_sha256':sha(witness_backup.read_bytes()),'missing_readiness':missing_readiness,
                            'missing_gc':missing_gc,'restored_readiness':witness_restored,
                            'effect_rows':witness_effect_rows},
        'resource':resource_facts}
    facts['cases'] = {
        'M5R-01': outbox_pending and outbox_result['delivery']['state']=='COMPLETED' and outbox_jobs==1,
        'M5R-02': len(lease_final)==2 and lease_final[0]['epoch_no']==1 and lease_final[0]['outcome']=='TEMPORARY_FAILURE' and lease_final[1]['epoch_no']==2 and lease_final[1]['worker_id']!=lease_fixture['worker'] and lease_job['active_epoch']==2 and stale_cas=={'attempt_rows':0,'job_rows':0},
        'M5R-03': unknown_final[0]['data_submitted']==1 and unknown_final[0]['outcome']=='UNKNOWN' and unknown_job['state']=='UNKNOWN' and unknown_job['attempt_count']==1 and accepted_before==accepted_after==1,
        'M5R-04': poison['reason_code']=='INVALID_SEND_EVENT' and poison['observed_count']==1 and valid_after_poison['delivery']['state']=='COMPLETED',
        'M5R-05': len(resource_rows)>=18 and resource_facts['full_topology_samples']>=18 and not resource_facts['stop_reasons'] and resource_facts['max_host_used_bytes']<14*1024**3 and resource_facts['min_container_memory_headroom_ratio']>=.10 and resource_facts['min_container_pid_headroom']>=16,
        'M5R-06': all(item['http']==503 and item['body']['state']=='NOT_RECONCILED' for item in old_readiness.values()) and all(item['http']==503 for item in old_gc.values()) and old_delivery['http']==503 and old_mailbox_write==503 and old_smtp_mail[0]==451 and old_effect_rows==0 and external_effect['accepted_count']==1,
        'M5R-07': all(item['http']==200 and item['body']['state']=='READY' for item in restored_readiness.values()) and restored_effect_rows==1,
        'M5R-08': missing_readiness['http']==503 and missing_readiness['body']['state']=='NOT_RECONCILED' and missing_gc['http']==503,
        'M5R-09': witness_restored['http']==200 and witness_restored['body']['state']=='READY' and witness_effect_rows==1,
        'M5R-10': external_effect['delivery_state']=='NEXT_HOP_ACCEPTED' and old_outbox=={'mailbox':0,'ingress':0},
    }
    return facts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--control',choices=['none','wrong-binding','missing-evidence'],default='none');parser.add_argument('--facts-from');args=parser.parse_args()
    if git('status','--porcelain') or version('veritrail')!='0.13.0':
        raise RuntimeError('M5 resilience evidence requires clean exact source and locked public Core')
    if args.facts_from and args.control=='none':raise RuntimeError('Reusing facts is limited to negative controls')
    source=git('rev-parse','HEAD');run='guihong-m5r-'+uuid.uuid4().hex;out=lab.local_run(run,create=True)
    request={'source_sha':source,'plan_sha256':sha((ROOT/'docs/m5-plan.md').read_bytes()),
             'resource_contract_sha256':sha((ROOT/'docs/m1-resource-contract-1.2.md').read_bytes()),
             'control':args.control,'facts_from':args.facts_from}
    spec={'id':'m5-resilience','contract':{'id':'guihong-m5-resilience','version':'1.0'},'evidence_type':'guihong.m5.resilience',
          'coordinates':request,'projections':['source_sha','cases','outbox','lease','lease_unknown','poison','snapshot','missing_witness','resource','boundary'],
          'canonicalization_profile':'veritrail-json-c14n/1'}
    assertions=[{'id':case.lower(),'severity':'HARD','left':{'requirement_id':'m5r','path':'/facts/cases/'+case},'operator':'eq','right':True} for case in [f'M5R-{n:02d}' for n in range(1,11)]]
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m5-resilience','version':1,
        'subject':{'id':'guihong-m5-resilience-candidate','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the exact candidate fail closed for leases, poison messages, old snapshots and missing witnesses?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:m5-resilience-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'m5r','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'m5r','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':80*1024*1024,'max_probe_seconds':900},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M5','consumers':['m5-stage-gate']},
        'reproduction_steps':['Use an exact clean build in one fresh owned lab.','Execute the fixed outage, lease, poison, T0/T1 and missing-journal sequence.'],
        'cleanup_steps':['Restore T1 databases and exact witness before normal shutdown.','Retain dumps and first failure privately; remove only exact owned resources.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',request);status='COMPLETED';error=None
    try:
        if args.facts_from:
            source_path=(ROOT/args.facts_from).resolve();local=(ROOT/'artifacts/local').resolve()
            if not source_path.is_file() or not source_path.is_relative_to(local):raise RuntimeError('Control facts must be retained local evidence')
            facts=json.loads(source_path.read_text(encoding='utf-8'))['facts']
            if facts.get('source_sha')!=source or not all(facts.get('cases',{}).values()):raise RuntimeError('Control facts are not a same-source complete PASS candidate')
        else:facts=collect(out)
    except Exception as failure:
        status='ERROR';error={'exception_type':type(failure).__name__,'message':str(failure),'traceback':traceback.format_exc()};facts={'source_sha':source,'cases':{},'boundary':'M5_RESILIENCE_COUNTEREXAMPLES_ONLY'};save(out/'collection-error.json',error)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
              'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(request),
              'collection_session_id':run,'collector_role':'guihong-m5-resilience-collector','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR',
              'normalization_semantics_version':'guihong-m5-resilience/1.0','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding':metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-m5-resilience/1.0','captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],'expected':expected,'control':args.control,'bundle':(out/'bundle').relative_to(ROOT).as_posix()}
    save(out/'summary.json',summary);print(json.dumps(summary));return 0 if status=='COMPLETED' and report['verdict']==expected else 1


if __name__=='__main__':raise SystemExit(main())
