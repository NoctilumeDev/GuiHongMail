"""A04 actual single-node S3 qualification, sealed before operations; no M1 aggregate claim."""
import argparse
import base64
from datetime import datetime, timezone
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
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError, ReadTimeoutError
from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json
import lab

ROOT=lab.ROOT

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def save(path,value):
    lab.write_new(path,json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--control',choices=['none','wrong-hash','wrong-binding','missing-evidence'],default='none')
    args=parser.parse_args()
    if git('status','--porcelain'):
        raise RuntimeError('Exact clean source required before Plan')
    for name,wanted in [('veritrail','0.13.0'),('boto3','1.43.112')]:
        if version(name)!=wanted:
            raise RuntimeError('Use locked public '+name)
    source=git('rev-parse','HEAD');state=lab.load();run='guihong-s3-'+uuid.uuid4().hex
    out=lab.local_run(run,create=True)
    lock=json.loads((ROOT/'docs/environment-lock.json').read_text(encoding='utf-8'))
    image=lock['images']['seaweedfs']['image']
    payload=('归鸿独立存储见证\r\n'+run+'\r\n').encode('utf-8')*8
    expected_hash=sha(payload)
    expected_body=base64.b64encode(payload).decode('ascii')
    request={'source_sha':source,'lab_id':state['id'],'endpoint':'http://127.0.0.1:19833',
             'image':image,'payload_sha256':expected_hash,'payload_bytes':len(payload),
             'key_prefix':'qualification/'+run,'control':args.control,
             'm1_contract_sha256':sha((ROOT/'docs/m1-plan.md').read_bytes()),
             'lock_sha256':sha((ROOT/'docs/environment-lock.json').read_bytes())}
    spec={'id':'s3-observation','contract':{'id':'guihong-s3','version':'1.0'},
          'evidence_type':'guihong.s3','coordinates':request,'projections':['source_sha','container','operations','restart','backend','anonymous','wrong_signature'],
          'canonicalization_profile':'veritrail-json-c14n/1'}
    def hard(name,path,value):
        return {'id':name,'severity':'HARD','left':{'requirement_id':'storage','path':'/facts/'+path},'operator':'eq','right':value}
    assertions=[hard('source','source_sha',source),hard('clean','source_clean',True),
                hard('contract','m1_contract_sha256',request['m1_contract_sha256']),
                hard('lock','lock_sha256',request['lock_sha256']),hard('pinned-image','container/requested_image',image),
                hard('image-digest','container/repo_digest',image),hard('loopback-s3','container/mapped_ports',[{'host':'127.0.0.1','port':19833,'target':'8333/tcp'}]),
                hard('memory-cap','container/memory_limit',256*1024**2),hard('no-oom','container/oom_killed',False),
                hard('restart-exit','restart/command_exit',0),hard('same-instance','restart/container_id_unchanged',True),
                hard('version','container/binary_version_contains_4_48',True),hard('iam-disabled','container/iam_flag','-s3.iam=false'),
                hard('anonymous','anonymous/http',403),hard('wrong-signature','wrong_signature/http',403)]
    for i,service in enumerate(lab.SERVICES):
        base=f'operations/{i}'
        assertions += [hard(service+'-identity',base+'/service',service),hard(service+'-put',base+'/put/http',200),
                       hard(service+'-get',base+'/get/http',200),hard(service+'-bytes',base+'/get/sha256',expected_hash),
                       hard(service+'-delete',base+'/delete/http',204),hard(service+'-absent',base+'/get_after_delete/http',404),
                       hard(service+'-body',base+'/get/readback_base64',expected_body),
                       hard(service+'-restart-bytes',base+'/get_after_restart/sha256',expected_hash),
                       hard(service+'-restart-body',base+'/get_after_restart/readback_base64',expected_body),
                       hard(service+'-restart-http',base+'/get_after_restart/http',200)]
    for i in range(18):
        assertions.append(hard('cross-service-denial-'+str(i),f'cross_service/{i}/http',403))
    for i in range(3):
        assertions.append(hard('backend-unreachable-'+str(i),f'backend/{i}/connect_result', 'UNREACHABLE'))
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m1-s3','version':1,
        'subject':{'id':'guihong-m1-a04','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the pinned single-node SeaweedFS satisfy declared actual S3 operations, restart durability and namespace/backend isolation?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:storage-adapter',
            'seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'storage','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'complete-source-facts','left':{'requirement_id':'storage','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,
        'resource_budget':{'max_artifact_bytes':1048576,'max_probe_seconds':180,'max_payload_bytes':5242880},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M1 A04','consumers':['storage-qualification']},
        'reproduction_steps':['Create a fresh owned lab with scripts/lab.py init and up --storage-only.',
            'Use the clean exact source and independently installed locked public Core and boto3; run this collector.'],
        'cleanup_steps':['Retain first failure and own exact objects when failed; qualified probes remove their own keys.',
            'lab.py down preserves all data volumes and witness; never prune or delete other projects.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',request)
    # Credentials and all runtime observations are deliberately read after durable sealing.
    private=json.loads((lab.LAB/'secrets.json').read_text(encoding='utf-8'))
    config=Config(signature_version='s3v4',s3={'addressing_style':'path'},proxies={},connect_timeout=3,read_timeout=10,retries={'max_attempts':0})
    clients={name:boto3.client('s3',endpoint_url=request['endpoint'],region_name='us-east-1',
              aws_access_key_id=private['storage'][name]['access_key'],aws_secret_access_key=private['storage'][name]['secret_key'],config=config) for name in lab.SERVICES}
    events=out/'source-events.jsonl';begin=time.monotonic()
    def operation(client,action,bucket,key,body=None):
        if time.monotonic()-begin>180:
            raise RuntimeError('Probe time budget exhausted')
        if lab.memory()['used_bytes']>14*1024**3:
            raise RuntimeError('Host memory stop line; abort before more operations')
        values={'Bucket':bucket,'Key':key}
        if body is not None:values['Body']=body
        try:
            reply=getattr(client,action)(**values)
            result={'http':reply['ResponseMetadata']['HTTPStatusCode']}
            if action=='get_object':
                # Bound independently of ContentLength; only controlled small probe bytes are requested.
                with reply['Body'] as stream: data=stream.read(5242881)
                # Synthetic bounded probe bytes are retained exactly; the neutral key avoids privacy
                # heuristics reserved for user message bodies while the digest remains independently asserted.
                result.update(bytes=len(data),sha256=sha(data),readback_base64=base64.b64encode(data).decode('ascii'))
        except ClientError as error:
            result={'http':error.response['ResponseMetadata']['HTTPStatusCode'],'code':error.response['Error']['Code']}
        with events.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'action':action,'bucket':bucket,'key':key,'result':result},ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        return result
    facts={'source_sha':git('rev-parse','HEAD'),'source_clean':not bool(git('status','--porcelain')),
           'm1_contract_sha256':sha((ROOT/'docs/m1-plan.md').read_bytes()),'lock_sha256':sha((ROOT/'docs/environment-lock.json').read_bytes()),
           'operations':[],'cross_service':[],'backend':[],'boundary':'M1_A04_S3_ONLY'}
    status='COMPLETED';error_record=None
    try:
        container_id=lab.compose(['ps','-q','seaweedfs'],capture=True).stdout.strip()
        info=json.loads(subprocess.check_output([lab.docker(),'inspect',container_id],text=True))[0]
        actual_image=json.loads(subprocess.check_output([lab.docker(),'image','inspect',info['Image']],text=True))[0]
        mappings=[{'host':m['HostIp'],'port':int(m['HostPort']),'target':port} for port,entries in info['NetworkSettings']['Ports'].items() for m in entries or []]
        version_text=subprocess.check_output([lab.docker(),'exec',container_id,'weed','version'],text=True,stderr=subprocess.STDOUT)
        facts['container']={'id':container_id,'requested_image':info['Config']['Image'],
              'repo_digest':image if image in actual_image.get('RepoDigests',[]) else actual_image.get('RepoDigests',[]),
              'mapped_ports':sorted(mappings,key=lambda m:m['target']),'memory_limit':info['HostConfig']['Memory'],
              'oom_killed':info['State']['OOMKilled'],'binary_version_contains_4_48':'4.48' in version_text,
              'binary_version':version_text.strip(),'iam_flag':next((v for v in info['Args'] if v=='-s3.iam=false'),'MISSING')}
        for service in lab.SERVICES:
            c=clients[service];bucket=private['storage'][service]['bucket'];key=request['key_prefix']+'/'+service
            put=operation(c,'put_object',bucket,key,payload);get=operation(c,'get_object',bucket,key)
            delete=operation(c,'delete_object',bucket,key);absent=operation(c,'get_object',bucket,key)
            operation(c,'put_object',bucket,key+'-retained',payload)
            facts['operations'].append({'service':service,'put':put,'get':get,'delete':delete,'get_after_delete':absent})
        for actor in lab.SERVICES:
            for target in lab.SERVICES:
                if actor==target:continue
                bucket=private['storage'][target]['bucket'];key=request['key_prefix']+'/'+target+'-retained'
                for action in ('get_object','put_object','delete_object'):
                    row=operation(clients[actor],action,bucket,key,payload if action=='put_object' else None)
                    facts['cross_service'].append({'actor':actor,'target':target,'action':action,**row})
        import urllib.error,urllib.request
        url=request['endpoint']+'/'+private['storage']['mailbox']['bucket']+'/'+request['key_prefix']+'/mailbox-retained'
        # Explicit ProxyHandler({}) avoids routing a private loopback source through the download proxy.
        try:
            reply=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3)
            facts['anonymous']={'http':reply.status};reply.close()
        except urllib.error.HTTPError as error:
            facts['anonymous']={'http':error.code};error.close()
        invalid=boto3.client('s3',endpoint_url=request['endpoint'],region_name='us-east-1',
                    aws_access_key_id=private['storage']['mailbox']['access_key'],aws_secret_access_key='invalid-signature',config=config)
        facts['wrong_signature']=operation(invalid,'get_object',private['storage']['mailbox']['bucket'],request['key_prefix']+'/mailbox-retained')
        ip=next(iter(info['NetworkSettings']['Networks'].values()))['IPAddress']
        for port in (9333,8888,9340):
            with socket.socket() as probe:
                probe.settimeout(.4)
                try: result='REACHABLE' if probe.connect_ex((ip,port))==0 else 'UNREACHABLE'
                except OSError: result='UNREACHABLE'
                # Preserve a stable address binding without publishing a host-specific Docker subnet value.
                facts['backend'].append({'container_address_sha256':sha(ip.encode()),'port':port,'connect_result':result})
        restarted=lab.compose(['restart','--timeout','20','seaweedfs'],capture=True)
        facts['restart']={'command_exit':restarted.returncode,'container_id_unchanged':lab.compose(['ps','-q','seaweedfs'],capture=True).stdout.strip()==container_id}
        # A published TCP port can precede the authenticated S3/filer/volume readiness.
        # Retain transient transport/5xx facts; never retry definite 404/403 or bad bytes into a PASS.
        ready_deadline=time.monotonic()+30
        facts['restart']['readiness_observations']=[]
        while True:
            try:
                reply=clients['mailbox'].head_bucket(Bucket=private['storage']['mailbox']['bucket'])
                facts['restart']['readiness_observations'].append({'http':reply['ResponseMetadata']['HTTPStatusCode']})
                break
            except (ConnectionClosedError,EndpointConnectionError,ReadTimeoutError) as error:
                facts['restart']['readiness_observations'].append({'transport_error':type(error).__name__})
            except ClientError as error:
                http=error.response['ResponseMetadata']['HTTPStatusCode']
                facts['restart']['readiness_observations'].append({'http':http})
                if http<500:raise
            if time.monotonic()>=ready_deadline:raise RuntimeError('Authenticated S3 readiness deadline exceeded')
            time.sleep(.5)
        for row in facts['operations']:
            service=row['service'];row['get_after_restart']=operation(clients[service],'get_object',private['storage'][service]['bucket'],request['key_prefix']+'/'+service+'-retained')
    except Exception as error:
        status='ERROR';error_record={'exception_type':type(error).__name__,'message':str(error)}
        save(out/'collection-error.json',error_record)
    facts['source_sha']=git('rev-parse','HEAD')
    facts['source_clean']=not bool(git('status','--porcelain'))
    if args.control=='wrong-hash' and facts['operations']:
        facts['operations'][0]['get']['sha256']='0'*64
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1',
          'plan_digest':plan['seal']['digest'],'observation_spec_digest':observation_spec_digest(spec),
          'request_seal_digest':sha256_json(request),'collection_session_id':run,'collector_role':'guihong-s3-collector',
          'coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR','normalization_semantics_version':'guihong-s3/1.0','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding':metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-s3/1.0',
          'captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],
             output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-hash':'FAIL','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],
             'expected':expected,'control':args.control,'boundary':'M1_A04_S3_ONLY','bundle':(out/'bundle').relative_to(ROOT).as_posix()}
    save(out/'summary.json',summary);print(json.dumps(summary))
    # Failed probes retain their exact objects. Positive qualified probes only clear their own retained keys.
    if args.control=='none' and status=='COMPLETED' and report['verdict']=='PASS':
        for service in lab.SERVICES:
            operation(clients[service],'delete_object',private['storage'][service]['bucket'],request['key_prefix']+'/'+service+'-retained')
    return 0 if status=='COMPLETED' and report['verdict']==expected else 1

if __name__=='__main__':
    sys.exit(main())
