import sys
from pathlib import Path

# make the self-contained scripts package importable from the repo-root test suite
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
