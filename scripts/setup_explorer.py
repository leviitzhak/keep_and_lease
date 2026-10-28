"""Create a local CPU-only environment; never trains or launches automatically."""
import argparse
from pathlib import Path
import platform
import struct
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Check Python/architecture only; do not install')
    args=parser.parse_args()
    print(f'Python {platform.python_version()} | {platform.system()} | {platform.machine()} | {struct.calcsize("P")*8}-bit')
    if not (3,12)<=sys.version_info[:2]<(3,15) or struct.calcsize('P')!=8:
        raise SystemExit('Use 64-bit CPython 3.12, 3.13 or 3.14. No environment was changed.')
    if platform.machine().lower() not in ('amd64','x86_64'):
        raise SystemExit('This CPU setup supports x64 Windows/Linux only. ARM/macOS wheels are not validated.')
    if platform.system() not in ('Windows','Linux'):
        raise SystemExit('This setup supports Windows/Linux only; other OS procedures are not validated.')
    if args.check:return
    env=ROOT/'.venv-explorer'
    if not env.exists():venv.EnvBuilder(with_pip=True).create(env)
    python=env/('Scripts/python.exe' if platform.system()=='Windows' else 'bin/python')
    def run(*arguments):subprocess.run([str(python),'-m','pip',*arguments],check=True)
    try:
        run('install','--index-url','https://pypi.org/simple','numpy==2.3.5')
        run('install','--index-url','https://download.pytorch.org/whl/cpu','torch==2.14.1')
        subprocess.run([str(python),'-c','import torch,numpy; print("Ready:",torch.__version__,numpy.__version__)'],check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit('Dependency installation failed. Check network access and availability of CPU wheels for this Python version. No training ran.') from error
    print('Setup complete. Run launch_ui.cmd on Windows, or .venv-explorer/bin/python -m research.post_decision_value.explorer --open on Linux.')

if __name__=='__main__':main()
