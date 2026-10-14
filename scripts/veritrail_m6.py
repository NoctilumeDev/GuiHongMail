"""Reconcile two fresh M6 rounds, product review and public release readback."""
import argparse
import copy
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


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    lab.write_new(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def load(path_text, schema, filename, source):
    path = Path(path_text).resolve()
    if not path.is_file() or path.is_symlink() or path.name != filename:
        raise RuntimeError('M6 input is missing or not an ordinary ' + filename)
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != schema or value.get('source_sha') != source or value.get('verdict') != 'PASS':
        raise RuntimeError('M6 input is not a same-source PASS: ' + str(path))
    return {'path': str(path), 'sha256': digest(path), 'value': value}


def collect(arguments, source):
    a = load(arguments.round_a, 'GuiHongM6Round/1.0', 'round.json', source)
    b = load(arguments.round_b, 'GuiHongM6Round/1.0', 'round.json', source)
    review = load(arguments.product_review, 'GuiHongM6ProductReview/1.0', 'review.json', source)
    release = load(arguments.release_readback, 'GuiHongM6ReleaseReadback/1.0', 'readback.json', source)
    release_value = copy.deepcopy(release['value'])
    if arguments.control == 'wrong-release':
        release_value['assets'][0]['verified'] = False
        release_value['verdict'] = 'FAIL'
    av, bv, pv, rv = a['value'], b['value'], review['value'], release_value
    both = (av, bv)
    resources = [item['resource'] for item in both]
    resource_ok = all(item['max_host_used_bytes'] < 14 * 1024**3 and
                      item['min_container_memory_headroom_ratio'] >= .10 and
                      item['min_container_pid_headroom'] >= 16 for item in resources)
    cleanup_ok = all(all(lab_row['clean'] for lab_row in item['cleanup']['labs']) and
                     all(item['cleanup']['ports_free'].values()) for item in both)
    cases = {
        'M6-01': all(av['cases'].values()),
        'M6-02': all(bv['cases'].values()) and av['identity'] != bv['identity'] and
                 av['checkout_identity'] != bv['checkout_identity'] and pv['cases']['P-02'],
        'M6-03': all(item['cases']['R-03'] for item in both),
        'M6-04': all(item['cases']['R-02'] and item['product']['cancel']['cancelled'] and
                     item['product']['unknown']['unknown_copy'] for item in both),
        'M6-05': all(item['cases']['R-04'] for item in both) and pv['cases']['P-03'] and pv['cases']['P-04'],
        'M6-06': all(item['cases']['R-05'] for item in both),
        'M6-07': all(item['cases']['R-06'] for item in both),
        'M6-08': all(item['cases']['R-07'] for item in both),
        'M6-09': resource_ok and all(item['cases']['R-08'] for item in both),
        'M6-10': all(pv['cases'].values()) and pv['visual_state'] == 'VISUAL_POLISH_PENDING' and
                  pv['scope']['public_internet_mail'] == 'NOT_PROVEN',
        'M6-11': rv['verdict'] == 'PASS' and rv['tag_target_sha'] == source and rv['prerelease'] and
                  not rv['draft'] and bool(rv['main_ci']) and all(item['verified'] for item in rv['assets']),
        'M6-12': cleanup_ok and all(item['operator_guide_sha256'] == digest(ROOT / 'docs/operator-guide.md') for item in both),
    }
    return {
        'source_sha': source, 'cases': cases,
        'rounds': {'a': {'identity': av['identity'], 'sha256': a['sha256']},
                   'b': {'identity': bv['identity'], 'sha256': b['sha256']}},
        'product_review': {'identity': pv['identity'], 'sha256': review['sha256'], 'cases': pv['cases']},
        'release': {'identity': rv['identity'], 'sha256': release['sha256'], 'tag': rv['tag'],
                    'target': rv['tag_target_sha'], 'url': rv['release_url'], 'assets': rv['assets'],
                    'main_ci': rv['main_ci'], 'verdict': rv['verdict']},
        'resource': {'max_host_used_bytes': max(item['max_host_used_bytes'] for item in resources),
                     'min_container_memory_headroom_ratio': min(item['min_container_memory_headroom_ratio'] for item in resources),
                     'min_container_pid_headroom': min(item['min_container_pid_headroom'] for item in resources)},
        'cleanup_ok': cleanup_ok,
        'boundary': 'ENGINEERING_CANDIDATE_VISUAL_POLISH_PENDING',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round-a', required=True)
    parser.add_argument('--round-b', required=True)
    parser.add_argument('--product-review', required=True)
    parser.add_argument('--release-readback', required=True)
    parser.add_argument('--control', choices=['none', 'wrong-binding', 'missing-evidence', 'wrong-release'], default='none')
    arguments = parser.parse_args()
    if git('status', '--porcelain'):
        raise RuntimeError('M6 reconciliation requires committed clean exact source')
    source = git('rev-parse', 'HEAD')
    run = 'guihong-m6-' + uuid.uuid4().hex
    output = lab.local_run(run, create=True)
    request = {
        'source_sha': source, 'plan_sha256': digest(ROOT / 'docs/m6-plan.md'),
        'resource_contract_sha256': digest(ROOT / 'docs/m1-resource-contract-1.3.md'),
        'operator_guide_sha256': digest(ROOT / 'docs/operator-guide.md'),
        'round_a': arguments.round_a, 'round_b': arguments.round_b,
        'product_review': arguments.product_review, 'release_readback': arguments.release_readback,
        'control': arguments.control,
    }
    spec = {
        'id': 'm6-engineering-candidate', 'contract': {'id': 'guihong-m6', 'version': '1.0'},
        'evidence_type': 'guihong.m6', 'coordinates': request,
        'projections': ['source_sha', 'cases', 'rounds', 'product_review', 'release', 'resource', 'cleanup_ok', 'boundary'],
        'canonicalization_profile': 'veritrail-json-c14n/1',
    }
    assertions = [
        {'id': case.lower(), 'severity': 'HARD', 'left': {'requirement_id': 'm6', 'path': '/facts/cases/' + case},
         'operator': 'eq', 'right': True} for case in [f'M6-{number:02d}' for number in range(1, 13)]
    ]
    plan = seal_acceptance_plan({
        'plan_kind': 'ACCEPTANCE', 'schema_version': '0.1', 'plan_id': 'guihong-m6', 'version': 1,
        'subject': {'id': 'guihong-engineering-candidate', 'version': source,
                    'source_ref': 'github:NoctilumeDev/GuiHongMail'},
        'question': 'Does the exact Go candidate satisfy the two-round M6 engineering exit contract?',
        'governance': {'claim_owner_ref': 'human:repository-owner', 'drafter_ref': 'guihong:m6-reconciler',
                       'seal_authority_ref': 'human:repository-owner:guihong-m1-m6-20261013',
                       'seal_decision': 'CONFIRMED'},
        'observation_specs': [spec],
        'evidence_requirements': [{'id': 'm6', 'observation_spec_id': spec['id'], 'cardinality': 'EXACTLY_ONE'}],
        'sufficiency_rules': [{'id': 'coverage', 'left': {'requirement_id': 'm6', 'path': '/metadata/veritrail_observation/coverage'},
                              'operator': 'eq', 'right': 'COMPLETE'}],
        'integrity_rules': [], 'assertions': assertions,
        'resource_budget': {'max_artifact_bytes': 20 * 1024 * 1024, 'max_probe_seconds': 180},
        'change_scope': {'level': 'L2_CONTRACT', 'owner': 'GuiHongMail M6', 'consumers': ['engineering-candidate']},
        'reproduction_steps': ['Build and execute two independent exact-main rounds.',
                               'Review product facts, publish prerelease assets, then reconcile public readback.'],
        'cleanup_steps': ['Remove exact owned runtime resources.', 'Retain qualification evidence and stop before M7.'],
    })
    save(output / 'sealed-plan.json', plan); save(output / 'request.json', request)
    status = 'COMPLETED'; error = None
    try:
        facts = collect(arguments, source)
    except Exception as failure:
        status = 'ERROR'; error = {'exception_type': type(failure).__name__, 'message': str(failure)}
        facts = {'source_sha': source, 'cases': {}, 'boundary': 'ENGINEERING_CANDIDATE_VISUAL_POLISH_PENDING'}
        save(output / 'collection-error.json', error)
    metadata = {
        'schema_version': '0.1', 'canonicalization_profile': 'veritrail-json-c14n/1',
        'plan_digest': plan['seal']['digest'], 'observation_spec_digest': observation_spec_digest(spec),
        'request_seal_digest': sha256_json(request), 'collection_session_id': run,
        'collector_role': 'guihong-m6-reconciler', 'coverage': 'COMPLETE' if status == 'COMPLETED' else 'ERROR',
        'normalization_semantics_version': 'guihong-m6/1.0', 'facts_digest': sha256_json(facts),
    }
    if arguments.control == 'wrong-binding':
        metadata['plan_digest'] = '0' * 64
    evidence = {
        'schema_version': '0.1', 'evidence_type': spec['evidence_type'], 'source': 'guihong-m6/1.0',
        'captured_at': datetime.now(timezone.utc).isoformat(), 'facts': facts,
        'metadata': {'veritrail_observation': metadata},
    }
    save(output / 'evidence.json', evidence)
    report = create_acceptance_bundle(plan=plan,
        evidence_paths=[] if arguments.control == 'missing-evidence' else [output / 'evidence.json'],
        output=output / 'bundle', acceptance_id=run, execution_status=status)
    expected = {'none': 'PASS', 'wrong-binding': 'INCONCLUSIVE', 'missing-evidence': 'PENDING', 'wrong-release': 'FAIL'}[arguments.control]
    summary = {'identity': run, 'source_sha': source, 'execution_status': report['execution_status'],
               'verdict': report['verdict'], 'expected': expected, 'control': arguments.control,
               'bundle': (output / 'bundle').relative_to(ROOT).as_posix()}
    save(output / 'summary.json', summary); print(json.dumps(summary))
    return 0 if status == 'COMPLETED' and report['verdict'] == expected else 1


if __name__ == '__main__':
    raise SystemExit(main())
