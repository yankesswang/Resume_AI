"""Test NVIDIA NIM API inference."""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("nvidia_api_key", "").split("https")[0].strip()
BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = os.getenv("model_id", "moonshotai/kimi-k2.5").strip()

# Fallback model if primary times out
FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"


def chat(prompt: str, model: str = MODEL, timeout: float = 120.0) -> str:
    """Send a chat completion request and return the response text."""
    resp = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.7,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def chat_stream(prompt: str, model: str = MODEL, timeout: float = 120.0):
    """Send a streaming chat completion request, yielding tokens as they arrive."""
    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.7,
            "stream": True,
        },
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload.strip() == "[DONE]":
                break
            import json
            chunk = json.loads(payload)
            delta = chunk["choices"][0].get("delta", {})
            token = delta.get("content", "")
            if token:
                yield token


if __name__ == "__main__":
    print(f"Base URL : {BASE_URL}")
    print(f"Model    : {MODEL}")
    print(f"API Key  : {API_KEY[:20]}...{API_KEY[-4:]}")
    print("-" * 50)

    prompt = "Explain what a transformer model is in 3 sentences."

    # Try primary model, fall back if it times out
    for model in [MODEL, FALLBACK_MODEL]:
        try:
            print(f"\n[Streaming] {model}")
            print("-" * 50)
            for token in chat_stream(prompt, model=model):
                print(token, end="", flush=True)
            print("\n")
            break
        except httpx.TimeoutException:
            print(f"\n  -> {model} timed out, trying fallback...")
        except httpx.HTTPStatusError as e:
            print(f"\n  -> {model} error: {e.response.status_code} {e.response.text}")
            if model != FALLBACK_MODEL:
                print("  -> trying fallback...")
