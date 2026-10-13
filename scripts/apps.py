"""Own three local JVMs; bind jar hashes/PID creation time, never kill by process name."""
import argparse
import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid
import lab

JAVA = Path('D:/IDEA/JDK17/bin/java.exe')
MVN = Path('D:/Maven/apache-maven-3.9.11-bin/apache-maven-3.9.11/bin/mvn.cmd')
PORTS = {'mailbox':18080,'ingress':18081,'delivery':18082}
MODULES = {'mailbox':'mailbox-service','ingress':'smtp-ingress','delivery':'delivery-worker'}
PROCESSES = lab.LAB/'applications'

class TcpOwnerRow(ctypes.Structure):
    _fields_=[('state',ctypes.c_ulong),('local_address',ctypes.c_ulong),('local_port',ctypes.c_ulong),
              ('remote_address',ctypes.c_ulong),('remote_port',ctypes.c_ulong),('pid',ctypes.c_ulong)]

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

def tcp_server_owners(port,client_port):
    """Return Windows PIDs owning the accepted side of one established loopback connection."""
    if os.name!='nt':raise RuntimeError('This pinned app profile is Windows native')
    api=ctypes.windll.iphlpapi.GetExtendedTcpTable;size=ctypes.c_ulong(0)
    result=api(None,ctypes.byref(size),False,socket.AF_INET,5,0) # TCP_TABLE_OWNER_PID_ALL
    if result!=122:raise RuntimeError('Cannot size TCP ownership table')
    buffer=ctypes.create_string_buffer(size.value)
    result=api(buffer,ctypes.byref(size),False,socket.AF_INET,5,0)
    if result!=0:raise RuntimeError('Cannot read TCP ownership table')
    count=ctypes.c_ulong.from_buffer(buffer).value;base=ctypes.addressof(buffer)+ctypes.sizeof(ctypes.c_ulong)
    owners=set()
    for index in range(count):
        row=TcpOwnerRow.from_address(base+index*ctypes.sizeof(TcpOwnerRow))
        if (row.state==5 and socket.ntohs(row.local_port&0xffff)==port
                and socket.ntohs(row.remote_port&0xffff)==client_port):
            owners.add(row.pid)
    return owners

def owned_process(role):
    record=PROCESSES/(role+'.json')
    if not record.is_file():raise RuntimeError('No owned process record for '+role)
    owned=json.loads(record.read_text(encoding='utf-8'));current=process_identity(owned['pid'])
    if (owned.get('lab_id')!=lab.load()['id'] or owned.get('role')!=role or current is None
            or current!={key:owned[key] for key in ('creation_ticks','executable')}
            or Path(current['executable']).resolve()!=JAVA.resolve()):
        raise RuntimeError('Application process ownership is not current')
    return owned

def repo_file(relative,label):
    value=Path(relative)
    if value.is_absolute() or '..' in value.parts:raise RuntimeError('Unsafe '+label+' path')
    resolved=(lab.ROOT/value).resolve()
    if not resolved.is_relative_to(lab.ROOT.resolve()) or not resolved.is_file():
        raise RuntimeError(label+' escaped or is missing')
    return resolved

def verified_build(source):
    receipt_path=lab.ROOT/'.artifacts/build'/('build-'+source+'.json')
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('schema')!='GuiHongBuildReceipt/1.0' or receipt.get('source_sha')!=source or receipt.get('exit_code')!=0:
        raise RuntimeError('Build receipt does not bind the exact source')
    log=repo_file(receipt['log'],'build log')
    if hashlib.sha256(log.read_bytes()).hexdigest()!=receipt['log_sha256']:
        raise RuntimeError('Build log digest mismatch')
    artifacts={}
    for row in receipt.get('artifacts',[]):
        module=row.get('module');path=repo_file(row.get('path',''),'build artifact')
        expected=lab.ROOT/'backend'/str(module)/'target'/(str(module)+'-0.1.0-SNAPSHOT.jar')
        if module in artifacts or path!=expected.resolve() or path.stat().st_size!=row.get('bytes'):
            raise RuntimeError('Unexpected build artifact binding')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=row.get('sha256'):raise RuntimeError('Build artifact digest mismatch')
        artifacts[module]={'path':path,'sha256':digest}
    expected={'platform-common',*MODULES.values()}
    if set(artifacts)!=expected:raise RuntimeError('Build receipt artifact set mismatch')
    return receipt_path,artifacts

def private():return json.loads((lab.LAB/'secrets.json').read_text())

def owned_http(role,path,method='GET',body=None,headers=None,internal=False,max_bytes=1048577):
    owned=owned_process(role);connection=http.client.HTTPConnection('127.0.0.1',PORTS[role],timeout=10)
    try:
        connection.connect();client_port=connection.sock.getsockname()[1];deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            owners=tcp_server_owners(PORTS[role],client_port)
            if owners=={owned['pid']}:break
            if owners and owners!={owned['pid']}:raise RuntimeError('Connected listener is not the owned application')
            time.sleep(.02)
        else:raise RuntimeError('Cannot bind connected listener to the owned application')
        outbound=dict(headers or {})
        if internal:
            # The capability is loaded and transmitted only after the already-connected server socket is PID-bound.
            outbound.update(Authorization='Bearer '+private()['internal'][role],**{'X-GuiHong-Service':'lab'})
        connection.request(method,path,body=body,headers=outbound)
        response=connection.getresponse();raw=response.read(max_bytes+1)
        if len(raw)>max_bytes:raise RuntimeError('Owned application response exceeded byte limit')
        return response.status,response.headers,raw
    finally:connection.close()

def request(role,path,method='GET'):
    status,_,body=owned_http(role,path,method=method,internal=True)
    if status<200 or status>=300:raise RuntimeError('Owned internal request returned HTTP '+str(status))
    return json.loads(body)

def prepare():
    import pymysql
    lab.assert_owned();credentials=private();observations=[]
    for role in lab.SERVICES:
        root=lab.LAB/'witness'/role
        if root.exists():raise RuntimeError('Witness already exists; no reset/adopt operation')
        db=credentials['database'][role]
        deadline=time.monotonic()+60
        while True:
            try:
                with pymysql.connect(host='127.0.0.1',port=13306,user=db['user'],password=db['password'],database=db['schema'],connect_timeout=5) as c:
                    with c.cursor() as q:
                        q.execute('SHOW TABLES');tables=q.fetchall()
                        q.execute('SELECT DATABASE(),CURRENT_USER(),VERSION()');binding=q.fetchone()
                break
            except pymysql.err.OperationalError as error:
                code=error.args[0] if error.args else None
                if code not in {2003,2013} or time.monotonic()>=deadline:raise
                time.sleep(.5)
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
    attempt=uuid.uuid4().hex
    target=root/('build-'+sha+'-'+attempt+'.log')
    with target.open('x',encoding='utf-8') as log:
        p=subprocess.run([str(MVN),'-B','-ntp','-s',str(settings),'-Dmaven.repo.local='+str(lab.ROOT/'.artifacts/m2'),
            '-f',str(lab.ROOT/'backend/pom.xml'),'-Dguihong.source_sha='+sha,'verify'],cwd=lab.ROOT,env=environment(),stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if p.returncode:raise RuntimeError('Build failed; retained '+str(target))
    artifacts=[]
    for module in ('platform-common',*MODULES.values()):
        jar=lab.ROOT/'backend'/module/'target'/(module+'-0.1.0-SNAPSHOT.jar')
        if not jar.is_file():raise RuntimeError('Build succeeded without expected artifact '+str(jar))
        artifacts.append({'module':module,'path':jar.relative_to(lab.ROOT).as_posix(),
                          'bytes':jar.stat().st_size,'sha256':hashlib.sha256(jar.read_bytes()).hexdigest()})
    receipt={'schema':'GuiHongBuildReceipt/1.0','source_sha':sha,'attempt_id':attempt,'exit_code':p.returncode,
             'log':target.relative_to(lab.ROOT).as_posix(),'log_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
             'artifacts':artifacts}
    lab.write_new(root/('build-'+sha+'.json'),json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt))

def start(database_ports=None):
    lab.assert_owned()
    if subprocess.check_output(['git','status','--porcelain'],cwd=lab.ROOT):
        raise RuntimeError('Application startup requires committed clean source')
    if lab.memory()['used_bytes']>14*1024**3:raise RuntimeError('Host memory stop line reached before app startup')
    database_ports=database_ports or {}
    PROCESSES.mkdir(exist_ok=True)
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=lab.ROOT,text=True).strip()
    receipt_path,artifacts=verified_build(source);credentials=private()
    for role in lab.SERVICES:
        record=PROCESSES/(role+'.json')
        if record.exists():
            previous=json.loads(record.read_text())
            if process_identity(previous['pid']) is not None:raise RuntimeError('Prior PID remains active; no implicit adoption')
            record.rename(PROCESSES/(role+'-exited-'+uuid.uuid4().hex+'.json'))
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',PORTS[role]))==0:raise RuntimeError('Unknown listener on required app port')
        jar=artifacts[MODULES[role]]['path']
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
            'source_sha':source,'build_receipt':str(receipt_path),'jar':str(jar),'jar_sha256':artifacts[MODULES[role]]['sha256'],'log':str(log)},indent=2)+'\n')
        until=time.monotonic()+60
        while time.monotonic()<until:
            if process_identity(p.pid)!=identity:raise RuntimeError('Application exited; original log retained')
            try:
                actual=request(role,'/internal/identity')
                if actual['source_sha']!=source or actual['service']!=role:raise RuntimeError('Installed app/source binding mismatch')
                print(json.dumps({'started':role,'identity':actual}));break
            except (OSError,http.client.HTTPException):time.sleep(.5)
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
        graceful=True
        try:request(role,'/internal/drain','POST');request(role,'/internal/shutdown','POST')
        except Exception:graceful=False
        until=time.monotonic()+30
        while time.monotonic()<until:
            if process_identity(owned['pid']) is None:print(json.dumps({'stopped':role,'pid':owned['pid'],'mode':'graceful' if graceful else 'exited'}));break
            if not graceful:break
            time.sleep(.5)
        else:graceful=False
        if process_identity(owned['pid']) is not None:
            current=process_identity(owned['pid'])
            if (owned['lab_id']!=lab.load()['id'] or current!={k:owned[k] for k in ('creation_ticks','executable')}
                    or Path(current['executable']).resolve()!=JAVA.resolve()):
                raise RuntimeError('PID ownership changed; force stop without mutation')
            os.kill(owned['pid'],signal.SIGTERM)
            until=time.monotonic()+10
            while time.monotonic()<until:
                if process_identity(owned['pid']) is None:
                    print(json.dumps({'stopped':role,'pid':owned['pid'],'mode':'forced-owned-pid'}));break
                time.sleep(.25)
            else:raise RuntimeError('Exact owned PID did not exit after forced cleanup')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','build','start','stop','status']);a=p.parse_args()
    if a.action=='status':
        for role in lab.SERVICES:
            try:print(json.dumps({'role':role,'readiness':request(role,'/health/ready')}))
            except Exception as e:print(json.dumps({'role':role,'readiness_error':type(e).__name__}))
    else:globals()[a.action]()
