"""Manual check: how the intake parser reads real assignments.

Runs with an empty key on purpose, so the deterministic first pass is shown
and the optional model gap-filler never touches the network.

Usage:
    python tools/dev_check_intake.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before app.config is imported (.env must not win).
os.environ["DEEPSEEK_API_KEY"] = ""

from app.intake import parse_assignment  # noqa: E402

SAMPLES = {
    "raid10": (
        "Вариант 12. Сконфигурируйте файловое хранилище: RAID 10 из четырёх дисков, "
        "точка монтирования /raid10. Домен au-team.irpo. HQ-CLI 192.168.0.65/28. "
        "Шара NFS /raid10/nfs для сети 192.168.0.64/28. NTP-сервер 172.16.1.14."
    ),
    "raid1": (
        "Соберите RAID 1 из двух дисков и смонтируйте в /raid1. "
        "Сервер HQ-SRV 192.168.0.10, клиент 192.168.0.70."
    ),
    "empty": "привет",
    "freeform": (
        "Задание: RAID 5 на трёх дисках, /raid5. Домен test.local, пароль Admin123. "
        "NFS 192.168.0.64/28, свой сервер времени 10.0.0.1, порт приложения 9090."
    ),
    "freeform2": (
        "Соберите RAID 0 из двух дисков, смонтируйте в /data. "
        "Chrony 10.1.1.5. Порт веб 8443. Домен lab.local, рабочая группа LAB."
    ),
}

EXPECT = {
    "raid10": {
        "storage.raid_level": 10,
        "storage.disks": 4,
        "storage.mount": "/raid10",
        "ntp.server": "172.16.1.14",
    },
    "raid1": {
        "storage.raid_level": 1,
        "storage.disks": 2,
        "storage.mount": "/raid1",
    },
    "freeform": {
        "storage.raid_level": 5,
        "storage.disks": 3,
        "storage.mount": "/raid5",
        "domain": "test.local",
        "admin_password": "Admin123",
        "nfs.clients": "192.168.0.64/28",
        "ntp.server": "10.0.0.1",
        "docker.port": 9090,
    },
    "freeform2": {
        "storage.raid_level": 0,
        "storage.disks": 2,
        "storage.mount": "/data",
        "ntp.server": "10.1.1.5",
        "docker.port": 8443,
        "domain": "lab.local",
        "workgroup": "LAB",
    },
}


def dig(variant, dotted):
    node = variant
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _check_model_merge(failures) -> None:
    """Simulate the second pass: no network, validates merge priority + whitelists."""
    import types

    import app.intake as module

    real_settings = module.settings
    real_extract = module.llm.extract_variant
    try:
        module.settings = types.SimpleNamespace(mock_llm=False)
        module.llm.extract_variant = lambda text: {
            "storage": {"raid_level": 5, "disks": 9, "mount": "bad mount"},
            "hosts": {"hq-srv": "999.1.1.1"},
            "ntp": {"server": "10.9.9.9"},
            "docker": {"port": 9091},
            "nfs": {"clients": "10.0.0.0/24"},
        }
        result = module.parse_assignment("Задание: RAID 0. Соберите массив.")
        variant = result["variant"]
        sources = {item["key"]: item for item in result["sources"]}
        checks = [
            ("deterministic RAID wins", variant["storage"]["raid_level"] == 0),
            ("model fills ntp.server", variant["ntp"]["server"] == "10.9.9.9"),
            ("model fills docker.port", variant["docker"]["port"] == 9091),
            ("invalid disks rejected", variant["storage"]["disks"] == 2),
            ("invalid host rejected", variant["hosts"]["hq-srv"] == "192.168.0.1"),
            ("model source tagged", sources.get("ntp.server", {}).get("source") == "model"),
            ("junk produced warnings", len(result["warnings"]) >= 3),
        ]
        print("--- model merge (simulated, no network)")
        for label, ok in checks:
            print(f"  {label}: {'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"model merge: {label}")
    finally:
        module.settings = real_settings
        module.llm.extract_variant = real_extract


def main() -> int:
    failures = []
    for name, text in SAMPLES.items():
        result = parse_assignment(text)
        variant = result["variant"]
        print(f"--- {name}")
        print("storage:", json.dumps(variant["storage"], ensure_ascii=False))
        print("hosts:", json.dumps(variant["hosts"], ensure_ascii=False))
        print("nfs:", json.dumps(variant["nfs"], ensure_ascii=False))
        print("ntp:", json.dumps(variant["ntp"], ensure_ascii=False))
        print("docker:", json.dumps(variant["docker"], ensure_ascii=False))
        print("domain/password:", variant["domain"], "/", variant["admin_password"])
        print("sources:", json.dumps(result["sources"], ensure_ascii=False))
        print("unknown:", result["unknown"], "warnings:", result["warnings"])

        for key, expected in EXPECT.get(name, {}).items():
            actual = dig(variant, key)
            ok = actual == expected
            print(f"  {key}: {actual!r} (expected {expected!r}) {'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"{name}: {key} = {actual!r}, expected {expected!r}")

    _check_model_merge(failures)

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("-", failure)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
