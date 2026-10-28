"""Create a local CPU-only environment; never trains or launches automatically."""
import argparse
from pathlib import Path
import platform
import struct
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def validate_platform(system, machine, version, bits):
    if not (3,12)<=version<(3,15) or bits!=64:
        raise ValueError('Use 64-bit CPython 3.12, 3.13 or 3.14.')
    machine=machine.lower()
    if system=='Windows' and machine in ('arm64','aarch64'):
        if version>=(3,14):
            raise ValueError('Native Snapdragon/ARM Windows needs Python 3.12 or 3.13: the pinned PyTorch release has no cp314 Windows ARM64 wheel.')
        return 'Windows ARM64: native wheels are available; Windows runtime is not yet tested.'
    if system not in ('Windows','Linux') or machine not in ('amd64','x86_64'):
        raise ValueError('Supported setup targets: x64 Windows/Linux, or ARM64 Windows with Python 3.12/3.13.')
    return f'{system} x64 setup'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Check Python/architecture only; do not install')
    args=parser.parse_args()
    print(f'Python {platform.python_version()} | {platform.system()} | {platform.machine()} | {struct.calcsize("P")*8}-bit')
    try:
        print(validate_platform(platform.system(),platform.machine(),sys.version_info[:2],struct.calcsize('P')*8))
    except ValueError as error:
        raise SystemExit(str(error)+' No environment was changed.') from error
    if args.check:return
    env=ROOT/'.venv-explorer'
    if not env.exists():venv.EnvBuilder(with_pip=True).create(env)
    python=env/('Scripts/python.exe' if platform.system()=='Windows' else 'bin/python')
    # Refuse to silently reuse a venv created with another Python/architecture.
    probe=subprocess.check_output([str(python),'-c','import platform,sys;print(platform.machine().lower(),sys.version_info.major,sys.version_info.minor)'],text=True).strip()
    expected=f'{platform.machine().lower()} {sys.version_info.major} {sys.version_info.minor}'
    if probe!=expected:
        raise SystemExit('The existing .venv-explorer uses another Python or architecture. Rename that folder and rerun setup with the intended Python. No dependencies were changed.')
    def run(*arguments):subprocess.run([str(python),'-m','pip',*arguments],check=True)
    try:
        run('install','--only-binary=:all:','--index-url','https://pypi.org/simple','numpy==2.3.5')
        run('install','--only-binary=:all:','--index-url','https://download.pytorch.org/whl/cpu','torch==2.14.1')
        subprocess.run([str(python),'-c','import torch,numpy; print("Ready:",torch.__version__,numpy.__version__)'],check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit('Dependency installation failed. Check network access and availability of CPU wheels for this Python version. No training ran.') from error
    print('Setup complete. Run launch_ui.cmd on Windows, or .venv-explorer/bin/python -m research.post_decision_value.explorer --open on Linux.')

if __name__=='__main__':main()
