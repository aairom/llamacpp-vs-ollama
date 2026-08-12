# Benchmarking Feature — Technical Reference

**Document version:** 1.0  
**Applies to:** llama.cpp vs Ollama — Visual Comparison App  
**Scope:** Benchmark Runner menu, associated REST API, backend runners, result storage, and analysis of potential parameter extensions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Menu Structure and Navigation](#2-menu-structure-and-navigation)
3. [Functionality Description](#3-functionality-description)
   - 3.1 [High-Level Architecture](#31-high-level-architecture)
   - 3.2 [Request Lifecycle](#32-request-lifecycle)
   - 3.3 [Ollama Benchmark Runner](#33-ollama-benchmark-runner)
   - 3.4 [llama.cpp Benchmark Runner](#34-llamacpp-benchmark-runner)
   - 3.5 [Result Storage and History](#35-result-storage-and-history)
4. [Parameters](#4-parameters)
   - 4.1 [API Request Parameters](#41-api-request-parameters)
   - 4.2 [Environment Variables](#42-environment-variables)
   - 4.3 [In-Memory Store Limits](#43-in-memory-store-limits)
5. [Usage Examples](#5-usage-examples)
   - 5.1 [Running a Benchmark via the Web UI](#51-running-a-benchmark-via-the-web-ui)
   - 5.2 [Running a Benchmark via the REST API](#52-running-a-benchmark-via-the-rest-api)
   - 5.3 [Polling a Background Job](#53-polling-a-background-job)
   - 5.4 [Retrieving Benchmark History](#54-retrieving-benchmark-history)
6. [Results Interpretation](#6-results-interpretation)
   - 6.1 [Metric Definitions](#61-metric-definitions)
   - 6.2 [Backend-Specific Metric Availability](#62-backend-specific-metric-availability)
   - 6.3 [History Table Color Coding](#63-history-table-color-coding)
   - 6.4 [Limitations of the Measurements](#64-limitations-of-the-measurements)
7. [Technical Analysis: Should `temperature` (or Stochastic Parameters) Be Added?](#7-technical-analysis-should-temperature-or-stochastic-parameters-be-added)
   - 7.1 [What `temperature` Controls in This Context](#71-what-temperature-controls-in-this-context)
   - 7.2 [Potential Benefits](#72-potential-benefits)
   - 7.3 [Potential Drawbacks and Risks](#73-potential-drawbacks-and-risks)
   - 7.4 [Recommendation and Implementation Guidance](#74-recommendation-and-implementation-guidance)

---

## 1. Overview

The **Benchmark Runner** is a built-in performance measurement subsystem embedded in the llama.cpp vs Ollama Visual Comparison Application. Its primary purpose is to allow a user to execute a real inference task against either of the two locally installed LLM backends — **Ollama** or **llama.cpp** — and to record precise, reproducible timing metrics that characterise that backend's inference performance under a controlled workload.

Unlike static comparison data (which is loaded from `data/comparison.json` and reflects general, editorial assessments), the Benchmark Runner produces **live, host-specific measurements** that reflect the actual hardware, model quantization, system load, and driver configuration present on the user's machine at the time of the test.

**When to use the Benchmark Runner:**

| Scenario | Rationale |
|---|---|
| Comparing inference speed between Ollama and llama.cpp on the same hardware | Eliminates hardware variability; both runs share the same CPU/GPU |
| Evaluating a newly downloaded model | Establishes a performance baseline for the model on the current machine |
| Detecting performance regressions after a software or driver upgrade | The history table allows before/after comparison |
| Investigating time-to-first-token (TTFT) latency for interactive use cases | TTFT is a first-class metric in the runner |
| Verifying that a particular model meets a minimum tokens-per-second threshold | The result card and history table display TPS prominently |

The Benchmark Runner does **not** measure output quality, correctness, or determinism. It is a latency and throughput measurement tool.

---

## 2. Menu Structure and Navigation

### 2.1 Sidebar Navigation

The application uses a single-page layout with a persistent left-hand sidebar. The Benchmark Runner is accessible via the **"Jump to"** section of the sidebar:

```
Sidebar
├── Categories
│   ├── [category items populated from comparison.json]
│   └── …
└── Jump to
    ├── ⚖️ Verdict & Summary
    ├── 📚 Sources
    └── 🏎️ Benchmark Runner          ← anchor link to #bench-section
```

Clicking **🏎️ Benchmark Runner** scrolls the main content area to the `#bench-section` element.

### 2.2 Benchmark Section Layout

Once the user navigates to the Benchmark Runner section, the layout is divided into three functional zones:

```
#bench-section
├── Introduction paragraph
├── Benchmark Form Card             ← input panel
│   ├── Backend selector (radio)
│   │   ├── 🦙 Ollama
│   │   └── ⚡ llama.cpp
│   ├── Model field (text input)
│   │   └── Model hints (auto-populated chips)
│   ├── Prompt field (textarea)
│   ├── Tokens to generate (number input)
│   └── ▶ Run Benchmark button
├── Result Card (hidden until first run)
│   ├── Result header (backend · model · timestamp · tokens requested)
│   ├── Metrics tile grid
│   ├── Command block (exact CLI or API call)
│   └── Prompt display block
└── History Table
    ├── Refresh (↻) button
    └── Table: Timestamp | Backend | Model | Tokens/s | Total Time | TTFT | Tokens
```

### 2.3 Backend Selector

The **Backend** radio group has two mutually exclusive options:

| Option | Value sent to API | Description |
|---|---|---|
| 🦙 Ollama | `"ollama"` | Routes the benchmark to the local Ollama daemon at `localhost:11434` via its streaming `/api/generate` endpoint |
| ⚡ llama.cpp | `"llamacpp"` | Routes the benchmark to the locally installed `llama` binary invoked as a subprocess |

Switching the backend selector immediately updates the **Model hints** area below the model field, showing models relevant to the selected backend.

### 2.4 Model Hints

The model hint area is automatically populated 2 seconds after page load by calling three probe endpoints in parallel:

- `GET /api/probe/llamacpp` — discovers the llama binary path
- `GET /api/probe/ollama` — retrieves installed Ollama models via `/api/tags`
- `GET /api/probe/llamacpp/models` — scans the filesystem for `.gguf` files

Discovered models are rendered as **clickable chips**. Clicking a chip fills the model input field with the appropriate value (model name for Ollama; absolute filesystem path for llama.cpp).

---

## 3. Functionality Description

### 3.1 High-Level Architecture

The Benchmark Runner is implemented across three layers:

```
┌─────────────────────────────────────────────────────┐
│  Browser (static/js/app.js)                         │
│  benchRun() → POST /api/bench → poll /api/bench/job │
└────────────────────┬────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────┐
│  Flask Backend (app.py)                             │
│  api_bench() → spawns background thread             │
│  _run_bench_job() → _bench_ollama() or              │
│                     _bench_llamacpp()               │
│  api_bench_job() → returns job status               │
│  api_bench_history() → reads bench_history.json     │
└───────────┬───────────────────┬─────────────────────┘
            │ HTTP              │ subprocess
┌───────────▼──────┐  ┌─────────▼────────────────────┐
│  Ollama daemon   │  │  llama binary                │
│  localhost:11434 │  │  PATH / ~/.local/bin          │
│  /api/generate   │  │  llama cli -m … -p … -n …    │
└──────────────────┘  └──────────────────────────────┘
```

### 3.2 Request Lifecycle

The benchmark is designed as an **asynchronous job** to prevent the HTTP connection from timing out during long inference runs (particularly on CPU-only machines or with large models). The sequence is as follows:

```
Client                            Server
  │                                 │
  │── POST /api/bench ─────────────►│  validates body, creates job_id
  │◄─ 202 Accepted {job_id} ────────│  spawns daemon thread, returns immediately
  │                                 │
  │── GET /api/bench/job/{id} ─────►│  (poll every 2 seconds)
  │◄─ 200 {status:"running"} ───────│
  │                                 │  [inference running in background thread]
  │── GET /api/bench/job/{id} ─────►│
  │◄─ 200 {status:"done", result} ──│
  │                                 │
  │── GET /api/bench/history ───────►│  (automatic refresh after done)
  │◄─ 200 [array of past results] ──│
```

**Client-side polling ceiling:** The client calculates its maximum polling duration as `timeout_s + 20` seconds, where `timeout_s` is the value of `BENCH_TIMEOUT` returned by the server in the 202 response. If the job does not reach a terminal state within this window, the client displays a timeout error.

**Server-side timeout:** `BENCH_TIMEOUT` seconds (default 300 s). For Ollama, this is passed as the `requests.post(timeout=)` argument. For llama.cpp, it is passed as the `proc.communicate(timeout=)` argument. Exceeding this limit triggers a `RuntimeError` that transitions the job to the `"error"` state.

### 3.3 Ollama Benchmark Runner

**Function:** [`_bench_ollama(model, prompt, n_predict)`](../app.py:140)

The Ollama runner uses the streaming `/api/generate` endpoint rather than the non-streaming version. This design choice enables **precise measurement of time-to-first-token (TTFT)** by recording the wall-clock timestamp of the first non-empty `response` chunk received from the stream.

**Processing steps:**

1. Record `t_start` using `time.monotonic()`.
2. Issue a streaming `POST` to `http://localhost:11434/api/generate` with the payload:
   ```json
   {
     "model":   "<model>",
     "prompt":  "<prompt>",
     "stream":  true,
     "options": { "num_predict": <n_predict> }
   }
   ```
3. Iterate over lines of the streaming response. For each JSON chunk:
   - If the `response` field is non-empty and `t_first_token` has not yet been recorded, record `t_first_token = time.monotonic()`.
   - When the `done` field is `true`, extract `eval_duration` (ns), `prompt_eval_duration` (ns), and `eval_count` (tokens generated). Break the loop.
4. Record `t_end = time.monotonic()`.
5. Compute derived metrics:
   - **TTFT** = `(t_first_token − t_start) × 1000` ms
   - **Total time** = `(t_end − t_start) × 1000` ms
   - **Eval time** = `eval_duration / 1,000,000` ms
   - **Prompt eval time** = `prompt_eval_duration / 1,000,000` ms
   - **Tokens per second** = `eval_count / (eval_ms / 1000)` (uses Ollama's internal timing for accuracy)

> **Note:** Ollama's internal `eval_duration` is preferred over wall-clock time for TPS calculation because it excludes network overhead and scheduler jitter.

**Error handling:**
- `ConnectionError` → raises `RuntimeError` prompting the user to start `ollama serve`.
- `Timeout` → raises `RuntimeError` suggesting a reduction in `n_predict`.

### 3.4 llama.cpp Benchmark Runner

**Function:** [`_bench_llamacpp(model, prompt, n_predict)`](../app.py:216)

The llama.cpp runner invokes the `llama` binary as a subprocess and parses its timing output.

**Binary resolution:** The function [`_find_llama_cli()`](../app.py:76) searches for a usable binary in the following order:

| Priority | Path / Name | Notes |
|---|---|---|
| 1 | `llama` (on PATH) | Modern dispatcher binary; invoked as `llama cli …` |
| 2 | `~/.local/bin/llama` | Explicit user install |
| 3 | `/usr/local/bin/llama` | System-wide install |
| 4 | `/opt/homebrew/bin/llama` | Homebrew (macOS) install |

**Command constructed:**

```
llama cli
  -m <model>
  -p <prompt>
  -n <n_predict>
  --no-conversation    (disable interactive REPL)
  --single-turn        (guarantee one-shot exit on reasoning models)
  --reasoning off      (suppress <think> blocks on Qwen3/DeepSeek models)
  --log-disable
  -e
```

**I/O handling:** The runner uses `subprocess.Popen` with `communicate()` rather than `subprocess.run(capture_output=True)`. This avoids a deadlock condition that arises when llama.cpp's verbose output fills the OS pipe buffer before the process exits.

**Output parsing (Format A — classic `llama_print_timings`):**

```
load time     =   123.45 ms
prompt eval time =   12.34 ms /  10 tokens (  1.23 ms per token, 123.45 tokens per second)
eval time     =  456.78 ms /  64 runs   (  7.13 ms per token,  89.77 tokens per second)
total time    =  580.12 ms /  74 tokens
```

Regular expressions extract: `load_ms`, `prompt_ms`, `eval_ms`, `total_ms_stat`, `eval_tps`, `prompt_tps`, `eval_tokens`, `prompt_tokens`.

**Output parsing (Format B — inline speed line, build b10217+):**

```
[ Prompt: 373.0 t/s | Generation: 88.3 t/s ]
```

If Format A fields are absent, Format B fields are used as fallback. `eval_ms` is derived from `n_predict / eval_tps × 1000` when the timing block is missing.

**TTFT approximation:**

```
ttft_ms = load_ms + prompt_ms   (if both available)
        = prompt_ms              (if only prompt_ms available)
```

This is an approximation: for llama.cpp, the model must be fully loaded into memory before the first token can be generated, making `load_time + prompt_eval_time` the earliest possible moment of first output.

**Error handling:** If the process exits with a non-zero return code and no timing metrics were parsed, the last 800 characters of `stderr` are surfaced as the error message.

### 3.5 Result Storage and History

**Storage file:** `data/bench_history.json`

After each successful benchmark, the result is appended to the persistent history file. The stored entry contains:

```json
{
  "timestamp": "2024-07-15T10:30:00Z",
  "backend":   "ollama",
  "model":     "llama3.2",
  "prompt":    "<first 200 characters of prompt>",
  "n_predict": 128,
  "metrics":   { … }
}
```

> The prompt is truncated to 200 characters for storage to prevent the history file from growing unbounded with long prompts. The live result object (returned via the job API) retains the full prompt text.

**Storage limits:**

| Limit | Value | Location |
|---|---|---|
| Maximum entries on disk | 50 | `BENCH_HISTORY_MAX` constant in `app.py` |
| Maximum completed jobs in memory | 100 | `JOB_STORE_MAX` constant in `app.py` |
| Entries displayed in UI history table | 10 | `history.slice(0, 10)` in `app.js` |

The history file is capped by slicing to `[-BENCH_HISTORY_MAX:]` on every write, ensuring older entries are automatically evicted.

---

## 4. Parameters

### 4.1 API Request Parameters

These parameters are submitted in the JSON body of `POST /api/bench`.

| Parameter | Type | Required | Default | Accepted Range / Values | Effect |
|---|---|---|---|---|---|
| `backend` | string | Yes | — | `"ollama"` \| `"llamacpp"` | Selects the inference backend. Routing to Ollama uses HTTP streaming; routing to llama.cpp uses a subprocess invocation. |
| `model` | string | Yes | — | Any non-empty string | For Ollama: the model tag as shown by `ollama list` (e.g., `llama3.2`, `mistral:7b`). For llama.cpp: the absolute filesystem path to a `.gguf` model file. |
| `prompt` | string | Yes | — | Any non-empty string | The input text sent to the model. Length affects prompt evaluation time and, consequently, TTFT. |
| `n_predict` | integer | No | `128` | 1 – 4096 | The maximum number of tokens the model is instructed to generate. Controls evaluation time and total time. Higher values increase benchmark duration proportionally to generation TPS. |
| `temperature` | float | No | N/A (not yet implemented — effective default is `0.0`, greedy decoding) | `0.0` – `2.0` (prospective) | **Not a live parameter in the current implementation.** The backend is always invoked in greedy-decoding mode (`temperature = 0.0`), which produces deterministic, reproducible results optimal for infrastructure benchmarking. For Ollama this would map to `"options": { "temperature": <value> }` in the `/api/generate` payload; for llama.cpp it would map to the `--temp <value>` CLI flag. See [Section 7](#7-technical-analysis-should-temperature-or-stochastic-parameters-be-added) for a full analysis of whether and how this parameter should be introduced. |

**Validation rules enforced server-side:**
- `backend` must be exactly `"ollama"` or `"llamacpp"` (case-insensitive after `.strip().lower()`).
- `model` must not be empty after stripping whitespace.
- `prompt` must not be empty after stripping whitespace.
- `n_predict` must satisfy `1 ≤ n_predict ≤ 4096`. Values outside this range return HTTP 400.
- `temperature` is not accepted by the current API; any value supplied in the request body is silently ignored.

### 4.2 Environment Variables

These variables control global benchmark behaviour and are read once at server startup.

| Variable | Type | Default | Description |
|---|---|---|---|
| `BENCH_TIMEOUT` | integer (seconds) | `300` | Maximum wall-clock time (in seconds) allowed for a single benchmark run. For Ollama, this is the HTTP request timeout. For llama.cpp, this is the subprocess `communicate()` timeout. If the inference does not complete within this window, the job transitions to `"error"`. Recommended minimum: 120 s for small models on CPU; 300 s for large models. |
| `PORT` | integer | `8080` (fallback), `8088` (`.env.example`) | HTTP port the Flask server listens on. |
| `DEBUG` | boolean string | `"false"` | Enables Flask debug mode. Should not be `"true"` in production as it disables Werkzeug's `use_reloader=False` guard. |

### 4.3 In-Memory Store Limits

These are compile-time constants defined in [`app.py`](../app.py) and are not configurable via environment variables.

| Constant | Value | Description |
|---|---|---|
| `BENCH_HISTORY_MAX` | 50 | Maximum entries persisted to `data/bench_history.json`. Oldest entries are evicted when this limit is exceeded. |
| `JOB_STORE_MAX` | 100 | Maximum completed (done or error) job entries retained in the in-memory `_jobs` dictionary. Oldest completed jobs are pruned on each successful write. Running jobs are never pruned. |

---

## 5. Usage Examples

### 5.1 Running a Benchmark via the Web UI

**Scenario:** Measure inference speed of `llama3.2` on Ollama with a 256-token output.

1. Open the application at `http://localhost:8088`.
2. In the sidebar, click **🏎️ Benchmark Runner**.
3. Under **Backend**, select **🦙 Ollama**.
4. In the **Model** field, click the `llama3.2` hint chip (or type `llama3.2` manually).
5. In the **Prompt** field, replace the default text with:
   ```
   Describe the process of photosynthesis in detail.
   ```
6. Set **Tokens to generate** to `256`.
7. Click **▶ Run Benchmark**.
8. The button changes to **⏳ Running… 0s** and increments every second.
9. After inference completes (typically 5–60 s depending on hardware), the **Result Card** appears displaying all metrics.
10. The **History Table** is automatically refreshed.

### 5.2 Running a Benchmark via the REST API

**Request:**

```bash
curl -X POST http://localhost:8088/api/bench \
  -H "Content-Type: application/json" \
  -d '{
    "backend":   "ollama",
    "model":     "llama3.2",
    "prompt":    "Describe the process of photosynthesis in detail.",
    "n_predict": 256
  }'
```

**Response (HTTP 202):**

```json
{
  "job_id":    "c3d8f2a1-4b5e-4c2d-9f1a-0e7b3c8d2f5a",
  "timeout_s": 300
}
```

**llama.cpp example:**

```bash
curl -X POST http://localhost:8088/api/bench \
  -H "Content-Type: application/json" \
  -d '{
    "backend":   "llamacpp",
    "model":     "/Users/alice/models/llama-3.2-1b-Q4_K_M.gguf",
    "prompt":    "Describe the process of photosynthesis in detail.",
    "n_predict": 256
  }'
```

### 5.3 Polling a Background Job

Using the `job_id` from the response above:

```bash
# Poll every 2 seconds
while true; do
  curl -s http://localhost:8088/api/bench/job/c3d8f2a1-4b5e-4c2d-9f1a-0e7b3c8d2f5a | python3 -m json.tool
  sleep 2
done
```

**Response while running:**

```json
{ "status": "running" }
```

**Response when complete:**

```json
{
  "status": "done",
  "result": {
    "timestamp":  "2024-07-15T10:30:00Z",
    "backend":    "ollama",
    "model":      "llama3.2",
    "prompt":     "Describe the process of photosynthesis in detail.",
    "n_predict":  256,
    "metrics": {
      "time_to_first_token_ms": 182.34,
      "total_time_ms":          8412.10,
      "eval_time_ms":           8220.50,
      "prompt_eval_time_ms":    163.10,
      "tokens_per_second":      29.87,
      "tokens_generated":       245,
      "command":                "ollama run llama3.2 \"Describe the process...\""
    }
  }
}
```

**Response on error:**

```json
{
  "status": "error",
  "error":  "Cannot connect to Ollama at localhost:11434 — is it running? Start it with: ollama serve"
}
```

### 5.4 Retrieving Benchmark History

```bash
curl http://localhost:8088/api/bench/history | python3 -m json.tool
```

Returns an array of up to 50 entries, most-recent first:

```json
[
  {
    "timestamp":  "2024-07-15T10:30:00Z",
    "backend":    "ollama",
    "model":      "llama3.2",
    "prompt":     "Describe the process of photosynthesis...",
    "n_predict":  256,
    "metrics": { … }
  },
  {
    "timestamp":  "2024-07-15T09:15:22Z",
    "backend":    "llamacpp",
    "model":      "/Users/alice/models/llama-3.2-1b-Q4_K_M.gguf",
    "prompt":     "Why is the sky blue? Explain concisely.",
    "n_predict":  128,
    "metrics": { … }
  }
]
```

---

## 6. Results Interpretation

### 6.1 Metric Definitions

| Metric Key | Display Label | Unit | Description |
|---|---|---|---|
| `tokens_per_second` | Tokens / sec | tok/s | The rate at which the model generates output tokens during the **evaluation (generation) phase**. This is the primary throughput metric. Higher is better. |
| `time_to_first_token_ms` | Time to First Token | ms or s | Elapsed time from the moment the request was issued until the first output token was received. Directly affects perceived responsiveness in interactive use cases. Lower is better. |
| `total_time_ms` | Total Time | ms or s | Total wall-clock duration from request submission to final token. For Ollama, this is measured by the Python client. For llama.cpp, this is the value from `llama_print_timings: total time` if available, otherwise the Python wall-clock measurement. |
| `eval_time_ms` | Eval Time | ms or s | Time spent in the token generation (sampling) loop, excluding model load and prompt processing. For Ollama, this is derived from `eval_duration` (nanoseconds) reported by the daemon. |
| `prompt_eval_time_ms` | Prompt Eval Time | ms or s | Time spent processing (encoding) the input prompt. Scales with prompt length. For Ollama, derived from `prompt_eval_duration`. |
| `tokens_generated` | Tokens Generated | tokens | The number of tokens actually produced. May be less than `n_predict` if the model emitted an end-of-sequence token earlier. |
| `load_time_ms` | Model Load Time | ms or s | *(llama.cpp only)* Time to load the model weights from disk into memory. This contributes to TTFT but is a one-time cost per invocation when Ollama is not caching the model. |
| `prompt_tokens_per_second` | Prompt Tok/s | tok/s | *(llama.cpp only)* Tokenization and encoding throughput for the input prompt. |
| `wall_time_ms` | — (internal) | ms | *(llama.cpp only)* Raw Python `time.monotonic()` measurement. Used as a fallback for `total_time_ms` when the parsed timing block is absent. |
| `command` | Command | — | The exact command string or API call used to invoke the backend. Useful for reproducing the measurement independently. |

### 6.2 Backend-Specific Metric Availability

| Metric | Ollama | llama.cpp |
|---|---|---|
| `tokens_per_second` | ✓ (from `eval_duration`) | ✓ (from timing block or inline speed line) |
| `time_to_first_token_ms` | ✓ (wall clock to first chunk) | ✓ (load_time + prompt_eval_time approximation) |
| `total_time_ms` | ✓ (wall clock) | ✓ (timing block or wall clock fallback) |
| `eval_time_ms` | ✓ | ✓ |
| `prompt_eval_time_ms` | ✓ | ✓ |
| `tokens_generated` | ✓ (from `eval_count`) | ✓ (from `eval time / N runs`) |
| `load_time_ms` | ✗ | ✓ |
| `prompt_tokens_per_second` | ✗ | ✓ |
| `wall_time_ms` | ✗ (same as `total_time_ms`) | ✓ (always present as fallback) |

### 6.3 History Table Color Coding

The **Tokens/s** column in the history table is color-coded to provide rapid visual classification:

| Color class | Threshold | Interpretation |
|---|---|---|
| `bench-tps-good` (green) | TPS ≥ 30 | Acceptable real-time performance for interactive chat |
| `bench-tps-mid` (amber) | 10 ≤ TPS < 30 | Perceptible but usable; may be acceptable for batch tasks |
| `bench-tps-slow` (red) | TPS < 10 | Noticeably slow; consider a smaller or more quantized model |
| No color | TPS = null | Metric not available for this run |

### 6.4 Limitations of the Measurements

The following factors can affect the reliability and comparability of benchmark results and should be taken into account when interpreting output:

- **System load:** Background processes competing for CPU, GPU, or memory bandwidth will increase latency and reduce TPS.
- **Thermal throttling:** Sustained inference on laptops without active cooling may cause the CPU or GPU to throttle, artificially degrading performance for longer runs.
- **Model caching:** Ollama keeps models resident in memory (VRAM or system RAM) between requests. The first benchmark run after loading a model will show higher TTFT due to model load; subsequent runs will not. llama.cpp loads the model fresh on each subprocess invocation.
- **Quantization:** The `.gguf` file used for llama.cpp must be specified by the user. Different quantization levels (Q4_K_M, Q8_0, F16, etc.) have significantly different speed and quality trade-offs.
- **`n_predict` vs actual tokens generated:** The `tokens_generated` field reflects the number of tokens the model actually produced, which may be less than `n_predict` if an EOS token was generated. TPS is computed from the actual generation count, not the requested maximum.
- **TTFT for llama.cpp is an approximation:** The value `load_time + prompt_eval_time` is the lower bound for TTFT; actual time-to-first-rendered-token may be slightly higher due to output buffering.

---

## 7. Technical Analysis: Should `temperature` (or Stochastic Parameters) Be Added?

### 7.1 What `temperature` Controls in This Context

In LLM inference, `temperature` is a scalar parameter applied to the logit distribution before the softmax sampling step. A value of `0.0` (or very near zero) makes the model deterministic by always selecting the token with the highest probability (greedy decoding). A value greater than `1.0` increases stochasticity, resulting in more varied and less predictable outputs.

In the context of the Benchmark Runner, adding `temperature` would affect:

1. **Token selection path:** At `temperature = 0.0`, most LLM runtimes use greedy decoding, which is a single `argmax` operation per token — computationally cheaper than nucleus or top-k sampling. At higher temperatures, the sampler must compute a weighted random draw from the full vocabulary distribution, adding a small but measurable overhead per token.

2. **Output length variance:** Greedy outputs tend to be more compact and often terminate sooner (via EOS). Stochastic outputs may produce longer sequences for the same `n_predict` budget, or terminate at different points depending on the random draw. This directly affects the denominator of the TPS calculation.

3. **Reproducibility:** At `temperature = 0.0`, identical inputs produce identical outputs across runs (subject to floating-point determinism on the same hardware). At `temperature > 0.0`, outputs differ between runs, making it impossible to compare results from separate benchmark runs as truly "same workload" comparisons.

For **Ollama**, this maps to `"options": { "temperature": <value> }` in the `/api/generate` payload. For **llama.cpp**, it maps to the `--temp <value>` CLI flag.

### 7.2 Potential Benefits

**A. Stress-testing the sampling pipeline**

At `temperature = 0.0`, many runtimes bypass the full sampling stack (top-p, top-k, mirostat) and use a simple greedy path. Running benchmarks at `temperature > 0.0` exercises the complete sampling pipeline and may reveal performance differences that are hidden when only the greedy path is active. This is relevant when the production use case involves non-zero temperature.

**B. Measuring variance in generation length**

For research or quality-assurance purposes, running multiple benchmarks at the same temperature setting and comparing the standard deviation of `tokens_generated` and `tokens_per_second` can characterise the stability of the inference backend under typical stochastic conditions.

**C. Alignment with production conditions**

Most production chatbot deployments use a non-zero temperature (commonly `0.7`–`0.9`). Benchmarking at `temperature = 0.0` may produce optimistic results that do not reflect real-world throughput.

**D. Cross-backend sampling path comparison**

Ollama and llama.cpp may implement their sampling stacks differently. Exposing `temperature` as a parameter would allow a user to verify whether the TPS differential between the two backends changes materially at non-greedy settings, which would indicate that the sampling implementation is a significant cost centre in one backend.

### 7.3 Potential Drawbacks and Risks

**A. Non-reproducible results undermine benchmark validity**

The primary purpose of a benchmark is to produce a stable, comparable metric. At `temperature > 0.0`, each run generates different output of potentially different length. Two runs with identical inputs may yield TPS values that differ by 10–30% purely due to output length variance. This makes the history table misleading: the user cannot distinguish genuine performance changes from statistical noise.

**B. Inconsistent token count distorts TPS**

TPS is defined as `tokens_generated / eval_time`. If `temperature > 0.0` causes the model to generate 80 tokens in one run and 190 tokens in another (both within the same `n_predict` budget), the reported TPS values are not comparable even under constant hardware conditions.

**C. Added UI and API complexity**

Introducing `temperature` as a user-facing parameter requires input validation (range: typically `0.0`–`2.0`), default value selection, documentation, and UI space in the form card. It also adds a conditional code path in both `_bench_ollama` and `_bench_llamacpp` to inject the parameter correctly for each backend's respective API format.

**D. Risk of misinterpretation by non-expert users**

Users unfamiliar with LLM sampling may not understand that changing `temperature` between benchmark runs makes those runs non-comparable. The history table currently shows no annotation distinguishing greedy from stochastic runs, which could lead to incorrect conclusions if the parameter is added without adequate UI labelling.

**E. Orthogonality to the benchmarking objective**

The Benchmark Runner is designed to measure **infrastructure performance** (latency, throughput, model load time) rather than **model quality** (coherence, diversity, instruction-following). `temperature` is a model quality parameter. Adding it conflates two distinct evaluation concerns.

### 7.4 Recommendation and Implementation Guidance

**Recommendation: Do not add `temperature` as a user-facing parameter in the current implementation. Add it as an optional, explicitly labelled parameter in a future "advanced mode" only if the following conditions are met.**

**Rationale:**

The core risk is that exposing `temperature` without strict guardrails will produce inconsistent benchmark results and mislead users who are trying to compare backends or track performance over time. The benchmarking objective — measuring infrastructure throughput — is best served by deterministic, reproducible runs. For this purpose, `temperature = 0.0` (greedy decoding) is the correct and sufficient setting, and it should be applied unconditionally as a non-configurable default.

The documented benefits (stress-testing the sampling pipeline, alignment with production conditions) are real but secondary concerns that are better addressed by a separate, explicitly labelled "sampling performance test" mode, distinct from the primary benchmark metric.

**If `temperature` is added in a future release, the following constraints are strongly recommended:**

| Constraint | Rationale |
|---|---|
| **Default value must be `0.0`** | Preserves backward compatibility and ensures the default benchmark is deterministic |
| **UI must display a warning when `temperature > 0.0`** | Example: *"Results at non-zero temperature are not deterministic. Use temperature = 0 for reproducible comparisons."* |
| **`temperature` must be stored in the history record** | Without this, historical results cannot be correctly interpreted |
| **History table must display `temperature` value** | Prevents silent comparison of deterministic and stochastic runs |
| **Validation range: `0.0` – `2.0`** | Values above 2.0 produce incoherent output and serve no benchmarking purpose |
| **Only inject the parameter when `temperature > 0.0`** | For Ollama: add `"temperature": <value>` to `options` only if non-zero; for llama.cpp: add `--temp <value>` only if non-zero. This avoids altering behaviour on backends that treat explicit `temperature=0` differently from absent `temperature` |

**Minimal implementation sketch (backend injection):**

For Ollama:
```python
# In _bench_ollama, extend options dict conditionally:
options: dict = {"num_predict": n_predict}
if temperature is not None and temperature > 0.0:
    options["temperature"] = temperature
payload = {"model": model, "prompt": prompt, "stream": True, "options": options}
```

For llama.cpp:
```python
# In _bench_llamacpp, append flag conditionally:
if temperature is not None and temperature > 0.0:
    cmd += ["--temp", str(temperature)]
```

In summary: `temperature = 0.0` should remain the hard-coded default for all benchmark runs in the current implementation. The parameter should be considered for addition only in a future "advanced / experimental" panel, accompanied by explicit reproducibility warnings and mandatory annotation of historical records.

---

*End of document.*
