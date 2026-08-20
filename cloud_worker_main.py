"""Cloud Run Job entry point."""

from server.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
