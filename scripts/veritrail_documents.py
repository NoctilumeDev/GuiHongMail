"""Observe real frozen document bytes with public Acceptance Core 0.13.0.

Negative controls corrupt collected Evidence only, never the frozen source.
This gate proves document identity/structure, not mailbox runtime behavior.
"""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import uuid

from veritrail.acceptance_plan import observation_spec_digest, seal_acceptance_plan
from veritrail.acceptance_reporting import create_acceptance_bundle
from veritrail.canonical import sha256_json
from check import digest, verify_seal

ROOT = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def write_new(path, value):
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write('\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control',choices=['none','wrong-hash','wrong-binding','missing-evidence'],default='none')
    args = parser.parse_args()
    if version('veritrail') != '0.13.0':
        raise RuntimeError('Use verified public Core 0.13.0')
    if git('status','--porcelain'):
        raise RuntimeError('Exact clean source required before Plan')
    source_sha = git('rev-parse','HEAD')
    authority = json.loads((ROOT/'docs/m0-seal.json').read_text(encoding='utf-8'))
    identity = 'guihong-m0-'+uuid.uuid4().hex
    output = ROOT/'artifacts/local'/identity
    output.mkdir(parents=True,exist_ok=False)
    request = {'source_sha':source_sha,'m0_digest':authority['digest'],
               'collector':'guihong-documents/0.1','control':args.control}
    spec = {'id':'document-observation','contract':{'id':'guihong-documents','version':'0.1'},
            'evidence_type':'guihong.documents','coordinates':request,
            'projections':['source_sha','source_clean','command_exit','doc_audit','files','m0_digest'],
            'canonicalization_profile':'veritrail-json-c14n/1'}
    def hard(name,path,expected):
        return {'id':name,'severity':'HARD','left':{'requirement_id':'documents','path':path},
                'operator':'eq','right':expected}
    assertions = [hard('exact-source','/facts/source_sha',source_sha),
                  hard('clean-source','/facts/source_clean',True),
                  hard('document-command','/facts/command_exit',0),
                  hard('no-broken-links','/facts/doc_audit/link_errors',0),
                  hard('exact-m0-seal','/facts/m0_digest',authority['digest'])]
    for i,(path,entry) in enumerate(sorted(authority['content']['files'].items())):
        # List indexes avoid interpreting file names as JSON-pointer paths.
        assertions.extend([hard(f'file-{i}-name',f'/facts/files/{i}/path',path),
                           hard(f'file-{i}-hash',f'/facts/files/{i}/sha256',entry['sha256']),
                           hard(f'file-{i}-size',f'/facts/files/{i}/bytes',entry['bytes'])])
    plan = seal_acceptance_plan({
        'plan_kind':'ACCEPTANCE','schema_version':'0.1','plan_id':'guihong-m0-documents','version':1,
        'subject':{'id':'guihong-m0','version':source_sha,'source_ref':'github:NoctilumeDev/GuiHongMail'},
        'question':'Do the approved M0 document bytes, links and source coordinate satisfy the frozen document obligations?',
        'governance':{'claim_owner_ref':'human:repository-owner','drafter_ref':'guihong:documents-adapter',
                      'seal_authority_ref':'human:repository-owner:guihong-m1-m6-20261013','seal_decision':'CONFIRMED'},
        'observation_specs':[spec],
        'evidence_requirements':[{'id':'documents','observation_spec_id':spec['id'],'cardinality':'EXACTLY_ONE'}],
        'sufficiency_rules':[{'id':'complete-observation','left':{'requirement_id':'documents',
                             'path':'/metadata/veritrail_observation/coverage'},'operator':'eq','right':'COMPLETE'}],
        'integrity_rules':[],'assertions':assertions,
        'resource_budget':{'max_artifact_bytes':1048576,'command_timeout_seconds':30},
        'change_scope':{'level':'L2_CONTRACT','owner':'GuiHongMail M0','consumers':['document-gates']},
        'reproduction_steps':['Use the exact clean checkout and independently verified public Core 0.13.0 wheel.',
                              'Run scripts/veritrail_documents.py; negative controls remain distinctly labelled.'],
        'cleanup_steps':['No services are started; retain immutable qualification/negative-control records.']})
    write_new(output/'sealed-plan.json',plan)
    write_new(output/'request.json',request)
    # All declared source observation follows the durable Plan file.
    completed = subprocess.run([sys.executable,'-B','scripts/check.py','docs'],cwd=ROOT,
                               capture_output=True,text=True,encoding='utf-8',timeout=30)
    (output/'stdout.txt').write_text(completed.stdout,encoding='utf-8')
    (output/'stderr.txt').write_text(completed.stderr,encoding='utf-8')
    audit = json.loads(completed.stdout)['docs'] if completed.returncode == 0 else {'collection_error':'DOCUMENT_GATE_ERROR'}
    files = [{'path':path,'sha256':digest(ROOT/path),'bytes':(ROOT/path).stat().st_size}
             for path in sorted(authority['content']['files'])]
    facts = {'source_sha':git('rev-parse','HEAD'),'source_clean':not bool(git('status','--porcelain')),
             'command_exit':completed.returncode,'doc_audit':audit,'files':files,
             'm0_digest':json.loads((ROOT/'docs/m0-seal.json').read_text(encoding='utf-8'))['digest'],
             'boundary':'DOCUMENTS_ONLY','control':args.control}
    if args.control == 'wrong-hash':
        facts['files'][0]['sha256'] = '0'*64
    metadata = {'schema_version':'0.1','canonicalization_profile':'veritrail-json-c14n/1',
                'plan_digest':plan['seal']['digest'],'observation_spec_digest':observation_spec_digest(spec),
                'request_seal_digest':sha256_json(request),'collection_session_id':identity,
                'collector_role':'guihong-document-collector','coverage':'COMPLETE' if completed.returncode==0 else 'ERROR',
                'normalization_semantics_version':'guihong-documents/0.1','facts_digest':sha256_json(facts)}
    if args.control == 'wrong-binding':
        metadata['plan_digest'] = '0'*64
    evidence = {'schema_version':'0.1','evidence_type':spec['evidence_type'],'source':'guihong-documents/0.1',
                'captured_at':datetime.now(timezone.utc).isoformat(),'facts':facts,
                'metadata':{'veritrail_observation':metadata}}
    write_new(output/'evidence.json',evidence)
    report = create_acceptance_bundle(plan=plan,
        evidence_paths=[] if args.control=='missing-evidence' else [output/'evidence.json'],
        output=output/'bundle',acceptance_id=identity,execution_status='COMPLETED' if completed.returncode==0 else 'ERROR')
    expected = {'none':'PASS','wrong-hash':'FAIL','wrong-binding':'INCONCLUSIVE','missing-evidence':'PENDING'}[args.control]
    summary = {'identity':identity,'source_sha':source_sha,'m0_digest':authority['digest'],
               'execution_status':report['execution_status'],'verdict':report['verdict'],
               'control':args.control,'expected':expected,'boundary':'M0_DOCUMENTS_ONLY',
               'bundle':str((output/'bundle').relative_to(ROOT)),
               'public_core_version':version('veritrail')}
    write_new(output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if report['verdict']==expected else 1

if __name__ == '__main__':
    sys.exit(main())
