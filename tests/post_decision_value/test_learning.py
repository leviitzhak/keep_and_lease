from copy import deepcopy
import tempfile
import unittest
import numpy as np
import torch
from research.post_decision_value.accounting import Instrument,Ledger,Goal
from research.post_decision_value.engine import Engine,Trade,Instruction,Order,Delays,post_decision
from research.post_decision_value.model import ValueNetwork,features,batch,fit,save_model,load_model,labels

class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)
    def tiny(self):
        ins={'A':Instrument('A',10000,tick=1,lot=.001,fee_bps=0),
             'B':Instrument('B',20000,tick=1,lot=.001,fee_bps=0)}
        goal=Goal({'BTC':1.,'USD':100.},1000,20000,reference={'BTC':100.,'USD':1.})
        seeds=[Trade(0,s,p,1000,'buy',s,100.) for s,p in [('A',100),('B',120)]]
        choices=[Instruction(),Instruction('create',(Order('a','A',.01,100,'g'),Order('b','B',-.009,120,'g'))),
                 Instruction('create',(Order('a','A',.01,110,'g'),Order('b','B',-.009,120,'g'))),
                 Instruction('create',(Order('a','A',.01,90,'g'),Order('b','B',-.009,120,'g')))]
        records=[]
        for seed in range(6):
            for choice in choices:
                e=Engine(ins,Ledger(goal.initial.copy()),goal,seed,Delays(0,0,0,0,0,0),participation=1)
                e.seed_market(seeds,1);f=features(post_decision(e.observe(),choice,ins),goal,ins)
                e.submit(choice)
                e.add_tape([Trade(10,'A',99,1000,'sell','fa',100),Trade(11,'B',121,1000,'buy','fb',100)])
                e.advance(1000)
                records.append(dict(features=f,outcome=e.outcome(),continuation='wait_after_initial_instruction'))
        return records
    def test_price_dependent_dominant_action_predicted_and_realized(self):
        records=self.tiny();torch.manual_seed(5);model=ValueNetwork(width=32,layers=2,heads=4)
        optimizer,rng,info=fit(model,records,updates=350,seed=3)
        pred=model.predict([r['features'] for r in records[:4]])
        real=np.array([r['outcome']['utility'] for r in records[:4]])
        self.assertEqual(int(np.argmax(real)),1);self.assertEqual(int(np.argmax(pred['objective'])),1)
        self.assertLess(float(np.max(np.abs(real-pred['objective']))),.0005)
        # A posted price change affects the selected executable instruction.
        self.assertLess(pred['objective'][2],pred['objective'][1])
        self.assertLess(pred['objective'][3],pred['objective'][1])
        self.assertEqual(pred['continuation'],'wait_after_initial_instruction')
    def test_causal_attention_future_token_cannot_change_prefix(self):
        torch.manual_seed(2);model=ValueNetwork();model.eval()
        history=torch.randn(1,8,8);mask=torch.zeros(1,8,dtype=torch.bool)
        with torch.no_grad():a=model.history_encoding(history,mask);history[:,5:]+=500;b=model.history_encoding(history,mask)
        self.assertTrue(torch.allclose(a[:,:5],b[:,:5],atol=1e-6))
    def test_continuation_and_truncation_rejected(self):
        rs=self.tiny();rs[1]['continuation']='other'
        with self.assertRaises(ValueError):labels(rs)
        rs=self.tiny();rs[1]['outcome']['done']=False
        with self.assertRaises(ValueError):labels(rs)
    def test_training_resume_exact_weights_and_rng(self):
        rs=self.tiny();torch.manual_seed(3);model=ValueNetwork(width=16,layers=1,heads=4)
        opt,rng,_=fit(model,rs,updates=3,seed=1)
        with tempfile.TemporaryDirectory() as d:
            save_model(d+'/m.pt',model,opt,rng,{'code':'same'})
            restored,opt2,rng2=load_model(d+'/m.pt',{'code':'same'})
            with self.assertRaises(ValueError):load_model(d+'/m.pt',{'code':'changed'})
            fit(model,rs,updates=3,optimizer=opt,rng=rng,normalize=False)
            fit(restored,rs,updates=3,optimizer=opt2,rng=rng2,normalize=False)
            for k,v in model.state_dict().items():self.assertTrue(torch.equal(v,restored.state_dict()[k]),k)
    def test_scalar_not_derived_from_commodity_predictions(self):
        torch.manual_seed(4);m=ValueNetwork(width=16,layers=1,heads=4);rs=self.tiny()
        fs=[r['features'] for r in rs[:4]];before=m.predict(fs)
        with torch.no_grad():m.readout[-1].bias[1:3]+=100
        after=m.predict(fs)
        np.testing.assert_array_equal(before['objective'],after['objective'])
        self.assertFalse(np.array_equal(before['terminal_holdings'],after['terminal_holdings']))
