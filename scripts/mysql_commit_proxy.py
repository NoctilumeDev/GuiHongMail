"""Owned one-shot MySQL fault proxy: drop only the armed COMMIT response, retain hashes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import socket
import threading
import time
import uuid
import lab

class Proxy:
    def __init__(self,port,root):
        self.port=port;self.root=root;self.stop=threading.Event();self.threads=[]
        self.owner=lab.load()['id'];self.root.mkdir(parents=True,exist_ok=False)
        lab.write_new(root/'identity.json',json.dumps({'lab_id':self.owner,'listen':f'127.0.0.1:{port}','upstream':'127.0.0.1:13306'},indent=2)+'\n')
    def record(self,name,value):lab.write_new(self.root/(name+'-'+uuid.uuid4().hex+'.json'),json.dumps(value,indent=2)+'\n')
    def client(self,downstream):
        upstream=socket.create_connection(('127.0.0.1',13306),timeout=5);downstream.settimeout(None);upstream.settimeout(None)
        fired=False
        def server_to_client():
            nonlocal fired
            try:
                while True:
                    data=upstream.recv(65536)
                    if not data:break
                    if fired:
                        self.record('commit-response',{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'observed_after_downstream_close':True});break
                    downstream.sendall(data)
            except OSError:pass
        reader=threading.Thread(target=server_to_client,daemon=True);reader.start()
        buffer=b''
        try:
            while True:
                data=downstream.recv(65536)
                if not data:break
                buffer+=data
                while len(buffer)>=4:
                    length=buffer[0]|buffer[1]<<8|buffer[2]<<16
                    if len(buffer)<length+4:break
                    packet,buffer=buffer[:length+4],buffer[length+4:]
                    payload=packet[4:]
                    armed=(self.root/'arm').is_file()
                    commit=len(payload)>1 and payload[0]==3 and payload[1:].decode('utf-8','replace').strip().lower()=='commit'
                    upstream.sendall(packet)
                    if armed and commit:
                        fired=True
                        os.replace(self.root/'arm',self.root/'fired')
                        self.record('commit-request',{'bytes':len(packet),'sha256':hashlib.sha256(packet).hexdigest(),'forwarded_upstream':True})
                        try:downstream.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                        downstream.close();reader.join(10);return
        finally:
            try:downstream.close()
            except OSError:pass
            try:upstream.close()
            except OSError:pass
    def run(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',self.port));listener.listen(8);listener.settimeout(.5)
            lab.write_new(self.root/'ready',str(os.getpid())+'\n')
            while not (self.root/'stop').exists():
                try:client,_=listener.accept()
                except socket.timeout:continue
                thread=threading.Thread(target=self.client,args=(client,),daemon=True);thread.start();self.threads.append(thread)
        for thread in self.threads:thread.join(10)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    if args.port<20000 or args.port>40000 or args.root.exists() or not args.root.resolve().is_relative_to(lab.LAB.resolve()):raise RuntimeError('Unsafe proxy coordinates')
    lab.assert_owned();Proxy(args.port,args.root.resolve()).run()
