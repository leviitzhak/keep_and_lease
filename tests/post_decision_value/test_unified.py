import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.post_decision_value.unified import Source, build_union, iter_trades


class UnionTests(unittest.TestCase):
    def row(self,seq=1,ts=100):
        return dict(instrument_name='BTC-X',trade_id=str(seq),trade_seq=seq,timestamp=ts,
                    price=100.,amount=10.,index_price=99.,direction='buy')

    def source(self,root,name,rows):
        path=root/name;data=gzip.compress(('\n'.join(json.dumps(r) for r in rows)+'\n').encode())
        path.write_bytes(data)
        return Source(str(path),'fixture://'+name,hashlib.sha256(data).hexdigest(),len(data),len(rows),'BTC-X')

    def test_overlap_deduplicated_with_both_provenances(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=self.source(root,'a.gz',[self.row(),self.row(2,200)])
            same=self.row(2,200);same['price']=100
            b=self.source(root,'b.gz',[same,self.row(3,300)])
            report=build_union([a,b],root/'db')
            self.assertEqual((report['input_rows'],report['unique_rows'],report['duplicate_rows']),(4,3,1))
            with sqlite3.connect(root/'db') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM origins WHERE id="2"').fetchone()[0],2)
            self.assertEqual([t.identifier for t in iter_trades(root/'db',0,1000)],['1','2','3'])

    def test_conflicting_overlap_is_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);changed=self.row();changed['price']=101
            sources=[self.source(root,'a.gz',[self.row()]),self.source(root,'b.gz',[changed])]
            with self.assertRaisesRegex(ValueError,'Conflicting overlap'):build_union(sources,root/'db')
            self.assertFalse((root/'db').exists());self.assertFalse((root/'db.tmp').exists())

    def test_conflicting_sequence_identity_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);changed=self.row();changed['trade_id']='different'
            with self.assertRaises(sqlite3.IntegrityError):
                build_union([self.source(root,'a.gz',[self.row()]),self.source(root,'b.gz',[changed])],root/'db')

    def test_backdated_print_has_causal_availability_and_no_retroactive_fill(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            build_union([self.source(root,'a.gz',[self.row(1,300),self.row(2,200),self.row(3,400)])],root/'db')
            tape=list(iter_trades(root/'db',0,1000))
            self.assertEqual([t.time for t in tape],[300,300,400]);self.assertEqual(tape[1].source_time,200)
            self.assertFalse(tape[1].executable);self.assertTrue(tape[0].executable)

    def test_missing_prefix_requires_verified_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);build_union([self.source(root,'a.gz',[self.row(5,100)])],root/'db')
            with self.assertRaisesRegex(ValueError,'prefix anchor'):list(iter_trades(root/'db',0,1000))
            tape=list(iter_trades(root/'db',0,1000,prefix_anchors={'BTC-X':(4,200)}))
            self.assertEqual(tape[0].time,200);self.assertFalse(tape[0].executable)

    def test_gap_preserved_but_blocks_strict_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            report=build_union([self.source(root,'a.gz',[self.row()]),self.source(root,'b.gz',[self.row(3,300)])],root/'db')
            self.assertEqual(len(report['sequence_gaps']),1)
            with self.assertRaisesRegex(ValueError,'sequence gap'):list(iter_trades(root/'db',0,1000))

    def test_numeric_anomaly_and_block_trade_retained_not_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bad=self.row(2,200);bad['price']=0;block=self.row(3,300);block['block_trade_id']='block'
            missing=self.row(4,400);del missing['index_price']
            report=build_union([self.source(root,'a.gz',[self.row(),bad,block,missing])],root/'db')
            self.assertEqual(report['unique_rows'],4)
            tape=list(iter_trades(root/'db',0,1000));self.assertEqual(len(tape),2);self.assertFalse(tape[1].executable)

    def test_bounds_hash_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.source(root,'a.gz',[self.row()])
            with self.assertRaisesRegex(ValueError,'cap'):build_union([source],root/'db',row_cap=0)
            build_union([source],root/'db')
            with self.assertRaisesRegex(ValueError,'existing'):build_union([source],root/'db')
            Path(source.path).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'hash/size'):build_union([source],root/'db2')


if __name__=='__main__':unittest.main()
