import unittest,tempfile,sqlite3
from pathlib import Path
from stockflow import Ledger
from vehicle_archive import rows,encode,safe_to_prune
class VehicleArchiveTests(unittest.TestCase):
    def test_archive_does_not_delete_required_history(self):
        with tempfile.TemporaryDirectory() as d:
            l=Ledger(Path(d)/"stock.sqlite")
            l.departure("bengkalis","525002060","2026-11-18T10:00:00+07:00")
            with l.connect() as db:
                data=rows(db,"2026-11-18")
                self.assertEqual(len(data),1)
                self.assertIn(b"525002060",encode(data))
                self.assertFalse(safe_to_prune(db,"2026-11-18"))
            l.set_opening("bengkalis","2026-11-19T00:00:00+07:00",10,10,0,0)
            with l.connect() as db:self.assertTrue(safe_to_prune(db,"2026-11-18"))
            l.close()
