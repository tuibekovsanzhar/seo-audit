"""Compatibility entry point; hardened implementation is shared with the application."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from maya_audit.client_reporting import reliability as _implementation
# Keep the historical import surface (including private helpers) for existing callers.
globals().update({k: v for k, v in vars(_implementation).items() if not k.startswith("__")})
if __name__ == "__main__":
    _implementation.main()
