"""Foreground bounded watchdog: preserve observations and stop ONLY the exact owned lab."""
import argparse
import ctypes
import json
import os
import time
import uuid
import apps
import lab

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
    lab.assert_owned();target=lab.LAB/('resource-'+uuid.uuid4().hex+'.jsonl');high=0
    deadline=time.monotonic()+duration
    with target.open('x',encoding='utf-8',newline='\n') as log:
        while time.monotonic()<deadline:
            memory=lab.memory();processes=[];reason=None
            for role in lab.SERVICES:
                path=apps.PROCESSES/(role+'.json')
                if not path.exists():continue
                owner=json.loads(path.read_text());actual=apps.process_identity(owner['pid'])
                if actual is None:continue
                if actual!={k:owner[k] for k in ('creation_ticks','executable')} or owner['lab_id']!=lab.load()['id']:
                    raise RuntimeError('PID ownership changed; no stop/mutation of unknown process')
                value=rss(owner['pid']);processes.append({'role':role,'pid':owner['pid'],'rss_bytes':value})
                if value>384*1024**2:reason='APPLICATION_RSS_STOP_LINE'
            high=high+1 if memory['used_bytes']>14*1024**3 else 0
            if high>=3:reason='HOST_MEMORY_STOP_LINE'
            row={'utc_epoch':time.time(),'memory':memory,'processes':processes,'consecutive_high':high,'stop_reason':reason}
            log.write(json.dumps(row)+'\n');log.flush();os.fsync(log.fileno())
            if reason:
                apps.stop();lab.assert_owned();lab.compose(['stop','--timeout','20'])
                print(json.dumps({'stopped':reason,'evidence':str(target)}),flush=True);return 2
            time.sleep(5)
    print(json.dumps({'window_complete':duration,'evidence':str(target)}),flush=True);return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--duration',type=int,default=600);a=p.parse_args()
    if a.duration<5 or a.duration>3600:raise RuntimeError('Watchdog window must be 5..3600 seconds')
    raise SystemExit(run(a.duration))
