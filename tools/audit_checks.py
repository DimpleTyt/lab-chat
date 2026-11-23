"""Regression checks for the issues found in the audit (mock LLM, temp DB)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="lab-chat-audit-"))
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["DEEPSEEK_BASE_URL"] = "http://127.0.0.1:9"
os.environ["DB_PATH"] = str(TMP / "audit.db")
os.environ["APP_SECRET"] = "audit"
os.environ["COOKIE_SECURE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
import create_user  # noqa: E402
from app import main  # noqa: E402

client = TestClient(main.app)
create_user.upsert_user("audit", "auditpass", "Audit")
assert client.post("/api/login", json={"username": "audit", "password": "auditpass"}).status_code == 200

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))


def post(path, body=None):
    return client.post(path, json=body or {})


# 1. custom ntp survives confirm
post("/api/intake", {"text": "RAID 5 из 3 дисков, /raid5. Сервер времени 10.0.0.5."})
d = post("/api/intake/confirm", {"variant": {}}).json()
st = client.get("/api/state").json()
check("ntp.server keeps assignment value", st["variant"]["ntp"]["server"] == "10.0.0.5", st["variant"]["ntp"]["server"])

# 2. partial variant keeps admin password from the assignment
post("/api/intake", {"text": "Домен lab.local, пароль Secret123, RAID 1 из двух дисков."})
post("/api/intake/confirm", {"variant": {"domain": "lab.local"}})
st = client.get("/api/state").json()
check("admin_password survives partial confirm", st["variant"]["admin_password"] == "Secret123", st["variant"]["admin_password"])

# 3. cancel restores chat
post("/api/intake", {"text": "RAID 10 из четырёх дисков."})
before = client.get("/api/state").json()
r = post("/api/intake/cancel").json()
st = client.get("/api/state").json()
check("cancel returns to chat", r["phase"] == "chat" and st["phase"] == "chat", r)
check("cancel keeps the plan", st["progress"]["total"] > 0, st["progress"])

# 4. unsupported RAID rejected
r = post("/api/intake/confirm", {"variant": {"storage": {"raid_level": 7, "disks": 4}}})
check("RAID 7 rejected", r.status_code == 400, r.status_code)

# 5. empty modules rejected
r = post("/api/intake/confirm", {"variant": {"modules": []}})
check("empty modules rejected", r.status_code == 400, r.status_code)

# 6. md path is honoured in commands
post("/api/intake", {"text": "RAID 5 из трёх дисков, /raid5."})
post("/api/intake/confirm", {"variant": {"storage": {"md": "/dev/md1"}}})
st = client.get("/api/state").json()
plan = main.compiler_service.plan_from_json(main._ensure_chat(st["user"]["id"])["plan"])
cmd = next((s["command"] for s in plan if (s.get("command") or "").startswith("mdadm --create")), "")
check("md1 used in command", "/dev/md1" in cmd, cmd)
check("no md0 left in plan", not any("/dev/md0" in (s.get("command") or "") for s in plan))

# 7. client_msg_id required
r = client.post("/api/chat", json={"text": "привет"})
check("chat without client_msg_id rejected", r.status_code in (400, 422), r.status_code)

failed = [name for name, ok, _ in results if not ok]
print("\nsummary:", len(results) - len(failed), "/", len(results), "passed")
sys.exit(1 if failed else 0)
