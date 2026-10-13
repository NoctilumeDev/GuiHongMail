"""Bounded repository gates; never installs or starts resources implicitly."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SEAL = ROOT / 'docs/m0-seal.json'
REQUIRED = ['README.md', 'AGENTS.md', 'SECURITY.md', 'docs/m0.md', 'docs/milestones.md',
            'docs/continuous-run.md', 'docs/authorization.md', 'docs/acceptance-obligations.md',
            'docs/contracts/mail-facts.md', 'docs/contracts/security.md',
            'docs/contracts/service-boundaries.md', 'docs/contracts/delivery-lifecycle.md',
            'docs/contracts/storage-lifecycle.md', 'docs/contracts/recovery.md',
            'docs/design.md', 'docs/verification.md', 'docs/failure-matrix.md',
            'docs/engineering-gates.md', 'docs/decisions.md', 'docs/research-sources.md']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def contract_files():
    # Freeze normative M0 bytes, not mutable status, future stage docs or gate tooling.
    names = set(['docs/m0.md','docs/milestones.md','docs/continuous-run.md',
                 'docs/authorization.md','docs/acceptance-obligations.md',
                 'docs/contracts/mail-facts.md','docs/contracts/security.md',
                 'docs/contracts/service-boundaries.md','docs/contracts/delivery-lifecycle.md',
                 'docs/contracts/storage-lifecycle.md','docs/contracts/recovery.md',
                 'docs/design.md','docs/verification.md','docs/engineering-gates.md',
                 'docs/failure-matrix.md','design/references/README.md',
                 'design/references/guihong-inbox-light-ink-candidate.png'])
    return sorted(names)

def docs():
    errors = []
    for rel in REQUIRED:
        if not (ROOT/rel).is_file():
            errors.append('missing required contract: '+rel)
    for rel in sorted(set(REQUIRED + contract_files())):
        p = ROOT/rel
        if not p.is_file():
            errors.append('missing seal input: '+rel)
            continue
        if p.suffix != '.md':
            continue
        text = p.read_text(encoding='utf-8')
        for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
            href = match[1].strip('<>')
            parsed = urlsplit(href)
            if parsed.scheme or not parsed.path:
                continue
            target = (p.parent/unquote(parsed.path)).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f'{rel}: broken local link {href}')
    image = ROOT/'design/references/guihong-inbox-light-ink-candidate.png'
    if image.exists() and digest(image) != '85c9a697ecc3d004a257fae8d73fe78a9f947bcb3cea7bce902455e9c0398972':
        errors.append('reference image digest changed')
    required_ids = re.findall(r'^\| (A\d\d) \|', (ROOT/'docs/acceptance-obligations.md').read_text(encoding='utf-8'), re.MULTILINE)
    if required_ids != [f'A{i:02}' for i in range(1,18)]:
        errors.append('obligation denominator differs from approved A01-A17')
    if errors:
        raise RuntimeError('\n'.join(errors))
    result = {'required_contracts': len(REQUIRED), 'link_errors': 0,
              'reference_sha256': digest(image), 'obligation_ids': required_ids}
    if SEAL.exists():
        verify_seal()
        result['seal_digest'] = json.loads(SEAL.read_text(encoding='utf-8'))['digest']
    return result

def make_seal():
    if SEAL.exists():
        raise RuntimeError('M0 seal already exists; immutable, create a new reviewed version')
    docs()
    content = {'schema_version': '1.0', 'contract_version': 1,
               'authority': 'human:repository-owner:guihong-m1-m6-20261013',
               'scope': 'M0 contracts only; no runtime qualification',
               'files': {rel: {'sha256': digest(ROOT/rel), 'bytes': (ROOT/rel).stat().st_size}
                         for rel in contract_files()}}
    sealed = {'content': content, 'digest': hashlib.sha256(canonical(content)).hexdigest()}
    with SEAL.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(sealed,out,ensure_ascii=False,indent=2)
        out.write('\n')
    return verify_seal()

def verify_seal():
    sealed = json.loads(SEAL.read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(sealed['content'])).hexdigest() != sealed['digest']:
        raise RuntimeError('M0 seal manifest digest mismatch')
    if set(sealed['content']['files']) != set(contract_files()):
        raise RuntimeError('M0 seal input set changed')
    for rel, entry in sealed['content']['files'].items():
        path = (ROOT/rel).resolve()
        if not path.is_relative_to(ROOT) or path.is_symlink() or not path.is_file():
            raise RuntimeError('M0 seal input unsafe or missing: '+rel)
        if digest(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
            raise RuntimeError('M0 frozen bytes changed: '+rel)
    return {'seal_digest': sealed['digest'], 'files_verified': len(sealed['content']['files'])}

def hygiene():
    files = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    forbidden = []
    for rel in filter(None,files):
        parts = Path(rel).parts
        if ('.artifacts' in parts or 'node_modules' in parts or 'target' in parts
            or rel.endswith(('.eml','.mbox','.pem','.key','.p12'))
            or (Path(rel).name.startswith('.env') and Path(rel).name!='.env.example')):
            forbidden.append(rel)
    if forbidden:
        raise RuntimeError('tracked private/generated files: '+', '.join(forbidden))
    return {'tracked_files': len(list(filter(None,files))), 'forbidden_tracked': forbidden}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('gate',choices=['docs','seal','hygiene','all'])
    args = parser.parse_args()
    gates = {'docs':docs,'seal':make_seal,'hygiene':hygiene}
    selected = ['docs','hygiene'] if args.gate=='all' else [args.gate]
    print(json.dumps({key:gates[key]() for key in selected}, ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
