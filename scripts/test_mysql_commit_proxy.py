import unittest
import tempfile
import threading
from pathlib import Path

from mysql_commit_proxy import Proxy,is_commit_query


class CommitPacketTest(unittest.TestCase):
    def test_traditional_commit(self):
        self.assertTrue(is_commit_query(b'\x03COMMIT'))

    def test_connector_j_query_attributes_commit(self):
        self.assertTrue(is_commit_query(b'\x03\x00\x01COMMIT'))

    def test_query_attributes_must_have_the_observed_shape(self):
        self.assertFalse(is_commit_query(b'\x03\x00\x02COMMIT'))

    def test_commit_text_inside_another_query_is_not_a_match(self):
        self.assertFalse(is_commit_query(b'\x03SELECT COMMIT'))

    def test_non_query_command_is_not_a_match(self):
        self.assertFalse(is_commit_query(b'\x01COMMIT'))

    def test_arm_is_consumed_by_exactly_one_concurrent_commit(self):
        class Upstream:
            def __init__(self):self.sent=[]
            def sendall(self,value):self.sent.append(value)
        with tempfile.TemporaryDirectory() as directory:
            proxy=object.__new__(Proxy);proxy.root=Path(directory);proxy.arm_lock=threading.Lock();proxy.record=lambda *args:None
            (proxy.root/'arm').write_text('one\n')
            start=threading.Barrier(3);results=[];upstreams=[Upstream(),Upstream()]
            def commit(index):
                start.wait();results.append(proxy.forward(upstreams[index],b'packet',b'\x03COMMIT'))
            threads=[threading.Thread(target=commit,args=(index,)) for index in range(2)]
            for thread in threads:thread.start()
            start.wait()
            for thread in threads:thread.join()
            self.assertEqual(1,sum(results));self.assertTrue((proxy.root/'fired').is_file())
            self.assertFalse((proxy.root/'arm').exists());self.assertEqual(2,sum(len(item.sent) for item in upstreams))


if __name__=='__main__':unittest.main()
