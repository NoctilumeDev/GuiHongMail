import unittest

from mysql_commit_proxy import is_commit_query


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


if __name__=='__main__':unittest.main()
