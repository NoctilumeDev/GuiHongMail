"""Finite M1 foundation/identity/SMTP witnesses. Seal first; preserve primitive source facts."""
from datetime import datetime,timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import smtplib
import subprocess
import sys
import time
import uuid
import pymysql
from veritrail.acceptance_plan import observation_spec_digest,seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json
import apps,lab

ROOT=lab.ROOT
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def sha(bytes):return hashlib.sha256(bytes).hexdigest()
def save(path,value):lab.write_new(path,json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')

def main():
    if git('status','--porcelain') or version('veritrail')!='0.13.0':raise RuntimeError('Clean exact source and public locked Core required')
    source=git('rev-parse','HEAD');run='guihong-foundation-'+uuid.uuid4().hex;out=lab.local_run(run,create=True)
    expected={'source_sha':source,'lab_id':lab.load()['id'],'component_sha256':sha((ROOT/'docs/m1-components.md').read_bytes()),
        'contract_sha256':sha((ROOT/'docs/m1-plan.md').read_bytes()),'mq_topic':lab.load()['id'].replace('-','_')+'_probe_'+uuid.uuid4().hex[:12],
        'jars':{r:sha((ROOT/'backend'/apps.MODULES[r]/'target'/(apps.MODULES[r]+'-0.1.0-SNAPSHOT.jar')).read_bytes()) for r in lab.SERVICES}}
    spec={'id':'foundation-observation','contract':{'id':'guihong-foundation','version':'1.0'},'evidence_type':'guihong.foundation',
        'coordinates':expected,'projections':['source_sha','startup','database','sessions','smtp','mq','drain','shutdown'],
        'canonicalization_profile':'veritrail-json-c14n/1'}
    def hard(id,path,value):return {'id':id,'severity':'HARD','left':{'requirement_id':'foundation','path':'/facts/'+path},'operator':'eq','right':value}
    assertions=[hard('exact-source','source_sha',source),hard('clean','source_clean',True),hard('component','component_sha256',expected['component_sha256'])]
    for r in lab.SERVICES:
        assertions+=[hard(r+'-role','startup/'+r+'/service',r),hard(r+'-source','startup/'+r+'/source_sha',source),hard(r+'-state','startup/'+r+'/state','READY'),
            hard(r+'-ready','readiness/'+r+'/http',200),hard(r+'-jar','startup_jars/'+r,expected['jars'][r]),hard(r+'-own-db','database/'+r+'/own_crud','ROLLED_BACK'),
            hard(r+'-wrong-token','internal_wrong/'+r+'/http',401),hard(r+'-no-token','internal_anonymous/'+r+'/http',401),
            hard(r+'-db-read','database/'+r+'/read_hash',sha(r.encode())),hard(r+'-db-delete','database/'+r+'/deleted_rows',1),
            hard(r+'-storage-down','dependency_down/'+r+'/http',503),hard(r+'-storage-restored','dependency_restored/'+r+'/http',200),hard(r+'-drain','drain/'+r+'/http',200),hard(r+'-shutdown','shutdown/'+r,True)]
    for i in range(12):assertions.append(hard('cross-db-'+str(i),'cross_database/'+str(i)+'/error_code',1142))
    for name,code in {'alice_login':200,'bob_login':200,'invalid_login':401,'unknown_account':401,'alice_me':200,'alice_reads_bob':404,
        'cookie_internal':401,'origin_login':403,'csrf_refresh':403,'refresh':200,'old_after_refresh':401,'logout':204,'after_logout':401,
        'bob_disabled':401,'rate_limit':429,'correct_after_rate_limit':200,'drained_login':503}.items():assertions.append(hard('http-'+name,'sessions/'+name+'/http',code))
    assertions+=[hard('uniform-login-feedback','sessions/invalid_login/body',{'code':'AUTHENTICATION_FAILED'}),hard('uniform-unknown-feedback','sessions/unknown_account/body',{'code':'AUTHENTICATION_FAILED'}),
        hard('http-only','session_attributes/httponly',True),hard('same-site','session_attributes/samesite','Strict'),hard('cookie-path','session_attributes/path','/api'),
        hard('external-relay','smtp/external_rcpt',550),hard('no-false-accept','smtp/local_rcpt',451),hard('no-data-responsibility','smtp/data',503),
        hard('mq-send','mq/send_status','SEND_OK'),hard('mq-pull','mq/pull_status','FOUND'),hard('mq-body','mq/received_sha256',sha(('归鸿真实 MQ 见证|'+expected['mq_topic']).encode())),
        hard('mq-cleanup','mq/cleanup','EXACT_CREATED_TOPIC_AND_GROUP'),hard('broker-budget','broker/memory_limit',512*1024**2),hard('broker-no-oom','broker/oom_killed',False),hard('broker-pid-budget','broker/pid_limit',128)]
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m1-foundation','version':2,
        'subject':{'id':'guihong-m1-foundation-identity-smtp','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Do independent services, actual database identities, bounded sessions, rejecting SMTP and actual ordinary MQ satisfy M1 foundation obligations?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:foundation-collector','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'foundation','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'foundation','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':2097152,'max_probe_seconds':600},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M1','consumers':['foundation','identity','smtp-foundation']},
        'reproduction_steps':['Build exact clean candidate with scripts/apps.py build; preserve owned virgin preparation and witness.','Run this collector in separately installed locked public Core environment.'],
        'cleanup_steps':['Normal owned app shutdown; dependency outage is restored; retain all first failures and durable witness.','Only exact probe topic/group created in this run may be removed.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',expected)
    begin=time.monotonic();credentials=apps.private();events=out/'source-events.jsonl'
    def event(value):
        with events.open('a',encoding='utf-8',newline='\n') as f:f.write(json.dumps({'time':datetime.now(timezone.utc).isoformat(),**value},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    def call(role,path,method='GET',body=None,cookie=None,csrf=None,internal=False,wrong_token=False,origin='http://127.0.0.1:18080'):
        if time.monotonic()-begin>600:raise RuntimeError('Foundation time budget exceeded')
        headers={'Content-Type':'application/json'}
        if origin is not None:headers['Origin']=origin
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-GuiHong-CSRF']=csrf
        if internal and wrong_token:headers.update({'X-GuiHong-Service':'lab','Authorization':'Bearer wrong-token'})
        data=None if body is None else json.dumps(body).encode()
        status,response_headers,raw=apps.owned_http(role,path,method=method,body=data,headers=headers,
            internal=internal and not wrong_token,max_bytes=1048577)
        value=json.loads(raw) if raw else None;set_cookie=response_headers.get('Set-Cookie')
        public=value
        if isinstance(public,dict):
            # Only public protocol observations, never nonce values or address material.
            public={k:v for k,v in public.items() if k!='csrf'}
            if isinstance(public.get('user'),dict):public['user']={k:v for k,v in public['user'].items() if k!='address'}
            public.pop('address',None)
        result={'http':status,'body':public}
        event({'method':method,'service':role,'path':path,'result':result,'response_bytes':len(raw),'response_sha256':sha(raw)})
        return result,value,set_cookie
    facts={'source_sha':source,'source_clean':True,'component_sha256':expected['component_sha256'],'boundary':'M1_FOUNDATION_IDENTITY_SMTP_ONLY'}
    status='COMPLETED';bob_id=None
    try:
        apps.start();facts['startup']={r:apps.request(r,'/internal/identity') for r in lab.SERVICES}
        facts['startup_jars']={r:json.loads((apps.PROCESSES/(r+'.json')).read_text())['jar_sha256'] for r in lab.SERVICES}
        facts['readiness']={r:call(r,'/health/ready')[0] for r in lab.SERVICES}
        facts['internal_wrong']={r:call(r,'/internal/identity',internal=True,wrong_token=True)[0] for r in lab.SERVICES}
        facts['internal_anonymous']={r:call(r,'/internal/identity')[0] for r in lab.SERVICES}
        facts['database']={};facts['cross_database']=[]
        for r in lab.SERVICES:
            db=credentials['database'][r]
            with pymysql.connect(host='127.0.0.1',port=13306,user=db['user'],password=db['password'],database=db['schema'],connect_timeout=3) as c:
                with c.cursor() as q:
                    q.execute('SELECT DATABASE(),CURRENT_USER(),VERSION()');binding=q.fetchone();identity=str(uuid.uuid4())
                    q.execute('INSERT INTO tx_receipts(tx_id,sequence_no,payload_sha256) VALUES(%s,%s,%s)',(identity,999999,sha(run.encode())))
                    q.execute('UPDATE tx_receipts SET payload_sha256=%s WHERE tx_id=%s',(sha(r.encode()),identity))
                    q.execute('SELECT payload_sha256 FROM tx_receipts WHERE tx_id=%s',(identity,));actual=q.fetchone()[0]
                    q.execute('DELETE FROM tx_receipts WHERE tx_id=%s',(identity,));deleted=q.rowcount;c.rollback()
                    facts['database'][r]={'binding':binding,'read_hash':actual,'deleted_rows':deleted,'own_crud':'ROLLED_BACK'}
                    for target in lab.SERVICES:
                        if target==r:continue
                        for action,sql in [('SELECT',f'SELECT * FROM guihong_{target}.tx_receipts LIMIT 1'),('INSERT',f"INSERT INTO guihong_{target}.tx_receipts(tx_id,sequence_no,payload_sha256) VALUES('{identity}',999999,'{'0'*64}')")]:
                            try:q.execute(sql);code=0;c.rollback()
                            except pymysql.MySQLError as error:code=error.args[0];c.rollback()
                            facts['cross_database'].append({'actor':r,'target':target,'action':action,'error_code':code})
            event({'database_role':r,'facts':facts['database'][r]})
        account_ids={}
        # Provision only absent fixed synthetic fixtures; existing identities are never reset or replaced.
        db=credentials['database']['mailbox']
        for name in ('alice','bob'):
            with pymysql.connect(host='127.0.0.1',port=13306,user=db['user'],password=db['password'],database=db['schema']) as c:
                with c.cursor() as q:q.execute('SELECT account_id FROM accounts WHERE address=%s',(credentials['accounts'][name]['address'],));row=q.fetchone()
            if row:account_ids[name]=row[0]
            else:
                result,value,_=call('mailbox','/internal/accounts','POST',{**credentials['accounts'][name],'displayName':name},internal=True)
                account_ids[name]=value['account_id']
        bob_id=account_ids['bob'];sessions={};facts['sessions']=sessions
        # Keep all bounded login checks in one actual server minute. No manufactured client identity.
        with pymysql.connect(host='127.0.0.1',port=13306,user=db['user'],password=db['password'],database=db['schema']) as c:
            login_bucket=sha(('127.0.0.1|'+credentials['accounts']['alice']['address']).encode())
            with c.cursor() as q:q.execute('SELECT minute_window,attempts FROM login_buckets WHERE bucket_hash=%s',(login_bucket,));bucket=q.fetchone()
        if time.time()%60>35 or (bucket and bucket[0]==int(time.time()/60) and bucket[1]>0):time.sleep(60-time.time()%60+.1)
        cookies={};csrf={}
        for name in ('alice','bob'):
            sessions[name+'_login'],value,header=call('mailbox','/api/auth/login','POST',credentials['accounts'][name]);cookies[name]=header.split(';',1)[0];csrf[name]=value['csrf']
            if name=='alice':
                from http.cookies import SimpleCookie
                parsed=SimpleCookie();parsed.load(header);m=parsed['guihong_session'];facts['session_attributes']={'httponly':bool(m['httponly']),'samesite':m['samesite'],'path':m['path']}
        sessions['invalid_login']=call('mailbox','/api/auth/login','POST',{'address':credentials['accounts']['alice']['address'],'password':'wrong-synthetic-password'})[0]
        sessions['unknown_account']=call('mailbox','/api/auth/login','POST',{'address':'absent@guihong.test','password':'wrong-synthetic-password'})[0]
        sessions['alice_me']=call('mailbox','/api/auth/me',cookie=cookies['alice'])[0]
        sessions['alice_reads_bob']=call('mailbox','/api/accounts/'+bob_id,cookie=cookies['alice'])[0]
        sessions['cookie_internal']=call('mailbox','/internal/identity',cookie=cookies['alice'])[0]
        sessions['origin_login']=call('mailbox','/api/auth/login','POST',credentials['accounts']['alice'],origin='https://untrusted.invalid')[0]
        sessions['csrf_refresh']=call('mailbox','/api/auth/refresh','POST',cookie=cookies['alice'],csrf='wrong-nonce')[0]
        sessions['refresh'],value,header=call('mailbox','/api/auth/refresh','POST',cookie=cookies['alice'],csrf=csrf['alice'])
        sessions['old_after_refresh']=call('mailbox','/api/auth/me',cookie=cookies['alice'])[0]
        sessions['logout']=call('mailbox','/api/auth/logout','POST',cookie=header.split(';',1)[0],csrf=value['csrf'])[0]
        sessions['after_logout']=call('mailbox','/api/auth/me',cookie=header.split(';',1)[0])[0]
        call('mailbox','/internal/accounts/'+bob_id+'/enabled','POST',{'enabled':False},internal=True)
        sessions['bob_disabled']=call('mailbox','/api/auth/me',cookie=cookies['bob'])[0]
        call('mailbox','/internal/accounts/'+bob_id+'/enabled','POST',{'enabled':True},internal=True);bob_id=None
        for _ in range(4):call('mailbox','/api/auth/login','POST',{'address':credentials['accounts']['alice']['address'],'password':'wrong-synthetic-password'})
        sessions['rate_limit']=call('mailbox','/api/auth/login','POST',{'address':credentials['accounts']['alice']['address'],'password':'wrong-synthetic-password'})[0]
        sessions['correct_after_rate_limit']=call('mailbox','/api/auth/login','POST',credentials['accounts']['alice'])[0]
        facts['smtp']={}
        with smtplib.SMTP('127.0.0.1',12525,timeout=10) as smtp:
            smtp.ehlo();facts['smtp']['mail']=smtp.mail('sender@outside.test')[0]
            facts['smtp']['external_rcpt']=smtp.rcpt('recipient@outside.test')[0]
            facts['smtp']['local_rcpt']=smtp.rcpt('alice@guihong.test')[0]
            smtp.putcmd('DATA');facts['smtp']['data']=smtp.getreply()[0]
        event({'smtp':facts['smtp']})
        env=apps.environment();env.update(GUIHONG_INTEGRATION='1',GUIHONG_LAB_ID=lab.load()['id'],GUIHONG_MQ_PROBE_TOPIC=expected['mq_topic'],GUIHONG_MQ_PROBE_OUT=str(out/'mq-native.json'))
        with (out/'mq-native.log').open('x',encoding='utf-8') as log:
            result=subprocess.run([str(apps.MVN),'-B','-ntp','-s',str(ROOT/'.artifacts/build/settings.xml'),'-Dmaven.repo.local='+str(ROOT/'.artifacts/m2'),'-f',str(ROOT/'backend/pom.xml'),'-pl','platform-common','-Dtest=OwnedMqIntegrationTest','test'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        if (out/'mq-native.json').exists():facts['mq']=json.loads((out/'mq-native.json').read_text())
        if result.returncode:raise RuntimeError('Real MQ native probe failed; original log preserved')
        broker=json.loads(subprocess.check_output([lab.docker(),'inspect',lab.load()['id']+'-broker-1'],text=True,encoding='utf-8'))[0]
        facts['broker']={'memory_limit':broker['HostConfig']['Memory'],'pid_limit':broker['HostConfig']['PidsLimit'],'oom_killed':broker['State']['OOMKilled'],'jvm':next(x for x in broker['Config']['Env'] if x.startswith('HEAP_OPTS='))}
        lab.compose(['stop','--timeout','20','seaweedfs'],capture=True)
        facts['dependency_down']={r:call(r,'/health/ready')[0] for r in lab.SERVICES}
        lab.compose(['up','-d','seaweedfs'],capture=True)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            result=call('mailbox','/health/ready')[0]
            if result['http']==200:break
            time.sleep(.5)
        facts['dependency_restored']={r:call(r,'/health/ready')[0] for r in lab.SERVICES}
        facts['drain']={r:call(r,'/internal/drain','POST',internal=True)[0] for r in lab.SERVICES}
        sessions['drained_login']=call('mailbox','/api/auth/login','POST',credentials['accounts']['alice'])[0]
        apps.stop();facts['shutdown']={r:apps.process_identity(json.loads((apps.PROCESSES/(r+'.json')).read_text())['pid']) is None for r in lab.SERVICES}
    except Exception as error:
        status='ERROR';save(out/'collection-error.json',{'exception':type(error).__name__,'message':str(error)})
    finally:
        if bob_id:
            try:call('mailbox','/internal/accounts/'+bob_id+'/enabled','POST',{'enabled':True},internal=True)
            except Exception:pass # Preserve failed cleanup; never edit database behind the witness.
    facts['source_sha']=git('rev-parse','HEAD');facts['source_clean']=not bool(git('status','--porcelain'))
    save(out/'facts.json',facts)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
        'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(expected),'collection_session_id':run,
        'collector_role':'guihong-foundation-collector','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR',
        'normalization_semantics_version':'guihong-foundation/1.1','facts_digest':sha256_json(facts)}
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-foundation/1.1',
        'captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    summary={'run_id':run,'execution':status,'source_sha':source,'boundary':facts['boundary'],'bundle':str(out/'bundle'),'verdict':report['verdict']}
    save(out/'summary.json',summary);print(json.dumps(summary))
    return 0 if status=='COMPLETED' and report['verdict']=='PASS' else 1

if __name__=='__main__':sys.exit(main())
