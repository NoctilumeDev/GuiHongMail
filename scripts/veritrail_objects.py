"""Actual M1 A05 object/ref/GC/recovery qualification with one native COMMIT ambiguity."""
from datetime import datetime,timezone
import base64
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import pymysql
from veritrail.acceptance_plan import observation_spec_digest,seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json
import apps,lab

ROOT=lab.ROOT
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def sha(data):return hashlib.sha256(data).hexdigest()
def save(path,value):lab.write_new(path,json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def save_bytes(path,value):
    with path.open('xb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
def wait_port(port,up=True,seconds=30):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        with socket.socket() as probe:actual=probe.connect_ex(('127.0.0.1',port))==0
        if actual==up:return
        time.sleep(.25)
    raise RuntimeError('Port readiness deadline exceeded')

def main():
    if git('status','--porcelain') or version('veritrail')!='0.13.0' or version('boto3')!='1.43.112':raise RuntimeError('Clean exact source and locked public dependencies required')
    source=git('rev-parse','HEAD');run='guihong-objects-'+uuid.uuid4().hex;out=lab.local_run(run,create=True)
    request={'source_sha':source,'lab_id':lab.load()['id'],'contract_sha256':sha((ROOT/'docs/m1-plan.md').read_bytes()),
        'component_sha256':sha((ROOT/'docs/m1-components.md').read_bytes()),'proxy_port':23306,
        'object_ids':{name:str(uuid.uuid4()) for name in ['mailbox','ingress','delivery','put_failure','rollback','unknown']}}
    spec={'id':'objects-observation','contract':{'id':'guihong-objects','version':'1.0'},'evidence_type':'guihong.objects',
        'coordinates':request,'projections':['source_sha','positive','put_failure','known_rollback','commit_unknown','gc','integrity','journal_recovery','final_cleanup'],
        'canonicalization_profile':'veritrail-json-c14n/1'}
    def hard(id,path,value):return {'id':id,'severity':'HARD','left':{'requirement_id':'objects','path':'/facts/'+path},'operator':'eq','right':value}
    assertions=[hard('source','source_sha',source),hard('clean','source_clean',True),hard('contract','contract_sha256',request['contract_sha256']),hard('component','component_sha256',request['component_sha256'])]
    for role in lab.SERVICES:
        assertions += [hard(role+'-stage','positive/'+role+'/stage_http',200),hard(role+'-reference','positive/'+role+'/reference_http',200),
            hard(role+'-read','positive/'+role+'/read_http',200),hard(role+'-bytes','positive/'+role+'/read_sha256',sha((role+'|'+run+'|归鸿对象').encode())),
            hard(role+'-deref','positive/'+role+'/dereference_http',204),hard(role+'-gc','positive/'+role+'/database_state','DELETED'),hard(role+'-absent','positive/'+role+'/s3_after_gc',404)]
    assertions += [hard('put-failed-http','put_failure/http',503),hard('put-failed-orphan','put_failure/database_state','ORPHAN'),hard('put-failed-no-object','put_failure/s3_http',404),
        hard('rollback-http','known_rollback/http',503),hard('rollback-orphan','known_rollback/database_state','ORPHAN'),hard('rollback-object-retained','known_rollback/s3_http',200),hard('rollback-zero-ref','known_rollback/ref_count',0),
        hard('unknown-http','commit_unknown/http',503),hard('unknown-journal','commit_unknown/journal_outcome','U'),hard('unknown-journal-count','commit_unknown/journal_new_records',2),
        hard('unknown-journal-binding','commit_unknown/journal_transaction_bound',True),hard('unknown-database-binding','commit_unknown/database_receipt_bound',True),
        hard('unknown-db-object','commit_unknown/database_state','LIVE'),hard('unknown-db-ref','commit_unknown/ref_count',1),hard('unknown-s3','commit_unknown/s3_http',200),hard('unknown-blocks','commit_unknown/readiness_after/http',503),
        hard('unknown-reconciles','commit_unknown/readiness_restart/http',200),hard('unknown-read','commit_unknown/read_after_restart_sha256',sha(('unknown|'+run+'|归鸿对象').encode())),hard('unknown-gc-protected','commit_unknown/current_object_protected',True),
        hard('gc-failure','gc/failure_http',503),hard('gc-deleting','gc/state_after_failure','DELETING'),hard('gc-retry','gc/retry_http',200),hard('gc-bounded','gc/deleted_count',5),
        hard('corrupt-read','integrity/read_http',503),hard('corrupt-block','integrity/readiness_after/http',503),hard('corrupt-restore','integrity/readiness_restart/http',200),
        hard('journal-missing','journal_recovery/readiness_missing/http',503),hard('journal-restored','journal_recovery/readiness_restored/http',200),
        hard('cleanup-deref','final_cleanup/dereference_http',204),hard('cleanup-gc','final_cleanup/gc_http',200),
        hard('cleanup-state','final_cleanup/database_state','DELETED'),hard('cleanup-object','final_cleanup/s3_http',404)]
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m1-objects','version':1,
        'subject':{'id':'guihong-m1-a05','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Do standard S3 application writes, refs, native commit ambiguity, bounded GC and recovery fail closed under the declared M1 mechanisms?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:objects-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'objects','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'objects','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':3145728,'max_probe_seconds':600,'max_gc_items':50},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M1 A05','consumers':['object-lifecycle','recovery-foundation']},
        'reproduction_steps':['Start the exact clean candidate and owned local dependencies after full-lab admission.','Run this collector with locked public Core, boto3 and PyMySQL.'],
        'cleanup_steps':['Restore every injected dependency or exact synthetic object before exit; stop applications.','Preserve first failures, COMMIT U witness, proxy facts and database evidence; never reset/adopt.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',request)
    credentials=apps.private();events=out/'source-events.jsonl';begin=time.monotonic()
    def event(value):
        with events.open('a',encoding='utf-8',newline='\n') as f:f.write(json.dumps({'time':datetime.now(timezone.utc).isoformat(),**value},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    def call(role,path,method='GET',body=None,timeout=15):
        headers={'Content-Type':'application/json'}
        data=None if body is None else json.dumps(body).encode()
        status,response_headers,raw=apps.owned_http(role,path,method=method,body=data,headers=headers,
            internal=True,max_bytes=6*1024*1024)
        kind=response_headers.get_content_type()
        value=json.loads(raw) if raw and kind=='application/json' else None
        result={'http':status,'bytes':len(raw),'sha256':sha(raw)}
        event({'service':role,'method':method,'path':path,'result':result})
        return result,value,raw
    def s3(role):
        item=credentials['storage'][role]
        return boto3.client('s3',endpoint_url='http://127.0.0.1:19833',region_name='us-east-1',aws_access_key_id=item['access_key'],aws_secret_access_key=item['secret_key'],config=Config(signature_version='s3v4',s3={'addressing_style':'path'},proxies={},connect_timeout=3,read_timeout=10,retries={'max_attempts':0}))
    def s3_get(role,key,body_path=None):
        try:
            response=s3(role).get_object(Bucket=credentials['storage'][role]['bucket'],Key=key);data=response['Body'].read(5242881);http=response['ResponseMetadata']['HTTPStatusCode']
            if body_path:save_bytes(body_path,data)
            return {'http':http,'bytes':len(data),'sha256':sha(data)}
        except ClientError as error:return {'http':error.response['ResponseMetadata']['HTTPStatusCode']}
    def db(role,object_id):
        item=credentials['database'][role]
        with pymysql.connect(host='127.0.0.1',port=13306,user=item['user'],password=item['password'],database=item['schema']) as c:
            with c.cursor() as q:
                q.execute('SELECT object_key,lifecycle,in_flight,sha256 FROM stored_objects WHERE object_id=%s',(object_id,));row=q.fetchone()
                q.execute('SELECT COUNT(*) FROM object_refs WHERE object_id=%s',(object_id,));refs=q.fetchone()[0]
        return {'object_key':row[0],'database_state':row[1],'in_flight':row[2],'sha256':row[3],'ref_count':refs}
    def stage(role,name,payload):return call(role,'/internal/storage/objects','POST',{'objectId':request['object_ids'][name],'authority':'qualification:'+run,'base64':base64.b64encode(payload).decode()})
    def reference(role,name,kind='qualification'):return call(role,f"/internal/storage/objects/{request['object_ids'][name]}/references",'POST',{'kind':kind,'referenceId':run})
    def dereference(role,name):return call(role,f"/internal/storage/objects/{request['object_ids'][name]}/references",'DELETE',{'kind':'qualification','referenceId':run})
    def require_http(label,result,expected):
        if result[0]['http']!=expected:raise RuntimeError(f'{label} returned HTTP {result[0]["http"]}, expected {expected}')
    facts={'source_sha':source,'source_clean':True,'contract_sha256':request['contract_sha256'],'component_sha256':request['component_sha256'],'boundary':'M1_A05_OBJECTS_RECOVERY'}
    status='COMPLETED';proxy=None;mailbox_running=False
    try:
        proxy_root=lab.LAB/('mysql-commit-proxy-'+run);proxy_log=out/'mysql-commit-proxy.log'
        with proxy_log.open('xb') as log:
            proxy=subprocess.Popen([str(Path('D:/python-3.10.6/python.exe')),str(ROOT/'scripts/mysql_commit_proxy.py'),'--port',str(request['proxy_port']),'--root',str(proxy_root)],cwd=ROOT,env=apps.environment(),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        until=time.monotonic()+10
        while time.monotonic()<until and not (proxy_root/'ready').exists():
            if proxy.poll() is not None:raise RuntimeError('Owned MySQL fault proxy exited before readiness')
            time.sleep(.1)
        if not (proxy_root/'ready').exists():raise RuntimeError('Owned MySQL fault proxy readiness timeout')
        apps.start({'mailbox':request['proxy_port']});mailbox_running=True
        facts['positive']={}
        for role in lab.SERVICES:
            payload=(role+'|'+run+'|归鸿对象').encode();name=role
            staged=stage(role,name,payload);require_http(role+' positive stage',staged,200)
            referenced=reference(role,name);require_http(role+' positive reference',referenced,200)
            read=call(role,f"/internal/storage/objects/{request['object_ids'][name]}");require_http(role+' positive read',read,200)
            save_bytes(out/(role+'-application-read.body'),read[2])
            deref=dereference(role,name);require_http(role+' positive dereference',deref,204)
            facts['positive'][role]={'stage_http':staged[0]['http'],'reference_http':referenced[0]['http'],'read_http':read[0]['http'],'read_sha256':read[0]['sha256'],'dereference_http':deref[0]['http'],**db(role,request['object_ids'][name])}
        # Prove a PUT connection refusal never creates an object and becomes a known orphan.
        lab.compose(['stop','--timeout','20','seaweedfs'],capture=True);wait_port(19833,False)
        put_result=stage('mailbox','put_failure',('put_failure|'+run).encode())
        lab.compose(['up','-d','seaweedfs'],capture=True);wait_port(19833,True)
        until=time.monotonic()+30
        while time.monotonic()<until:
            ready=call('mailbox','/health/ready')[0]
            if ready['http']==200:break
            time.sleep(.5)
        if ready['http']!=200:raise RuntimeError('Mailbox did not reconcile after SeaweedFS restart')
        put_db=db('mailbox',request['object_ids']['put_failure']);facts['put_failure']={'http':put_result[0]['http'],**put_db,**{'s3_http':s3_get('mailbox',put_db['object_key'])['http']}}
        # A deterministic SQL constraint error occurs only after successful PUT and GET/hash.
        rollback_payload=('rollback|'+run+'|归鸿对象').encode();require_http('rollback stage',stage('mailbox','rollback',rollback_payload),200)
        rollback=reference('mailbox','rollback','x'*40);rollback_db=db('mailbox',request['object_ids']['rollback']);rollback_s3=s3_get('mailbox',rollback_db['object_key'],out/'rollback-retained.body')
        facts['known_rollback']={'http':rollback[0]['http'],**rollback_db,'s3_http':rollback_s3['http'],'s3_sha256':rollback_s3.get('sha256')}
        # Forward COMMIT upstream, close only the downstream response, then read DB and S3 independently.
        unknown_payload=('unknown|'+run+'|归鸿对象').encode();require_http('commit-unknown stage',stage('mailbox','unknown',unknown_payload),200)
        journal_path=lab.LAB/'witness/mailbox/transactions.log';journal_before=journal_path.read_text(encoding='utf-8').splitlines()
        expected_tx_digest=sha(('object-reference|'+request['object_ids']['unknown']+'|qualification|'+run+'|'+sha(unknown_payload)).encode())
        lab.write_new(proxy_root/'arm','drop exactly one COMMIT response\n')
        unknown_call=reference('mailbox','unknown');unknown_db=db('mailbox',request['object_ids']['unknown']);unknown_s3=s3_get('mailbox',unknown_db['object_key'],out/'unknown-retained.body')
        journal=journal_path.read_text(encoding='utf-8').splitlines();new_rows=[row.split('|') for row in journal[len(journal_before):]]
        transaction_bound=(len(new_rows)==2 and all(len(row)==6 for row in new_rows)
            and new_rows[0][1]==new_rows[1][1] and new_rows[0][0]==new_rows[1][0]
            and [new_rows[0][2],new_rows[1][2]]==['P','U']
            and new_rows[0][3]==expected_tx_digest==new_rows[1][3])
        tx_id=new_rows[0][1] if transaction_bound else ''
        with pymysql.connect(host='127.0.0.1',port=13306,user=credentials['database']['mailbox']['user'],password=credentials['database']['mailbox']['password'],database=credentials['database']['mailbox']['schema']) as connection:
            with connection.cursor() as query:query.execute('SELECT sequence_no,payload_sha256 FROM tx_receipts WHERE tx_id=%s',(tx_id,));receipt=query.fetchone()
        database_bound=bool(receipt and str(receipt[0])==new_rows[0][0] and receipt[1]==expected_tx_digest) if transaction_bound else False
        outcome=new_rows[1][2] if transaction_bound else 'UNBOUND'
        readiness_after=call('mailbox','/health/ready')[0]
        facts['commit_unknown']={'http':unknown_call[0]['http'],'journal_outcome':outcome,'journal_new_records':len(new_rows),
            'journal_transaction_bound':transaction_bound,'database_receipt_bound':database_bound,'transaction_id_sha256':sha(tx_id.encode()) if tx_id else None,
            **unknown_db,'s3_http':unknown_s3['http'],'s3_sha256':unknown_s3.get('sha256'),'readiness_after':readiness_after}
        require_http('commit-unknown reference',unknown_call,503)
        if outcome!='U' or not transaction_bound or not database_bound:raise RuntimeError('Commit-unknown witness did not bind the exact transaction')
        apps.stop();mailbox_running=False
        lab.write_new(proxy_root/'stop','normal exact proxy stop\n');proxy.wait(10)
        apps.start();mailbox_running=True
        facts['commit_unknown']['readiness_restart']=call('mailbox','/health/ready')[0]
        read=call('mailbox',f"/internal/storage/objects/{request['object_ids']['unknown']}");save_bytes(out/'unknown-application-read.body',read[2]);facts['commit_unknown']['read_after_restart_sha256']=read[0]['sha256']
        protected_gc=call('mailbox','/internal/storage/gc','POST')[1]['deleted']
        facts['commit_unknown']['current_object_protected']=request['object_ids']['unknown'] not in protected_gc
        facts['commit_unknown']['other_recovered_count']=len(protected_gc)
        # Wait for the approved grace without blocking status communication from the caller.
        grace_deadline=time.monotonic()+62
        while time.monotonic()<grace_deadline:
            if lab.memory()['used_bytes']>14*1024**3:raise RuntimeError('Host memory stop line during GC grace')
            time.sleep(2)
        # First GC delete fails and remains DELETING; restart makes the same operation reentrant.
        lab.compose(['stop','--timeout','20','seaweedfs'],capture=True);wait_port(19833,False)
        gc_failure=call('mailbox','/internal/storage/gc','POST');oldest=request['object_ids']['mailbox'];after_failure=db('mailbox',oldest)
        lab.compose(['up','-d','seaweedfs'],capture=True);wait_port(19833,True);time.sleep(2)
        gc_retry=call('mailbox','/internal/storage/gc','POST');deleted=list(gc_retry[1]['deleted'])
        for role in ('ingress','delivery'):
            role_gc=call(role,'/internal/storage/gc','POST');deleted.extend(role_gc[1]['deleted'])
        expected_gc_ids={request['object_ids'][name] for name in ('mailbox','ingress','delivery','put_failure','rollback')}
        own_deleted=[item for item in deleted if item in expected_gc_ids]
        facts['gc']={'failure_http':gc_failure[0]['http'],'state_after_failure':after_failure['database_state'],'retry_http':gc_retry[0]['http'],
            'deleted_count':len(own_deleted),'deleted_ids':own_deleted,'other_recovered_count':len(deleted)-len(own_deleted)}
        for role in lab.SERVICES:
            row=db(role,request['object_ids'][role]);facts['positive'][role]['database_state']=row['database_state'];facts['positive'][role]['s3_after_gc']=s3_get(role,row['object_key'])['http']
        for name in ('put_failure','rollback'):
            fact_name='known_rollback' if name=='rollback' else name
            row=db('mailbox',request['object_ids'][name]);facts[fact_name]['database_state_after_gc']=row['database_state'];facts[fact_name]['s3_after_gc']=s3_get('mailbox',row['object_key'])['http']
        # Missing referenced bytes block reads/GC until exact bytes are restored and startup reconciles.
        s3('mailbox').delete_object(Bucket=credentials['storage']['mailbox']['bucket'],Key=unknown_db['object_key'])
        corrupt=call('mailbox',f"/internal/storage/objects/{request['object_ids']['unknown']}");corrupt_ready=call('mailbox','/health/ready')[0]
        facts['integrity']={'read_http':corrupt[0]['http'],'readiness_after':corrupt_ready}
        s3('mailbox').put_object(Bucket=credentials['storage']['mailbox']['bucket'],Key=unknown_db['object_key'],Body=unknown_payload)
        apps.stop();mailbox_running=False;apps.start();mailbox_running=True
        facts['integrity']['readiness_restart']=call('mailbox','/health/ready')[0]
        # Exact missing-journal challenge, with byte-for-byte restoration after fail-closed observation.
        apps.stop();mailbox_running=False;journal_path=lab.LAB/'witness/mailbox/transactions.log';fault_path=lab.LAB/'witness/mailbox/transactions.log.m1-fault'
        if fault_path.exists():raise RuntimeError('Pre-existing witness fault coordinate')
        os.replace(journal_path,fault_path);apps.start();mailbox_running=True
        missing=call('mailbox','/health/ready')[0];facts['journal_recovery']={'readiness_missing':missing}
        apps.stop();mailbox_running=False;os.replace(fault_path,journal_path);apps.start();mailbox_running=True
        facts['journal_recovery']['readiness_restored']=call('mailbox','/health/ready')[0]
        cleanup_deref=dereference('mailbox','unknown');cleanup_gc=call('mailbox','/internal/storage/gc','POST')
        cleanup_db=db('mailbox',request['object_ids']['unknown'])
        facts['final_cleanup']={'dereference_http':cleanup_deref[0]['http'],'gc_http':cleanup_gc[0]['http'],**cleanup_db,
            's3_http':s3_get('mailbox',cleanup_db['object_key'])['http']}
    except Exception as error:
        status='ERROR';save(out/'collection-error.json',{'exception':type(error).__name__,'message':str(error)})
    finally:
        if mailbox_running:
            try:apps.stop()
            except Exception as cleanup:save(out/'application-cleanup-error.json',{'exception':type(cleanup).__name__,'message':str(cleanup)})
        if proxy is not None and proxy.poll() is None:
            try:
                if 'proxy_root' in locals() and proxy_root.exists() and not (proxy_root/'stop').exists():lab.write_new(proxy_root/'stop','cleanup stop\n')
                proxy.wait(10)
            except Exception:proxy.terminate()
    facts['source_sha']=git('rev-parse','HEAD');facts['source_clean']=not bool(git('status','--porcelain'));save(out/'facts.json',facts)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],'observation_spec_digest':observation_spec_digest(spec),
        'request_seal_digest':sha256_json(request),'collection_session_id':run,'collector_role':'guihong-objects-collector','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR',
        'normalization_semantics_version':'guihong-objects/1.1','facts_digest':sha256_json(facts)}
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-objects/1.1','captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    summary={'run_id':run,'source_sha':source,'execution':status,'verdict':report['verdict'],'boundary':facts['boundary'],'bundle':str(out/'bundle')};save(out/'summary.json',summary);print(json.dumps(summary))
    return 0 if status=='COMPLETED' and report['verdict']=='PASS' else 1

if __name__=='__main__':sys.exit(main())
