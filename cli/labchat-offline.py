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


FIELDS = [
    ("domain", "Домен", "str"),
    ("workgroup", "Рабочая группа", "str"),
    ("admin_password", "Пароль администратора", "str"),
    ("storage.raid_level", "Уровень RAID", "int"),
    ("storage.disks", "Дисков в массиве", "int"),
    ("storage.mount", "Точка монтирования", "str"),
    ("hosts.hq-srv", "HQ-SRV", "str"),
    ("hosts.hq-cli", "HQ-CLI", "str"),
    ("hosts.hq-rtr", "HQ-RTR", "str"),
    ("hosts.br-srv", "BR-SRV", "str"),
    ("nfs.clients", "NFS-клиенты", "str"),
    ("ntp.server", "Сервер времени", "str"),
    ("docker.port", "Порт приложения", "int"),
]


def get_path(data, path):
    node = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def set_path(data, path, value):
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def default_values(params):
    base = params.DEFAULTS
    raid = int(base["storage"]["raid_level"])
    return {
        "domain": base["domain"],
        "workgroup": base["workgroup"],
        "admin_password": base["admin_password"],
        "storage.raid_level": raid,
        "storage.disks": params.RAID_MIN.get(raid, 2),
        "storage.mount": "/raid%s" % raid,
        "hosts.hq-srv": base["hosts"]["hq-srv"],
        "hosts.hq-cli": base["hosts"]["hq-cli"],
        "hosts.hq-rtr": base["hosts"]["hq-rtr"],
        "hosts.br-srv": base["hosts"]["br-srv"],
        "nfs.clients": base["nfs"]["clients"],
        "ntp.server": base["hosts"]["isp"],
        "docker.port": base["docker"]["port"],
    }


def apply_parsed(values, parsed):
    variant = (parsed or {}).get("variant") or {}
    for key, _label, _kind in FIELDS:
        value = get_path(variant, key)
        if value not in (None, ""):
            values[key] = value
    return values


def validate_values(params, values):
    try:
        raid = int(values["storage.raid_level"])
        disks = int(values["storage.disks"])
        port = int(values["docker.port"])
    except (TypeError, ValueError):
        return "в числовых полях должны быть числа"
    if raid not in params.RAID_MIN:
        allowed = ", ".join(str(item) for item in sorted(params.RAID_MIN))
        return "RAID %s не поддерживается, доступны: %s" % (raid, allowed)
    minimum = params.RAID_MIN[raid]
    if disks < minimum:
        return "для RAID %s нужно минимум %s %s" % (
            raid, minimum, plural(minimum, "диск", "диска", "дисков"))
    if disks > 5:
        return "в пуле 5 дисков, больше не собрать"
    if not str(values["storage.mount"]).startswith("/"):
        return "точка монтирования должна начинаться с /"
    if not 1 <= port <= 65535:
        return "порт вне диапазона 1..65535"
    return None


def print_table(values):
    print()
    print(rule())
    print(Color.wrap(BOLD, "Параметры задания"))
    for index, (key, label, _kind) in enumerate(FIELDS, 1):
        print("  %2d) %-24s %s" % (index, label, values[key]))
    print(rule())
    print(Color.wrap(DIM, "Enter — принять. Номер строки — изменить. «сброс» — значения методички."))


def edit_table(params, values):
    manual = set()
    while True:
        print_table(values)
        answer = ask("Номер строки: ").strip().lower()
        if answer in ("/quit", "/exit", "/q"):
            print()
            raise SystemExit(0)
        if not answer:
            break
        if answer in ("сброс", "reset"):
            values = default_values(params)
            manual.clear()
            continue
        if not answer.isdigit():
            continue
        number = int(answer)
        if not 1 <= number <= len(FIELDS):
            continue
        key, label, kind = FIELDS[number - 1]
        raw = ask("%s [%s]: " % (label, values[key])).strip()
        if not raw:
            continue
        if kind == "int":
            try:
                raw = int(raw)
            except ValueError:
                print(Color.wrap(RED, "Нужно число."))
                continue
        values[key] = raw
        manual.add(key)
        if key == "storage.raid_level":
            raid = int(raw)
            if "storage.disks" not in manual:
                values["storage.disks"] = params.RAID_MIN.get(raid, 2)
            if "storage.mount" not in manual:
                values["storage.mount"] = "/raid%s" % raid
    return values


def variant_from_values(values):
    variant = {}
    for key, _label, _kind in FIELDS:
        set_path(variant, key, values[key])
    return variant


def collect_variant(params, intake, args):
    print("Если есть текст задания, вставь одной строкой. Enter — заполним таблицу вручную.")
    text = ask("> ").strip()
    if text.lower() in ("/quit", "/exit", "/q"):
        print()
        raise SystemExit(0)
    parsed = intake.parse_assignment(text) if text else {}
    values = apply_parsed(default_values(params), parsed)
    if args.raid is not None:
        values["storage.raid_level"] = args.raid
        if not args.disks:
            values["storage.disks"] = params.RAID_MIN.get(args.raid, 2)
        if not args.mount:
            values["storage.mount"] = "/raid%s" % args.raid
    if args.disks:
        values["storage.disks"] = args.disks
    if args.mount:
        values["storage.mount"] = args.mount
    if args.domain:
        values["domain"] = args.domain

    while True:
        values = edit_table(params, values)
        problem = validate_values(params, values)
        if not problem:
            return variant_from_values(values)
        print(Color.wrap(RED, problem))


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

    variant = collect_variant(params, intake, args)
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
            variant = collect_variant(params, intake, args)
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
