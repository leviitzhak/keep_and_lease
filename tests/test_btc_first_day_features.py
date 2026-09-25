import unittest
from scripts.export_btc_first_day_features import feature_rows
from trade_replay import Trade


class FeatureTests(unittest.TestCase):
    def test_subsecond_delay_boundaries_and_lossless_asof_compression(self):
        events=[Trade(100000,'SPOT',100,1,'buy','a'),Trade(450000,'SPOT',120,1,'buy','b'),
                Trade(800000,'F',110,1,'buy','c',False)]
        rows=list(feature_rows(iter(events),[],['SPOT','F'],0,2000000,window_seconds=1))
        spot={row[0]:row for symbol,row in rows if symbol=='SPOT'}
        self.assertEqual(spot[1][1:4],[100,100000,1])
        self.assertEqual(spot[2][1:4],[120,450000,2])
        self.assertEqual(spot[2][6],110)
        self.assertAlmostEqual(spot[2][7],(1/100+1/120)/2)
        self.assertEqual(spot[3][3],0)
        self.assertNotIn(4,spot)  # unchanged features reconstruct by as-of lookup
        future={row[0]:row for symbol,row in rows if symbol=='F'}
        self.assertEqual(future[1][3],0)
        self.assertEqual(future[2][1],110)
        self.assertEqual(future[2][8],0)


if __name__=='__main__':unittest.main()
