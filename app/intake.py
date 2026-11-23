"""Intake parser: free-form assignment -> variant.

First pass is deterministic and always available (no key, no network).
If DEEPSEEK_API_KEY is set, a second pass asks the model only for the fields
the parser did not recognise; deterministic values always win.
"""
from __future__ import annotations

import bisect
import copy
import logging
import re

from shared.params import DEFAULTS, RAID_MIN, deep_merge, normalize

from . import llm
from .config import settings

log = logging.getLogger(__name__)

IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
HOST_NAMES = ("hq-srv", "hq-cli", "hq-rtr", "br-srv", "isp")

# "RAID 5 на трёх дисках" -> 3
DISK_WORDS = {
    "два": 2, "две": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
}

# Model output whitelists.
MODEL_RAID_LEVELS = {0, 1, 5, 10}

# Fields normalize() recomputes; never merge stale copies back in.
DERIVED_STORAGE = ("devices", "devices_str", "md", "mount", "raid_name")
DERIVED_NFS = ("export", "server", "client_host")

SOURCE_LABELS = {
    "domain": "Домен",
    "admin_password": "Пароль",
    "workgroup": "Рабочая группа",
    "storage.raid_level": "RAID",
    "storage.disks": "Диски",
    "storage.mount": "Монтирование",
    "storage.md": "Устройство",
    "nfs.export": "NFS-экспорт",
    "nfs.clients": "NFS-клиенты",
    "ntp.server": "Сервер времени",
    "ntp.stratum": "NTP-стратум",
    "docker.port": "Порт",
    "modules": "Модули",
}

# Values that always come from the methodology unless the assignment or the
# user overrides them. Appended to sources with source="method".
METHOD_KEYS = (
    "domain",
    "workgroup",
    "hosts.hq-srv",
    "hosts.hq-cli",
    "hosts.hq-rtr",
    "hosts.br-srv",
    "storage.raid_level",
    "storage.disks",
    "storage.mount",
    "nfs.export",
    "nfs.clients",
    "ntp.server",
    "docker.port",
)


def source_label(key: str) -> str:
    if key.startswith("hosts."):
        return key.split(".", 1)[1].upper()
    return SOURCE_LABELS.get(key, key)


def add_method_sources(entries: list[dict], variant: dict | None) -> list[dict]:
    """Append default values as source="method"; existing keys keep priority."""
    present = {
        item.get("key")
        for item in entries
        if isinstance(item, dict) and item.get("key")
    }
    result = list(entries)
    if not isinstance(variant, dict):
        return result
    for key in METHOD_KEYS:
        if key in present:
            continue
        value = _dig_variant(variant, key.split("."))
        if value is None:
            continue
        result.append({
            "key": key,
            "label": source_label(key),
            "value": value,
            "source": "method",
        })
        present.add(key)
    return result


def source_entries(sources: dict, origins: dict | None = None) -> list[dict]:
    """Readable list for the intake card: what exactly came from where."""
    origins = origins or {}
    entries = []
    for key, value in sources.items():
        entries.append({
            "key": key,
            "label": source_label(key),
            "value": value,
            "source": origins.get(key, "exam"),
        })
    return entries


def _valid_ip(value) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


class _Text:
    """Whole-text matcher that remembers which source lines were understood."""

    def __init__(self, text: str):
        self.text = text
        self.lines = text.splitlines()
        self.starts: list[int] = []
        pos = 0
        for line in self.lines:
            self.starts.append(pos)
            pos += len(line) + 1
        self.hits: set[int] = set()

    def finditer(self, pattern: str, flags: int = 0):
        for match in re.finditer(pattern, self.text, flags):
            index = bisect.bisect_right(self.starts, match.start()) - 1
            if index >= 0:
                self.hits.add(index)
            yield match


def _strip_derived(variant: dict | None) -> dict:
    if not variant:
        return {}
    base = copy.deepcopy(variant)
    storage = base.get("storage")
    if isinstance(storage, dict):
        for key in DERIVED_STORAGE:
            storage.pop(key, None)
    nfs = base.get("nfs")
    if isinstance(nfs, dict):
        for key in DERIVED_NFS:
            nfs.pop(key, None)
    ntp = base.get("ntp")
    if isinstance(ntp, dict):
        ntp.pop("server", None)
    return base


# --------------------------------------------------------------------------- #
# Second pass: model fills the gaps. Deterministic values always win.
# --------------------------------------------------------------------------- #
def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    return None


def _dig_variant(data, path):
    node = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _validate_model_variant(raw, taken: set[str]) -> tuple[dict, dict, list[str]]:
    """Whitelist model output. Returns (override, origins, warnings)."""
    override: dict = {}
    origins: dict = {}
    warnings: list[str] = []

    if not isinstance(raw, dict):
        return override, origins, ["Модель вернула не JSON-объект — пропущено."]
    if set(raw) == {"variant"} and isinstance(raw.get("variant"), dict):
        raw = raw["variant"]

    def accept(path: tuple[str, ...], value) -> None:
        key = ".".join(path)
        if key in taken:
            return
        node = override
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
        origins[key] = "model"

    domain = raw.get("domain")
    if domain is not None:
        value = domain.strip().lower() if isinstance(domain, str) else ""
        if value and re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", value):
            accept(("domain",), value)
        else:
            warnings.append("Модель вернула некорректный домен — пропущено.")

    workgroup = raw.get("workgroup")
    if workgroup is not None:
        value = workgroup.strip() if isinstance(workgroup, str) else ""
        if value and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
            accept(("workgroup",), value)
        else:
            warnings.append("Модель вернула некорректную рабочую группу — пропущено.")

    password = raw.get("admin_password")
    if password is not None:
        if (isinstance(password, str) and 0 < len(password) <= 128
                and not any(ch.isspace() for ch in password)):
            accept(("admin_password",), password)
        else:
            warnings.append("Модель вернула некорректный пароль — пропущено.")

    hosts = raw.get("hosts")
    if isinstance(hosts, dict):
        hosts = {str(key).strip().lower(): value for key, value in hosts.items()}
        for name in HOST_NAMES:
            ip = hosts.get(name)
            if ip is None:
                continue
            if _valid_ip(ip):
                accept(("hosts", name), ip)
            else:
                warnings.append(f"Модель вернула некорректный IP для {name.upper()} — пропущено.")
    elif hosts is not None:
        warnings.append("Модель вернула некорректный блок hosts — пропущено.")

    storage = raw.get("storage")
    if isinstance(storage, dict):
        level = _as_int(storage.get("raid_level"))
        if storage.get("raid_level") is not None:
            if level in MODEL_RAID_LEVELS:
                accept(("storage", "raid_level"), level)
            else:
                warnings.append("Модель вернула недопустимый RAID (нужно 0/1/5/10) — пропущено.")

        disks = _as_int(storage.get("disks"))
        if storage.get("disks") is not None:
            pool_size = len(DEFAULTS["storage"]["disk_pool"])
            if disks is not None and 2 <= disks <= 6 and disks <= pool_size:
                accept(("storage", "disks"), disks)
            else:
                warnings.append("Модель вернула недопустимое число дисков (2..6) — пропущено.")

        mount = storage.get("mount")
        if mount is not None:
            if (isinstance(mount, str) and mount.startswith("/")
                    and len(mount) > 1 and not re.search(r"\s", mount)):
                accept(("storage", "mount"), mount)
            else:
                warnings.append("Модель вернула некорректную точку монтирования — пропущено.")

        md = storage.get("md")
        if md is not None:
            if isinstance(md, str) and re.fullmatch(r"/dev/md\d+", md):
                accept(("storage", "md"), md)
            else:
                warnings.append("Модель вернула некорректное устройство md — пропущено.")
    elif storage is not None:
        warnings.append("Модель вернула некорректный блок storage — пропущено.")

    nfs = raw.get("nfs")
    if isinstance(nfs, dict):
        clients = nfs.get("clients")
        if clients is not None:
            ok = False
            if isinstance(clients, str):
                address, sep, prefix = clients.partition("/")
                ok = bool(sep) and prefix.isdigit() and 0 <= int(prefix) <= 32 and _valid_ip(address)
            if ok:
                accept(("nfs", "clients"), clients)
            else:
                warnings.append("Модель вернула некорректную NFS-сеть — пропущено.")
    elif nfs is not None:
        warnings.append("Модель вернула некорректный блок nfs — пропущено.")

    ntp = raw.get("ntp")
    if isinstance(ntp, dict):
        server = ntp.get("server")
        if server is not None:
            if _valid_ip(server):
                accept(("ntp", "server"), server)
            else:
                warnings.append("Модель вернула некорректный сервер времени — пропущено.")
        stratum = _as_int(ntp.get("stratum"))
        if ntp.get("stratum") is not None:
            if stratum is not None and 1 <= stratum <= 15:
                accept(("ntp", "stratum"), stratum)
            else:
                warnings.append("Модель вернула некорректный NTP-стратум — пропущено.")
    elif ntp is not None:
        warnings.append("Модель вернула некорректный блок ntp — пропущено.")

    docker = raw.get("docker")
    if isinstance(docker, dict):
        port = _as_int(docker.get("port"))
        if docker.get("port") is not None:
            if port is not None and 1 <= port <= 65535:
                accept(("docker", "port"), port)
            else:
                warnings.append("Модель вернула некорректный порт (1..65535) — пропущено.")
    elif docker is not None:
        warnings.append("Модель вернула некорректный блок docker — пропущено.")

    modules = raw.get("modules")
    if modules is not None:
        valid: list[int] = []
        if isinstance(modules, list):
            for item in modules:
                number = _as_int(item)
                if number is not None and 1 <= number <= 9:
                    valid.append(number)
        if valid:
            accept(("modules",), sorted(set(valid)))
        else:
            warnings.append("Модель вернула некорректный список модулей — пропущено.")

    return override, origins, warnings


def parse_assignment(text: str, base: dict | None = None) -> dict:
    """Return {variant, sources, unknown, warnings} for an assignment text."""
    text = (text or "").strip()
    skipped = text.lower() in ("без задания", "по методичке", "нет задания", "нет")
    if skipped:
        text = ""
    t = _Text(text)
    warnings: list[str] = []
    sources: dict = {}
    origins: dict[str, str] = {}
    override: dict = {}

    # --- hosts ---------------------------------------------------------- #
    hosts: dict[str, str] = {}
    for match in t.finditer(rf"\b(hq-srv|hq-cli|hq-rtr|br-srv|isp)\b[^\n\d]{{0,40}}{IP}", re.I):
        host, ip = match.group(1).lower(), match.group(2)
        if _valid_ip(ip):
            hosts[host] = ip
    for match in t.finditer(rf"{IP}[^\w\n]{{0,20}}(hq-srv|hq-cli|hq-rtr|br-srv|isp)\b", re.I):
        ip, host = match.group(1), match.group(2).lower()
        if _valid_ip(ip):
            hosts.setdefault(host, ip)
    if hosts:
        override["hosts"] = hosts
        for host, ip in hosts.items():
            sources[f"hosts.{host}"] = ip

    # --- domain --------------------------------------------------------- #
    domain = None
    for match in t.finditer(r"(?:домен[а-яё]*|domain)\s*[:\-–—]?\s*([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.I):
        domain = match.group(1).rstrip(".")
    if not domain:
        for match in t.finditer(r"\b([a-z0-9][a-z0-9-]*\.(?:irpo|local|lan|ru|com|net|org))\b", re.I):
            domain = match.group(1).lower()
            break
    if domain:
        override["domain"] = domain
        sources["domain"] = domain

    # --- password ------------------------------------------------------- #
    password = None
    if "P@ssw0rd" in text:
        password = "P@ssw0rd"
    for match in t.finditer(r"(?:парол[а-яё]*|password)\s*[:\-–—]?\s*([^\s,;]{3,})", re.I):
        value = match.group(1).strip(".,;:()«»\"'")
        if value.lower() in {"для", "от", "пользователя", "администратора", "root", "домена", "admin"}:
            continue
        if re.fullmatch(r"[а-яё]+", value, re.I):
            # "пароль домена ..." — not a password value.
            continue
        password = value
    if password:
        override["admin_password"] = password
        sources["admin_password"] = password

    # --- workgroup ------------------------------------------------------ #
    for match in t.finditer(
        r"(?:workgroup|рабоч[а-яё]*\s+групп[а-яё]*)\s*[:\-–—]?\s*([A-Za-z0-9_-]+)", re.I
    ):
        override["workgroup"] = match.group(1)
        sources["workgroup"] = match.group(1)
        break

    # --- storage -------------------------------------------------------- #
    raid = None
    for match in t.finditer(r"\braid[-\s]*(?:уровн[а-яё]*|level)?\s*(10|6|5|1|0)\b", re.I):
        raid = int(match.group(1))
    if raid is None and re.search(r"\braid\b", text, re.I):
        for match in t.finditer(r"(?:уровень|level)\s*(10|6|5|1|0)\b", re.I):
            raid = int(match.group(1))
    if raid is not None and raid not in RAID_MIN:
        warnings.append(f"Уровень RAID {raid} не поддерживается — использую значение по умолчанию.")
        raid = None

    disks = None
    for match in t.finditer(
        r"(\d{1,2}|два|две|двух|три|трёх|трех|четыре|четырёх|четырех|пять|пяти|шесть|шести)"
        r"\s*(?:диск[а-яё]*|hdd|ssd|накопител[а-яё]*)",
        re.I,
    ):
        token = match.group(1).lower()
        disks = DISK_WORDS.get(token) or int(token)
    if raid is not None and disks is not None and disks < RAID_MIN[raid]:
        disks = RAID_MIN[raid]
        warnings.append(f"Для RAID {raid} нужно минимум {disks} диска — подставил {disks}.")

    mount = None
    for match in t.finditer(
        r"(?:монтир[а-яё]*|mount|точк[а-яё]*\s+монтирования|каталог[а-яё]*)"
        r"[^\n/]{0,60}(/[A-Za-z0-9_./-]+)",
        re.I,
    ):
        path = match.group(1).rstrip(".,;:)")
        if not path.startswith("/dev"):
            mount = path
    if not mount:
        for match in t.finditer(r"(?<![\w/])(/raid\d+)\b", re.I):
            mount = match.group(1)

    md = None
    for match in t.finditer(r"(/dev/md\d+)\b", re.I):
        md = match.group(1)
    if md:
        override.setdefault("storage", {})["md"] = md
        sources["storage.md"] = md

    storage: dict = {}
    if raid is not None:
        storage["raid_level"] = raid
        sources["storage.raid_level"] = raid
    if disks is not None:
        storage["disks"] = disks
        sources["storage.disks"] = disks
    if mount:
        storage["mount"] = mount
        sources["storage.mount"] = mount
    if storage:
        override.setdefault("storage", {}).update(storage)

    # --- nfs / ntp / docker --------------------------------------------- #
    for match in t.finditer(r"\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b"):
        override["nfs"] = {"clients": match.group(1)}
        sources["nfs.clients"] = match.group(1)

    # "сервер времени 10.0.0.1", "NTP-сервер 10.0.0.1", "chrony 10.0.0.1"
    for match in t.finditer(
        rf"\b(?:сервер[а-яё]*\s+времени|ntp|chrony)\b[^\n\d]{{0,40}}{IP}", re.I
    ):
        server = match.group(1)
        if _valid_ip(server):
            override.setdefault("ntp", {})["server"] = server
            sources["ntp.server"] = server

    for match in t.finditer(r"(?:страт[а-яё]*|stratum)\s*[:\-–—]?\s*(\d+)", re.I):
        override.setdefault("ntp", {})["stratum"] = int(match.group(1))
        sources["ntp.stratum"] = int(match.group(1))

    # "порт 9090", "порт приложения 9090", "порт веб 9090"
    for match in t.finditer(r"\b(?:порт|port)\b[^\n\d]{0,30}(\d{1,5})\b", re.I):
        port = int(match.group(1))
        if 1 <= port <= 65535:
            override.setdefault("docker", {})["port"] = port
            sources["docker.port"] = port

    # --- module list ---------------------------------------------------- #
    modules = list(DEFAULTS["modules"])
    modules_changed = False
    for match in t.finditer(r"(?:без|кроме)\s+(?:модул[а-яё]*|modules?)\s*([\d,\sи]+)", re.I):
        removed = {int(x) for x in re.findall(r"\d+", match.group(1))}
        modules = [m for m in modules if m not in removed]
        modules_changed = True
    for match in t.finditer(r"только\s+модул[а-яё]*\s*[:\-–—]?\s*([\d,\sи]+)", re.I):
        numbers = sorted({int(x) for x in re.findall(r"\d+", match.group(1)) if int(x) > 0})
        if numbers:
            modules = numbers
            modules_changed = True
    if modules_changed:
        override["modules"] = modules
        sources["modules"] = modules

    # --- second pass: model fills only what the parser missed ----------- #
    model_override: dict = {}
    if text and not settings.mock_llm:
        try:
            raw = llm.extract_variant(text)
            if raw:
                model_override, model_origins, model_warnings = _validate_model_variant(
                    raw, set(sources)
                )
                origins.update(model_origins)
                for key in model_origins:
                    if key not in sources:
                        value = _dig_variant(model_override, key.split("."))
                        if value is not None:
                            sources[key] = value
                warnings.extend(model_warnings)
                if model_origins:
                    log.info("model filled intake gaps: %s", sorted(model_origins))
        except Exception:  # noqa: BLE001 - the deterministic result must survive
            log.exception("variant extractor failed; keeping deterministic result")

    # --- merge ---------------------------------------------------------- #
    combined = deep_merge(model_override, override)  # deterministic wins
    merged = deep_merge(_strip_derived(base), combined)
    try:
        variant = normalize(merged)
    except ValueError as exc:
        warnings.append(f"Параметры дисков не подошли ({exc}) — использую значения по умолчанию.")
        combined.pop("storage", None)
        merged = deep_merge(_strip_derived(base), combined)
        try:
            variant = normalize(merged)
        except ValueError:
            variant = normalize({})
            warnings.append("Собрать вариант не удалось — взяты значения по умолчанию.")

    if not sources and not skipped:
        warnings.append("Параметры в тексте не распознаны — используются значения по умолчанию.")

    # --- lines that were not understood --------------------------------- #
    unknown: list[str] = []
    for index, line in enumerate(t.lines):
        stripped = line.strip()
        if index in t.hits or len(stripped) < 4:
            continue
        if stripped.endswith(":") and len(stripped) < 40:
            continue
        if stripped.lower() in {"задание", "вариант", "исходные данные"}:
            continue
        unknown.append(stripped[:300])
        if len(unknown) >= 30:
            break

    entries = source_entries(sources, origins)
    return {
        "variant": variant,
        "sources": add_method_sources(entries, variant),
        "unknown": unknown,
        "warnings": warnings,
    }
