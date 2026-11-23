"""Wrappers around shared.compiler used by the HTTP layer."""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path

from shared.compiler import compile_plan, load_modules, unresolved
from shared.params import RAID_MIN
from shared.render import step_brief, step_markdown

from .config import ROOT

log = logging.getLogger(__name__)

MODULES_DIR = ROOT / "content" / "modules"


class CompileError(RuntimeError):
    pass


def load_content_modules() -> dict:
    """Load content/modules/m*.json, falling back to _fixture.json."""
    modules = load_modules(MODULES_DIR)
    if not modules:
        fixture = MODULES_DIR / "_fixture.json"
        if fixture.exists():
            data = json.loads(fixture.read_text(encoding="utf-8"))
            modules = {int(data["module"]): data}
            log.warning("no m*.json modules found, using %s", fixture.name)
    if not modules:
        log.error("no module templates in %s", MODULES_DIR)
    return modules


def sanitize_variant(variant: dict | None, preserve: set[str] | None = None) -> dict:
    """Drop derived/stale fields before normalize() recomputes them.

    The UI round-trips the normalized variant, so an edited raid_level can
    arrive together with the old mount. Derived fields must never win over
    what normalize() computes; a custom mount is kept unless it is clearly
    the auto-generated `/raidN` for a different level. Values the user edited
    by hand are passed in `preserve` and always survive.
    """
    preserve = preserve or set()
    clean = copy.deepcopy(variant or {})
    storage = clean.get("storage")
    if isinstance(storage, dict):
        for key in ("devices", "devices_str", "raid_name"):
            storage.pop(key, None)
        mount = storage.get("mount")
        level = storage.get("raid_level")
        match = re.fullmatch(r"/raid(10|6|5|1|0)", str(mount or ""))
        if (match and level is not None and str(level) != match.group(1)
                and "storage.mount" not in preserve):
            storage.pop("mount", None)

        # Contract §2: minimal disk count per RAID level.
        try:
            minimum = RAID_MIN.get(int(level))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            minimum = None
        disks = storage.get("disks")
        if minimum and disks is not None:
            try:
                if int(disks) < minimum:
                    log.warning("raid %s needs at least %s disks, got %s", level, minimum, disks)
                    storage["disks"] = minimum
            except (TypeError, ValueError):
                pass
    nfs = clean.get("nfs")
    if isinstance(nfs, dict):
        for key in ("server", "client_host"):
            nfs.pop(key, None)
    return clean


def compile_variant(variant: dict | None, preserve: set[str] | None = None) -> tuple[list[dict], dict]:
    """Return (plan, normalized_variant). Raises CompileError on bad input."""
    try:
        plan, normalized = compile_plan(
            sanitize_variant(variant, preserve), load_content_modules()
        )
    except Exception as exc:  # KeyError on unknown placeholder, ValueError on disks
        raise CompileError(str(exc)) from exc

    bad = unresolved(plan)
    if bad:
        log.warning("unresolved placeholders in steps: %s", bad)
    return plan, normalized


def step_payload(plan: list[dict], index: int) -> dict | None:
    if not plan or index < 1:
        return None
    index = min(index, len(plan))
    step = plan[index - 1]
    return {
        "num": step["num"],
        "total": step["total"],
        "id": step["id"],
        "module": step["module"],
        "module_title": step["module_title"],
        "markdown": step_markdown(step),
        "image": step.get("image"),
        # Extra fields, handy for the UI (copy button, check list).
        "title": step.get("title"),
        "action": step.get("action"),
        "command": step.get("command"),
        "gui": step.get("gui"),
        "check": step.get("check"),
        "pitfalls": step.get("pitfalls") or [],
    }


def step_context(plan: list[dict], index: int) -> str:
    if not plan or index < 1:
        return "План ещё не начат."
    return step_brief(plan[min(index, len(plan)) - 1])


def find_index(plan: list[dict], target) -> int | None:
    """Resolve 12 / "12" / "2.3" / "шаг 12" to a 1-based plan index."""
    if not plan or target is None or isinstance(target, bool):
        return None
    if isinstance(target, int):
        num = target
    else:
        text = str(target).strip()
        if not text:
            return None
        dot = text.replace(",", ".")
        if dot.count(".") == 1 and dot.split(".")[0].isdigit() and dot.split(".")[1].isdigit():
            for idx, step in enumerate(plan, start=1):
                if str(step.get("id")) == dot:
                    return idx
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        num = int(digits)
    if 1 <= num <= len(plan):
        return num
    return None


def plan_to_json(plan: list[dict]) -> str:
    return json.dumps(plan, ensure_ascii=False)


def plan_from_json(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("corrupted plan JSON in chats row")
        return []
    return data if isinstance(data, list) else []


def modules_dir() -> Path:
    return MODULES_DIR
