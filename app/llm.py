"""DeepSeek client: intent classification and streamed answers.

No key -> deterministic mock mode, so the whole app and smoke test run offline.
`reasoning_content` is ignored everywhere and never leaves this module.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import httpx

from .config import settings

log = logging.getLogger(__name__)

INTENTS = {"question", "error", "jump", "restart", "advance", "off_topic", "edit_variant"}

PROMPT_PATH = Path(__file__).with_name("prompt_system.md")

CLASSIFY_SYSTEM = (
    "Ты классификатор сообщений в чате-инструкторе по лабораторной работе. "
    "Ответь строго JSON-объектом без пояснений: "
    '{"intent": "question|error|jump|restart|advance|off_topic|edit_variant", "target": "12" | "2.3" | null}. '
    "advance — пользователь готов идти дальше; jump — просит конкретный шаг; "
    "restart — начать заново; error — у него ошибка/не работает; "
    "off_topic — не про лабораторную; edit_variant — хочет изменить задание."
)

EXTRACT_SYSTEM = (
    "Ты извлекаешь параметры варианта лабораторной работы из текста задания. "
    "Верни строгий JSON-объект без markdown и пояснений. "
    "Включай только те поля, которые явно есть в тексте; отсутствующие не добавляй. "
    "Схема: "
    '{"domain": "строка", "workgroup": "строка", "admin_password": "строка", '
    '"hosts": {"hq-srv": "ip", "hq-cli": "ip", "hq-rtr": "ip", "br-srv": "ip", "isp": "ip"}, '
    '"storage": {"raid_level": 0, "disks": 3, "mount": "/raid5", "md": "/dev/md0"}, '
    '"nfs": {"clients": "192.168.0.64/28"}, '
    '"ntp": {"server": "ip", "stratum": 5}, '
    '"docker": {"port": 8080}, "modules": [1, 2, 3]}. '
    "raid_level только 0, 1, 5 или 10. disks — целое 2..6. mount начинается с /. port 1..65535."
)

ADVANCE_WORDS = {
    "дальше", "далее", "next", "готово", "ок", "ok", "да", "д", "продолжай",
    "продолжить", "сделал", "сделано", "выполнил", "выполнено", "done",
}
RESTART_MARKERS = ("заново", "с начала", "сначала", "restart", "начать сначала", "по новой")


# --------------------------------------------------------------------------- #
# Deterministic routing (runs before any model call)
# --------------------------------------------------------------------------- #
def route(text: str) -> dict | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    short = re.sub(r"[.!?…]+$", "", raw).strip()

    if short in ADVANCE_WORDS:
        return {"intent": "advance", "target": None}

    if any(marker in raw for marker in RESTART_MARKERS):
        return {"intent": "restart", "target": None}

    match = re.search(r"(?:шаг[а-яё]*|step)\s*#?\s*(\d+(?:\.\d+)?)", raw)
    if match:
        return {"intent": "jump", "target": match.group(1)}

    match = re.search(r"(?<![\d.])(\d+\.\d+)(?![\d.])", raw)
    if match:
        return {"intent": "jump", "target": match.group(1)}

    return None


def _keyword_intent(text: str) -> dict:
    found = route(text)
    if found:
        return found
    low = (text or "").lower()
    if re.search(r"ошибк|не работает|не получается|не выходит|failed|error|denied|not found|exception|fatal", low):
        return {"intent": "error", "target": None}
    if re.search(r"измени|поменяй|исправь задание|другое задание|редактир|edit variant", low):
        return {"intent": "edit_variant", "target": None}
    if re.search(r"\bпривет\b|\bспасибо\b|кто ты|погода|анекдот|\bhello\b|\bhi\b", low):
        return {"intent": "off_topic", "target": None}
    return {"intent": "question", "target": None}


def _normalize_decision(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    intent = str(data.get("intent") or "").strip()
    if intent not in INTENTS:
        return None
    target = data.get("target")
    if target in ("", "null"):
        target = None
    return {"intent": intent, "target": target}


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #
def _thinking() -> dict:
    """DeepSeek V4 reasons by default and eats max_tokens. Short answers don't need it."""
    if settings.thinking:
        return {}
    return {"thinking": {"type": "disabled"}}


def _url() -> str:    return settings.deepseek_base_url + "/chat/completions"


def _headers() -> dict:
    return {
        "Authorization": "Bearer " + settings.deepseek_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(60.0, connect=10.0)


def _should_retry(status: int) -> bool:
    return status == 429 or status >= 500


def _post_json(payload: dict) -> dict | None:
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(_url(), json=payload, headers=_headers())
            if _should_retry(response.status_code):
                log.warning("deepseek http %s (attempt %s)", response.status_code, attempt)
                if attempt == 1:
                    continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if _should_retry(status) and attempt == 1:
                continue
            log.error("deepseek request failed: %s", exc)
            return None
        except (httpx.HTTPError, ValueError) as exc:
            log.error("deepseek request failed: %s", exc)
            if attempt == 1:
                continue
            return None
    return None


@lru_cache(maxsize=1)
def system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        log.warning("prompt_system.md not found, using a short fallback")
        return (
            "Ты инструктор по лабораторной. Отвечай по-русски, максимум 4 строки, "
            "только про текущий шаг, команды дословно, без приветствий."
        )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def model_for(intent: str | None = None) -> str:
    if settings.mock_llm:
        return "mock"
    if intent == "error" and settings.model_reasoner:
        return settings.model_reasoner
    return settings.model_main


def classify(text: str, context: str = "", history: list[dict] | None = None) -> dict:
    """Intent + jump target. Router first, then DeepSeek, then keyword fallback."""
    found = route(text)
    if found:
        return found
    if settings.mock_llm:
        return _keyword_intent(text)

    user_parts = []
    if context:
        user_parts.append("Текущий шаг:\n" + context)
    user_parts.append("Сообщение пользователя:\n" + text)
    payload = {
        "model": settings.model_main,
        "messages": [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
        "stream": False,
        **_thinking(),
    }
    data = _post_json(payload)
    content = ""
    try:
        content = data["choices"][0]["message"]["content"] or ""  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        content = ""

    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content).strip()
    decision = None
    if content:
        try:
            decision = _normalize_decision(json.loads(content))
        except ValueError:
            decision = None
    if not decision:
        log.warning("classifier returned unusable payload, falling back to keywords")
        return _keyword_intent(text)
    return decision


def extract_variant(text: str) -> dict | None:
    """Second pass: ask the model for variant fields the parser missed.

    Returns a raw dict or None. Validation lives in intake.py; any failure
    here is silent for the caller.
    """
    if settings.mock_llm or not (text or "").strip():
        return None

    payload = {
        "model": settings.model_main,
        "messages": [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "stream": False,
        **_thinking(),
    }
    data = _post_json(payload)
    try:
        content = data["choices"][0]["message"]["content"] or ""  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None

    content = str(content).strip()
    if not content:
        return None
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content).strip()
    try:
        parsed = json.loads(content)
    except ValueError:
        log.warning("variant extractor returned non-JSON, ignored")
        return None
    if not isinstance(parsed, dict):
        log.warning("variant extractor returned %s, ignored", type(parsed).__name__)
        return None
    return parsed


def _answer_messages(
    text: str, intent: str, context: str, history: list[dict] | None
) -> list[dict]:
    parts = []
    if context:
        parts.append("Контекст текущего шага:\n" + context)
    parts.append("Тип сообщения: " + intent)
    parts.append("Сообщение пользователя:\n" + text)
    messages = [{"role": "system", "content": system_prompt()}]
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


def answer_stream(
    text: str,
    intent: str,
    context: str = "",
    step: dict | None = None,
    history: list[dict] | None = None,
) -> Iterator[str]:
    """Yield answer text chunks. Falls back to mock text when no key is set."""
    if settings.mock_llm:
        yield from _mock_answer(text, intent, step)
        return

    payload = {
        "model": model_for(intent),
        "messages": _answer_messages(text, intent, context, history),
        "temperature": 0.3,
        "max_tokens": 500,
        "stream": True,
        **_thinking(),
    }

    for attempt in (1, 2):
        emitted = False
        try:
            with httpx.Client(timeout=_timeout()) as client:
                with client.stream("POST", _url(), json=payload, headers=_headers()) as response:
                    if _should_retry(response.status_code):
                        response.read()
                        log.warning("deepseek stream http %s (attempt %s)", response.status_code, attempt)
                        if attempt == 1:
                            continue
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            return
                        try:
                            obj = json.loads(chunk)
                        except ValueError:
                            continue
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        # reasoning_content is deliberately ignored.
                        piece = delta.get("content")
                        if piece:
                            emitted = True
                            yield piece
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            log.warning("deepseek stream failed http %s (attempt %s)", status, attempt)
            if _should_retry(status) and attempt == 1 and not emitted:
                continue
            yield "Модель временно недоступна, повторите запрос."
            return
        except httpx.HTTPError as exc:
            log.warning("deepseek stream failed (attempt %s): %s", attempt, exc)
            if attempt == 1 and not emitted:
                continue
            yield "Модель временно недоступна, повторите запрос."
            return

    yield "Модель временно недоступна, повторите запрос."


# --------------------------------------------------------------------------- #
# Mock answers (no key): deterministic, short, no reasoning
# --------------------------------------------------------------------------- #
def _mock_answer(text: str, intent: str, step: dict | None) -> Iterator[str]:
    if not step:
        yield "План ещё не собран. Пришлите задание и подтвердите карточку."
        return

    num = step.get("num", 0)
    total = step.get("total", 0)

    if intent == "off_topic":
        yield f"Сейчас идёт шаг {num}/{total}, я отвечаю только по лабораторной."
        yield "\nНапишите, что именно не получается на текущем шаге."
        return

    if intent == "error":
        yield "Причина: шаг выполнен не на том узле или с другим именем устройства."
        yield f"\nПроверьте: {step.get('check') or 'результат команды'}, затем повторите команду из шага."
        yield "\nДальше?"
        return

    yield f"На шаге {num}/{total}: {step.get('action') or 'выполните действие из шага'}"
    if step.get("command"):
        yield f"\nКоманда: `{step['command']}`"
    elif step.get("gui"):
        yield f"\nКуда нажать: {step['gui']}"
    if step.get("check"):
        yield f"\nГотово, если: {step['check']}"
    yield "\nДальше?"
