import gzip,json,tempfile,unittest
from pathlib import Path
from research.post_decision_value.archive_union_worker import merge,encode,digest,PREFIX
from research.post_decision_value.logical_data import LogicalArchive,local_getter
from tests.post_decision_value import test_archive_union_worker as fixtures

class LogicalReaderTests(unittest.TestCase):
    def fixture(self):
        inputs,objects,get=fixtures.ArchiveUnionTests().fixture()
        with tempfile.TemporaryDirectory() as d:m=merge(inputs,get,d)
        m['read_object_pins']=[]
        return m,objects
    def test_union_reads_canonical_once_and_window_is_half_open(self):
        m,objects=self.fixture();reader=LogicalArchive(m,objects.__getitem__)
        tape=list(reader.trades(0,104,symbols=['BTC-X']))
        self.assertEqual([t.identifier for t in tape],['1','2','3'])
        self.assertEqual([t.identifier for t in reader.trades(102,103,symbols=['BTC-X'])],['2'])
        self.assertEqual(reader.instrument_metadata()[0]['instrument'],'BTC-X')
    def test_receipt_and_object_hashes_and_duplicate_sources(self):
        m,objects=self.fixture();key=next(k for k in objects if k.endswith('/trades.jsonl.gz'));objects[key]=b'bad'
        with self.assertRaisesRegex(ValueError,'hash mismatch'):list(LogicalArchive(m,objects.__getitem__).trades(0,200,symbols=['BTC-X']))
        m['canonical_receipt_keys'].append(m['canonical_receipt_keys'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate canonical'):LogicalArchive(m,objects.__getitem__)
    def test_cross_chunk_backdating_is_not_a_retroactive_fill(self):
        m,objects=self.fixture()
        key=m['canonical_receipt_keys'][1];r=json.loads(objects[key]);obj=r['objects'][0]
        row=json.loads(gzip.decompress(objects[obj['key']]));row['timestamp']=100
        raw=gzip.compress(encode(row));objects[obj['key']]=raw;obj.update(sha256=digest(raw),bytes=len(raw));objects[key]=encode(r)
        tape=list(LogicalArchive(m,objects.__getitem__).trades(0,200,symbols=['BTC-X']))
        self.assertEqual([t.time for t in tape],[101,102,102]);self.assertFalse(tape[-1].executable)
    def test_prefix_anchor_and_gap_validation(self):
        m,objects=self.fixture();m['canonical_receipt_keys']=m['canonical_receipt_keys'][1:]
        reader=LogicalArchive(m,objects.__getitem__)
        with self.assertRaisesRegex(ValueError,'prefix anchor'):list(reader.trades(0,200,symbols=['BTC-X']))
        tape=list(reader.trades(0,200,symbols=['BTC-X'],prefix_anchors={'BTC-X':(2,110)}))
        self.assertEqual(tape[0].time,110);self.assertFalse(tape[0].executable)
    def test_local_cache_and_manifest_pin(self):
        m,objects=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=encode(m);p=root/'manifest.json.gz';p.write_bytes(gzip.compress(raw))
            for key,data in objects.items():
                path=root/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            reader=LogicalArchive.open(p,local_getter(root),expected_sha256=digest(raw))
            self.assertEqual(len(list(reader.trades(0,200,symbols=['BTC-X']))),3)
            with self.assertRaisesRegex(ValueError,'manifest hash'):LogicalArchive.open(p,local_getter(root),expected_sha256='bad')
            with self.assertRaisesRegex(ValueError,'outside cache'):local_getter(root)('../outside')

if __name__=='__main__':unittest.main()
