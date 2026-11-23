"""Compile per-user plan from module templates + variant."""
import json
from pathlib import Path

from .params import flatten, matches, normalize, render_obj

RENDER_KEYS = ("title", "action", "command", "gui", "check", "pitfalls", "note")


def load_modules(modules_dir):
    """Load content/modules/m*.json into {module_number: module_dict}."""
    modules = {}
    for path in sorted(Path(modules_dir).glob("m*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        modules[int(data["module"])] = data
    return modules


def compile_plan(variant, modules):
    """Return (plan, normalized_variant). Plan is a flat list of rendered steps."""
    v = normalize(variant)
    flat = flatten(v)
    plan = []

    for number in v["modules"]:
        module = modules.get(int(number))
        if not module:
            continue
        for raw in module.get("steps", []):
            if not matches(raw.get("requires"), flat):
                continue
            if raw.get("exclude") and matches(raw["exclude"], flat):
                continue
            step = {k: raw.get(k) for k in ("id", "requires", "exclude")}
            for key in RENDER_KEYS:
                step[key] = render_obj(raw.get(key), flat)
            step["module"] = int(number)
            step["module_title"] = module.get("title", "")
            plan.append(step)

    total = len(plan)
    for index, step in enumerate(plan, start=1):
        step["num"] = index
        step["total"] = total
    return plan, v


def unresolved(plan):
    """Steps that still contain a {{placeholder}} after rendering."""
    bad = []
    for step in plan:
        blob = json.dumps(step, ensure_ascii=False)
        if "{{" in blob:
            bad.append(step.get("id"))
    return bad
