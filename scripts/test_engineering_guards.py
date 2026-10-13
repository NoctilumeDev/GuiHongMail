import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import apps
import lab


class BuildReceiptTest(unittest.TestCase):
    def test_exact_artifacts_are_verified_and_external_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);build=root/'.artifacts/build';build.mkdir(parents=True)
            log=build/'build-source.log';log.write_bytes(b'build log')
            rows=[]
            for module in ('platform-common',*apps.MODULES.values()):
                jar=root/'backend'/module/'target'/(module+'-0.1.0-SNAPSHOT.jar');jar.parent.mkdir(parents=True);jar.write_bytes(module.encode())
                rows.append({'module':module,'path':jar.relative_to(root).as_posix(),'bytes':jar.stat().st_size,
                             'sha256':hashlib.sha256(jar.read_bytes()).hexdigest()})
            receipt={'schema':'GuiHongBuildReceipt/1.0','source_sha':'source','exit_code':0,
                     'log':log.relative_to(root).as_posix(),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'artifacts':rows}
            receipt_path=build/'build-source.json';receipt_path.write_text(json.dumps(receipt))
            with patch.object(apps.lab,'ROOT',root):
                _,verified=apps.verified_build('source');self.assertEqual(4,len(verified))
                receipt['log']=str(Path(directory).parent/'outside.log');receipt_path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(RuntimeError,'Unsafe build log path'):apps.verified_build('source')


class LocalArtifactTest(unittest.TestCase):
    def test_run_identity_is_bounded_to_the_ordinary_local_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts').mkdir()
            with patch.object(lab,'ROOT',root):
                run=lab.local_run('guihong-test-123',create=True)
                self.assertEqual((root/'artifacts/local/guihong-test-123').resolve(),run.resolve())
                with self.assertRaisesRegex(RuntimeError,'Invalid local run identity'):lab.local_run('../escape',create=True)


@unittest.skipUnless(os.name=='nt','Windows TCP ownership gate')
class ConnectedPeerTest(unittest.TestCase):
    def test_unowned_connected_listener_receives_no_http_or_bearer_bytes(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1];received=[]
        def accept():
            connection,_=listener.accept();connection.settimeout(3)
            try:received.append(connection.recv(4096))
            finally:connection.close();listener.close()
        thread=threading.Thread(target=accept);thread.start()
        with patch.dict(apps.PORTS,{'mailbox':port}),patch.object(apps,'owned_process',return_value={'pid':os.getpid()+100000}),patch.object(apps,'private',side_effect=AssertionError('secret loaded')):
            with self.assertRaisesRegex(RuntimeError,'listener is not the owned application'):
                apps.owned_http('mailbox','/health/ready',internal=True)
        thread.join(5);self.assertEqual([b''],received)

    def test_owned_connected_listener_receives_the_capability_on_that_connection(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1];received=[]
        def accept():
            connection,_=listener.accept();connection.settimeout(3);data=b''
            while b'\r\n\r\n' not in data:data+=connection.recv(4096)
            received.append(data)
            connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}')
            connection.close();listener.close()
        thread=threading.Thread(target=accept);thread.start()
        with patch.dict(apps.PORTS,{'mailbox':port}),patch.object(apps,'owned_process',return_value={'pid':os.getpid()}),patch.object(apps,'private',return_value={'internal':{'mailbox':'x'*64}}):
            status,_,body=apps.owned_http('mailbox','/internal/identity',internal=True)
        thread.join(5);self.assertEqual(200,status);self.assertEqual(b'{}',body)
        self.assertIn(b'Authorization: Bearer '+b'x'*64,received[0])


if __name__=='__main__':unittest.main()
