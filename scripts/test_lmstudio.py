"""Quick smoke test for LM Studio server connectivity and chat completions."""

import httpx
import json
import sys
import time

BASE_URL = "http://192.168.0.84:1234"
CHAT_URL = f"{BASE_URL}/v1/chat/completions"
MODELS_URL = f"{BASE_URL}/v1/models"


def test_models():
    """List available models."""
    print("=== Checking available models ===")
    resp = httpx.get(MODELS_URL, timeout=10.0)
    resp.raise_for_status()
    models = resp.json()
    for m in models.get("data", []):
        print(f"  - {m['id']}")
    return models


def test_chat(prompt: str = "Say hello in one sentence."):
    """Send a simple chat completion request."""
    print(f"\n=== Chat completion test ===")
    print(f"Prompt: {prompt}")

    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 256,
    }

    start = time.time()
    resp = httpx.post(CHAT_URL, json=payload, timeout=120.0)
    elapsed = time.time() - start

    resp.raise_for_status()
    data = resp.json()

    reply = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    print(f"Reply: {reply}")
    print(f"Time: {elapsed:.2f}s")
    if usage:
        print(f"Tokens — prompt: {usage.get('prompt_tokens')}, "
              f"completion: {usage.get('completion_tokens')}, "
              f"total: {usage.get('total_tokens')}")


def test_json_output():
    """Test structured JSON output (used by resume extraction)."""
    print("\n=== JSON output test ===")

    payload = {
        "messages": [
            {"role": "system", "content": "Return ONLY valid JSON, no explanation."},
            {"role": "user", "content": 'Return a JSON object with keys "name", "score" and "tags" (array). Make up sample data.'},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    resp = httpx.post(CHAT_URL, json=payload, timeout=120.0)
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    print(f"Raw: {raw}")
    parsed = json.loads(raw)
    print(f"Parsed: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
    print("JSON parsing: OK")


if __name__ == "__main__":
    try:
        test_models()
        test_chat(sys.argv[1] if len(sys.argv) > 1 else "Say hello in one sentence.")
        test_json_output()
        print("\nAll tests passed.")
    except httpx.ConnectError:
        print(f"ERROR: Cannot connect to LM Studio at {BASE_URL}")
        print("Make sure LM Studio is running and the server is started.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
