"""Build the small standalone explorer ZIP, without repository data or a venv."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MODULES=('__init__','accounting','engine','decision_clock','liquidation','robust_rollout',
         'treasury_fixtures','treasury_model','market_simulation','explorer')
FILES=[f'research/post_decision_value/{m}.py' for m in MODULES]+[
    'research/post_decision_value/explorer_web/index.html',
    'research/post_decision_value/explorer_web/style.css',
    'research/post_decision_value/explorer_web/app.js',
    'docs/research/post_decision_value/treasury-maxmin-v1.tar.gz',
    'docs/research/post_decision_value/STATE_VALUE_EXPLORER.md',
    'scripts/setup_explorer.py','scripts/package_explorer.py','setup_ui.cmd','launch_ui.cmd']
README='''TREASURY EXPLORER - LOCAL WINDOWS SETUP

1. Right-click this ZIP and choose Extract All. Open the extracted folder.
   Do not run the programs from inside the ZIP viewer.
2. Double-click setup_ui.cmd. It finds a supported Python and installs NumPy
   and CPU PyTorch into this folder's .venv-explorer environment.
3. Double-click launch_ui.cmd. Keep its terminal open while using the UI.
   The browser opens http://127.0.0.1:8765. Stop with Ctrl+C in the terminal.

Prerequisites:
- Intel/AMD Windows: 64-bit CPython 3.12, 3.13 or 3.14, with Python launcher.
- Snapdragon/ARM Windows: native ARM64 CPython 3.12 or 3.13, with launcher.
  The pinned Torch version has no Windows ARM64 Python 3.14 wheel.
- Python installers: https://www.python.org/downloads/windows/
  Choose the architecture/version above. This package does not install Python.
- Internet is required for the first dependency setup. Model and example data
  are included; subsequent launches work offline. Git and Node are not needed.

No administrator privileges are required by these scripts. Setup modifies only
this folder's isolated environment; it does not change system Python packages.
If setup reports an incompatible existing environment, rename .venv-explorer
and rerun setup with the intended Python. Installation errors remain in the
terminal; no model training runs during setup, launch or evaluation.

Simulation is off by default. This is research software, not live trading.
The checkpoint is diagnostic-only; its repeated network policy failed acceptance.
Windows execution is not yet verified. Native Windows ARM64 dependency wheels
were checked, but that does not establish runtime compatibility on your laptop.
Linux setup, extracted-package inference and accounting/API tests were verified.

See docs/research/post_decision_value/STATE_VALUE_EXPLORER.md for the full guide.
PACKAGE-MANIFEST.json records SHA-256 for every packaged file.
'''


def build(destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('Refusing to replace an existing package')
    payload={name:(ROOT/name).read_bytes() for name in FILES}
    for name in payload:
        if name.endswith('.cmd'):payload[name]=payload[name].replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    payload['START-HERE.txt']=README.replace('\n','\r\n').encode()
    manifest=dict(schema='state-explorer-package-v1',files={name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
                                                         for name,body in sorted(payload.items())})
    payload['PACKAGE-MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,body in sorted(payload.items()):
            entry=zipfile.ZipInfo('treasury-explorer/'+name,date_time=(2026,10,28,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
            z.writestr(entry,body)
    receipt=dict(file=destination.name,bytes=destination.stat().st_size,
                 sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),members=len(payload))
    print(json.dumps(receipt));return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);args=p.parse_args()
    build(args.output)


if __name__=='__main__':main()
