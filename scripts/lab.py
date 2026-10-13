"""Explicit owned lab operations. No global install/configuration/prune or secret output."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / '.artifacts' / 'lab'
SERVICES = ('mailbox', 'ingress', 'delivery')

def docker():
    found = shutil.which('docker')
    if found:
        return found
    candidate = Path('D:/DevTools/DockerDesktop/resources/bin/docker.exe')
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError('Existing Docker CLI unavailable; no implicit installation')

def memory():
    if sys.platform == 'win32':
        class State(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (x, ctypes.c_ulonglong) for x in ('total', 'free', 'page_total', 'page_free', 'virtual_total', 'virtual_free', 'extended')]
        state = State(); state.length = ctypes.sizeof(state)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            raise RuntimeError('Cannot establish memory stop line')
        return {'total_bytes': state.total, 'free_bytes': state.free, 'used_bytes': state.total - state.free}
    values = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    total = int(values['MemTotal'].split()[0]) * 1024
    free = int(values['MemAvailable'].split()[0]) * 1024
    return {'total_bytes': total, 'free_bytes': free, 'used_bytes': total-free}

def write_new(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

def load():
    state = json.loads((LAB/'state.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'guihong-[a-z0-9-]{1,40}', state['id']):
        raise RuntimeError('Invalid ownership id')
    if Path(state['root']).resolve() != LAB.resolve():
        raise RuntimeError('Lab moved; do not implicitly adopt its persistent resources')
    return state

def compose(args, timeout=300, capture=False):
    state = load()
    env = dict(os.environ)
    env.update(GUIHONG_LAB_ID=state['id'], GUIHONG_LAB_DIR=LAB.resolve().as_posix())
    cmd = [docker(), 'compose', '--project-name', state['id'], '-f', str(ROOT/'deploy/compose.yaml'), *args]
    return subprocess.run(cmd, cwd=ROOT, env=env, timeout=timeout, capture_output=capture, text=True, check=True)

def assert_owned():
    state = load()
    ids = subprocess.check_output([docker(),'ps','-aq','--filter','label=com.docker.compose.project='+state['id']],text=True).split()
    for identity in ids:
        info = json.loads(subprocess.check_output([docker(),'inspect',identity],text=True))[0]
        if info['Config']['Labels'].get('guihong.owner') != state['id']:
            raise RuntimeError('Project collision/unowned container; stop without mutation')
    # Existing named volumes/networks must agree before Compose is allowed to reuse them.
    for kind in ('volume','network'):
        names = subprocess.check_output([docker(),kind,'ls','-q','--filter','label=com.docker.compose.project='+state['id']],text=True).split()
        for name in names:
            info = json.loads(subprocess.check_output([docker(),kind,'inspect',name],text=True))[0]
            if (info.get('Labels') or {}).get('guihong.owner') != state['id']:
                raise RuntimeError('Project collision/unowned persistent resource')
        expected = ('mysql-data','object-data','mq-data') if kind=='volume' else ('database','storage','mq')
        for suffix in expected:
            name=state['id']+'_'+suffix
            inspected=subprocess.run([docker(),kind,'inspect',name],capture_output=True,text=True)
            if inspected.returncode==0:
                info=json.loads(inspected.stdout)[0]
                if (info.get('Labels') or {}).get('guihong.owner')!=state['id']:
                    raise RuntimeError('Exact-name collision with unowned '+kind)
            elif ('no such volume' not in inspected.stderr.lower() if kind=='volume'
                  else re.search(r'network .* not found',inspected.stderr.lower()) is None):
                raise RuntimeError('Cannot establish ownership before mutation')
    return ids

def owned_ports():
    ports=set()
    for identity in assert_owned():
        info=json.loads(subprocess.check_output([docker(),'inspect',identity],text=True))[0]
        for mappings in (info['NetworkSettings'].get('Ports') or {}).values():
            for mapping in mappings or []:
                if mapping['HostIp']=='127.0.0.1':
                    ports.add(int(mapping['HostPort']))
    return ports

def init():
    if LAB.exists():
        raise RuntimeError('Lab already exists; use it explicitly, never overwrite credentials or witness')
    LAB.mkdir(parents=True)
    run_id = 'guihong-local-'+uuid.uuid4().hex[:12]
    state = {'schema':'GuiHongLab/1.0','id':run_id,'root':str(LAB.resolve()),'ports':{'mysql':13306,'s3':19833,'namesrv':19876,'broker':20911}}
    private = {'database':{}, 'storage':{}, 'internal':{}, 'accounts':{}}
    root_password = secrets.token_hex(24)
    write_new(LAB/'mysql-root', root_password+'\n')
    sql=[]; identities=[]
    for service in SERVICES:
        db='guihong_'+service; user='guihong_'+service; password=secrets.token_hex(24)
        private['database'][service]={'schema':db,'user':user,'password':password}
        sql.extend([f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;',
                    f"CREATE USER '{user}'@'%' IDENTIFIED BY '{password}';",
                    f"GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,INDEX,REFERENCES ON `{db}`.* TO '{user}'@'%';"])
        key=secrets.token_hex(12); secret=secrets.token_hex(24); bucket='guihong-'+service
        private['storage'][service]={'access_key':key,'secret_key':secret,'bucket':bucket}
        private['internal'][service]=secrets.token_hex(32)
        identities.append({'name':service,'credentials':[{'accessKey':key,'secretKey':secret}],
                           'actions':[f'{action}:{bucket}' for action in ('Read','Write','List')]})
    for name in ('alice','bob'):
        private['accounts'][name]={'address':name+'@guihong.test','password':secrets.token_urlsafe(24)}
    write_new(LAB/'mysql-init.sql', '\n'.join(sql)+'\n')
    write_new(LAB/'s3.json',json.dumps({'identities':identities},indent=2)+'\n')
    write_new(LAB/'secrets.json',json.dumps(private,indent=2)+'\n')
    write_new(LAB/'broker.conf','\n'.join([
        'brokerClusterName='+run_id,'brokerName='+run_id+'-broker','brokerId=0','brokerRole=ASYNC_MASTER',
        'brokerIP1=127.0.0.1','listenPort=20911','autoCreateTopicEnable=false','autoCreateSubscriptionGroup=false',
        'flushDiskType=SYNC_FLUSH','storePathRootDir=/home/rocketmq/store','mapedFileSizeCommitLog=67108864',
        'maxMessageSize=1048576','diskMaxUsedSpaceRatio=85','deleteWhen=04','fileReservedTime=72',
        'enableControllerMode=false'])+'\n')
    (LAB/'witness').mkdir()
    write_new(LAB/'state.json',json.dumps(state,indent=2)+'\n')
    print(json.dumps({'id':run_id,'initialized':True,'credentials':'private ignored files only'}))

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','up','down','status','restart-storage']);p.add_argument('--storage-only',action='store_true')
    args=p.parse_args()
    if args.action=='init':
        init();return
    state=load();assert_owned()
    if args.action=='up':
        snapshot=memory()
        if snapshot['free_bytes']<4*1024**3 or snapshot['used_bytes']>14*1024**3:
            raise RuntimeError('Memory admission denied; leave other applications/resources untouched')
        if shutil.disk_usage(ROOT).free<10*1024**3:
            raise RuntimeError('Disk admission denied')
        for port in ([19833] if args.storage_only else state['ports'].values()):
            # Reentrant owned containers may already bind these ports; only unoccupied startup is admitted here.
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',int(port)))==0:
                    if int(port) not in owned_ports():
                        raise RuntimeError('Unknown listener on required project port')
        compose(['up','-d',*(['seaweedfs'] if args.storage_only else [])])
    elif args.action=='down':
        compose(['down','--timeout','20']) # deliberately preserve data volumes and witness
    elif args.action=='restart-storage':
        compose(['restart','--timeout','20','seaweedfs'])
    else:
        print(compose(['ps','--format','json'],capture=True).stdout)
        print(json.dumps({'memory':memory(),'id':state['id']}))

if __name__=='__main__':
    main()
