"""LLM providers: Gemini, Groq, or any OpenAI-compatible API (OpenAI, OpenRouter, Ollama...)."""

import json
import re

import requests

from .runtime import log, sleep


class LLMConfigError(RuntimeError):
    pass


def call_gemini(prompt, cfg, json_mode=True):
    config = {"temperature": 0.2}
    if json_mode:
        config["responseMimeType"] = "application/json"
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent",
        headers={"x-goog-api-key": cfg["gemini_api_key"], "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config},
        timeout=60,
    )
    return r, lambda: r.json()["candidates"][0]["content"]["parts"][0]["text"]


def chat_completion(base_url, key, model, prompt, json_mode):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = requests.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=body,
                      timeout=120)
    return r, lambda: r.json()["choices"][0]["message"]["content"]


def call_groq(prompt, cfg, json_mode=True):
    return chat_completion("https://api.groq.com/openai/v1", cfg["groq_api_key"],
                           cfg["groq_model"], prompt, json_mode)


def call_openai(prompt, cfg, json_mode=True):
    return chat_completion(cfg["openai_base_url"], cfg["openai_api_key"], cfg["openai_model"],
                           prompt, json_mode)


PROVIDERS = {"gemini": call_gemini, "groq": call_groq, "openai": call_openai}
# provider -> setting that must be filled in (the OpenAI-compatible one may be a keyless local server)
REQUIRED = {"gemini": "gemini_api_key", "groq": "groq_api_key", "openai": "openai_base_url"}


def check_config(cfg):
    provider = cfg["llm_provider"]
    if provider not in PROVIDERS:
        raise LLMConfigError(f"Unknown LLM provider {provider!r}")
    if not cfg[REQUIRED[provider]]:
        raise LLMConfigError(f"Set {REQUIRED[provider].replace('_', ' ')} in Settings -> AI provider")


def ask_llm(prompt, cfg, json_mode=True):
    """Send a prompt, retrying on rate limits; returns parsed JSON or plain text."""
    check_config(cfg)
    provider = cfg["llm_provider"]
    call = PROVIDERS[provider]
    for attempt in range(6):
        try:
            r, extract = call(prompt, cfg, json_mode)
        except requests.exceptions.Timeout:
            log.info("  LLM timed out, retrying")
            continue
        if r.status_code == 429 or r.status_code >= 500:
            wait = 15 * (attempt + 1)
            log.info(f"  LLM returned {r.status_code}, waiting {wait}s")
            sleep(wait)
            continue
        if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in r.text.lower()):
            raise LLMConfigError(f"{provider} rejected the API key ({r.status_code}). "
                                 "Check it in Settings -> AI provider.")
        if not r.ok:
            raise RuntimeError(f"{provider} error {r.status_code}: {r.text[:300]}")
        text = extract().strip()
        if not json_mode:
            return text
        text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        return json.loads(text)
    raise RuntimeError(f"{provider}: gave up after repeated rate limits")
