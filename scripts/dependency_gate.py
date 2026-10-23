"""Current Go module / npm advisory change gate; not risk acceptance."""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'docs/governance/dependency-review.json'
GOVULNCHECK = 'v1.9.0'
GO_VERSION = 'go1.27.2'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def tool(name):
    executable = shutil.which(name + ('.cmd' if name == 'npm' else '.exe') if os.name == 'nt' else name)
    require(executable, f'missing {name}')
    return executable


def npm_findings(report, lock, exit_code):
    require(exit_code in (0, 1) and not report.get('error'), 'npm audit execution failed')
    require(lock.get('lockfileVersion') == 3, 'unsupported npm lockfile')
    packages = lock.get('packages', {})
    require(isinstance(packages, dict) and '' in packages and len(packages) > 1, 'empty npm lockfile')
    require(report.get('auditReportVersion') == 2, 'unsupported npm audit report')
    metadata = report.get('metadata', {})
    require(metadata.get('dependencies', {}).get('total') == len(packages) - 1, 'npm audit dependency denominator differs from lockfile')
    findings = report.get('vulnerabilities')
    require(isinstance(findings, dict), 'missing npm findings')
    levels = Counter()
    for name, finding in findings.items():
        require(finding.get('name') == name, 'npm finding identity mismatch')
        require(finding.get('severity') in {'info', 'low', 'moderate', 'high', 'critical'}, 'invalid npm severity')
        levels[finding['severity']] += 1
        nodes = finding.get('nodes')
        require(isinstance(nodes, list) and nodes and len(set(nodes)) == len(nodes), 'missing or duplicate npm nodes')
        require(all(node in packages for node in nodes), 'npm finding outside lockfile')
        via = finding.get('via')
        require(isinstance(via, list) and via, 'missing npm advisory origin')
        for source in via:
            if isinstance(source, str):
                require(source in findings, 'dangling npm advisory propagation')
            else:
                require(isinstance(source, dict) and source.get('source') and source.get('url') and source.get('title'), 'incomplete npm advisory')
    totals = metadata.get('vulnerabilities', {})
    require(totals.get('total') == len(findings), 'npm finding total mismatch')
    require(all(totals.get(k) == levels[k] for k in ('info', 'low', 'moderate', 'high', 'critical')), 'npm severity totals mismatch')
    require(exit_code == (1 if findings else 0), 'npm exit/report disagreement')
    # Keep raw reports. Remediation recommendations are not current risk facts.
    # npm's mutable reverse-effects set can differ while its complete advisory
    # 'via' relation is unchanged; reconstruct the inverse without losing edges.
    normalized = {}
    for name, finding in findings.items():
        value = deepcopy(finding)
        value.pop('fixAvailable', None)
        value['effects'] = sorted(parent for parent, detail in findings.items() if name in detail['via'])
        for field in ('nodes', 'effects', 'via'):
            if isinstance(value.get(field), list):
                value[field] = sorted(value[field], key=lambda x: json.dumps(x, sort_keys=True))
        normalized[name] = value
    return normalized


def stream(text):
    decoder = json.JSONDecoder(object_pairs_hook=unique)
    records, offset = [], 0
    while text[offset:].strip():
        offset += len(text[offset:]) - len(text[offset:].lstrip())
        value, offset = decoder.raw_decode(text, offset)
        require(isinstance(value, dict), 'non-object in JSON stream')
        records.append(value)
    require(records, 'empty JSON stream')
    return records


def go_inventory(records):
    modules = {}
    main = [x for x in records if x.get('Main')]
    require(len(main) == 1 and main[0].get('Path') == 'github.com/NoctilumeDev/GuiHongMail', 'wrong Go module root')
    for item in records:
        require(not item.get('Error') and not item.get('Replace'), 'Go resolution error or unreviewed replacement')
        name = item.get('Path')
        require(isinstance(name, str) and name and name not in modules, 'duplicate or missing Go module')
        version = item.get('Version', '')
        require(item.get('Main') or (isinstance(version, str) and version.startswith('v')), 'unresolved Go version')
        modules[name] = version
    require(len(modules) > 1, 'empty dependency denominator')
    modules['stdlib'] = 'v' + GO_VERSION.removeprefix('go')
    return modules


def imported_inventory(records, inventory):
    selected, roots = {'stdlib': inventory['stdlib']}, set()
    for package in records:
        require(not package.get('Error') and not package.get('DepsErrors') and not package.get('Incomplete'), 'Go package loading incomplete')
        path = package.get('ImportPath')
        require(isinstance(path, str) and path, 'missing Go package identity')
        if not package.get('DepOnly'):
            # go list identifies an in-package test variant with " [x.test]";
            # go/packages (and govulncheck SBOM) exposes its original PkgPath.
            roots.add(re.sub(r' \[[^\[\]]+\.test\]$', '', path))
        module = package.get('Module')
        if module:
            name, version = module.get('Path'), module.get('Version', '')
            require(not module.get('Replace') and name in inventory and inventory[name] == version, 'imported module outside resolved graph')
            selected[name] = version
        else:
            require(package.get('Standard'), 'unattributed non-standard Go package')
    require(roots and len(selected) > 1, 'empty Go source denominator')
    return selected, roots


def go_findings(records, inventory, roots, exit_code):
    require(exit_code == 0, 'govulncheck JSON execution failed')
    require(records and 'config' in records[0], 'missing govulncheck configuration')
    config, sbom, advisories, findings = [], [], {}, []
    for item in records:
        require(len(item) == 1, 'invalid govulncheck message')
        kind, value = next(iter(item.items()))
        require(kind in {'config', 'SBOM', 'progress', 'osv', 'finding'} and isinstance(value, dict), 'unknown or invalid scan message')
        if kind == 'config':
            config.append(value)
        elif kind == 'SBOM':
            sbom.append(value)
        elif kind == 'osv':
            key = value.get('id')
            require(isinstance(key, str) and key.startswith('GO-'), 'invalid Go advisory')
            # One advisory can be returned for multiple modules. Identical
            # records are valid; conflicting records must never be overwritten.
            require(key not in advisories or advisories[key] == value, 'conflicting Go advisory')
            advisories[key] = value
        elif kind == 'finding':
            findings.append(value)
    require(len(config) == len(sbom) == 1, 'missing or duplicate scan identity/coverage')
    cfg = config[0]
    require(cfg.get('protocol_version') == 'v1.0.0' and cfg.get('scanner_name') == 'govulncheck'
            and cfg.get('scanner_version') == GOVULNCHECK and cfg.get('go_version') == GO_VERSION
            and cfg.get('scan_level') == 'symbol' and cfg.get('scan_mode') == 'source'
            and cfg.get('db') == 'https://vuln.go.dev', 'unexpected scanner version or scope')
    require(sbom[0].get('go_version') == GO_VERSION, 'SBOM Go version mismatch')
    require(set(sbom[0].get('roots', [])) == set(roots), 'scan roots differ from requested source/test packages')
    observed = {}
    for item in sbom[0].get('modules', []):
        name = item.get('path')
        require(name in inventory and name not in observed, 'unexpected or duplicate scanned module')
        observed[name] = item.get('version', '')
    require(observed == inventory, 'scan SBOM differs from imported Go module graph')
    result = {}
    for finding in findings:
        key = finding.get('osv')
        trace = finding.get('trace')
        require(key in advisories and isinstance(trace, list) and trace, 'missing advisory or invalid trace')
        frame = trace[0]
        name = frame.get('module')
        require(name in inventory and frame.get('version') == inventory[name], 'finding outside module/version scope')
        identity = f'{name}@{inventory[name]}/{key}'
        entry = result.setdefault(identity, {'findings': [], 'advisory': advisories[key]})
        require(finding not in entry['findings'], 'duplicate Go finding')
        entry['findings'].append(finding)
    for entry in result.values():
        entry['findings'].sort(key=lambda x: json.dumps(x, sort_keys=True))
    return result


def review(observation, policy):
    require(policy.get('schema') == 'guihong-dependency-review/1', 'missing dependency review')
    require(re.fullmatch('[0-9a-f]{40}', policy.get('source_revision', '')), 'missing review source')
    require(policy.get('owner') == 'NoctilumeDev/GuiHongMail maintainers' and policy.get('risk_accepted') is False, 'missing owner or unauthorized risk acceptance')
    require(policy.get('inputs') == observation['inputs'], 'dependency inputs changed; review required')
    previous = policy.get('sources', {})
    require(set(previous) == set(observation['sources']), 'missing source')
    for name, current in observation['sources'].items():
        old = previous[name]
        require(old.get('inventory_sha256') == current['inventory_sha256'] and old.get('package_count') == current['package_count'], name + ': inventory/denominator changed')
        retained = old.get('findings', {})
        require(set(retained) == set(current['findings']), name + ': findings changed; review required')
        for key, finding in current['findings'].items():
            record = retained[key]
            require(record.get('sha256') == digest(finding), name + ': advisory details changed: ' + key)
            require(record.get('status') == 'UNRESOLVED', 'initial gate cannot accept or close risk')
            action = record.get('next_action')
            require(isinstance(action, str) and action.strip() and '\ufffd' not in action, 'missing or unreadable follow-up')
    return sum(len(x['findings']) for x in observation['sources'].values())


def command(args, cwd, output, stem, env=None, allowed=(0,)):
    with (output / (stem + '.stdout')).open('wb') as out, (output / (stem + '.stderr')).open('wb') as err:
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, stdout=out, stderr=err, timeout=600)
    save(output / (stem + '.exit.json'), {'exit_code': result.returncode})
    require(result.returncode in allowed, stem + ': command failed; see retained output')
    return result.returncode


def inputs():
    names = ['go.mod', 'go.sum', 'frontend/web/package.json', 'frontend/web/package-lock.json']
    return {name: digest(read(ROOT / name)) if name.endswith('.json') else hashlib.sha256((ROOT / name).read_text(encoding='utf-8').encode()).hexdigest() for name in names}


def collect(output):
    before = inputs()
    env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOFLAGS='-mod=readonly', GOSUMDB='sum.golang.org', GOPROXY='https://proxy.golang.org,direct')
    go = tool('go')
    command([go, 'env', 'GOVERSION'], ROOT, output, 'go-version', env)
    require((output / 'go-version.stdout').read_text().strip() == GO_VERSION, 'unexpected Go toolchain')
    command([go, 'mod', 'download'], ROOT, output, 'go-download', env)
    command([go, 'mod', 'verify'], ROOT, output, 'go-verify', env)
    command([go, 'list', '-m', '-json', 'all'], ROOT, output, 'go-modules', env)
    records = stream((output / 'go-modules.stdout').read_text(encoding='utf-8'))
    inventory = go_inventory(records)
    missing = [x['Path'] + '@' + x['Version'] for x in records if not x.get('Main') and not x.get('Dir')]
    if missing:
        command([go, 'mod', 'download', '-json', *missing], ROOT, output, 'go-missing-sources', env)
        downloaded = stream((output / 'go-missing-sources.stdout').read_text(encoding='utf-8'))
        by_path = {x['Path']: x for x in downloaded}
        require(len(by_path) == len(missing), 'module source download denominator mismatch')
        for item in records:
            if item['Path'] in by_path:
                resolved = by_path[item['Path']]
                require(not resolved.get('Error') and resolved.get('Version') == item['Version'], 'module source download failed')
                item['Dir'] = resolved.get('Dir')
    licenses = {}
    for item in records:
        if item.get('Main'):
            continue
        directory = item.get('Dir')
        require(directory and Path(directory).is_dir(), 'module cache/source missing')
        license_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(directory).iterdir()
                         if p.is_file() and p.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE'))}
        licenses[item['Path'] + '@' + item['Version']] = {'source_files': license_files, 'status': 'SOURCE_HASHED_NOT_LEGAL_REVIEW' if license_files else 'LICENSE_SOURCE_UNVERIFIED'}
    save(output / 'go-licenses.json', licenses)
    # Install only a fixed scanner into this unique run directory, never global PATH.
    env['GOBIN'] = str(output / 'tools')
    command([go, 'install', 'golang.org/x/vuln/cmd/govulncheck@' + GOVULNCHECK], ROOT, output, 'scanner-install', env)
    scanner = Path(env['GOBIN']) / ('govulncheck.exe' if os.name == 'nt' else 'govulncheck')
    command([go, 'version', '-m', scanner], ROOT, output, 'scanner-build', env)
    sources = {}
    for target_os in ('windows', 'linux'):
        target_env = dict(env, GOOS=target_os, GOARCH='amd64', CGO_ENABLED='0')
        stem = 'go-' + target_os
        command([go, 'list', '-deps', '-test', '-json', './...'], ROOT, output, stem + '-packages', target_env)
        imported, roots = imported_inventory(stream((output / (stem + '-packages.stdout')).read_text(encoding='utf-8')), inventory)
        code = command([scanner, '-json', '-scan=symbol', '-test', '-db=https://vuln.go.dev', './...'], ROOT, output, stem + '-vuln', target_env)
        findings = go_findings(stream((output / (stem + '-vuln.stdout')).read_text(encoding='utf-8')), imported, roots, code)
        sources[stem] = {'inventory_sha256': digest({'resolved_modules': inventory, 'imported_modules': imported, 'licenses': licenses, 'roots': sorted(roots)}), 'package_count': len(imported), 'findings': findings}
    directory = ROOT / 'frontend/web'
    lock = read(directory / 'package-lock.json')
    code = command([tool('npm'), 'audit', '--package-lock-only', '--ignore-scripts', '--include=dev', '--include=optional', '--include=peer', '--audit-level=info', '--json', '--registry=https://registry.npmjs.org'], directory, output, 'npm', allowed=(0, 1))
    sources['npm-web'] = {'inventory_sha256': digest(lock), 'package_count': len(lock['packages']) - 1, 'findings': npm_findings(read(output / 'npm.stdout'), lock, code)}
    require(before == inputs(), 'source inputs changed during scan')
    observation = {'inputs': before, 'sources': sources}
    save(output / 'observation.json', observation)
    return observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect-only', action='store_true')
    args = parser.parse_args()
    parent = ROOT / 'artifacts/local/governance/dependencies'
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    print('Dependency evidence: ' + str(output), flush=True)
    record = {'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'working_tree_changed': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()), 'state': 'STARTED'}
    save(output / 'run.json', record)
    try:
        observation = collect(output)
        if args.collect_only:
            record['state'] = 'OBSERVATION_ONLY_NOT_GATE_PASS'
        else:
            record.update(state='CHANGE_GATE_PASS', unresolved=review(observation, read(POLICY)))
        print(json.dumps(record))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        record.update(state='ERROR_OR_REVIEW_REQUIRED', error=str(error))
        print('Dependency gate rejected: ' + str(error), file=sys.stderr)
        return 1
    finally:
        save(output / 'run.json', record)


if __name__ == '__main__':
    sys.exit(main())
