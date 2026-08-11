# Architecture

## System Overview

```mermaid
flowchart TD
    subgraph Browser["Browser — Single Page App"]
        direction TB
        A[index.html shell] --> B[app.js — vanilla JS]
        B --> C[Score overview]
        B --> D[10 category sections]
        B --> E[Verdict + Sources]
        B --> F[Live probe banner]
        B --> G[Benchmark runner]
    end

    subgraph Flask["Flask Backend — app.py"]
        H[GET /]
        I[GET /api/data]
        J[GET /api/probe/llamacpp]
        K[GET /api/probe/llamacpp/models]
        L[GET /api/probe/ollama]
        M[POST /api/bench]
        N[GET /api/bench/history]
    end

    subgraph Local["Local Machine"]
        O[(data/comparison.json)]
        P[(data/bench_history.json)]
        Q[llama-cli binary\nPATH / ~/.local/bin\n/opt/homebrew/bin / /usr/local/bin]
        R[Ollama daemon\nlocalhost:11434]
        S[GGUF files\n~/.ollama/blobs\n~/.cache/huggingface/hub\n~/Library/Caches/llama.cpp (macOS)\n~/.cache/llama.cpp (Linux)\n~/models, ~/Downloads]
    end

    Browser -->|HTTP| Flask
    H -->|render_template| Browser
    I -->|reads JSON| O
    J -->|subprocess which / --version + extra paths| Q
    K -->|walks filesystem (4 source types)| S
    L -->|subprocess ollama --version\nHTTP /api/tags| R
    M -->|subprocess llama-cli| Q
    M -->|HTTP streaming /api/generate| R
    M -->|reads/writes| P
    N -->|reads| P
```

## Data Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as Flask
    participant D as data/comparison.json
    participant BH as data/bench_history.json
    participant LC as llama-cli binary
    participant OL as Ollama API

    B->>F: GET /
    F-->>B: index.html

    par Load comparison data
        B->>F: GET /api/data
        F->>D: read file
        D-->>F: JSON
        F-->>B: comparison data
    and Probe llama.cpp
        B->>F: GET /api/probe/llamacpp
        F->>LC: which llama-cli / --version
        LC-->>F: binary paths + version
        F-->>B: {installed, version, tools}
    and Probe Ollama
        B->>F: GET /api/probe/ollama
        F->>OL: ollama --version
        F->>OL: GET /api/tags
        OL-->>F: version + model list
        F-->>B: {installed, version, models[]}
    end

    B->>B: Render UI (score bars, cards, modals)

    note over B,F: Benchmark flow (user-triggered)

    B->>F: GET /api/probe/llamacpp/models
    F-->>B: GGUF model list (Ollama blobs + local dirs)

    B->>F: POST /api/bench {backend, model, prompt, n_predict}
    alt backend = ollama
        F->>OL: POST /api/generate (streaming)
        OL-->>F: streamed tokens + eval_duration
    else backend = llamacpp
        F->>LC: llama-cli -m model -p prompt -n n_predict
        LC-->>F: stdout/stderr with llama_print_timings
    end
    F->>BH: append result
    F-->>B: {timestamp, backend, model, metrics}

    B->>F: GET /api/bench/history
    F->>BH: read last 50 entries (stored cap)
    F-->>B: results array, most-recent first (UI shows last 10)
```

## Key Metrics Captured per Benchmark Run

| Metric | Ollama | llama-cli |
|---|---|---|
| `time_to_first_token_ms` | Wall clock to first non-empty chunk | `load_time + prompt_eval_time` |
| `tokens_per_second` | From `eval_duration` (daemon-reported) | From `llama_print_timings: eval time` |
| `eval_time_ms` | `eval_duration` converted from ns | `llama_print_timings: eval time` |
| `prompt_eval_time_ms` | `prompt_eval_duration` converted from ns | `llama_print_timings: prompt eval time` |
| `load_time_ms` | — | `llama_print_timings: load time` |
| `wall_time_ms` | `total_time_ms` | Measured by Python `time.monotonic()` |
