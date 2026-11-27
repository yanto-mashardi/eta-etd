import unittest
from capacity import allocate
class CapacityTests(unittest.TestCase):
 def test_bounds(self):
    for c in range(0,81,5):
     for m in range(0,151,5):
      a,b=allocate(c,m,dict(capacity_units=3800,motor_units=25,fill_fraction=1))
      self.assertTrue(0<=a<=c and 0<=b<=m and 100*a+25*b<=3800)
 def test_empty(self):self.assertEqual(allocate(0,0,dict(capacity_units=3800,motor_units=25,fill_fraction=1)),(0,0))
 def test_under_capacity(self):self.assertEqual(allocate(5,10,dict(capacity_units=3800,motor_units=25,fill_fraction=1)),(5,10))
