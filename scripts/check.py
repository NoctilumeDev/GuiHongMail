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
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    stage_docs = [p for p in tracked if p.startswith('docs/') and p.endswith('.md')]
    for rel in sorted(set(REQUIRED + contract_files() + stage_docs)):
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

def backend():
    errors = []
    pom = (ROOT/'backend/pom.xml').read_text(encoding='utf-8')
    modules = re.findall(r'<module>([^<]+)</module>', pom)
    expected = ['platform-common','mailbox-service','smtp-ingress','delivery-worker']
    if modules != expected:
        errors.append('backend module boundary differs from '+repr(expected))
    for value in ['<java.version>17</java.version>','<aws.version>2.55.15</aws.version>',
                  '<rocketmq.version>5.5.0</rocketmq.version>','<angus.version>2.0.5</angus.version>',
                  '<html-sanitizer.version>20260313.1</html-sanitizer.version>']:
        if value not in pom:errors.append('missing backend version lock '+value)
    services = {'mailbox-service':'mailbox','smtp-ingress':'ingress','delivery-worker':'delivery'}
    for module, migration in services.items():
        module_pom=(ROOT/'backend'/module/'pom.xml').read_text(encoding='utf-8')
        internal=[item for item in re.findall(r'<groupId>dev\.guihong</groupId><artifactId>([^<]+)</artifactId>',module_pom)
                  if item!='guihong-backend']
        if internal != ['platform-common']:errors.append(module+' has cross-service or missing internal dependency '+repr(internal))
        if not (ROOT/'backend'/module/'src/main/resources/db/migration'/migration/'V1__foundation.sql').is_file():
            errors.append(module+' missing independent foundation migration')
    if errors:raise RuntimeError('\n'.join(errors))
    return {'modules':modules,'independent_migrations':len(services),'java_release':17}

def frontend():
    package=json.loads((ROOT/'frontend/web/package.json').read_text(encoding='utf-8'))
    lock=json.loads((ROOT/'frontend/web/package-lock.json').read_text(encoding='utf-8'))
    errors=[]
    if package.get('dependencies')!={'vue':'3.5.44'}:errors.append('frontend runtime dependency set changed')
    if lock.get('lockfileVersion')!=3 or lock.get('packages',{}).get('',{}).get('dependencies')!=package.get('dependencies'):
        errors.append('frontend lock does not bind runtime dependencies')
    navigation=(ROOT/'frontend/web/src/navigation.ts').read_text(encoding='utf-8')
    labels=re.findall(r"label: '([^']+)'",navigation)
    if labels!=['写信','收件箱','已发邮件','草稿箱','归档','垃圾邮件','已删除']:
        errors.append('frontend navigation differs from frozen seven entries')
    css=(ROOT/'frontend/web/src/styles.css').read_text(encoding='utf-8')
    for required in ('.pane {','overflow-y: auto','@media (max-width: 700px)','.left-collapsed','.list-collapsed',
                     '.mobile-step-folders','.mobile-step-list','.mobile-step-reader'):
        if required not in css:errors.append('frontend layout contract missing '+required)
    app=(ROOT/'frontend/web/src/App.vue').read_text(encoding='utf-8')
    for required in ('sandbox=""','发送（M3 开放）'):
        if required not in app:errors.append('frontend safety/route contract missing '+required)
    if errors:raise RuntimeError('\n'.join(errors))
    return {'runtime_dependencies':package['dependencies'],'lockfile_version':3,'navigation_entries':labels,'independent_scroll_regions':3}

def architecture():
    errors=[]
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    java=[rel for rel in tracked if rel.startswith('backend/') and '/src/main/java/' in rel and rel.endswith('.java')]
    forbidden_domain=('org.springframework','jakarta.','java.sql','javax.sql','software.amazon','org.apache.rocketmq','org.subethamail')
    service_roots={'mailbox-service':'dev.guihong.mailbox','smtp-ingress':'dev.guihong.ingress','delivery-worker':'dev.guihong.delivery'}
    checked_domain=checked_application=0
    for rel in java:
        text=(ROOT/rel).read_text(encoding='utf-8')
        imports=re.findall(r'^import\s+([^;]+);',text,re.MULTILINE)
        parts=Path(rel).parts
        if 'domain' in parts:
            checked_domain+=1
            bad=[name for name in imports if name.startswith(forbidden_domain)]
            if bad:errors.append(rel+' domain imports implementation '+', '.join(bad))
        if 'application' in parts:
            checked_application+=1
            bad=[name for name in imports if '.infrastructure.' in name or '.interfaces.' in name]
            if bad:errors.append(rel+' application points outward '+', '.join(bad))
        module=parts[1] if len(parts)>1 else ''
        if module in service_roots:
            foreign=[namespace for owner,namespace in service_roots.items() if owner!=module and namespace in text]
            if foreign:errors.append(rel+' imports another service namespace '+', '.join(foreign))
    if checked_domain<3 or checked_application<1:errors.append('declared domain/application layers were not found')
    if errors:raise RuntimeError('\n'.join(errors))
    return {'main_java_files':len(java),'domain_files':checked_domain,'application_files':checked_application,'violations':0}

def security():
    errors=[]
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    signatures=[b'-----BEGIN '+b'PRIVATE KEY-----',b'AKIA'+b'[A-Z0-9]{16}',b'ghp_'+b'[A-Za-z0-9]{30,}',
                b'github_pat_'+b'[A-Za-z0-9_]{40,}',b'xoxb-'+b'[A-Za-z0-9-]{20,}']
    text_suffixes={'.md','.py','.java','.sql','.xml','.yml','.yaml','.json','.properties','.conf','.txt'}
    for rel in filter(None,tracked):
        path=ROOT/rel
        if path.suffix.lower() not in text_suffixes or not path.is_file() or path.stat().st_size>2*1024*1024:continue
        data=path.read_bytes()
        for signature in signatures:
            if re.search(signature,data):errors.append(rel+' contains a credential signature')
    compose=(ROOT/'deploy/compose.yaml').read_text(encoding='utf-8')
    published=re.findall(r"['\"]([^'\"]*:\d+:\d+)['\"]",compose)
    non_loopback=[item for item in published if not item.startswith('127.0.0.1:')]
    if not published or non_loopback:errors.append('compose host ports are absent or non-loopback '+repr(non_loopback))
    for module in ('mailbox-service','smtp-ingress','delivery-worker'):
        props=(ROOT/'backend'/module/'src/main/resources/application.properties').read_text(encoding='utf-8')
        for required in ('server.address=127.0.0.1','server.error.include-message=never','server.error.include-stacktrace=never'):
            if required not in props:errors.append(module+' missing '+required)
    smtp=(ROOT/'backend/smtp-ingress/src/main/java/dev/guihong/ingress/infrastructure/FoundationSmtpListener.java').read_text(encoding='utf-8')
    if 'bindAddress(InetAddress.getByName("127.0.0.1"))' not in smtp:errors.append('SMTP listener is not statically bound to loopback')
    identity=(ROOT/'backend/mailbox-service/src/main/java/dev/guihong/mailbox/interfaces/IdentityController.java').read_text(encoding='utf-8')
    for required in ('.httpOnly(true)','.sameSite("Strict")','.path("/api")'):
        if required not in identity:errors.append('session cookie missing '+required)
    store=(ROOT/'backend/platform-common/src/main/java/dev/guihong/platform/S3ObjectStore.java').read_text(encoding='utf-8')
    if 'retryPolicy(RetryPolicy.none())' not in store:errors.append('S3 automatic retry policy is not explicitly disabled')
    if errors:raise RuntimeError('\n'.join(errors))
    return {'credential_signatures':0,'published_ports':published,'loopback_services':3,'session_cookie_flags':3,'s3_sdk_retries':0}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('gate',choices=['docs','seal','backend','frontend','architecture','security','hygiene','all'])
    args = parser.parse_args()
    gates = {'docs':docs,'seal':make_seal,'backend':backend,'frontend':frontend,'architecture':architecture,'security':security,'hygiene':hygiene}
    selected = ['docs','backend','frontend','architecture','security','hygiene'] if args.gate=='all' else [args.gate]
    print(json.dumps({key:gates[key]() for key in selected}, ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
