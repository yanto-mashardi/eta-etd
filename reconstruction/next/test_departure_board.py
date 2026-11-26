import unittest
from datetime import datetime,timezone
from evaluation import departure_board
class DepartureBoardTest(unittest.TestCase):
 def test_phases(self):
  now=datetime(2026,11,26,10,tzinfo=timezone.utc)
  r=dict(mmsi="525003298",trip_id="x",destination_port="PAKNING",status="SAILING",etd_early="2026-11-26T09:00:00+00:00")
  self.assertEqual(departure_board([r],{r["mmsi"]:r},now)[0]["board_color"],"incoming")
  r.update(status="BERTHED",ATA="2026-11-26T08:30:00+00:00",etd_arrival="2026-11-26T09:30:00+00:00")
  self.assertEqual(departure_board([r],{r["mmsi"]:r},now)[0]["board_time"],r["etd_arrival"])
  r.update(status="COMPLETED_QC_PASS",etd_real="2026-11-26T09:15:00+00:00",early_error_min=-15,arrival_error_min=15)
  self.assertEqual(departure_board([r],{},now)[0]["board_color"],"late")
  r["early_error_min"]=0
  self.assertEqual(departure_board([r],{},now)[0]["board_color"],"actual")
  r["early_error_min"]=r["arrival_error_min"]=None
  self.assertEqual(departure_board([r],{},now)[0]["board_color"],"unknown")
