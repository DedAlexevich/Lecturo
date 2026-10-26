import json
import sys
from pathlib import Path

from app.main import app

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
