import unittest
from cctv_manager import reader_users,ReaderChange,reader_account
from fastapi import HTTPException
class ReaderTests(unittest.TestCase):
 def setUp(self):
  self.cfg={"authInternalUsers":[{"user":"campus_reader","pass":"original","permissions":[{"action":"read","path":"live/bengkalis"}]},{"user":"bengkalis_pub","pass":"publisher","permissions":[{"action":"publish","path":"live/bengkalis"}]}]}
 def test_new(self):
  users=reader_users(self.cfg,"campus_validation",ReaderChange(password="abcdef",ports=["pakning"]))
  self.assertEqual(users[-1]["permissions"],[{"action":"read","path":"live/pakning"}])
  self.assertEqual(users[:2],self.cfg["authInternalUsers"])
 def test_rotate(self):
  users=reader_users(self.cfg,"campus_reader",ReaderChange(password="new123"))
  self.assertEqual(users[-1]["pass"],"new123")
 def test_disable(self):
  self.assertEqual(len(reader_users(self.cfg,"campus_reader",ReaderChange(enabled=False))),1)
 def test_no_publish(self):
  with self.assertRaises(HTTPException):reader_users(self.cfg,"bengkalis_pub",ReaderChange(password="abcdef"))
 def test_short(self):
  with self.assertRaises(HTTPException):reader_users(self.cfg,"campus_reader",ReaderChange(password="12345"))
