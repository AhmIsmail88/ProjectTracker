"""
ai/openrouter_client.py
Minimal client for OpenRouter's OpenAI-compatible chat completions API.

This app is personal/non-commercial, so it uses OpenRouter (which gives
access to several free-tier models) instead of the Anthropic API directly,
to avoid any usage cost for now. Configure via a .env file next to main.py
(or next to the .exe, if you've built one — see app_paths.py):

    OPENROUTER_API_KEY=sk-or-...
    OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free

See https://openrouter.ai/docs for available models (filter by "free").
"""

import os
import json
import logging

import requests
from dotenv import load_dotenv

from app_paths import get_app_dir

logger = logging.getLogger(__name__)


def _reload_env():
    """Re-reads .env every time it's called (cheap — it's a small local
    text file) rather than caching it once per process. Two real bugs
    this avoids:
      1. python-dotenv's load_dotenv() does NOT overwrite a variable that
         is already set in the process environment by default — so a
         later edit to .env could silently be ignored unless we pass
         override=True.
      2. Caching "already loaded" for the whole app lifetime means
         editing .env while the app is running would never be picked up
         without a full restart. Re-reading every call means an edited
         .env takes effect on your very next AI request."""
    load_dotenv(os.path.join(get_app_dir(), ".env"), override=True)


def is_configured():
    _reload_env()
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def get_model():
    _reload_env()
    return os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")


class OpenRouterError(Exception):
    pass


def chat(messages, temperature=0.3, timeout=60, max_tokens=4000, allow_reasoning=False):
    """messages: list of {"role": "system"|"user"|"assistant", "content": str}
    Returns the assistant's reply text.

    max_tokens is set explicitly (and generously) because several
    OpenRouter free-tier models silently truncate long structured
    responses when it's left unset — which then fails to parse downstream.

    allow_reasoning=False (default) asks the provider to skip/exclude
    "thinking" tokens where supported. Several free-tier models are
    reasoning models that spend their entire token budget thinking and
    never emit an actual answer (finish_reason='length' with empty
    content) — this is the #1 cause of "AI returned nothing" failures
    with free models on short, structured tasks like ours. The parameter
    is ignored by models that don't support it, so it's safe to always
    send."""
    _reload_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set. Create a .env file next to main.py "
            "(see .env.example) with your OpenRouter API key."
        )
    model = get_model()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not allow_reasoning:
        payload["reasoning"] = {"exclude": True}

    resp = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these purely for their public leaderboard; harmless to omit values.
            "HTTP-Referer": "https://localhost",
            "X-Title": "Project Tracker (personal)",
        },
        data=json.dumps(payload),
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise OpenRouterError(f"OpenRouter API error {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter response: {data}") from exc

    if content is None or not str(content).strip():
        # Some models (especially "reasoning" free-tier models) sometimes
        # return an empty/null content field. Fail loudly and catchably
        # here instead of letting a None ripple into a confusing
        # AttributeError somewhere downstream (e.g. text.strip()).
        finish_reason = choice.get("finish_reason", "unknown")
        raise OpenRouterError(
            f"The model returned no usable content (finish_reason={finish_reason}). "
            f"This usually means the configured model is a 'reasoning' model that used its "
            f"whole token budget thinking. Try again, or switch OPENROUTER_MODEL in .env to a "
            f"plain instruct model, e.g. meta-llama/llama-3.3-70b-instruct:free."
        )
    return content


def test_connection():
    """Sends one trivial request and returns a short diagnostic dict:
    {"ok": bool, "model": str, "reply": str, "seconds": float, "error": str|None,
     "env_path": str, "env_exists": bool}.
    Used by the "Test AI Connection" button so a broken/misconfigured
    model — or a missing/misnamed .env file — can be caught in one quick,
    visible check instead of guessing blind. env_path/env_exists in
    particular catch the single most common real-world cause of "my .env
    changes aren't taking effect": the file isn't actually where (or
    named what) you think it is — e.g. Windows silently saving it as
    ".env.txt" when "hide known file extensions" is on."""
    import time
    env_path = os.path.join(get_app_dir(), ".env")
    env_exists = os.path.isfile(env_path)
    _reload_env()
    model = get_model()
    started = time.monotonic()
    try:
        reply = chat(
            [{"role": "user", "content": "Reply with exactly one word: OK"}],
            temperature=0, timeout=30, max_tokens=200,
        )
        elapsed = time.monotonic() - started
        return {"ok": True, "model": model, "reply": reply.strip(), "seconds": elapsed, "error": None,
                "env_path": env_path, "env_exists": env_exists}
    except Exception as exc:
        elapsed = time.monotonic() - started
        return {"ok": False, "model": model, "reply": None, "seconds": elapsed, "error": str(exc),
                "env_path": env_path, "env_exists": env_exists}
