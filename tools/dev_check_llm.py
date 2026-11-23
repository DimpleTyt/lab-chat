"""Live DeepSeek check through the app's own LLM layer."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import llm  # noqa: E402

STEP = {
    "num": 15,
    "total": 84,
    "id": "2.3",
    "module": 2,
    "module_title": "Файловое хранилище: RAID",
    "action": "Собери массив RAID 5 из 3 дисков.",
    "command": "mdadm --create --verbose /dev/md0 -l 5 -n 3 /dev/sdb /dev/sdc /dev/sdd",
    "check": "mdadm сообщил о создании массива /dev/md0",
}

context = (
    "Шаг 15/84 (id 2.3), модуль 2: Файловое хранилище: RAID\n"
    f"Действие: {STEP['action']}\nКоманда: {STEP['command']}\nКритерий: {STEP['check']}"
)

print("model_for:", llm.model_for())
for text in ("дальше", "вернись к шагу 5", "у меня mdadm: no devices", "привет"):
    print(f"route {text!r} ->", llm.route(text))

print("\nclassify:")
for text in ("у меня mdadm: no devices to create array", "вернись к шагу 5", "дальше"):
    print(" ", text, "->", llm.classify(text, context))

print("\nanswer_stream (error):")
chunks = []
for piece in llm.answer_stream("mdadm: no devices to create array", "error", context, STEP):
    chunks.append(piece)
print(repr("".join(chunks)))

print("\nanswer_stream (question):")
chunks = []
for piece in llm.answer_stream("почему именно 3 диска?", "question", context, STEP):
    chunks.append(piece)
print(repr("".join(chunks)))

print("\nextract_variant:")
print(json.dumps(
    llm.extract_variant("Вариант 7. RAID 10 из четырёх дисков, /raid10. Домен lab.local. NTP 10.0.0.5."),
    ensure_ascii=False,
)[:500])
