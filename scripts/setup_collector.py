"""Explicit isolated public dependency installation; no source-tree VeriTrail imports."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--proxy')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,10):
        raise RuntimeError('Qualified collector profile uses Python 3.10')
    target=ROOT/'.artifacts/lab-env'
    if not target.exists():venv.EnvBuilder(with_pip=True).create(target)
    executable=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    env=dict(os.environ)
    for key in ('PYTHONPATH','GH_TOKEN','GITHUB_TOKEN'):env.pop(key,None)
    if args.proxy:
        env['HTTP_PROXY']=env['HTTPS_PROXY']=args.proxy
    subprocess.run([str(executable),'-m','pip','install','--disable-pip-version-check','--require-hashes',
                    '--force-reinstall','-r',str(ROOT/'scripts/collector-requirements.lock')],
                   cwd=ROOT,env=env,timeout=300,check=True)

if __name__=='__main__':main()
