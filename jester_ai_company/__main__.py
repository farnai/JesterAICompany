"""Module execution entrypoint for python -m jester_ai_company."""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
