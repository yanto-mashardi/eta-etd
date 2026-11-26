import unittest
from urllib.parse import urlsplit,parse_qs
from cctv_manager import connection_fields
class ConnectionTests(unittest.TestCase):
 def test_both_ports(self):
  for port in ("bengkalis","pakning"):
   c=connection_fields(port,port+"_pub","abcDEF")
   self.assertEqual(c["server"]+"/"+c["stream_key"],c["url"])
   self.assertEqual(urlsplit(c["url"]).path,"/live/"+port)
   self.assertEqual(parse_qs(urlsplit(c["url"]).query)["user"],[port+"_pub"])
   self.assertEqual(c["rtsp_url"],"rtsp://192.236.226.247:8554/live/"+port)
 def test_encoding(self):
  c=connection_fields("bengkalis","u","a&b+c")
  self.assertEqual(parse_qs(urlsplit(c["url"]).query)["pass"],["a&b+c"])
 def test_unknown(self):
  with self.assertRaises(ValueError):connection_fields("other","u","p")
