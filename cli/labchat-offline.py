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

BUNDLE = "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"

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
