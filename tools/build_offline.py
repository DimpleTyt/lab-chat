"""Build the single-file offline client.

Packs the step templates plus the assignment parser and the plan compiler into
cli/labchat-offline.py, then self-tests it against the online compiler.
"""
import base64
import json
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.compiler import compile_plan, load_modules  # noqa: E402

TEMPLATE = ROOT / "cli" / "_offline_template.py"
OUTPUT = ROOT / "cli" / "labchat-offline.py"

SOURCES = {
    "params": ROOT / "shared" / "params.py",
    "compiler": ROOT / "shared" / "compiler.py",
    "intake": ROOT / "app" / "intake.py",
}


def main():
    modules = load_modules(ROOT / "content" / "modules")
    if not modules:
        print("no modules, nothing to pack")
        return 1

    bundle = {
        "src": {name: path.read_text(encoding="utf-8") for name, path in SOURCES.items()},
        "modules": {str(number): module for number, module in sorted(modules.items())},
    }
    raw = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    blob = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")

    template = TEMPLATE.read_text(encoding="utf-8")
    if "__BUNDLE__" not in template:
        print("template has no __BUNDLE__ placeholder")
        return 1
    OUTPUT.write_text(template.replace("__BUNDLE__", blob), encoding="utf-8")
    print("built:", OUTPUT, "size:", OUTPUT.stat().st_size, "bytes")

    result = subprocess.run(
        [sys.executable, str(OUTPUT), "--selftest"],
        capture_output=True, text=True, encoding="utf-8",
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr[-1000:])
        return 1

    # Cross-check against the online compiler.
    ok = True
    for level in (0, 1, 5, 10):
        plan, _ = compile_plan({"storage": {"raid_level": level}}, modules)
        expected = next(
            (step["command"] for step in plan if (step.get("command") or "").startswith("mdadm --create")),
            None,
        )
        if not expected or expected not in result.stdout:
            print("MISMATCH for RAID", level, "->", expected)
            ok = False
    print("cross-check:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
