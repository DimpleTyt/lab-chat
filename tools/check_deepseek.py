"""Check the DeepSeek key and print the model ids it can see.

Run:  python tools/check_deepseek.py
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
BASE = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
MODEL = (os.getenv("MODEL_MAIN") or "").strip()

if not KEY:
    print("DEEPSEEK_API_KEY is empty in .env")
    sys.exit(1)

headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

with httpx.Client(timeout=30) as client:
    print(f"GET {BASE}/models")
    resp = client.get(f"{BASE}/models", headers=headers)
    print("status:", resp.status_code)
    ids = []
    if resp.status_code == 200:
        ids = [item.get("id") for item in resp.json().get("data", [])]
        for model_id in ids:
            print("  -", model_id)
    else:
        print(resp.text[:500])
        sys.exit(1)

    if MODEL and ids and MODEL not in ids:
        print(f"\nWARNING: MODEL_MAIN={MODEL} is not in the list above")
    model = MODEL if MODEL in ids else (ids[0] if ids else MODEL)

    print(f"\nPOST {BASE}/chat/completions model={model}")
    resp = client.post(
        f"{BASE}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Ответь одним словом: работает"}],
            "max_tokens": 20,
            "temperature": 0,
        },
    )
    print("status:", resp.status_code)
    if resp.status_code != 200:
        print(resp.text[:800])
        sys.exit(1)
    data = resp.json()
    print("reply:", data["choices"][0]["message"]["content"])
    usage = data.get("usage") or {}
    print("tokens:", usage.get("prompt_tokens"), "->", usage.get("completion_tokens"))

print("\nOK. Put the working id into MODEL_MAIN in .env")
