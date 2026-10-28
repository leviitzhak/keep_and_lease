"""Platform gates and an extracted distribution smoke test, without installing."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.setup_explorer import validate_platform
from scripts.package_explorer import build


class InstallTests(unittest.TestCase):
    def test_windows_architecture_and_wheel_matrix(self):
        for version in ((3,12),(3,13)):
            self.assertIn('ARM64',validate_platform('Windows','ARM64',version,64))
        for version in ((3,12),(3,13),(3,14)):
            self.assertIn('x64',validate_platform('Windows','AMD64',version,64))
        with self.assertRaisesRegex(ValueError,'no cp314'):
            validate_platform('Windows','ARM64',(3,14),64)
        self.assertIn('x64',validate_platform('Linux','x86_64',(3,12),64))

    def test_unsupported_targets_fail_before_install(self):
        for args in [('Windows','AMD64',(3,11),64),('Windows','AMD64',(3,15),64),
                     ('Windows','x86',(3,13),32),('Linux','aarch64',(3,13),64),('Darwin','arm64',(3,13),64)]:
            with self.subTest(args=args),self.assertRaises(ValueError):validate_platform(*args)

    def test_extracted_package_is_self_contained_and_checksummed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'explorer.zip';build(archive)
            with zipfile.ZipFile(archive) as z:
                self.assertLess(archive.stat().st_size,3_000_000)
                self.assertTrue(all(name.startswith('treasury-explorer/') and '..' not in Path(name).parts for name in z.namelist()))
                z.extractall(root)
            package=root/'treasury-explorer';manifest=json.loads((package/'PACKAGE-MANIFEST.json').read_text())
            for name,entry in manifest['files'].items():
                data=(package/name).read_bytes()
                self.assertEqual(len(data),entry['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
            self.assertIn(b'\r\n',(package/'setup_ui.cmd').read_bytes())
            script='''from pathlib import Path
from research.post_decision_value import explorer
assert Path(explorer.__file__).resolve().is_relative_to(Path.cwd())
a=explorer.Explorer();m=a.market({'kind':'fixture'})
r=a.evaluate({'market_id':m['id'],'state':m['defaults']})
assert r['prediction']['value'] is not None
assert r['checkpoint']['target']=='diagnostic-hold-boundary-v1'
s=a.market({'kind':'simulation','configuration':{'enabled':True}})
assert s['rows']>0
print('standalone inference and simulator passed')'''
            result=subprocess.run([sys.executable,'-c',script],cwd=package,text=True,capture_output=True,timeout=20,check=True)
            self.assertIn('passed',result.stdout)
            with self.assertRaises(ValueError):build(archive)


if __name__=='__main__':unittest.main()
