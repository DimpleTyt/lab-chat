#!/usr/bin/env python3
"""lab-chat CLI - walks the lab steps from a terminal.

No third-party packages: works on the python3 that ships with Astra Linux.
Talks to the same server as the web UI, so accounts, progress and the
one-hour session are shared.
"""
import argparse
import getpass
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_SERVER = os.environ.get("LABCHAT_SERVER", "https://exam.nothing-box.com")
SESSION_FILE = os.path.expanduser("~/.labchat/session.json")
TIMEOUT = 90
SSL_CONTEXT = None  # set by --insecure on old Astra installs

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


class Color:
    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def wrap(cls, code, text):
        if not cls.enabled:
            return text
        return code + text + RESET


def enable_windows_ansi():
    """Make cmd.exe and PowerShell understand ANSI colors."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
    except Exception:  # noqa: BLE001 - colors are cosmetic
        pass


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, server):
        self.server = server.rstrip("/")
        parsed = urlsplit(self.server)
        self.scheme = parsed.scheme or "https"
        self.host = parsed.hostname or ""
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.prefix = parsed.path.rstrip("/")
        self.conn = None
        self.sid = None
        self.user = None

    # -- connection --------------------------------------------------------
    def _connect(self):
        if self.conn is None:
            if self.scheme == "https":
                self.conn = http.client.HTTPSConnection(
                    self.host, self.port, timeout=TIMEOUT, context=SSL_CONTEXT
                )
            else:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT)
        return self.conn

    def _drop(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None

    def _headers(self, extra=None):
        headers = {"Accept": "application/json"}
        if self.sid:
            headers["Cookie"] = "sid=" + self.sid
        if extra:
            headers.update(extra)
        return headers

    def _error(self, status, text):
        message = text
        try:
            payload = json.loads(text)
        except ValueError:
            return ApiError(status, message)
        detail = payload.get("detail")
        if isinstance(detail, dict):
            message = detail.get("message") or message
        else:
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = error["message"]
        return ApiError(status, message)

    # -- low level ---------------------------------------------------------
    def _json(self, path, payload=None, method=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        extra = {"Content-Type": "application/json; charset=utf-8"} if body is not None else {}
        for attempt in (1, 2):
            try:
                conn = self._connect()
                conn.request(
                    method or "GET", self.prefix + path, body=body, headers=self._headers(extra)
                )
                response = conn.getresponse()
                raw = response.read()
                self._remember_cookie(response)
                if response.will_close:
                    self._drop()
                text = raw.decode("utf-8", "replace")
                if response.status >= 400:
                    raise self._error(response.status, text)
                return json.loads(text) if text.strip() else {}
            except (http.client.HTTPException, OSError) as exc:
                self._drop()
                if attempt == 1:
                    continue
                raise ApiError(0, "нет связи с сервером: %s" % exc)
        return {}

    def _remember_cookie(self, response):
        cookie = response.getheader("Set-Cookie") or ""
        match = re.search(r"sid=([^;]+)", cookie)
        if match:
            self.sid = match.group(1)
            save_session(self.server, self.sid)
        elif "sid=;" in cookie:
            self.sid = None

    # -- api ---------------------------------------------------------------
    def login(self, username, password):
        data = self._json("/api/login", {"username": username, "password": password}, "POST")
        self.user = data.get("user") or {"username": username}
        return self.user

    def logout(self):
        try:
            self._json("/api/logout", {}, "POST")
        except ApiError:
            pass
        self.sid = None
        save_session(self.server, None)

    def state(self):
        return self._json("/api/state")

    def intake(self, text):
        return self._json("/api/intake", {"text": text}, "POST")

    def confirm(self, variant):
        return self._json("/api/intake/confirm", {"variant": variant}, "POST")

    def next_step(self):
        return self._json("/api/next", {"client_msg_id": "%d" % time.time_ns()}, "POST")

    def jump(self, target):
        return self._json("/api/jump", {"to": target}, "POST")

    def restart(self):
        return self._json("/api/restart", {}, "POST")

    def chat(self, text, on_delta):
        payload = {"text": text, "client_msg_id": "%d" % time.time_ns()}
        body = json.dumps(payload).encode("utf-8")
        extra = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
        }
        for attempt in (1, 2):
            try:
                conn = self._connect()
                conn.request(
                    "POST", self.prefix + "/api/chat", body=body, headers=self._headers(extra)
                )
                response = conn.getresponse()
                if response.status != 200:
                    raw = response.read().decode("utf-8", "replace")
                    self._drop()
                    raise self._error(response.status, raw)
                event = None
                result = {"intent": None, "step": None, "done": None}
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    event_payload = json.loads(line[5:].strip() or "{}")
                    if event == "meta":
                        result["intent"] = event_payload.get("intent")
                    elif event == "delta":
                        piece = event_payload.get("text") or ""
                        if piece:
                            on_delta(piece)
                    elif event == "step":
                        result["step"] = event_payload.get("step") or event_payload
                    elif event == "done":
                        result["done"] = event_payload
                if response.will_close:
                    self._drop()
                return result
            except (http.client.HTTPException, OSError) as exc:
                self._drop()
                if attempt == 1:
                    continue
                raise ApiError(0, "нет связи с сервером: %s" % exc)
        return {"intent": None, "step": None, "done": None}


# --------------------------------------------------------------------------- #
# Session file
# --------------------------------------------------------------------------- #
def save_session(server, sid):
    if not sid:
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass
        return
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as fh:
            json.dump({"server": server, "sid": sid}, fh)
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def load_session(server):
    try:
        with open(SESSION_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get("server") != server:
        return None
    return data.get("sid")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def rule():
    return Color.wrap(DIM, "-" * 62)


def print_step(step):
    num = step.get("num")
    total = step.get("total")
    module = step.get("module")
    title = step.get("module_title") or ""
    header = "Шаг %s/%s · Модуль %s: %s" % (num, total, module, title)
    print()
    print(rule())
    print(Color.wrap(BOLD, header))
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
    image = step.get("image")
    if image:
        print()
        print(Color.wrap(DIM, "Картинка: ") + step.get("_server", "") + "/" + image.lstrip("/"))
    print(rule())


def print_progress(progress):
    if not progress:
        return
    idx = progress.get("idx") or 0
    total = progress.get("total") or 0
    if total:
        filled = int(round(20 * idx / total))
        bar = "#" * filled + "." * (20 - filled)
        print(Color.wrap(DIM, "[%s] %s/%s" % (bar, idx, total)))


def print_card(data):
    variant = data.get("variant") or {}
    sources = data.get("sources") or []
    exam = [s for s in sources if s.get("source") != "method"]
    method = [s for s in sources if s.get("source") == "method"]

    def show(title, items):
        if not items:
            return
        print()
        print(Color.wrap(BOLD, title))
        for item in items:
            label = item.get("label") or item.get("key")
            print("  %-22s %s" % (label + ":", item.get("value")))

    print()
    print(rule())
    show("ИЗ ЗАДАНИЯ", exam)
    show("ИЗ МЕТОДИЧКИ", method)
    print()
    if data.get("unknown"):
        print(Color.wrap(YELLOW, "Не распознано: ") + ", ".join(map(str, data["unknown"])))
    for warning in data.get("warnings") or []:
        print(Color.wrap(YELLOW, "Внимание: ") + warning)
    print(rule())
    _ = variant


# --------------------------------------------------------------------------- #
# Interaction
# --------------------------------------------------------------------------- #
HELP = """
Enter        следующий шаг
текст        вопрос или описание ошибки
/step N      перейти к шагу N (или к id вида 2.3)
/restart     начать заново
/variant     изменить задание
/repeat      повторить текущий шаг
/copy        показать команду текущего шага отдельно
/logout      выйти
/quit        закрыть программу
""".strip()


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return "/quit"


def ensure_login(client, username=None, password=None):
    # Explicit credentials win over a saved session.
    sid = load_session(client.server) if not username else None
    if sid:
        client.sid = sid
        try:
            data = client.state()
            client.user = data.get("user")
            return data
        except ApiError as exc:
            if exc.status != 401:
                raise
            client.sid = None

    while True:
        user = username or ask("Логин: ")
        if not username:
            username = None
        secret = password or getpass.getpass("Пароль: ")
        try:
            client.login(user.strip(), secret)
            return client.state()
        except ApiError as exc:
            print(Color.wrap(RED, "Не получилось: ") + str(exc))
            if username and password:
                raise
            username = password = None


def run_intake(client):
    print()
    print("Вставь текст задания. Одна строка, Enter — по методичке.")
    text = ask("> ").strip()
    if text.lower() in ("/quit", "/exit", "/q"):
        print()
        raise SystemExit(0)
    if not text:
        text = "без задания"
        print(Color.wrap(DIM, "Идём по методичке."))

    while True:
        try:
            data = client.intake(text)
        except ApiError as exc:
            print(Color.wrap(RED, "Ошибка: ") + str(exc))
            return

        print_card(data)
        answer = ask("Всё верно? [Y/n] ").strip().lower()
        if answer in ("/quit", "/exit", "/q"):
            print()
            raise SystemExit(0)
        if answer in ("", "y", "yes", "д", "да"):
            try:
                result = client.confirm(data.get("variant") or {})
            except ApiError as exc:
                print(Color.wrap(RED, "Ошибка: ") + str(exc))
                return
            step = result.get("step")
            if step:
                step["_server"] = client.server
                print_step(step)
                print_progress(result.get("progress"))
            return
        text = ask("Задание: ").strip()
        if text.lower() in ("/quit", "/exit", "/q"):
            print()
            raise SystemExit(0)
        if not text:
            text = "без задания"
            print(Color.wrap(DIM, "Идём по методичке."))


def loop(client, state):
    phase = state.get("phase")
    if phase in ("intake", "confirm"):
        try:
            run_intake(client)
        except ApiError as exc:
            print(Color.wrap(RED, "Ошибка: ") + str(exc))
            return
        state = client.state()
    else:
        step = state.get("step")
        if step:
            step["_server"] = client.server
            print_step(step)
            print_progress(state.get("progress"))

    last_step = state.get("step")
    while True:
        raw = ask(Color.wrap(DIM, "\n> "))
        text = raw.strip()

        if text in ("/quit", "/exit", "/q"):
            return
        if text in ("/help", "?"):
            print(HELP)
            continue
        if text == "/repeat":
            if last_step:
                last_step["_server"] = client.server
                print_step(last_step)
            continue
        if text == "/copy":
            if last_step and last_step.get("command"):
                print(last_step["command"])
            else:
                print(Color.wrap(DIM, "На этом шаге нет команды."))
            continue
        if text == "/logout":
            client.logout()
            print("Вышел.")
            return
        if text == "/variant":
            run_intake(client)
            last_step = client.state().get("step")
            continue

        try:
            if text.startswith("/step"):
                target = text[5:].strip()
                data = client.jump(target)
                step = data.get("step")
                if step:
                    step["_server"] = client.server
                    last_step = step
                    print_step(step)
                    print_progress(data.get("progress"))
                continue

            if text == "/restart":
                data = client.restart()
                step = data.get("step")
                if step:
                    step["_server"] = client.server
                    last_step = step
                    print_step(step)
                    print_progress(data.get("progress"))
                continue

            if text == "":
                data = client.next_step()
                step = data.get("step")
                if step:
                    step["_server"] = client.server
                    last_step = step
                    print_step(step)
                    print_progress(data.get("progress"))
                continue

            # free text: question or error
            print()
            started = [False]

            def emit(piece):
                if sys.stdout.isatty() and not started[0]:
                    sys.stdout.write("\r" + " " * 12 + "\r")
                    started[0] = True
                sys.stdout.write(piece)
                sys.stdout.flush()

            if sys.stdout.isatty():
                sys.stdout.write(Color.wrap(DIM, "думаю…"))
                sys.stdout.flush()

            result = client.chat(text, emit)
            if sys.stdout.isatty() and not started[0]:
                sys.stdout.write("\r" + " " * 12 + "\r")
            print()
            step = result.get("step")
            if step:
                step["_server"] = client.server
                last_step = step
                print_step(step)
            progress = (result.get("done") or {}).get("progress")
            print_progress(progress)
        except ApiError as exc:
            if exc.status == 401:
                print(Color.wrap(YELLOW, "Сессия истекла, войди снова."))
                state = ensure_login(client)
                print(Color.wrap(DIM, "Продолжаем с сохранённого шага."))
                step = state.get("step")
                if step:
                    step["_server"] = client.server
                    last_step = step
                    print_step(step)
                continue
            print(Color.wrap(RED, "Ошибка: ") + str(exc))


def main():
    parser = argparse.ArgumentParser(description="lab-chat в терминале")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--user", default=os.environ.get("LABCHAT_USER"))
    parser.add_argument("--password", default=os.environ.get("LABCHAT_PASSWORD"))
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="не проверять TLS-сертификат")
    parser.add_argument("--logout-on-exit", action="store_true", help="выйти из аккаунта при закрытии")
    parser.add_argument("--keep-session", action="store_true", help="не выходить из аккаунта при закрытии")
    args = parser.parse_args()

    if args.no_color:
        Color.enabled = False
    else:
        enable_windows_ansi()

    if args.insecure:
        global SSL_CONTEXT
        SSL_CONTEXT = ssl.create_default_context()
        SSL_CONTEXT.check_hostname = False
        SSL_CONTEXT.verify_mode = ssl.CERT_NONE

    client = Client(args.server)
    try:
        state = ensure_login(client, args.user, args.password)
    except KeyboardInterrupt:
        print()
        return 0
    except EOFError:
        print()
        return 0
    except ApiError as exc:
        print(Color.wrap(RED, "Вход не удался: ") + str(exc))
        return 1

    name = (client.user or {}).get("display_name") or (client.user or {}).get("username")
    print(Color.wrap(BOLD, "lab-chat") + Color.wrap(DIM, " · " + args.server))
    print("Пользователь: %s   ·   /help — команды, /logout — сменить аккаунт" % name)
    logout_on_exit = (
        args.logout_on_exit
        or os.environ.get("LABCHAT_LOGOUT_ON_EXIT") == "1"
    ) and not args.keep_session

    try:
        loop(client, state)
    except KeyboardInterrupt:
        print()
    except ApiError as exc:
        print(Color.wrap(RED, "Ошибка: ") + str(exc))
    finally:
        if logout_on_exit:
            client.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
