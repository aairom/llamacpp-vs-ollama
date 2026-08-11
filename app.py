"""
llama.cpp vs Ollama — Visual Comparison App
Flask backend: serves static assets, comparison data, live probe, and benchmark endpoints.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

DATA_PATH  = os.path.join(os.path.dirname(__file__), "data", "comparison.json")
BENCH_PATH = os.path.join(os.path.dirname(__file__), "data", "bench_history.json")

# Maximum number of history entries kept on disk
BENCH_HISTORY_MAX = 50

# Default inference timeout (seconds) — can be overridden via BENCH_TIMEOUT env var.
# 300 s gives enough headroom for model load + generation on CPU-only machines.
BENCH_TIMEOUT = int(os.environ.get("BENCH_TIMEOUT", 300))

# ---------------------------------------------------------------------------
# llama.cpp binary resolution
# ---------------------------------------------------------------------------
# Ordered list of candidate paths / names to try when looking for llama-cli.
# The installed binary is the multi-command dispatcher `llama`.
# Inference is run via:  llama cli -m <model> -p <prompt> -n <n_predict>
# Legacy standalone `llama-cli` binaries (older builds) are still tried as fallback.
_LLAMA_CLI_CANDIDATES = [
    "llama",                                        # new dispatcher (llama.app install)
    os.path.expanduser("~/.local/bin/llama"),       # explicit path first
    "llama-cli",                                    # legacy standalone binary on PATH
    os.path.expanduser("~/.local/bin/llama-cli"),
    "/usr/local/bin/llama",
    "/usr/local/bin/llama-cli",
    "/opt/homebrew/bin/llama",
    "/opt/homebrew/bin/llama-cli",
    "./llama-cli",
    "./llama.cpp/main",                             # legacy in-tree build
    "./main",
]

# Dispatcher binaries use subcommand style: `llama cli -m …`
# Standalone binaries use direct flags:   `llama-cli -m …`
_LLAMA_DISPATCHER_NAMES = {"llama"}


def _find_llama_cli() -> tuple[str, bool] | tuple[None, None]:
    """
    Return (path, is_dispatcher) for the first usable llama binary, or (None, None).

    is_dispatcher=True  → binary is the new `llama` dispatcher; invoke as:
                          llama cli -m <model> …
    is_dispatcher=False → binary is legacy `llama-cli`; invoke as:
                          llama-cli -m <model> …
    """
    for candidate in _LLAMA_CLI_CANDIDATES:
        # Bare command name: resolve via `which`
        if os.sep not in candidate:
            try:
                proc = subprocess.run(
                    ["which", candidate],
                    capture_output=True, text=True, timeout=3
                )
                if proc.returncode == 0:
                    resolved = proc.stdout.strip()
                    is_dispatcher = os.path.basename(resolved) in _LLAMA_DISPATCHER_NAMES
                    return resolved, is_dispatcher
            except Exception:
                continue
        else:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                is_dispatcher = os.path.basename(candidate) in _LLAMA_DISPATCHER_NAMES
                return candidate, is_dispatcher
    return None, None


# ---------------------------------------------------------------------------
# Benchmark history helpers
# ---------------------------------------------------------------------------

def _load_history() -> list:
    """Load benchmark history from disk, returning an empty list on any error."""
    if not os.path.exists(BENCH_PATH):
        return []
    try:
        with open(BENCH_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(history: list) -> None:
    """Persist benchmark history to disk (capped at BENCH_HISTORY_MAX entries)."""
    os.makedirs(os.path.dirname(BENCH_PATH), exist_ok=True)
    with open(BENCH_PATH, "w", encoding="utf-8") as fh:
        json.dump(history[-BENCH_HISTORY_MAX:], fh, indent=2)


def _append_result(result: dict) -> None:
    """Append one benchmark result to persistent history."""
    history = _load_history()
    history.append(result)
    _save_history(history)


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

def _bench_ollama(model: str, prompt: str, n_predict: int) -> dict:
    """
    Run one benchmark against the local Ollama daemon.

    Uses the streaming /api/generate endpoint so we can measure time-to-first-token
    precisely: the first streamed chunk with `done=false` carries the first token.

    Returns a metrics dict (all times in ms).
    """
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": n_predict},
    }

    t_start = time.monotonic()
    t_first_token: float | None = None
    total_tokens = 0
    eval_duration_ns = 0       # nanoseconds from Ollama's final stats object
    prompt_eval_duration_ns = 0

    try:
        resp = requests.post(url, json=payload, stream=True, timeout=BENCH_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Cannot connect to Ollama at localhost:11434 — is it running? "
            "Start it with: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama request timed out after {BENCH_TIMEOUT}s. "
            "Try a smaller n_predict or a lighter model."
        )

    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        try:
            chunk = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        response_text = chunk.get("response", "")
        if response_text and t_first_token is None:
            t_first_token = time.monotonic()

        if chunk.get("done"):
            # Final stats object
            eval_duration_ns    = chunk.get("eval_duration", 0)
            prompt_eval_duration_ns = chunk.get("prompt_eval_duration", 0)
            total_tokens        = chunk.get("eval_count", 0)
            break

    t_end = time.monotonic()

    total_ms   = (t_end - t_start) * 1000
    ttft_ms    = (t_first_token - t_start) * 1000 if t_first_token else None
    # Prefer Ollama's own eval_duration for TPS (more accurate than wall clock)
    eval_ms    = eval_duration_ns / 1_000_000 if eval_duration_ns else None
    prompt_ms  = prompt_eval_duration_ns / 1_000_000 if prompt_eval_duration_ns else None
    tps        = (total_tokens / (eval_ms / 1000)) if (eval_ms and total_tokens) else None

    return {
        "time_to_first_token_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "total_time_ms":          round(total_ms, 2),
        "eval_time_ms":           round(eval_ms, 2) if eval_ms is not None else None,
        "prompt_eval_time_ms":    round(prompt_ms, 2) if prompt_ms is not None else None,
        "tokens_per_second":      round(tps, 2) if tps is not None else None,
        "tokens_generated":       total_tokens,
    }


def _bench_llamacpp(model: str, prompt: str, n_predict: int) -> dict:
    """
    Run one benchmark using the llama binary.

    New dispatcher style (llama.app install):
        llama cli -m <model> -p <prompt> -n <n_predict> --log-disable

    Legacy standalone style (llama-cli):
        llama-cli -m <model> -p <prompt> -n <n_predict> --log-disable

    Parses llama_print_timings lines from combined stdout/stderr.
    """
    cli_path, is_dispatcher = _find_llama_cli()
    if cli_path is None:
        raise RuntimeError(
            "llama binary not found. Searched: " +
            ", ".join(_LLAMA_CLI_CANDIDATES) +
            ". Install from https://llama.app or https://github.com/ggml-org/llama.cpp/releases"
        )

    # Build the command depending on binary style
    if is_dispatcher:
        # `llama cli -m model -p prompt -n n_predict …`
        cmd = [
            cli_path, "cli",
            "-m", model,
            "-p", prompt,
            "-n", str(n_predict),
            "--log-disable",
            "-e",
        ]
    else:
        # `llama-cli -m model -p prompt -n n_predict …`
        cmd = [
            cli_path,
            "-m", model,
            "-p", prompt,
            "-n", str(n_predict),
            "--log-disable",
            "-e",
        ]

    t_start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BENCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"llama timed out after {BENCH_TIMEOUT}s. "
            "Try reducing n_predict or using a smaller/more quantized model."
        )
    except FileNotFoundError:
        raise RuntimeError(f"llama binary not executable at resolved path: {cli_path}")

    t_end = time.monotonic()
    total_wall_ms = (t_end - t_start) * 1000

    combined = proc.stdout + "\n" + proc.stderr

    # --- Parse llama_print_timings lines ---
    def _parse_ms(pattern: str) -> float | None:
        m = re.search(pattern, combined)
        return float(m.group(1)) if m else None

    def _parse_tps(pattern: str) -> float | None:
        m = re.search(pattern, combined)
        return float(m.group(1)) if m else None

    def _parse_tokens(pattern: str) -> int | None:
        m = re.search(pattern, combined)
        return int(m.group(1)) if m else None

    load_ms        = _parse_ms(r"load time\s*=\s*([\d.]+)\s*ms")
    prompt_ms      = _parse_ms(r"prompt eval time\s*=\s*([\d.]+)\s*ms")
    eval_ms        = _parse_ms(r"(?<!prompt )eval time\s*=\s*([\d.]+)\s*ms")
    total_ms_stat  = _parse_ms(r"total time\s*=\s*([\d.]+)\s*ms")
    eval_tps       = _parse_tps(r"eval time.*?([\d.]+)\s*tokens per second")
    prompt_tps     = _parse_tps(r"prompt eval time.*?([\d.]+)\s*tokens per second")
    eval_tokens    = _parse_tokens(r"eval time\s*=.*?/\s*(\d+)\s*runs")
    prompt_tokens  = _parse_tokens(r"prompt eval time\s*=.*?/\s*(\d+)\s*tokens")

    # TTFT ≈ load time + prompt eval time (time before first generated token)
    ttft_ms: float | None = None
    if load_ms is not None and prompt_ms is not None:
        ttft_ms = load_ms + prompt_ms
    elif prompt_ms is not None:
        ttft_ms = prompt_ms

    total_tokens = (eval_tokens or 0) + (prompt_tokens or 0)

    # If the process failed with no timing output, surface stderr
    if proc.returncode != 0 and eval_ms is None:
        stderr_snippet = proc.stderr[-800:].strip() if proc.stderr else "(no stderr)"
        raise RuntimeError(
            f"llama exited with code {proc.returncode}.\n"
            f"Last stderr:\n{stderr_snippet}"
        )

    return {
        "time_to_first_token_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "total_time_ms":          round(total_ms_stat or total_wall_ms, 2),
        "eval_time_ms":           round(eval_ms, 2) if eval_ms is not None else None,
        "prompt_eval_time_ms":    round(prompt_ms, 2) if prompt_ms is not None else None,
        "tokens_per_second":      round(eval_tps, 2) if eval_tps is not None else None,
        "prompt_tokens_per_second": round(prompt_tps, 2) if prompt_tps is not None else None,
        "tokens_generated":       eval_tokens,
        "prompt_tokens":          prompt_tokens,
        "load_time_ms":           round(load_ms, 2) if load_ms is not None else None,
        "wall_time_ms":           round(total_wall_ms, 2),
    }


def load_comparison_data() -> dict:
    """Load and return the structured comparison data from JSON."""
    with open(DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/favicon.ico")
def favicon():
    """Serve favicon to suppress 404 errors."""
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico", mimetype="image/x-icon"
    )


@app.route("/")
def index():
    """Serve the main single-page comparison app."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Data API
# ---------------------------------------------------------------------------

@app.route("/api/data")
def api_data():
    """Return the full comparison dataset as JSON."""
    return jsonify(load_comparison_data())


# ---------------------------------------------------------------------------
# Live probe endpoints
# ---------------------------------------------------------------------------

@app.route("/api/probe/ollama")
def probe_ollama():
    """
    Probe the locally installed Ollama instance:
    - version via CLI
    - list of installed models via the Ollama REST API
    """
    result = {"installed": False, "version": None, "models": [], "error": None}

    # 1. Check version via CLI
    try:
        proc = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=5
        )
        raw = (proc.stdout + proc.stderr).strip()
        # "ollama version is 0.32.8"
        if "version" in raw.lower():
            parts = raw.split()
            result["version"] = parts[-1] if parts else raw
            result["installed"] = True
    except FileNotFoundError:
        result["error"] = "ollama binary not found in PATH"
        return jsonify(result)
    except subprocess.TimeoutExpired:
        result["error"] = "ollama --version timed out"
        return jsonify(result)

    # 2. Fetch model list from Ollama API
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("models", [])
            result["models"] = [
                {
                    "name": m.get("name", ""),
                    "size_gb": round(m.get("size", 0) / 1e9, 2),
                    "modified_at": m.get("modified_at", "")[:10],
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "family": m.get("details", {}).get("family", ""),
                }
                for m in models
            ]
    except urllib.error.URLError as exc:
        result["error"] = f"Ollama API unreachable: {exc.reason}"

    return jsonify(result)


@app.route("/api/probe/llamacpp/models")
def probe_llamacpp_models():
    """
    Return GGUF model files usable by the llama binary.

    Sources searched (in order):
    1. ~/.cache/huggingface/hub/  — the canonical location for models
       downloaded via `llama download` or the HuggingFace CLI.
       HF nests files as: models--<org>--<repo>/snapshots/<hash>/<file>.gguf
    2. Common hand-placed GGUF directories (~/models, ~/Downloads, etc.)

    Ollama blobs are intentionally excluded: they have opaque sha256 names
    and are managed by the Ollama daemon, not by llama directly.
    """
    models = []
    existing_paths: set[str] = set()

    # ── Directories to scan (all searched recursively for *.gguf) ─────────
    search_dirs = [
        os.path.expanduser("~/.cache/huggingface/hub"),  # primary: HF Hub / llama download
        os.path.expanduser("~/models"),
        os.path.expanduser("~/Models"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        "/usr/local/share/llama.cpp",
        "/opt/models",
    ]

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for dirpath, _dirs, files in os.walk(d):
            for fname in files:
                if not fname.lower().endswith(".gguf"):
                    continue
                full = os.path.join(dirpath, fname)
                if full in existing_paths:
                    continue
                # Derive a readable display name for HF hub layout:
                # models--org--repo/snapshots/<hash>/file.gguf → org/repo — file.gguf
                rel   = os.path.relpath(full, d)
                parts = rel.replace("\\", "/").split("/")
                if parts[0].startswith("models--") and len(parts) >= 4:
                    repo         = parts[0][len("models--"):].replace("--", "/", 1)
                    display_name = f"{repo} — {parts[-1]}"
                else:
                    display_name = fname
                models.append({
                    "name":    display_name,
                    "path":    full,
                    "source":  "local",
                    "size_gb": round(os.path.getsize(full) / 1e9, 2),
                })
                existing_paths.add(full)

    return jsonify({"models": models}), 200


@app.route("/api/probe/llamacpp")
def probe_llamacpp():
    """
    Probe the locally installed llama.cpp toolchain.
    Checks known install paths for llama-cli, llama-server, and llama-bench.
    """
    result = {"installed": False, "version": None, "tools": [], "error": None}

    # Known binary names / paths — put the new dispatcher first so version
    # is captured from the most commonly installed binary.
    candidates = [
        "llama",                    # new dispatcher binary (llama.app install)
        "llama-cli",                # legacy standalone
        "llama-server",
        "llama-bench",
        "llama-cpp",
    ]
    # Also check ~/.local/bin
    home_local = os.path.expanduser("~/.local/bin")
    extra_paths = [
        os.path.join(home_local, name) for name in candidates
    ]

    found_tools = []

    # Check PATH
    for name in candidates:
        try:
            proc = subprocess.run(
                ["which", name],
                capture_output=True, text=True, timeout=3
            )
            if proc.returncode == 0:
                path = proc.stdout.strip()
                found_tools.append({"name": name, "path": path})
        except Exception:
            pass

    # Check extra paths
    for path in extra_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            name = os.path.basename(path)
            if not any(t["name"] == name for t in found_tools):
                found_tools.append({"name": name, "path": path})

    if found_tools:
        result["installed"] = True
        result["tools"] = found_tools

        # Try to get version from first found tool
        first = found_tools[0]["path"]
        try:
            proc = subprocess.run(
                [first, "--version"],
                capture_output=True, text=True, timeout=5
            )
            raw = (proc.stdout + proc.stderr).strip()
            if raw:
                result["version"] = raw[:120]  # truncate for display
        except Exception as exc:
            result["version"] = f"(version check failed: {exc})"
    else:
        result["error"] = (
            "No llama.cpp binaries found in PATH or ~/.local/bin. "
            "Install from https://github.com/ggml-org/llama.cpp/releases"
        )

    return jsonify(result)


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

@app.route("/api/bench", methods=["POST"])
def api_bench():
    """
    Run a single benchmark and return unified metrics.

    Request JSON body:
        backend   : "ollama" | "llamacpp"  (required)
        model     : str                    (required)
        prompt    : str                    (required)
        n_predict : int                    (optional, default 128)
    """
    body = request.get_json(force=True, silent=True) or {}

    backend   = body.get("backend", "").strip().lower()
    model     = body.get("model", "").strip()
    prompt    = body.get("prompt", "").strip()
    n_predict = int(body.get("n_predict", 128))

    # --- Validation ---
    errors = []
    if backend not in ("ollama", "llamacpp"):
        errors.append("'backend' must be 'ollama' or 'llamacpp'.")
    if not model:
        errors.append("'model' is required.")
    if not prompt:
        errors.append("'prompt' is required.")
    if n_predict < 1 or n_predict > 4096:
        errors.append("'n_predict' must be between 1 and 4096.")
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    # --- Run ---
    try:
        if backend == "ollama":
            metrics = _bench_ollama(model, prompt, n_predict)
        else:
            metrics = _bench_llamacpp(model, prompt, n_predict)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend":   backend,
        "model":     model,
        "prompt":    prompt[:200],   # truncate for storage
        "n_predict": n_predict,
        "metrics":   metrics,
    }

    _append_result(result)
    return jsonify(result), 200


@app.route("/api/bench/history", methods=["GET"])
def api_bench_history():
    """Return the last 50 benchmark results, most-recent first."""
    history = _load_history()
    return jsonify(list(reversed(history))), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"\n  llama.cpp vs Ollama Comparison App")
    print(f"  ➜  http://localhost:{port}\n")
    # threaded=True is essential: the benchmark endpoint blocks for up to
    # BENCH_TIMEOUT seconds while the llama subprocess runs. Without threading,
    # the server handles only one request at a time and the browser appears to
    # hang with no feedback until inference finishes (or times out).
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
