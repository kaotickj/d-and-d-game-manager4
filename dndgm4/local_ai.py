"""Explicit opt-in localhost text-generation adapter for a Qwen3 LLM.

The Qwen3-TTS model in Plague's Voice Studio is a speech model and cannot
be used as a text-writing backend. This connector uses an existing local
Ollama /api/generate text server; it does not download or bundle models.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Loopback only. Generated bios/narration are never sent to remote providers.
BASE_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3:4b"

class LocalAIError(RuntimeError):
    pass

PROMPTS = {
    "bio": (
        "You are a fantasy tabletop D&D 3.5 campaign writer. Create an "
        "original grounded character biography: upbringing, personality, "
        "motivation, meaningful weakness, two plot hooks. Respect the name, "
        "race, class and alignment supplied. 180-260 words. Do not invent "
        "game mechanics or copyrighted setting characters. "
        "Provide plain prose without internal reasoning."
    ),
    "dm": (
        "You are a creative D&D 3.5 game master. Write an original "
        "60-150 word second-person scene narration with sensory detail, "
        "a clear invitation for player choices and no forced outcomes. "
        "No hidden mechanical rolls or spoilers. Plain prose only."
    ),
    "names": (
        "Generate eight original fantasy character names appropriate for "
        "the specified race, culture, and tone, one per line. Avoid "
        "published or famous character names. Names should be pronounceable "
        "and consistent with the requested tradition. Plain names only."
    ),
}

def text_generate(kind: str, context: str, *, model: str = DEFAULT_MODEL,
                  timeout: float = 75) -> str:
    """One user-initiated localhost inference, with explicit error handling."""
    if kind not in PROMPTS:
        raise ValueError("Unknown writing task.")
    if not 1 <= len(context.strip()) <= 6000:
        raise ValueError("Provide between 1 and 6,000 characters of context.")
    if not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,120}", model):
        raise ValueError("Invalid local model name.")
    payload = json.dumps({
        "model": model,
        "prompt": PROMPTS[kind] + "\n\nContext:\n" + context.strip() +
                  "\n\nResponse:",
        "stream": False,
        "options": {"temperature": .75, "num_predict": 650},
    }).encode("utf-8")
    req = Request(BASE_URL, data=payload, method="POST",
                  headers={"Content-Type":"application/json"})
    try:
        with urlopen(req,timeout=timeout) as res:
            if res.status != 200:
                raise LocalAIError(f"Local server returned status {res.status}.")
            data = json.loads(res.read(262144).decode("utf-8"))
    except (URLError, OSError) as exc:
        raise LocalAIError(
            "No local Qwen3 text server responded at 127.0.0.1:11434. "
            "Start Ollama and install/select a Qwen3 *language* model; "
            "Qwen3-TTS from Voice Studio cannot generate written bios."
        ) from exc
    except (ValueError, UnicodeError) as exc:
        raise LocalAIError("Invalid response from local model.") from exc
    result = data.get("response","")
    if not isinstance(result,str):
        raise LocalAIError("Local model did not return text.")
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.S).strip()
    if not result:
        raise LocalAIError("Local model returned no usable text.")
    return result[:12000]
