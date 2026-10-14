"""Reconcile exact-source M2-M4, object and resilience evidence into M5."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json

import lab

ROOT = lab.ROOT


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_child(relative, source):
    path = (ROOT/relative).resolve(); local = (ROOT/'artifacts/local').resolve()
    if not path.is_file() or not path.is_relative_to(local) or path.name != 'evidence.json':
        raise RuntimeError('M5 child evidence must be a retained local evidence.json')
    evidence = json.loads(path.read_text(encoding='utf-8'))
    facts = evidence.get('facts', {})
    summary_path = path.parent/'summary.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    execution_states = {summary[name] for name in ('execution_status', 'execution') if name in summary}
    if (facts.get('source_sha') != source or summary.get('source_sha') != source or
            summary.get('verdict') != 'PASS' or execution_states != {'COMPLETED'}):
        raise RuntimeError('M5 child is not a same-source completed PASS: ' + relative)
    if evidence.get('metadata', {}).get('veritrail_observation', {}).get('facts_digest') != sha256_json(facts):
        raise RuntimeError('M5 child facts digest mismatch: ' + relative)
    return {'path':relative,'sha256':digest(path),'summary':summary,'facts':facts}


def collect(paths):
    source=git('rev-parse','HEAD')
    children={name:load_child(path,source) for name,path in paths.items()}
    m2,m3,m4,objects,resilience=(children[name]['facts'] for name in ('m2','m3','m4','objects','resilience'))
    all_cases=lambda facts: bool(facts.get('cases')) and all(facts['cases'].values())
    object_ok=(objects['put_failure']['http']==503 and objects['known_rollback']['http']==503 and
        objects['commit_unknown']['readiness_after']['http']==503 and objects['commit_unknown']['readiness_restart']['http']==200 and
        objects['gc']['failure_http']==503 and objects['gc']['retry_http']==200 and
        objects['integrity']['read_http']==503 and objects['integrity']['readiness_after']['http']==503 and
        objects['integrity']['readiness_restart']['http']==200 and objects['journal_recovery']['readiness_missing']['http']==503 and
        objects['journal_recovery']['readiness_restored']['http']==200)
    cases={
        'M5-01': m3['cases']['M3-05'] and m4['cases']['M4-16'],
        'M5-02': m3['cases']['M3-11'],
        'M5-03': m3['cases']['M3-12'],
        'M5-04': m3['cases']['M3-09'] and m3['cases']['M3-10'],
        'M5-05': m3['cases']['M3-13'],
        'M5-06': m3['cases']['M3-14'],
        'M5-07': m3['cases']['M3-15'],
        'M5-08': resilience['cases']['M5R-02'],
        'M5-09': resilience['cases']['M5R-03'],
        'M5-10': m3['cases']['M3-04'] and resilience['cases']['M5R-01'],
        'M5-11': resilience['cases']['M5R-04'],
        'M5-12': m3['cases']['M3-08'],
        'M5-13': m3['cases']['M3-07'] and object_ok,
        'M5-14': all(m4['cases'][case] for case in ('M4-03','M4-06','M4-07','M4-11','M4-12')),
        'M5-15': m2['cases']['M2-03'] and m2['cases']['M2-14'] and m3['cases']['M3-03'],
        'M5-16': m2['cases']['M2-07'] and m2['cases']['M2-08'] and m3['cases']['M3-03'],
        'M5-17': resilience['cases']['M5R-06'] and resilience['cases']['M5R-07'] and resilience['cases']['M5R-10'],
        'M5-18': resilience['cases']['M5R-08'] and resilience['cases']['M5R-09'],
    }
    resource=resilience['resource']
    resource_ok=(resilience['cases']['M5R-05'] and resource['samples']>=18 and resource['full_topology_samples']>=18 and
        not resource['stop_reasons'] and resource['max_host_used_bytes']<14*1024**3 and
        resource['min_container_memory_headroom_ratio']>=.10 and resource['min_container_pid_headroom']>=16)
    return {'source_sha':source,'cases':cases,'all_child_cases':{'m2':all_cases(m2),'m3':all_cases(m3),'m4':all_cases(m4),'resilience':all_cases(resilience)},
        'object_lifecycle':object_ok,'resource_ok':resource_ok,'resource':resource,
        'children':{name:{'identity':item['summary']['identity'] if 'identity' in item['summary'] else item['summary'].get('run_id'),
                          'evidence_sha256':item['sha256'],'facts_digest':sha256_json(item['facts']),'verdict':item['summary']['verdict']}
                    for name,item in children.items()},
        'boundary':'M5_FINITE_COUNTEREXAMPLES_ONLY'}


def main():
    parser=argparse.ArgumentParser()
    for name in ('m2','m3','m4','objects','resilience'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--control',choices=['none','wrong-binding','missing-evidence'],default='none')
    args=parser.parse_args()
    if git('status','--porcelain'):raise RuntimeError('M5 aggregate requires committed clean exact source')
    source=git('rev-parse','HEAD');run='guihong-m5-'+uuid.uuid4().hex;out=lab.local_run(run,create=True)
    paths={name:getattr(args,name) for name in ('m2','m3','m4','objects','resilience')}
    request={'source_sha':source,'plan_sha256':digest(ROOT/'docs/m5-plan.md'),'resource_contract_sha256':digest(ROOT/'docs/m1-resource-contract-1.2.md'),
             'children':paths,'control':args.control}
    spec={'id':'m5-aggregate','contract':{'id':'guihong-m5-local','version':'1.0'},'evidence_type':'guihong.m5',
          'coordinates':request,'projections':['source_sha','cases','all_child_cases','object_lifecycle','resource_ok','resource','children','boundary'],
          'canonicalization_profile':'veritrail-json-c14n/1'}
    assertions=[{'id':case.lower(),'severity':'HARD','left':{'requirement_id':'m5','path':'/facts/cases/'+case},'operator':'eq','right':True} for case in [f'M5-{n:02d}' for n in range(1,19)]]
    assertions += [
        {'id':'child-'+name,'severity':'HARD','left':{'requirement_id':'m5','path':'/facts/all_child_cases/'+name},'operator':'eq','right':True} for name in ('m2','m3','m4','resilience')]
    assertions += [
        {'id':'objects','severity':'HARD','left':{'requirement_id':'m5','path':'/facts/object_lifecycle'},'operator':'eq','right':True},
        {'id':'resource','severity':'HARD','left':{'requirement_id':'m5','path':'/facts/resource_ok'},'operator':'eq','right':True}]
    plan=seal_acceptance_plan({'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m5-local','version':1,
        'subject':{'id':'guihong-m5-candidate','version':source,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Does the exact Go candidate satisfy all 18 finite M5 counterexample gates?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:m5-reconciler','seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],'evidence_requirements':[{'id':'m5','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'coverage','left':{'requirement_id':'m5','path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,'resource_budget':{'max_artifact_bytes':10*1024*1024,'max_probe_seconds':120},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M5','consumers':['m5-stage-gate']},
        'reproduction_steps':['Produce all five same-source child PASS records in fresh owned labs.','Run this independent digest-bound reconciler.'],
        'cleanup_steps':['Retain child and aggregate evidence including negative controls.','Remove only exact owned labs after evidence consolidation.']})
    save(out/'sealed-plan.json',plan);save(out/'request.json',request);status='COMPLETED';error=None
    try:facts=collect(paths)
    except Exception as failure:
        status='ERROR';error={'exception_type':type(failure).__name__,'message':str(failure)};facts={'source_sha':source,'cases':{},'boundary':'M5_FINITE_COUNTEREXAMPLES_ONLY'};save(out/'collection-error.json',error)
    metadata={'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1','plan_digest':plan['seal']['digest'],
              'observation_spec_digest':observation_spec_digest(spec),'request_seal_digest':sha256_json(request),'collection_session_id':run,
              'collector_role':'guihong-m5-reconciler','coverage':'COMPLETE' if status=='COMPLETED' else 'ERROR',
              'normalization_semantics_version':'guihong-m5/1.0','facts_digest':sha256_json(facts)}
    if args.control=='wrong-binding':metadata['plan_digest']='0'*64
    evidence={'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-m5/1.0','captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,'metadata':{'veritrail_observation':metadata}}
    save(out/'evidence.json',evidence)
    report=create_acceptance_bundle(plan=plan,evidence_paths=[] if args.control=='missing-evidence' else [out/'evidence.json'],output=out/'bundle',acceptance_id=run,execution_status=status)
    expected={'none':'PASS','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary={'identity':run,'source_sha':source,'execution_status':report['execution_status'],'verdict':report['verdict'],'expected':expected,'control':args.control,'bundle':(out/'bundle').relative_to(ROOT).as_posix()}
    save(out/'summary.json',summary);print(json.dumps(summary));return 0 if status=='COMPLETED' and report['verdict']==expected else 1


if __name__=='__main__':raise SystemExit(main())
