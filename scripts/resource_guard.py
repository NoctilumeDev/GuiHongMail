"""Foreground bounded watchdog: preserve observations and stop ONLY the exact owned lab."""
import argparse
import ctypes
import json
import os
import re
import subprocess
import time
import uuid
import apps
import lab

INFRASTRUCTURE = ('broker', 'mysql', 'namesrv', 'seaweedfs')
MIN_CONTAINER_MEMORY_HEADROOM_RATIO = .10
MIN_CONTAINER_PID_HEADROOM = 16
SIZE_UNITS = {
    'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4,
    'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'TiB': 1024**4,
}


def parse_size(value):
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)', value.strip())
    if match is None or match.group(2) not in SIZE_UNITS:
        raise RuntimeError('Unsupported Docker resource size')
    return int(float(match.group(1)) * SIZE_UNITS[match.group(2)])


def container_contract():
    state = lab.load();contracts = {}
    identities = lab.assert_owned()
    if identities:
        inspected = json.loads(subprocess.check_output(
            [lab.docker(), 'inspect', *identities], text=True, encoding='utf-8'))
    else:
        inspected = []
    for info in inspected:
        labels = info['Config'].get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        if service not in INFRASTRUCTURE:
            continue
        if labels.get('guihong.owner') != state['id'] or service in contracts:
            raise RuntimeError('Container ownership or service identity changed')
        memory_limit = int(info['HostConfig']['Memory'])
        pids_limit = int(info['HostConfig']['PidsLimit'])
        if memory_limit <= 0 or pids_limit <= MIN_CONTAINER_PID_HEADROOM:
            raise RuntimeError('Container limits do not establish the frozen budget')
        contracts[service] = {
            'container_id': info['Id'], 'name': info['Name'].lstrip('/'),
            'memory_limit_bytes': memory_limit, 'pids_limit': pids_limit,
        }
    if sorted(contracts) != list(INFRASTRUCTURE):
        raise RuntimeError('Exact infrastructure topology is not owned and available')
    return contracts


def container_snapshot(contracts):
    inspected = json.loads(subprocess.check_output(
        [lab.docker(), 'inspect', *[contracts[name]['container_id'] for name in INFRASTRUCTURE]],
        text=True, encoding='utf-8'))
    by_name = {info['Name'].lstrip('/'): info for info in inspected}
    running = [contracts[name]['container_id'] for name in INFRASTRUCTURE
               if by_name[contracts[name]['name']]['State']['Running']]
    stats = {}
    if running:
        output = subprocess.check_output(
            [lab.docker(), 'stats', '--no-stream', '--format', '{{json .}}', *running],
            text=True, encoding='utf-8')
        for line in output.splitlines():
            if line.strip():
                row = json.loads(line);stats[row['Name']] = row
    result = []
    for service in INFRASTRUCTURE:
        contract = contracts[service];info = by_name[contract['name']]
        labels = info['Config'].get('Labels') or {}
        if info['Id'] != contract['container_id'] or labels.get('guihong.owner') != lab.load()['id']:
            raise RuntimeError('Container identity changed during resource observation')
        running_now = bool(info['State']['Running']);row = {
            'service': service, **contract, 'running': running_now,
            'oom_killed': bool(info['State']['OOMKilled']), 'memory_usage_bytes': None,
            'memory_headroom_bytes': None, 'memory_headroom_ratio': None,
            'pids': None, 'pid_headroom': None,
        }
        if running_now:
            observed = stats.get(contract['name'])
            if observed is None:
                raise RuntimeError('Running container missing from Docker stats')
            usage = parse_size(observed['MemUsage'].split('/', 1)[0])
            pids = int(observed['PIDs'])
            row.update(memory_usage_bytes=usage,
                       memory_headroom_bytes=contract['memory_limit_bytes'] - usage,
                       memory_headroom_ratio=(contract['memory_limit_bytes'] - usage) / contract['memory_limit_bytes'],
                       pids=pids, pid_headroom=contract['pids_limit'] - pids)
        result.append(row)
    return result


def container_violation(containers):
    if any(row['oom_killed'] for row in containers):
        return 'CONTAINER_OOM_STOP_LINE'
    if any(row['running'] and row['memory_headroom_ratio'] < MIN_CONTAINER_MEMORY_HEADROOM_RATIO for row in containers):
        return 'CONTAINER_MEMORY_HEADROOM_STOP_LINE'
    if any(row['running'] and row['pid_headroom'] < MIN_CONTAINER_PID_HEADROOM for row in containers):
        return 'CONTAINER_PID_HEADROOM_STOP_LINE'
    return None

def rss(pid):
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(x,ctypes.c_size_t) for x in
            ('peak_ws','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    kernel=ctypes.windll.kernel32;kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x400|0x10,False,pid)
    if not handle:raise RuntimeError('Cannot observe owned RSS')
    try:
        value=Counters();value.cb=ctypes.sizeof(value)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle),ctypes.byref(value),value.cb):
            raise RuntimeError('Cannot establish RSS stop line')
        return value.working_set
    finally:kernel.CloseHandle(ctypes.c_void_p(handle))

def run(duration):
    lab.assert_owned();contracts=container_contract();target=lab.LAB/('resource-'+uuid.uuid4().hex+'.jsonl');high=0
    deadline=time.monotonic()+duration
    with target.open('x',encoding='utf-8',newline='\n') as log:
        while time.monotonic()<deadline:
            memory=lab.memory();processes=[];reason=None;error=None
            try:
                containers=container_snapshot(contracts)
                reason=container_violation(containers)
                for role in lab.SERVICES:
                    path=apps.PROCESSES/(role+'.json')
                    if not path.exists():continue
                    owner=json.loads(path.read_text());actual=apps.process_identity(owner['pid'])
                    if actual is None:continue
                    if actual!={k:owner[k] for k in ('creation_ticks','executable')} or owner['lab_id']!=lab.load()['id']:
                        raise RuntimeError('PID ownership changed; no stop/mutation of unknown process')
                    value=rss(owner['pid']);processes.append({'role':role,'pid':owner['pid'],'rss_bytes':value})
                    if value>384*1024**2:reason=reason or 'APPLICATION_RSS_STOP_LINE'
            except Exception as failure:
                containers=[];reason='RESOURCE_OBSERVATION_FAILURE';error={'type':type(failure).__name__,'message':str(failure)}
            high=high+1 if memory['used_bytes']>14*1024**3 else 0
            if high>=3:reason=reason or 'HOST_MEMORY_STOP_LINE'
            full_topology=(sorted(row['service'] for row in containers if row['running'])==list(INFRASTRUCTURE)
                           and sorted(process['role'] for process in processes)==sorted(lab.SERVICES))
            row={'utc_epoch':time.time(),'memory':memory,'processes':processes,'containers':containers,
                 'full_topology':full_topology,'consecutive_high':high,'stop_reason':reason,'observation_error':error}
            log.write(json.dumps(row)+'\n');log.flush();os.fsync(log.fileno())
            if reason:
                apps.stop();lab.assert_owned();lab.compose(['stop','--timeout','20']);apps.stop()
                print(json.dumps({'stopped':reason,'evidence':str(target)}),flush=True);return 2
            time.sleep(5)
    print(json.dumps({'window_complete':duration,'evidence':str(target)}),flush=True);return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--duration',type=int,default=600);a=p.parse_args()
    if a.duration<5 or a.duration>3600:raise RuntimeError('Watchdog window must be 5..3600 seconds')
    raise SystemExit(run(a.duration))
