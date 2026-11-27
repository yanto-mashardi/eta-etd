import unittest
from cctv_manager import reader_users,ReaderChange,reader_account
from fastapi import HTTPException
class ReaderTests(unittest.TestCase):
 def setUp(self):
  self.cfg={"authInternalUsers":[{"user":"campus_reader","pass":"original","permissions":[{"action":"read","path":"live/bengkalis"}]},{"user":"bengkalis_pub","pass":"publisher","permissions":[{"action":"publish","path":"live/bengkalis"}]}]}
 def test_new(self):
  users=reader_users(self.cfg,"campus_validation",ReaderChange(password="abcdef",ports=["pakning"]))
  self.assertEqual(users[-1]["permissions"],[{"action":"read","path":"validation/pakning"}])
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

 def test_selective_kick(self):
  from unittest.mock import patch
  from cctv_manager import disconnect_validation
  a="11111111-1111-1111-1111-111111111111";b="22222222-2222-2222-2222-222222222222"
  with patch("cctv_manager.relay",side_effect=[{"pageCount":1,"items":[{"id":a,"state":"read","path":"live/bengkalis"},{"id":b,"state":"read","path":"validation/pakning"}]},{}]) as mock:
   self.assertEqual(disconnect_validation(),1)
   mock.assert_called_with("/v3/rtspsessions/kick/"+b,"POST")
 def test_migration(self):
  from migrate_validation import migrate
  cfg={"authMethod":"internal","paths":{"live/bengkalis":{"source":"publisher"},"live/pakning":{"source":"publisher"}},"authInternalUsers":self.cfg["authInternalUsers"]+[{"user":"campus_validation","pass":"abcdef","permissions":[{"action":"read","path":"live/bengkalis"}]}]}
  result=migrate(cfg)
  self.assertEqual(result["paths"]["live/bengkalis"],cfg["paths"]["live/bengkalis"])
  self.assertTrue(result["paths"]["validation/pakning"]["sourceOnDemand"])
  self.assertEqual(reader_account(result,"campus_validation")["permissions"][0]["path"],"validation/bengkalis")
  self.assertEqual(migrate(result),result)
