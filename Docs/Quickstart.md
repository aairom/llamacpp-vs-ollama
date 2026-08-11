# Quickstart Guide

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.9+ | `python3 --version` |
| pip | bundled with Python 3.9+ |
| Ollama (optional) | for live model probe and Ollama benchmarks |
| llama.cpp (optional) | for live binary probe and llama-cli benchmarks |

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8088` (`.env.example`), `8080` (app fallback without `.env`) | HTTP port |
| `DEBUG` | `false` | Enable Flask debug mode |
| `BENCH_TIMEOUT` | `300` | Max seconds to wait per benchmark run |

---

## Step-by-Step

### 1. Enter the project directory

```bash
cd /path/to/llamacpp-vs-ollama
```

### 2. Copy the environment file

```bash
cp .env.example .env
```

Default settings:

```
PORT=8088
DEBUG=false
# Maximum seconds to wait for a single benchmark run
BENCH_TIMEOUT=120
```

> **macOS note:** Port 5000 is reserved by AirDrop. The `.env.example` default port is **8088**.
> If you skip the `.env` file and start `app.py` directly, it falls back to port **8080**.

### 3. Launch (detached, recommended)

```bash
bash scripts/launch.sh
```

Output:

```
🔧  Creating virtual environment…
📦  Installing / verifying dependencies…
🚀  Starting comparison app…

  ✅  llama.cpp vs Ollama Comparison App is running!
  ➜   http://localhost:8088

  PID   : 12345
  Log   : ./output/app.log
  Stop  : ./scripts/stop.sh
```

Open **http://localhost:8088** in your browser.

### 4. Stop the app

```bash
bash scripts/stop.sh
```

---

## Manual (foreground) start

```bash
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

---

## Using the Benchmark Runner

The **Benchmark Runner** section (accessible via the sidebar) lets you run timed inference on either backend and compare the results.

1. Select a backend: **Ollama** or **llama-cli**
2. Pick a model from the auto-discovered list (populated via `/api/probe/llamacpp/models` or `/api/probe/ollama`)
3. Enter a prompt and set `n_predict` (number of tokens to generate, default 128)
4. Click **Run Benchmark**
5. Results (tokens/second, TTFT, eval time) appear immediately and are saved to `data/bench_history.json`

> Benchmark results persist across restarts. Up to **50 runs** are stored in `data/bench_history.json`; the **History** view in the UI displays the most recent **10**.

---

## Updating comparison data

Edit [`data/comparison.json`](../data/comparison.json) directly.  
The UI re-reads the file on each page load — no restart required.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Port already in use | Change `PORT=8089` in `.env` and re-run |
| `flask` not found | Run `pip install -r requirements.txt` |
| `requests` not found | Run `pip install -r requirements.txt` |
| Live probe shows "Not found" for Ollama | Start Ollama: `ollama serve` |
| Live probe shows "Not found" for llama.cpp | Install from [GitHub releases](https://github.com/ggml-org/llama.cpp/releases) |
| Benchmark fails for Ollama | Confirm daemon is running: `ollama serve`, and model is pulled: `ollama pull <model>` |
| Benchmark fails for llama-cli | Ensure `llama-cli` is in PATH or `~/.local/bin` and the model path is a valid GGUF file |
| Benchmark times out | Increase `BENCH_TIMEOUT` env var (default 120 s) or reduce `n_predict` |
| App fails to start | Check `output/app.log` for error details |
