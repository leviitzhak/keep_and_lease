#!/usr/bin/env python3
"""Retry a Python cloud command only for transient credential transport failures."""
import runpy
import sys
import time
from pathlib import Path


def retry(operation, sleep=time.sleep):
    from google.auth.exceptions import RefreshError, TransportError
    for attempt in range(4):
        try:
            return operation()
        except (RefreshError, TransportError) as error:
            transient = any(marker in str(error).lower() for marker in (
                'connection timeout', 'connection reset', 'timed out',
                'upstream connect error', 'temporarily unavailable'))
            if not transient or attempt == 3:
                raise
            print(f'Transient credential transport failure; retry {attempt + 1}/3', flush=True)
            sleep(2 ** (attempt + 1))


if __name__ == '__main__':
    script = Path(sys.argv[1]).resolve()
    sys.argv = sys.argv[1:]
    sys.path.insert(0, str(script.parent))
    retry(lambda: runpy.run_path(str(script), run_name='__main__'))
