import unittest
from curriculum import sample_pairs,stage_caps,coverage
class CurriculumTests(unittest.TestCase):
 def test_support_reproducibility_and_retention(self):
  for horizon in [24,48,96,192,384,768,1024]:
   for stage,cap in enumerate(stage_caps(horizon)):
    pairs=sample_pairs(horizon,stage);self.assertEqual(pairs,sample_pairs(horizon,stage));self.assertEqual(len(pairs),192);self.assertEqual(len({(p['episode'],p['time'],p['end']) for p in pairs}),192)
    for p in pairs:self.assertTrue(0<=p['time']<p['end']<=horizon);self.assertLessEqual(p['length'],cap)
    for split in ['train','validation','test']:
     ss=[p for p in pairs if p['split']==split];self.assertGreaterEqual(sum(p['length']<=10 for p in ss),len(ss)//4)
    if cap==horizon:self.assertTrue(any(p['time']==0 and p['end']==horizon and p['split']=='train' for p in pairs))
 def test_all_states_counted(self):
  pairs=sample_pairs(24,2);report=coverage(24,pairs)
  self.assertEqual(sum(x['raw_all_timestep_examples'] for x in report.values()),sum(p['length']+1 for p in pairs))
if __name__=='__main__':unittest.main()
