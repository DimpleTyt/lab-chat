#!/usr/bin/env python3
"""lab-chat offline - the same steps, no network, no model.

Everything (step templates, assignment parser, plan compiler) is packed into
this single file. Works on a stock python3 in an isolated lab network.
"""
import argparse
import base64
import json
import os
import sys
import types
import zlib

BUNDLE = "__BUNDLE__"

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class Color:
    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def wrap(cls, code, text):
        return text if not cls.enabled else code + text + RESET


def enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
    except Exception:  # noqa: BLE001
        pass


def bootstrap():
    data = json.loads(zlib.decompress(base64.b64decode(BUNDLE)).decode("utf-8"))
    src = data["src"]
    for name in ("shared", "app"):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package

    params = types.ModuleType("shared.params")
    params.__package__ = "shared"
    exec(compile(src["params"], "shared/params.py", "exec"), params.__dict__)
    sys.modules["shared.params"] = params

    compiler = types.ModuleType("shared.compiler")
    compiler.__package__ = "shared"
    exec(compile(src["compiler"], "shared/compiler.py", "exec"), compiler.__dict__)
    sys.modules["shared.compiler"] = compiler

    config = types.ModuleType("app.config")
    config.settings = types.SimpleNamespace(mock_llm=True)
    sys.modules["app.config"] = config

    llm = types.ModuleType("app.llm")
    llm.extract_variant = lambda text: None
    sys.modules["app.llm"] = llm

    intake = types.ModuleType("app.intake")
    intake.__package__ = "app"
    exec(compile(src["intake"], "app/intake.py", "exec"), intake.__dict__)
    sys.modules["app.intake"] = intake

    modules = {int(key): value for key, value in data["modules"].items()}
    return params, compiler, intake, modules, data


def rule():
    return Color.wrap(DIM, "-" * 62)


def print_step(step):
    print()
    print(rule())
    print(Color.wrap(BOLD, "Шаг %s/%s · Модуль %s: %s" % (
        step.get("num"), step.get("total"), step.get("module"), step.get("module_title") or "")))
    print()
    print(Color.wrap(BOLD, "Что делать:") + " " + (step.get("action") or ""))
    if step.get("gui"):
        print()
        print(Color.wrap(BOLD, "Куда нажать:") + " " + step["gui"])
    if step.get("command"):
        print()
        for line in step["command"].splitlines():
            print("    " + Color.wrap(CYAN, line))
    if step.get("check"):
        print()
        print(Color.wrap(BOLD, "Готово, если:") + " " + step["check"])
    pitfalls = step.get("pitfalls") or []
    if pitfalls:
        print()
        print(Color.wrap(YELLOW, "Важно: ") + "; ".join(pitfalls))
    print(rule())


def print_progress(progress):
    idx = progress.get("idx") or 0
    total = progress.get("total") or 0
    if not total:
        return
    filled = int(round(20 * idx / total))
    print(Color.wrap(DIM, "[%s] %s/%s" % ("#" * filled + "." * (20 - filled), idx, total)))


def print_card(data):
    sources = data.get("sources") or []
    exam = [item for item in sources if item.get("source") != "method"]
    method = [item for item in sources if item.get("source") == "method"]

    def show(title, items):
        if not items:
            return
        print()
        print(Color.wrap(BOLD, title))
        for item in items:
            print("  %-22s %s" % ((item.get("label") or item.get("key")) + ":", item.get("value")))

    print()
    print(rule())
    show("ИЗ ЗАДАНИЯ", exam)
    show("ИЗ МЕТОДИЧКИ", method)
    for warning in data.get("warnings") or []:
        print(Color.wrap(YELLOW, "Внимание: ") + warning)
    if data.get("unknown"):
        print(Color.wrap(YELLOW, "Не распознано: ") + ", ".join(map(str, data["unknown"])))
    print(rule())


def plural(count, one, few, many):
    number = abs(int(count)) % 100
    if 11 <= number <= 14:
        return many
    last = number % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def print_plan(plan, variant):
    total = len(plan)
    modules = []
    for step in plan:
        if not modules or modules[-1] != step["module"]:
            modules.append(step["module"])
    print()
    print(Color.wrap(BOLD, "План готов: %s %s, %s %s." % (
        total, plural(total, "шаг", "шага", "шагов"),
        len(modules), plural(len(modules), "модуль", "модуля", "модулей"))))
    disks = variant["storage"]["disks"]
    print(Color.wrap(DIM, "RAID %s · %s %s · %s" % (
        variant["storage"]["raid_level"],
        disks, plural(disks, "диск", "диска", "дисков"),
        variant["storage"]["mount"])))
    print(Color.wrap(DIM, "Офлайн-режим: вопросов к модели нет, только шаги."))


HELP = """
Enter        следующий шаг
текст        подсказка по текущему шагу
/step N      перейти к шагу N (или к id вида 2.3)
/restart     начать заново
/variant     изменить задание
/repeat      повторить текущий шаг
/copy        показать команду текущего шага отдельно
/hint        подсказка по текущему шагу
/quit        закрыть программу
""".strip()

ERROR_MARKERS = (
    "ошибк", "error", "не работает", "не получается", "не выходит", "fail",
    "denied", "not found", "no such", "no devices", "command not found",
    "unable", "fatal", "unknown", "не найдено", "занят", "busy", "cannot",
    "missing", "invalid", "not available",
)


def local_hint(text, step):
    low = (text or "").lower()
    if not step:
        print("Сначала начни план: /variant.")
        return
    looks_like_error = any(marker in low for marker in ERROR_MARKERS)
    if looks_like_error:
        print(Color.wrap(BOLD, "Разбор ошибки (офлайн):"))
        pitfalls = step.get("pitfalls") or []
        if pitfalls:
            print("  Проверь в первую очередь:")
            for item in pitfalls:
                print("   - " + item)
        else:
            print("  Частые причины: опечатка в имени устройства, команда не от root,")
            print("  другой дистрибутив или сервис называется иначе.")
        if step.get("check"):
            print("  Признак успеха: " + step["check"])
        if step.get("command"):
            print("  Повтори команду: " + step["command"])
        print(Color.wrap(DIM, "  Модель в офлайне недоступна, поэтому ответ по методичке."))
        return

    print(Color.wrap(BOLD, "Сейчас шаг %s/%s: " % (step["num"], step["total"])) + (step.get("action") or ""))
    if step.get("gui"):
        print("Куда нажать: " + step["gui"])
    if step.get("check"):
        print("Готово, если: " + step["check"])
    print(Color.wrap(DIM, "Офлайн-режим: только шаги и подсказки из методички."))


def build_variant(parser, args, text):
    """Parse the assignment, then apply explicit command line overrides."""
    data = parser.parse_assignment(text or "")
    variant = data.get("variant") or {}
    storage = variant.setdefault("storage", {})
    if args.raid:
        storage["raid_level"] = args.raid
        storage.pop("disks", None)
        storage.pop("devices", None)
        storage.pop("devices_str", None)
    if args.disks:
        storage["disks"] = args.disks
    if args.mount:
        storage["mount"] = args.mount
    if args.domain:
        variant["domain"] = args.domain
    return data, variant


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return "/quit"


def render_plan(compiler, params, variant, modules):
    plan, normalized = compiler.compile_plan(variant, modules)
    for step in plan:
        step["markdown"] = ""
    return plan, normalized


def main():
    parser = argparse.ArgumentParser(description="lab-chat офлайн: шаги без сети")
    parser.add_argument("--raid", type=int, help="уровень RAID, например 10")
    parser.add_argument("--disks", type=int, help="сколько дисков")
    parser.add_argument("--mount", help="точка монтирования, например /raid10")
    parser.add_argument("--domain", help="домен, например au-team.irpo")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.no_color or args.selftest:
        Color.enabled = False
    else:
        enable_windows_ansi()

    params, compiler, intake, modules, bundle = bootstrap()

    if args.selftest:
        ok = True
        for level in (0, 1, 5, 10):
            variant = {"storage": {"raid_level": level}}
            plan, normalized = compiler.compile_plan(variant, modules)
            raid_steps = [s for s in plan if (s.get("command") or "").startswith("mdadm --create")]
            command = raid_steps[0]["command"] if raid_steps else "-"
            print("RAID %s: %s steps | %s" % (level, len(plan), command))
            if "-l %s" % level not in command:
                ok = False
        print("modules:", sorted(modules))
        print("self-test:", "OK" if ok else "FAIL")
        return 0 if ok else 1

    print(Color.wrap(BOLD, "lab-chat") + Color.wrap(DIM, " · офлайн, без сети"))
    print("Вставь задание одной строкой, Enter в конце. Пусто — пойдём по методичке.")

    text = ask("> ").strip()
    data, variant = build_variant(intake, args, text)
    while True:
        print_card(data)
        answer = ask("Всё верно? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes", "д", "да"):
            break
        text = ask("Задание: ").strip()
        data, variant = build_variant(intake, args, text)

    plan, normalized = render_plan(compiler, params, variant, modules)
    progress = {"idx": 1, "total": len(plan)}
    current = 0
    print_plan(plan, normalized)
    print_step(plan[current])
    print_progress(progress)
    print(Color.wrap(DIM, "/help — команды"))

    while True:
        raw = ask(Color.wrap(DIM, "\n> "))
        text = raw.strip()

        if text in ("/quit", "/exit", "/q"):
            return 0
        if text in ("/help", "?"):
            print(HELP)
            continue
        if text == "/repeat":
            print_step(plan[current])
            continue
        if text == "/copy":
            if plan[current].get("command"):
                print(plan[current]["command"])
            else:
                print(Color.wrap(DIM, "На этом шаге нет команды."))
            continue
        if text == "/hint":
            local_hint(text, plan[current])
            continue
        if text == "/restart":
            current = 0
            progress["idx"] = 1
            print_step(plan[current])
            print_progress(progress)
            continue
        if text == "/variant":
            text = ask("Задание: ").strip()
            data, variant = build_variant(intake, args, text)
            print_card(data)
            if ask("Всё верно? [Y/n] ").strip().lower() in ("", "y", "yes", "д", "да"):
                plan, normalized = render_plan(compiler, params, variant, modules)
                current = 0
                progress = {"idx": 1, "total": len(plan)}
                print_plan(plan, normalized)
                print_step(plan[current])
                print_progress(progress)
            continue
        if text.startswith("/step"):
            target = text[5:].strip()
            index = -1
            for position, step in enumerate(plan):
                if str(step.get("id")) == target:
                    index = position
                    break
            if index < 0:
                try:
                    number = int(target)
                    if 1 <= number <= len(plan):
                        index = number - 1
                except ValueError:
                    index = -1
            if index < 0:
                print(Color.wrap(RED, "Нет такого шага. Всего: %s" % len(plan)))
            else:
                current = index
                progress["idx"] = current + 1
                print_step(plan[current])
                print_progress(progress)
            continue

        if text == "":
            if current + 1 >= len(plan):
                print(Color.wrap(YELLOW, "Это последний шаг, дальше некуда."))
                continue
            current += 1
            progress["idx"] = current + 1
            print_step(plan[current])
            print_progress(progress)
            continue

        local_hint(text, plan[current])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(0)
