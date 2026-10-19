"""Explicit opt-in local prose generation with existing GGUF or Ollama models.

The model files are *not* downloaded, copied, modified, or bundled.
GGUF inference uses a separately installed llama.cpp llama-server executable,
started only for the user-requested generation on a localhost-only port.
Qwen3-TTS from Voice Studio is a speech model, not a writing model.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# All requests stay on the user's own loopback network interface.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
MODEL_FOLDER = Path.home() / ".goodneighbor_blues_dj" / "ai_writer" / "models"
GGUF_MODELS = {
    "Qwen3 4B Instruct (GGUF)": MODEL_FOLDER / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "Gemma The Writer 9B (GGUF)": MODEL_FOLDER / "Gemma-The-Writer-Mighty-Sword-9B-D_AU-Q4_k_m.gguf",
}
DEFAULT_MODEL = str(GGUF_MODELS["Qwen3 4B Instruct (GGUF)"])


class LocalAIError(RuntimeError):
    """Visible, user-actionable local inference error."""


PROMPTS = {
    "bio": (
        "You are a fantasy tabletop D&D 3.5 campaign writer. Create an "
        "original grounded character biography: upbringing, personality, "
        "motivation, meaningful weakness, two plot hooks. Respect the name, "
        "race, class and alignment supplied. 180-260 words. Do not invent "
        "game mechanics or copyrighted setting characters. "
        "Provide plain prose without internal reasoning."
    ),
    "npc_bio": (
        "You write nuanced, original NPC biographies for a D&D 3.5 tabletop "
        "campaign. Produce 160-250 words about the NPC's history, current "
        "occupation or faction, personality, public reputation, secrets or "
        "private motives, connections to other people, and two actionable "
        "adventure or roleplay hooks. Respect all supplied name, species, "
        "class, alignment, goals and campaign details. Make the NPC feel like "
        "a person who exists beyond the party. Do not change ability scores, "
        "CR, equipment, class features or other game mechanics. Avoid "
        "invented claims about canonical settings. Plain prose only."
    ),
    "monster_bio": (
        "You write evocative and original D&D 3.5 monster bestiary lore for "
        "a dungeon master, not a stat block. Produce 160-250 words covering "
        "physical appearance, habitat and ecology, typical behavior, "
        "how adventurers might encounter it, local rumors or folklore, "
        "and one or two adventure hooks. Honor the supplied monster type, "
        "size, subtype, intelligence, environment, attacks, known special "
        "qualities and alignment. Mindless creatures must not be described "
        "as speaking, scheming or reasoning. Do not invent new numerical "
        "stats, attacks, spells, feats, immunities, weaknesses or game "
        "mechanics, and do not assert unprovided official lore as canon. "
        "All details should be editable storytelling suggestions. "
        "Plain prose, no stat block."
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

def discover_llama_server() -> str:
    """Find an existing llama.cpp runtime without installing another copy."""
    from_path = shutil.which("llama-server") or shutil.which("llama-server.exe")
    if from_path:
        return from_path
    for candidate in (
        MODEL_FOLDER.parent / "llama-server.exe",
        MODEL_FOLDER.parent / "llama-server",
        Path.home() / "llama.cpp" / "build" / "bin" / "Release" / "llama-server.exe",
        Path.home() / "llama.cpp" / "build" / "bin" / "llama-server",
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


def _clean_output(value: object) -> str:
    if not isinstance(value, str):
        raise LocalAIError("Local inference returned no text.")
    cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.S).strip()
    if not cleaned:
        raise LocalAIError("Local model returned an empty draft.")
    return cleaned[:12000]


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = Request(url, method="POST",
                  headers={"Content-Type": "application/json"},
                  data=json.dumps(payload).encode("utf-8"))
    try:
        with urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read(262144).decode("utf-8"))
    except HTTPError as exc:
        try:
            body = exc.read(1024).decode("utf-8", errors="replace")
        except OSError:
            body = ""
        raise LocalAIError(f"Local generation HTTP {exc.code}: {body}") from exc
    except (URLError, OSError) as exc:
        raise LocalAIError(f"Could not contact local writing engine: {exc}") from exc
    except (ValueError, UnicodeError) as exc:
        raise LocalAIError("Writing engine returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise LocalAIError("Writing engine returned an invalid response.")
    return result


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_server(process: subprocess.Popen, url: str, deadline: float,
                     log) -> None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.seek(0)
            tail = log.read().decode("utf-8", errors="replace")[-1800:].strip()
            raise LocalAIError(
                "llama-server exited while loading the GGUF model. "
                + (tail or "Check the model and engine paths.")
            )
        try:
            with urlopen(url + "/health", timeout=1.5) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError, OSError):
            pass  # A loading server can return 503 until ready.
        time.sleep(.5)
    raise LocalAIError("Timed out waiting for llama-server to load the GGUF model.")


def generate_gguf(kind: str, context: str, model: str, *,
                  llama_server: str = "", gpu_layers: int = 0,
                  timeout: float = 240) -> str:
    """Use a model *in place* through a short-lived localhost llama-server.

    CPU inference is the portable default across AMD/Intel/NVIDIA Windows PCs.
    Users can supply their own optimized llama.cpp build, but the application
    will never download executables or model data.
    """
    if not isinstance(gpu_layers, int) or not 0 <= gpu_layers <= 99:
        raise ValueError("GPU layers must be between 0 and 99.")
    path = Path(model).expanduser()
    if not path.is_file() or path.suffix.casefold() != ".gguf":
        raise LocalAIError(
            "GGUF model file not found. Select the existing model file in "
            "the Goodneighbor Blues AI Writer models directory."
        )
    executable = llama_server.strip() or discover_llama_server()
    if not executable:
        raise LocalAIError(
            "A llama.cpp llama-server executable is required to run GGUF files. "
            "Choose your existing llama-server.exe in the Scribe settings. "
            "Model files alone cannot run inference. Nothing was downloaded."
        )
    binary = Path(executable).expanduser()
    if not binary.is_file():
        located = shutil.which(executable)
        if not located:
            raise LocalAIError("Selected llama-server executable does not exist.")
        binary = Path(located)
    port = _free_local_port()
    server_url = f"http://127.0.0.1:{port}"
    cmd = [str(binary), "-m", str(path.resolve()), "--host", "127.0.0.1",
           "--port", str(port), "--ctx-size", "4096",
           "--n-gpu-layers", str(gpu_layers)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL,
                                       creationflags=flags)
        except OSError as exc:
            raise LocalAIError(f"Unable to launch llama-server: {exc}") from exc
        try:
            _wait_for_server(process, server_url, time.monotonic() + 120, log)
            response = _post_json(server_url + "/v1/chat/completions", {
                "model": path.name,
                "messages": [
                    {"role": "system", "content": PROMPTS[kind]},
                    {"role": "user", "content": context.strip()},
                ],
                "stream": False,
                "temperature": .75,
                "max_tokens": 650,
            }, timeout=timeout)
            choices = response.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                raise LocalAIError("llama.cpp returned no completion choices.")
            return _clean_output(choices[0].get("message", {}).get("content", ""))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def text_generate(kind: str, context: str, *, model: str = DEFAULT_MODEL,
                  backend: str = "gguf", llama_server: str = "",
                  gpu_layers: int = 0, timeout: float = 240) -> str:
    """One user-initiated generation. Never silently falls back to the cloud."""
    if kind not in PROMPTS:
        raise ValueError("Unknown writing task.")
    if not 1 <= len(context.strip()) <= 6000:
        raise ValueError("Provide between 1 and 6,000 characters of context.")
    if backend == "gguf":
        return generate_gguf(kind, context, model,
                             llama_server=llama_server, gpu_layers=gpu_layers,
                             timeout=timeout)
    if backend != "ollama":
        raise ValueError("Unknown local inference engine.")
    if not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,120}", model):
        raise ValueError("Invalid Ollama model name.")
    try:
        response = _post_json(OLLAMA_URL, {
            "model": model,
            "prompt": PROMPTS[kind] + "\n\nContext:\n" + context.strip()
                      + "\n\nResponse:",
            "stream": False,
            "options": {"temperature": .75, "num_predict": 650},
        }, timeout=timeout)
    except LocalAIError as exc:
        raise LocalAIError(
            "Ollama localhost inference failed. To use your existing GGUF files "
            "without importing or copying them into Ollama, switch the backend "
            f"to GGUF (llama.cpp). Details: {exc}"
        ) from exc
    return _clean_output(response.get("response", ""))
