"""
llama.cpp vs Ollama — Visual Comparison App
Flask backend: serves static assets, comparison data, live probe, and benchmark endpoints.
"""

# Load .env before any os.environ access so BENCH_TIMEOUT, PORT, DEBUG are
# honoured from the project's .env file rather than always using defaults.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; fall back to environment variables

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
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
BENCH_TIMEOUT = int(os.getenv("BENCH_TIMEOUT", 300))

# ---------------------------------------------------------------------------
# Async job store
# ---------------------------------------------------------------------------
# Each benchmark runs in a background thread so the HTTP request returns
# immediately with a job_id.  The client polls GET /api/bench/job/<job_id>.
#
# Job states:  "running" | "done" | "error"
# Entries are kept in memory only; they are discarded on server restart.
# Completed jobs are pruned to the last JOB_STORE_MAX entries.
JOB_STORE_MAX = 100
_jobs: dict = {}          # job_id → {"status", "result"?, "error"?}
_jobs_lock = threading.Lock()

# ---------------------------------------------------------------------------
# llama.cpp binary resolution
# ---------------------------------------------------------------------------
# Ordered list of candidate paths / names to try when looking for the llama binary.
# The installed binary is the multi-command dispatcher `llama`.
# Inference is run via:  llama cli -m <model> -p <prompt> -n <n_predict>
_LLAMA_CLI_CANDIDATES = [
    "llama",                                  # dispatcher on PATH
    os.path.expanduser("~/.local/bin/llama"), # explicit ~/.local/bin
    "/usr/local/bin/llama",
    "/opt/homebrew/bin/llama",
]

# All supported binaries are dispatcher-style: `llama cli -m …`
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
        "command":                f'ollama run {model} "{prompt}"',
    }


def _bench_llamacpp(model: str, prompt: str, n_predict: int) -> dict:
    """
    Run one benchmark using the llama dispatcher binary.

        llama cli -m <model> -p <prompt> -n <n_predict> --log-disable -e

    Parses llama_print_timings lines from combined stdout/stderr.
    """
    cli_path, _ = _find_llama_cli()
    if cli_path is None:
        raise RuntimeError(
            "llama binary not found. Searched: " +
            ", ".join(_LLAMA_CLI_CANDIDATES) +
            ". Install from https://llama.app or https://github.com/ggml-org/llama.cpp/releases"
        )

    cmd = [
        cli_path, "cli",
        "-m", model,
        "-p", prompt,
        "-n", str(n_predict),
        "--no-conversation",   # disable interactive REPL
        "--single-turn",       # guarantee one-shot exit even on reasoning/thinking models
        "--reasoning", "off",  # suppress <think> block on Qwen3/DeepSeek-style models;
                               # ignored harmlessly by non-reasoning models
        "--log-disable",
        "-e",
    ]

    t_start = time.monotonic()
    try:
        # Use Popen + communicate() instead of subprocess.run(capture_output=True).
        # subprocess.run with capture_output buffers stdout and stderr in OS pipes;
        # if the llama process writes enough output (verbose logs, token stream) the
        # pipe buffer fills, the process blocks on write, and run() deadlocks waiting
        # for the process to exit — a hang that can outlast BENCH_TIMEOUT.
        # communicate() drains both pipes concurrently in background threads, so the
        # process is never blocked on a full pipe.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=BENCH_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # drain pipes after kill to avoid ResourceWarning
            raise RuntimeError(
                f"llama timed out after {BENCH_TIMEOUT}s. "
                "Try reducing n_predict or using a smaller/more quantized model."
            )
    except FileNotFoundError:
        raise RuntimeError(f"llama binary not executable at resolved path: {cli_path}")

    t_end = time.monotonic()
    total_wall_ms = (t_end - t_start) * 1000

    combined = stdout + "\n" + stderr

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

    # ── Format A: classic llama_print_timings block (older builds) ────────────
    #   load time     =   123.45 ms
    #   prompt eval time =   12.34 ms /  10 tokens (  1.23 ms per token, 123.45 tokens per second)
    #   eval time     =  456.78 ms /  64 runs   (  7.13 ms per token,  89.77 tokens per second)
    #   total time    =  580.12 ms /  74 tokens
    load_ms        = _parse_ms(r"load time\s*=\s*([\d.]+)\s*ms")
    prompt_ms      = _parse_ms(r"prompt eval time\s*=\s*([\d.]+)\s*ms")
    eval_ms        = _parse_ms(r"(?<!prompt )eval time\s*=\s*([\d.]+)\s*ms")
    total_ms_stat  = _parse_ms(r"total time\s*=\s*([\d.]+)\s*ms")
    eval_tps       = _parse_tps(r"eval time.*?([\d.]+)\s*tokens per second")
    prompt_tps     = _parse_tps(r"prompt eval time.*?([\d.]+)\s*tokens per second")
    eval_tokens    = _parse_tokens(r"eval time\s*=.*?/\s*(\d+)\s*runs")
    prompt_tokens  = _parse_tokens(r"prompt eval time\s*=.*?/\s*(\d+)\s*tokens")

    # ── Format B: new dispatcher inline speed line (build b10217+) ───────────
    #   [ Prompt: 373.0 t/s | Generation: 88.3 t/s ]
    if eval_tps is None:
        eval_tps   = _parse_tps(r"Generation:\s*([\d.]+)\s*t/s")
    if prompt_tps is None:
        prompt_tps = _parse_tps(r"Prompt:\s*([\d.]+)\s*t/s")
    # Derive eval_ms from wall time and generation TPS when the timing block is absent
    if eval_ms is None and eval_tps is not None and eval_tps > 0:
        # eval_tokens unknown from new format; use n_predict as upper bound
        eval_ms = (n_predict / eval_tps) * 1000

    # ── TTFT ≈ load time + prompt eval time ───────────────────────────────────
    ttft_ms: float | None = None
    if load_ms is not None and prompt_ms is not None:
        ttft_ms = load_ms + prompt_ms
    elif prompt_ms is not None:
        ttft_ms = prompt_ms

    total_tokens = (eval_tokens or 0) + (prompt_tokens or 0)

    # If the process failed with no timing output at all, surface stderr
    returncode = proc.returncode
    if returncode != 0 and eval_ms is None and eval_tps is None:
        stderr_snippet = stderr[-800:].strip() if stderr else "(no stderr)"
        raise RuntimeError(
            f"llama exited with code {returncode}.\n"
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
        "command":                " ".join(cmd),
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

def _run_bench_job(job_id: str, backend: str, model: str, prompt: str, n_predict: int) -> None:
    """
    Worker executed in a background thread for each benchmark job.
    Writes the outcome into _jobs[job_id] when complete.
    """
    try:
        if backend == "ollama":
            metrics = _bench_ollama(model, prompt, n_predict)
        else:
            metrics = _bench_llamacpp(model, prompt, n_predict)

        # Full prompt kept in the live result for display; truncated only for storage.
        result = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backend":   backend,
            "model":     model,
            "prompt":    prompt,
            "n_predict": n_predict,
            "metrics":   metrics,
        }
        _append_result({**result, "prompt": prompt[:200]})  # persist truncated

        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result}
            # Prune oldest completed jobs beyond JOB_STORE_MAX
            done_ids = [k for k, v in _jobs.items() if v["status"] != "running"]
            for old_id in done_ids[:-JOB_STORE_MAX]:
                del _jobs[old_id]

    except RuntimeError as exc:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(exc)}
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": f"Unexpected error: {exc}"}


@app.route("/api/bench", methods=["POST"])
def api_bench():
    """
    Start a benchmark job and return a job_id immediately (HTTP 202).
    The caller polls GET /api/bench/job/<job_id> for the result.

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

    # Fire background thread, return job_id immediately so the browser
    # connection is not held open for the full inference duration.
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    t = threading.Thread(
        target=_run_bench_job,
        args=(job_id, backend, model, prompt, n_predict),
        daemon=True,
    )
    t.start()

    # Return the server-side timeout so the client can align its polling ceiling.
    return jsonify({"job_id": job_id, "timeout_s": BENCH_TIMEOUT}), 202


@app.route("/api/bench/job/<job_id>", methods=["GET"])
def api_bench_job(job_id: str):
    """
    Poll the status of a running or completed benchmark job.

    Returns one of:
        {"status": "running"}
        {"status": "done",  "result": { ... }}
        {"status": "error", "error":  "..."}
    404 if the job_id is not recognised.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown job_id"}), 404
    return jsonify(job), 200


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
    # threaded=True: each request gets its own thread so the long-running
    # /api/bench/job/<id> poll never blocks probe or data endpoints.
    # use_reloader=False: Werkzeug's file-watcher spawns a watchdog subprocess
    # that loops endlessly printing restart messages to the terminal — disabling
    # it prevents that console spam regardless of the DEBUG setting.
    app.run(host="0.0.0.0", port=port, debug=debug,
            threaded=True, use_reloader=False)
