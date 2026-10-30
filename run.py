"""Launch PyCut from a source checkout: ``python run.py [project_dir]``."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pycut.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
