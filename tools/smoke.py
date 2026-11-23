"""Offline smoke test for the lab-chat backend.

Runs the whole HTTP flow against a temp SQLite DB with an empty
DEEPSEEK_API_KEY, so the deterministic mock LLM is used and no network is
touched.

Usage:
    python tools/smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP_DIR = Path(tempfile.mkdtemp(prefix="lab-chat-smoke-"))

# Must be set before importing app.config (which reads .env).
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["DEEPSEEK_BASE_URL"] = "http://127.0.0.1:9"
os.environ["DB_PATH"] = str(TMP_DIR / "smoke.db")
os.environ["APP_SECRET"] = "smoke-secret"
os.environ["COOKIE_SECURE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import create_user  # noqa: E402

from app import main  # noqa: E402

ASSIGNMENT = (
    "Задание: домен au-team.irpo, пароль P@ssw0rd, RAID 5 из 3 дисков, "
    "HQ-SRV 192.168.0.10, HQ-CLI 192.168.0.70, порт 8080."
)


def check(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = line[len("data:"):].strip()
                data = json.loads(payload) if payload else None
        if name:
            events.append((name, data or {}))
    return events


def event_names(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def main_() -> int:
    print("smoke: temp db", os.environ["DB_PATH"])

    user_id, created = create_user.upsert_user("smoke", "smoke-pass", "Smoke User")
    print(f"smoke: user {'created' if created else 'updated'} ({user_id})")

    with TestClient(main.app) as client:
        # --- auth --------------------------------------------------- #
        response = client.get("/api/state")
        check(response.status_code == 401, f"state without cookie: {response.status_code}")

        response = client.post("/api/login", json={"username": "smoke", "password": "wrong"})
        check(response.status_code == 401, f"wrong password: {response.status_code}")

        response = client.post(
            "/api/login", json={"username": "smoke", "password": "smoke-pass"}
        )
        check(response.status_code == 200, f"login: {response.status_code} {response.text}")
        check(response.json()["user"]["username"] == "smoke", "login user payload")
        check("sid" in client.cookies, "sid cookie missing")

        response = client.get("/api/nope")
        check(response.status_code == 404, "unknown api path must be 404")
        check(response.json()["error"]["code"] == "not_found", "404 error shape")

        response = client.post("/api/login", json={})
        check(response.status_code == 400, "invalid body must be 400")
        check(response.json()["error"]["code"] == "bad_request", "validation error shape")

        # --- intake ------------------------------------------------- #
        response = client.post("/api/intake", json={"text": ASSIGNMENT})
        check(response.status_code == 200, f"intake: {response.status_code} {response.text}")
        intake = response.json()
        variant = intake["variant"]
        check(variant["storage"]["raid_level"] == 5, "intake raid level")
        check(variant["storage"]["disks"] == 3, "intake disks")
        check(variant["hosts"]["hq-srv"] == "192.168.0.10", "intake hq-srv")
        check(variant["hosts"]["hq-cli"] == "192.168.0.70", "intake hq-cli")
        check(variant["docker"]["port"] == 8080, "intake port")
        check(variant["storage"]["mount"] == "/raid5", "derived mount")
        check(
            any(item.get("key") == "storage.raid_level" and item.get("value") == 5
                for item in intake["sources"]),
            "intake sources",
        )
        print("smoke: intake ok, sources", len(intake["sources"]))

        # --- confirm ------------------------------------------------ #
        response = client.post("/api/intake/confirm", json={"variant": variant})
        check(
            response.status_code == 200,
            f"confirm: {response.status_code} {response.text}",
        )
        payload = response.json()
        check(payload["step"]["num"] == 1, "confirm starts at step 1")
        total = payload["progress"]["total"]
        check(total >= 1, "plan has steps")
        check(payload["progress"]["can_advance"] is True, "can_advance after confirm")
        check("Шаг 1/" in payload["step"]["markdown"], "step markdown header")
        print(f"smoke: confirm ok, total steps {total}")

        # --- state -------------------------------------------------- #
        response = client.get("/api/state")
        check(response.status_code == 200, "state after confirm")
        state = response.json()
        check(state["phase"] == "chat", "phase after confirm")
        check(state["step"]["num"] == 1, "state step 1")
        check(state["user"]["username"] == "smoke", "state user")

        # --- next --------------------------------------------------- #
        response = client.post("/api/next", json={"client_msg_id": uuid.uuid4().hex})
        check(response.status_code == 200, f"next: {response.status_code} {response.text}")
        step = response.json()["step"]
        expected = 2 if total > 1 else 1
        check(step["num"] == expected, f"next step {step['num']} != {expected}")
        print(f"smoke: next ok, step {step['num']}/{total}")

        # --- jump --------------------------------------------------- #
        response = client.post("/api/jump", json={"to": 1})
        check(response.status_code == 200, f"jump: {response.status_code} {response.text}")
        check(response.json()["step"]["num"] == 1, "jump to 1")

        response = client.post("/api/jump", json={"to": total + 50})
        check(response.status_code == 400, "jump out of range must be 400")
        check(response.json()["error"]["code"] == "bad_target", "bad_target code")
        print("smoke: jump ok")

        # --- question (SSE), step must not move --------------------- #
        question_id = uuid.uuid4().hex
        response = client.post(
            "/api/chat",
            json={"text": "как проверить, что массив собрался?", "client_msg_id": question_id},
        )
        check(response.status_code == 200, f"chat question: {response.status_code}")
        check(
            response.headers.get("content-type", "").startswith("text/event-stream"),
            "chat question content-type",
        )
        events = parse_sse(response.text)
        names = event_names(events)
        check("meta" in names, f"question events: {names}")
        check("delta" in names, f"question has no delta: {names}")
        check("done" in names, f"question has no done: {names}")
        meta = dict(events)["meta"]
        check(meta["intent"] in {"question", "error", "off_topic"}, "question intent")
        done = dict(events)["done"]
        check(done["progress"]["idx"] == 1, "question must not move the step")
        print("smoke: question stream ok, events", names)

        # --- double send -------------------------------------------- #
        response = client.post(
            "/api/chat",
            json={"text": "как проверить, что массив собрался?", "client_msg_id": question_id},
        )
        check(response.status_code == 409, f"duplicate: {response.status_code}")
        check(response.json()["error"]["code"] == "duplicate", "duplicate code")
        print("smoke: duplicate protection ok")

        # --- advance via chat (no model) ---------------------------- #
        response = client.post(
            "/api/chat", json={"text": "дальше", "client_msg_id": uuid.uuid4().hex}
        )
        check(response.status_code == 200, "chat advance")
        events = parse_sse(response.text)
        names = event_names(events)
        check(names[0] == "meta", f"advance first event {names}")
        check("step" in names, f"advance has no step event: {names}")
        check("done" in names, f"advance has no done event: {names}")
        step_event = dict(events)["step"]
        check(step_event["num"] == expected, "advance moved one step")
        print("smoke: advance via chat ok")

        # --- restart ------------------------------------------------ #
        response = client.post("/api/restart")
        check(response.status_code == 200, "restart")
        check(response.json()["step"]["num"] == 1, "restart to step 1")
        print("smoke: restart ok")

        # --- variant ------------------------------------------------ #
        new_variant = json.loads(json.dumps(variant))
        new_variant["storage"]["raid_level"] = 1
        new_variant["storage"].pop("disks", None)
        response = client.post("/api/variant", json={"variant": new_variant})
        check(response.status_code == 200, f"variant: {response.text}")
        step = response.json()["step"]
        check(step["num"] == 1, "variant resets to step 1")
        check(bool(step["command"] or step["gui"]), "variant step has a command or gui")
        state = client.get("/api/state").json()
        check(state["variant"]["storage"]["raid_level"] == 1, "variant raid level applied")
        check(state["variant"]["storage"]["mount"] == "/raid1", "variant derived mount")
        print("smoke: variant recompile ok")

        # --- logout ------------------------------------------------- #
        response = client.post("/api/logout")
        check(response.status_code == 204, f"logout: {response.status_code}")
        response = client.get("/api/state")
        check(response.status_code == 401, "state after logout must be 401")
        print("smoke: logout ok")

        # --- intake through /api/chat (fresh user) ------------------ #
        create_user.upsert_user("smoke2", "smoke-pass", "Smoke Two")
        response = client.post(
            "/api/login", json={"username": "smoke2", "password": "smoke-pass"}
        )
        check(response.status_code == 200, "login smoke2")
        response = client.post(
            "/api/chat",
            json={"text": ASSIGNMENT, "client_msg_id": uuid.uuid4().hex},
        )
        check(response.status_code == 200, "chat intake")
        events = parse_sse(response.text)
        names = event_names(events)
        check("meta" in names and "done" in names, f"intake chat events: {names}")
        done = dict(events)["done"]
        check(done.get("phase") == "confirm", "chat intake sets confirm phase")
        check(done["variant"]["storage"]["raid_level"] == 5, "chat intake variant")
        check(done["progress"]["idx"] == 0, "chat intake progress")
        state = client.get("/api/state").json()
        check(state["phase"] == "confirm", "state after chat intake")
        print("smoke: intake via chat ok")

    print("OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main_())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
