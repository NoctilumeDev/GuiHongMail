"""Explicit isolated public dependency installation; no source-tree VeriTrail imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def plain_directory(path,parent):
    if not path.is_dir() or path.is_symlink():raise RuntimeError('Collector environment path is not an ordinary directory')
    if getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0):
        raise RuntimeError('Collector environment path is a reparse point')
    if path.resolve().parent!=parent.resolve():raise RuntimeError('Collector environment escaped its owned parent')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--proxy')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,10):
        raise RuntimeError('Qualified collector profile uses Python 3.10')
    artifacts=ROOT/'.artifacts';plain_directory(artifacts,ROOT)
    target=artifacts/'lab-env';created=False
    if not target.exists():venv.EnvBuilder(with_pip=True).create(target);created=True
    plain_directory(target,artifacts)
    executable=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not executable.is_file() or executable.is_symlink() or not executable.resolve().is_relative_to(target.resolve()):
        raise RuntimeError('Collector interpreter identity is unsafe')
    lock=ROOT/'scripts/collector-requirements.lock';marker=target/'.guihong-collector.json'
    expected={'schema':'GuiHongCollectorEnvironment/1.0','base_executable':str(Path(sys.executable).resolve()),
              'python_version':'.'.join(map(str,sys.version_info[:3])),'requirements_sha256':sha(lock),'executable_sha256':sha(executable)}
    if not created:
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8'))!=expected:
            raise RuntimeError('Existing collector environment has no matching creation receipt')
    env=dict(os.environ)
    for key in ('PYTHONPATH','GH_TOKEN','GITHUB_TOKEN'):env.pop(key,None)
    if args.proxy:
        env['HTTP_PROXY']=env['HTTPS_PROXY']=args.proxy
    subprocess.run([str(executable),'-m','pip','install','--disable-pip-version-check','--require-hashes',
                    '--force-reinstall','-r',str(lock)],
                   cwd=ROOT,env=env,timeout=300,check=True)
    if created:
        with marker.open('x',encoding='utf-8',newline='\n') as stream:json.dump(expected,stream,sort_keys=True);stream.write('\n')

if __name__=='__main__':main()
