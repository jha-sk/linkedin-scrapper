import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="phantom-tests-")
os.environ.setdefault("PHANTOM_DATA_DIR", _TMP)
os.environ.setdefault("PHANTOM_SECRET_KEY", "test-key-not-a-real-secret")
