"""Validate module templates and compile them for every RAID variant.

Run:  python tools/validate_modules.py
Missing modules are warnings, broken ones are errors.
Exit code 0 = ok, 1 = errors.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.compiler import compile_plan, load_modules, unresolved  # noqa: E402

MODULES_DIR = ROOT / "content" / "modules"
INDEX = json.loads((MODULES_DIR / "_index.json").read_text(encoding="utf-8"))

REQUIRED = ("id", "title", "action")

ALLOWED_KEYS = {
    "id", "title", "action", "command", "gui", "check",
    "pitfalls", "image", "requires", "exclude", "note",
}


def main():
    errors = []
    warnings = []
    modules = load_modules(MODULES_DIR)
    expected = {int(k): v for k, v in INDEX["files"].items()}

    for number, filename in expected.items():
        path = MODULES_DIR / filename
        if number not in modules:
            warnings.append(f"module {number}: not written yet ({filename})")
            continue
        module = modules[number]
        if int(module.get("module", -1)) != number:
            errors.append(f"{filename}: module number {module.get('module')} != {number}")
        if not module.get("title"):
            errors.append(f"{filename}: missing title")
        steps = module.get("steps", [])
        if not steps:
            errors.append(f"{filename}: no steps")
        ids = [s.get("id") for s in steps]
        if len(ids) != len(set(ids)):
            errors.append(f"{filename}: duplicate step ids")
        for step in steps:
            sid = step.get("id", "?")
            for key in REQUIRED:
                if not step.get(key):
                    errors.append(f"{filename} {sid}: missing '{key}'")
            if not str(sid).startswith(f"{number}."):
                errors.append(f"{filename} {sid}: id must start with '{number}.'")
            if step.get("command") and step.get("gui"):
                errors.append(f"{filename} {sid}: use command OR gui, not both")
            if not step.get("command") and not step.get("gui"):
                errors.append(f"{filename} {sid}: needs command or gui")
            extra = set(step) - ALLOWED_KEYS
            if extra:
                errors.append(f"{filename} {sid}: unknown keys {sorted(extra)}")
            if step.get("pitfalls") and len(step["pitfalls"]) > 2:
                errors.append(f"{filename} {sid}: max 2 pitfalls")

    if errors:
        print("\n".join(errors))
        return 1

    base = {}
    for level in (0, 1, 5, 10):
        plan, _ = compile_plan({"storage": {"raid_level": level}}, modules)
        bad = unresolved(plan)
        if bad:
            errors.append(f"RAID {level}: unresolved placeholders in {bad}")
        print(f"RAID {level}: {len(plan)} steps")

    for warning in warnings:
        print("WARN:", warning)
    if errors:
        print("\n".join(errors))
        return 1
    plan, _ = compile_plan({}, modules)
    print(f"OK: {len(plan)} steps, {len(modules)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
