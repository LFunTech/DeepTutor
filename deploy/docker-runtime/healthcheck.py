from pathlib import Path
import json
import urllib.request

port = 8001
settings_path = Path("/app/data/user/settings/system.json")
try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    port = int(settings.get("backend_port") or port)
except Exception:
    pass

urllib.request.urlopen(f"http://localhost:{port}/health/ready", timeout=5).close()
