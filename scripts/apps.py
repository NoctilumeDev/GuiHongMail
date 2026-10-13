"""Own three local JVMs; bind jar hashes/PID creation time, never kill by process name."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import uuid
import lab

JAVA = Path('D:/IDEA/JDK17/bin/java.exe')
MVN = Path('D:/Maven/apache-maven-3.9.11-bin/apache-maven-3.9.11/bin/mvn.cmd')
PORTS = {'mailbox':18080,'ingress':18081,'delivery':18082}
MODULES = {'mailbox':'mailbox-service','ingress':'smtp-ingress','delivery':'delivery-worker'}
PROCESSES = lab.LAB/'applications'

def environment():
    env=dict(os.environ)
    for name in list(env):
        if name.lower() in {'http_proxy','https_proxy','all_proxy','no_proxy','pythonpath','github_token','gh_token'}:
            env.pop(name,None)
    env.update(JAVA_HOME=str(JAVA.parent.parent),PYTHONUTF8='1',NO_PROXY='127.0.0.1,localhost')
    return env

def process_identity(pid):
    if os.name!='nt': raise RuntimeError('This pinned app profile is Windows native')
    kernel=ctypes.windll.kernel32
    kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x1000|0x100000,False,pid)
    if not handle:return None
    try:
        values=[ctypes.c_ulonglong() for _ in range(4)]
        if not kernel.GetProcessTimes(ctypes.c_void_p(handle),*[ctypes.byref(x) for x in values]):
            raise RuntimeError('Cannot bind PID creation time')
        exit_code=ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(exit_code)):
            raise RuntimeError('Cannot read owned process state')
        if exit_code.value!=259:return None
        size=ctypes.c_ulong(32768);name=ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(ctypes.c_void_p(handle),0,name,ctypes.byref(size)):
            if kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(exit_code)) and exit_code.value!=259:return None
            raise RuntimeError('Cannot bind process executable')
        if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(exit_code)):
            raise RuntimeError('Cannot read owned process state')
        if exit_code.value!=259:return None
        return {'creation_ticks':values[0].value,'executable':name.value}
    finally:kernel.CloseHandle(ctypes.c_void_p(handle))

def private():return json.loads((lab.LAB/'secrets.json').read_text())

def request(role,path,method='GET'):
    secret=private()['internal'][role]
    req=urllib.request.Request(f'http://127.0.0.1:{PORTS[role]}'+path,method=method,
       headers={'Authorization':'Bearer '+secret,'X-GuiHong-Service':'lab'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10) as response:
        return json.load(response)

def prepare():
    import pymysql
    lab.assert_owned();credentials=private();observations=[]
    for role in lab.SERVICES:
        root=lab.LAB/'witness'/role
        if root.exists():raise RuntimeError('Witness already exists; no reset/adopt operation')
        db=credentials['database'][role]
        with pymysql.connect(host='127.0.0.1',port=13306,user=db['user'],password=db['password'],database=db['schema'],connect_timeout=5) as c:
            with c.cursor() as q:
                q.execute('SHOW TABLES');tables=q.fetchall()
                q.execute('SELECT DATABASE(),CURRENT_USER(),VERSION()');binding=q.fetchone()
        if tables:raise RuntimeError('Bootstrap refused for a non-virgin schema')
        observations.append({'service':role,'schema':binding[0],'database_identity':binding[1],'version':binding[2],'tables':[]})
    # No filesystem authority is created until all three independent schemas are known virgin.
    for row in observations:
        root=lab.LAB/'witness'/row['service'];root.mkdir()
        lab.write_new(root/'generation.txt',str(uuid.uuid4())+'\n')
        lab.write_new(root/'virgin-observation.json',json.dumps(row,indent=2)+'\n')
        lab.write_new(root/'bootstrap-permit','virgin schema observed by explicit owned lab preparation\n')
    print(json.dumps({'prepared':list(PORTS),'schemas_virgin':True}))

def build():
    if subprocess.check_output(['git','status','--porcelain'],cwd=lab.ROOT):
        raise RuntimeError('Build identity requires committed clean source')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=lab.ROOT,text=True).strip()
    root=lab.ROOT/'.artifacts/build';root.mkdir(exist_ok=True,parents=True)
    settings=root/'settings.xml'
    if not settings.exists():lab.write_new(settings,'<settings><proxies><proxy><id>scoped</id><active>true</active><protocol>http</protocol><host>127.0.0.1</host><port>7897</port><nonProxyHosts>127.0.0.1|localhost</nonProxyHosts></proxy></proxies></settings>\n')
    target=root/('build-'+sha+'.log')
    with target.open('x',encoding='utf-8') as log:
        p=subprocess.run([str(MVN),'-B','-ntp','-s',str(settings),'-Dmaven.repo.local='+str(lab.ROOT/'.artifacts/m2'),
            '-f',str(lab.ROOT/'backend/pom.xml'),'-Dguihong.source_sha='+sha,'verify'],cwd=lab.ROOT,env=environment(),stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if p.returncode:raise RuntimeError('Build failed; retained '+str(target))
    print(json.dumps({'source_sha':sha,'build_log':str(target),'exit_code':p.returncode}))

def start(database_ports=None):
    lab.assert_owned()
    if lab.memory()['used_bytes']>14*1024**3:raise RuntimeError('Host memory stop line reached before app startup')
    database_ports=database_ports or {}
    PROCESSES.mkdir(exist_ok=True)
    credentials=private();source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=lab.ROOT,text=True).strip()
    for role in lab.SERVICES:
        record=PROCESSES/(role+'.json')
        if record.exists():
            previous=json.loads(record.read_text())
            if process_identity(previous['pid']) is not None:raise RuntimeError('Prior PID remains active; no implicit adoption')
            record.rename(PROCESSES/(role+'-exited-'+uuid.uuid4().hex+'.json'))
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',PORTS[role]))==0:raise RuntimeError('Unknown listener on required app port')
        jar=lab.ROOT/'backend'/MODULES[role]/'target'/(MODULES[role]+'-0.1.0-SNAPSHOT.jar')
        if not jar.is_file():raise RuntimeError('Exact build unavailable')
        db=credentials['database'][role];storage=credentials['storage'][role];env=environment()
        env.update(GUIHONG_WITNESS_ROOT=str(lab.LAB/'witness'/role),GUIHONG_INTERNAL_TOKEN=credentials['internal'][role],
            GUIHONG_DB_URL=f"jdbc:mysql://127.0.0.1:{database_ports.get(role,13306)}/{db['schema']}?sslMode=DISABLED&allowPublicKeyRetrieval=true&connectTimeout=3000&socketTimeout=10000",
            GUIHONG_DB_USER=db['user'],GUIHONG_DB_PASSWORD=db['password'],GUIHONG_S3_ENDPOINT='http://127.0.0.1:19833',
            GUIHONG_S3_BUCKET=storage['bucket'],GUIHONG_S3_KEY=storage['access_key'],GUIHONG_S3_SECRET=storage['secret_key'],
            GUIHONG_NAMESRV='127.0.0.1:19876',GUIHONG_BROKER='127.0.0.1:20911',GUIHONG_LAB_ID=lab.load()['id'])
        log=PROCESSES/(role+'-'+uuid.uuid4().hex+'.log')
        with log.open('xb') as output:
            p=subprocess.Popen([str(JAVA),'-Xms32m','-Xmx192m','-XX:MaxDirectMemorySize=32m','-XX:ActiveProcessorCount=2',
                '-jar',str(jar)],cwd=lab.ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        identity=process_identity(p.pid)
        if identity is None:raise RuntimeError('App exited before PID binding')
        lab.write_new(record,json.dumps({'lab_id':lab.load()['id'],'role':role,'pid':p.pid,**identity,
            'source_sha':source,'jar':str(jar),'jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'log':str(log)},indent=2)+'\n')
        until=time.monotonic()+60
        while time.monotonic()<until:
            if process_identity(p.pid)!=identity:raise RuntimeError('Application exited; original log retained')
            try:
                actual=request(role,'/internal/identity')
                if actual['source_sha']!=source or actual['service']!=role:raise RuntimeError('Installed app/source binding mismatch')
                print(json.dumps({'started':role,'identity':actual}));break
            except urllib.error.URLError:time.sleep(.5)
        else:raise RuntimeError('Application did not become identifiable within 60s')

def stop():
    if not PROCESSES.exists():return
    for role in reversed(lab.SERVICES):
        record=PROCESSES/(role+'.json')
        if not record.exists():continue
        owned=json.loads(record.read_text());current=process_identity(owned['pid'])
        if current is None:continue
        if owned['lab_id']!=lab.load()['id'] or current!={k:owned[k] for k in ('creation_ticks','executable')}:
            raise RuntimeError('PID ownership changed; stop without mutation')
        if Path(current['executable']).resolve()!=JAVA.resolve():raise RuntimeError('Owned executable mismatch')
        request(role,'/internal/drain','POST');request(role,'/internal/shutdown','POST')
        until=time.monotonic()+30
        while time.monotonic()<until:
            if process_identity(owned['pid']) is None:print(json.dumps({'stopped':role,'pid':owned['pid']}));break
            time.sleep(.5)
        else:raise RuntimeError('Owned application shutdown timeout; no unverified kill')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','build','start','stop','status']);a=p.parse_args()
    if a.action=='status':
        for role in lab.SERVICES:
            try:print(json.dumps({'role':role,'readiness':request(role,'/health/ready')}))
            except Exception as e:print(json.dumps({'role':role,'readiness_error':type(e).__name__}))
    else:globals()[a.action]()
