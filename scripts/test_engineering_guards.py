import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import apps
from evidence_summary import is_completed
import lab
import resource_guard


class ContainerBudgetTest(unittest.TestCase):
    def test_startup_admission_uses_resource_contract_1_3_without_moving_runtime_limits(self):
        self.assertEqual(2 * 1024**3, lab.STARTUP_FREE_BYTES)
        contract = (lab.ROOT / 'docs/m1-resource-contract-1.3.md').read_text(encoding='utf-8')
        self.assertIn('**2 GiB 空闲**', contract)
        self.assertIn('14 GiB', contract)
        self.assertIn('10%', contract)
        self.assertIn('16 PID', contract)

    def test_m6_exit_plan_and_operator_guide_keep_runtime_and_visual_boundaries(self):
        plan = (lab.ROOT / 'docs/m6-plan.md').read_text(encoding='utf-8')
        guide = (lab.ROOT / 'docs/operator-guide.md').read_text(encoding='utf-8')
        for number in range(1, 13):
            self.assertIn(f'M6-{number:02d}', plan)
        self.assertIn('错误 release', plan)
        self.assertIn('VISUAL_POLISH_PENDING', plan)
        self.assertIn('AWAITING_M7_HUMAN_REVIEW', plan)
        self.assertIn('scripts\\lab.py init', guide)
        self.assertIn('scripts\\go_apps.py start', guide)
        self.assertIn('scripts\\go_apps.py stop', guide)
        self.assertIn('scripts\\lab.py down', guide)
        self.assertIn('禁止 `docker system prune`', guide)

    def test_docker_memory_units_are_converted_without_treating_host_total_as_container_use(self):
        self.assertEqual(313 * 1024**2 + int(.9 * 1024**2), resource_guard.parse_size('313.9MiB'))
        self.assertEqual(153300000, resource_guard.parse_size('153.3MB'))
        with self.assertRaisesRegex(RuntimeError, 'Unsupported Docker resource size'):
            resource_guard.parse_size('61.3%')

    def test_container_pid_and_memory_headroom_are_hard_resource_witnesses(self):
        healthy = {'running': True, 'oom_killed': False, 'memory_headroom_ratio': .10, 'pid_headroom': 16}
        self.assertIsNone(resource_guard.container_violation([healthy]))
        self.assertEqual('CONTAINER_PID_HEADROOM_STOP_LINE',
                         resource_guard.container_violation([{**healthy, 'pid_headroom': 15}]))
        self.assertEqual('CONTAINER_MEMORY_HEADROOM_STOP_LINE',
                         resource_guard.container_violation([{**healthy, 'memory_headroom_ratio': .099}]))
        self.assertEqual('CONTAINER_OOM_STOP_LINE',
                         resource_guard.container_violation([{**healthy, 'oom_killed': True}]))


class OwnedCleanupTest(unittest.TestCase):
    def test_start_archives_reused_pid_without_adopting_or_stopping_it(self):
        owned={'lab_id':'lab','role':'mailbox','pid':123,'creation_ticks':1,'executable':str(apps.JAVA)}
        reused={'creation_ticks':2,'executable':'C:/Windows/System32/other.exe'}
        with tempfile.TemporaryDirectory() as directory:
            records=Path(directory);record=records/'mailbox.json';record.write_text(json.dumps(owned))
            with patch.object(apps,'PROCESSES',records),patch.object(apps.lab,'load',return_value={'id':'lab'}),\
                 patch.object(apps,'process_identity',return_value=reused),patch.object(os,'kill') as terminate:
                apps.archive_inactive_record(record,'mailbox')
                self.assertFalse(record.exists())
                self.assertEqual(1,len(list(records.glob('mailbox-pid-reused-*.json'))))
                terminate.assert_not_called()

    def test_start_refuses_when_exact_owned_pid_is_still_active(self):
        owned={'lab_id':'lab','role':'mailbox','pid':123,'creation_ticks':1,'executable':str(apps.JAVA)}
        current={'creation_ticks':1,'executable':str(apps.JAVA)}
        with tempfile.TemporaryDirectory() as directory:
            records=Path(directory);record=records/'mailbox.json';record.write_text(json.dumps(owned))
            with patch.object(apps,'PROCESSES',records),patch.object(apps.lab,'load',return_value={'id':'lab'}),\
                 patch.object(apps,'process_identity',return_value=current):
                with self.assertRaisesRegex(RuntimeError,'Prior exact owned PID remains active'):
                    apps.archive_inactive_record(record,'mailbox')
                self.assertTrue(record.exists())

    def test_stop_refuses_force_when_pid_identity_changes(self):
        owned={'lab_id':'lab','role':'mailbox','pid':123,'creation_ticks':1,'executable':str(apps.JAVA)}
        changed={'creation_ticks':2,'executable':str(apps.JAVA)}
        with tempfile.TemporaryDirectory() as directory:
            records=Path(directory);(records/'mailbox.json').write_text(json.dumps(owned))
            with patch.object(apps,'PROCESSES',records),patch.object(apps.lab,'SERVICES',('mailbox',)),\
                 patch.object(apps.lab,'load',return_value={'id':'lab'}),patch.object(apps,'process_identity',return_value=changed),\
                 patch.object(os,'kill') as terminate:
                with self.assertRaisesRegex(RuntimeError,'PID ownership changed'):
                    apps.stop()
                terminate.assert_not_called()


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
            lock=root/'frontend/web/package-lock.json';lock.parent.mkdir(parents=True);lock.write_bytes(b'lock')
            index=root/'backend/mailbox-service/src/main/resources/static/index.html';index.parent.mkdir(parents=True);index.write_bytes(b'index')
            assets=[{'path':index.relative_to(root).as_posix(),'bytes':index.stat().st_size,
                     'sha256':hashlib.sha256(index.read_bytes()).hexdigest()}]
            receipt={'schema':'GuiHongBuildReceipt/1.1','source_sha':'source','exit_code':0,
                     'log':log.relative_to(root).as_posix(),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
                     'frontend_lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'frontend_assets':assets,'artifacts':rows}
            receipt_path=build/'build-source.json';receipt_path.write_text(json.dumps(receipt))
            with patch.object(apps.lab,'ROOT',root):
                _,verified=apps.verified_build('source');self.assertEqual(4,len(verified))
                index.write_bytes(b'tampered')
                with self.assertRaisesRegex(RuntimeError,'Frontend asset binding mismatch'):apps.verified_build('source')
                index.write_bytes(b'index')
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


class M6ScreenshotTest(unittest.TestCase):
    def test_screenshot_uses_the_collector_subdirectory_and_rejects_escape(self):
        package=types.ModuleType('veritrail');package.__path__=[]
        canonical=types.ModuleType('veritrail.canonical');canonical.sha256_json=lambda value:'unused'
        with patch.dict(sys.modules,{'veritrail':package,'veritrail.canonical':canonical}):
            m6_round=importlib.import_module('m6_round')
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'run';image=parent/'browser-cancel/cancel.png'
            image.parent.mkdir(parents=True);image.write_bytes(b'png')
            observed=m6_round.screenshot(parent,Path('browser-cancel/cancel.png'))
            self.assertEqual(hashlib.sha256(b'png').hexdigest(),observed['sha256'])
            outside=parent.parent/'outside.png';outside.write_bytes(b'outside')
            with self.assertRaisesRegex(RuntimeError,'screenshot is missing or empty'):
                m6_round.screenshot(parent,Path('../outside.png'))


class BrowserProbeTest(unittest.TestCase):
    def test_m3_subject_locator_is_exact_after_classification_controls_are_present(self):
        probe = (lab.ROOT / 'scripts/browser_m3.py').read_text(encoding='utf-8')
        self.assertIn("get_by_role('textbox', name='主题', exact=True)", probe)
        self.assertNotIn("get_by_label('主题')", probe)


class M5ChildSummaryTest(unittest.TestCase):
    def test_object_summary_schema_is_accepted_but_conflicting_execution_is_rejected(self):
        self.assertTrue(is_completed({'execution': 'COMPLETED'}))
        self.assertTrue(is_completed({'execution_status': 'COMPLETED'}))
        self.assertTrue(is_completed({'execution': 'COMPLETED', 'execution_status': 'COMPLETED'}))
        self.assertFalse(is_completed({}))
        self.assertFalse(is_completed({'execution': 'COMPLETED', 'execution_status': 'ERROR'}))


class ObjectCollectorTest(unittest.TestCase):
    def test_gc_failure_witness_is_created_after_the_protection_probe(self):
        collector = (lab.ROOT / 'scripts/veritrail_objects.py').read_text(encoding='utf-8')
        protection = collector.index("protected_gc=call('mailbox','/internal/storage/gc','POST')")
        dedicated = collector.index("stage('mailbox','gc_failure'", protection)
        failure = collector.index("gc_failure=call('mailbox','/internal/storage/gc','POST')", dedicated)
        self.assertLess(protection, dedicated)
        self.assertLess(dedicated, failure)
        self.assertIn("hard('gc-bounded','gc/deleted_count',6)", collector)


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
