"""PyInstaller frozen entry point for the core_rpc sidecar (P3).

A PyInstaller entry script runs as ``__main__`` with no package context, so
``core_rpc/server.py``'s relative imports (``from .dispatch import ...``) would
fail if frozen directly. Importing it here as a proper package member
(``core_rpc.server``) restores the package context, so server.py stays unchanged
and the dev ``python -m core_rpc.server`` path is unaffected.
"""

import sys

from core_rpc.server import main

if __name__ == "__main__":
    sys.exit(main())
