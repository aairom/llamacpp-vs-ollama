/**
 * llama.cpp vs Ollama — Visual Comparison App
 * Main JavaScript: fetches data, renders all UI, handles interactions
 */

// ============================================================
// State
// ============================================================
let DATA = null;
let sourceMap = {};   // id -> { label, url, index }

// ============================================================
// Boot
// ============================================================
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([fetchData(), probeInstallations()]);
});

// ============================================================
// Data fetching
// ============================================================
async function fetchData() {
  try {
    const res = await fetch("/api/data");
    DATA = await res.json();
    buildSourceMap();
    render();
  } catch (err) {
    document.getElementById("categories-container").innerHTML =
      `<div style="color:#ff7b7b;padding:2rem">Failed to load comparison data: ${err.message}</div>`;
  }
}

function buildSourceMap() {
  DATA.meta.sources.forEach((s, i) => {
    sourceMap[s.id] = { ...s, index: i + 1 };
  });
}

// ============================================================
// LIVE PROBE
// ============================================================
async function probeInstallations() {
  const statusEl = document.getElementById("live-status");
  const dot = statusEl.querySelector(".live-dot");
  const span = statusEl.querySelector("span");

  try {
    const [llcResult, olResult] = await Promise.all([
      fetch("/api/probe/llamacpp").then(r => r.json()),
      fetch("/api/probe/ollama").then(r => r.json())
    ]);
    renderLiveBanner(llcResult, olResult);
    dot.className = "live-dot ok";
    span.textContent = "Local probe complete";
  } catch (err) {
    dot.className = "live-dot error";
    span.textContent = "Local probe failed";
  }
}

function renderLiveBanner(llc, ol) {
  const banner = document.getElementById("live-banner");
  banner.style.display = "";

  // llama.cpp card
  const lcStatus = document.getElementById("lc-status");
  const lcBody   = document.getElementById("lc-body");
  if (llc.installed) {
    lcStatus.textContent = "Installed";
    lcStatus.className = "status-tag installed";
    let html = `<div><strong>Version:</strong> ${esc(llc.version || "unknown")}</div>`;
    if (llc.tools && llc.tools.length) {
      html += `<div style="margin-top:0.35rem"><strong>Tools found:</strong></div>`;
      html += `<div class="live-model-list">` +
        llc.tools.map(t => `<span class="model-chip">${esc(t.name)}</span>`).join("") +
        `</div>`;
    }
    lcBody.innerHTML = html;
  } else {
    lcStatus.textContent = "Not found";
    lcStatus.className = "status-tag not-found";
    lcBody.innerHTML = `<div style="color:#ff7b7b">${esc(llc.error || "Binary not found")}</div>
      <div style="margin-top:0.35rem"><a href="https://github.com/ggml-org/llama.cpp/releases" target="_blank">Download from GitHub ↗</a></div>`;
  }

  // Ollama card
  const olStatus = document.getElementById("ol-status");
  const olBody   = document.getElementById("ol-body");
  if (ol.installed) {
    olStatus.textContent = "Installed";
    olStatus.className = "status-tag installed";
    let html = `<div><strong>Version:</strong> ${esc(ol.version || "unknown")}</div>`;
    if (ol.models && ol.models.length) {
      html += `<div style="margin-top:0.35rem"><strong>Models (${ol.models.length}):</strong></div>`;
      html += `<div class="live-model-list">` +
        ol.models.map(m => {
          const label = m.name.split(":")[0];
          const tag   = m.name.includes(":") ? m.name.split(":")[1] : "";
          const qInfo = m.quantization ? ` · ${m.quantization}` : "";
          const pInfo = m.parameter_size ? ` · ${m.parameter_size}` : "";
          return `<span class="model-chip" title="${esc(m.name)}">${esc(label)}<span class="chip-size">${esc(tag)}${pInfo}${qInfo}</span></span>`;
        }).join("") +
        `</div>`;
    } else if (ol.error) {
      html += `<div style="color:#f5a623;margin-top:0.25rem">API: ${esc(ol.error)}</div>`;
    }
    olBody.innerHTML = html;
  } else {
    olStatus.textContent = "Not found";
    olStatus.className = "status-tag not-found";
    olBody.innerHTML = `<div style="color:#ff7b7b">${esc(ol.error || "Binary not found")}</div>
      <div style="margin-top:0.35rem"><a href="https://ollama.com/download" target="_blank">Download from ollama.com ↗</a></div>`;
  }
}

// ============================================================
// MAIN RENDER
// ============================================================
function render() {
  renderScoreSummary();
  renderCategories();
  renderVerdict();
  renderSources();
  initScrollSpy();
}

// ============================================================
// SCORE OVERVIEW (above categories, small visual scoreboard)
// ============================================================
// Score mapping for visual bars (out of 10)
const SCORES = {
  architecture: { llama: 9, ollama: 7 },
  openness:     { llama: 10, ollama: 5 },
  model_support:{ llama: 10, ollama: 7 },
  api:          { llama: 9, ollama: 8 },
  hardware:     { llama: 10, ollama: 6 },
  performance:  { llama: 9, ollama: 7 },
  configuration:{ llama: 10, ollama: 5 },
  deployment:   { llama: 10, ollama: 7 },
  ecosystem:    { llama: 8, ollama: 9 },
  limitations:  { llama: 7, ollama: 7 },
};

function renderScoreSummary() {
  // Inject a score overview above the categories
  const main = document.getElementById("categories-container");
  const scores = Object.entries(SCORES);
  const llamaTotal = scores.reduce((s, [, v]) => s + v.llama, 0);
  const ollamaTotal = scores.reduce((s, [, v]) => s + v.ollama, 0);

  const introHtml = `
    <div class="score-overview" style="padding:1.5rem 0 0.5rem; border-bottom:1px solid var(--border); margin-bottom:0;">
      <div style="display:flex;align-items:center;gap:2rem;margin-bottom:1.2rem;">
        <div>
          <div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.25rem">Overall Score</div>
          <div style="display:flex;align-items:baseline;gap:1.5rem;">
            <span style="font-size:2rem;font-weight:800;color:var(--accent-llama)">${llamaTotal}<span style="font-size:0.85rem;color:var(--text-muted)">/100</span></span>
            <span style="font-size:0.9rem;color:var(--text-muted)">vs</span>
            <span style="font-size:2rem;font-weight:800;color:var(--accent-ollama)">${ollamaTotal}<span style="font-size:0.85rem;color:var(--text-muted)">/100</span></span>
          </div>
          <div style="display:flex;gap:1.5rem;margin-top:0.25rem;font-size:0.75rem;color:var(--text-muted)">
            <span style="color:var(--accent-llama)">●</span> llama.cpp &nbsp;
            <span style="color:var(--accent-ollama)">●</span> Ollama
          </div>
        </div>
        <div style="flex:1;max-width:400px">
          ${scores.map(([key, val]) => {
            const cat = DATA.categories.find(c => c.id === key);
            const label = cat ? cat.label.replace(/ & .*/,'') : key;
            return `
              <div class="score-row">
                <div class="score-label">${esc(label)}</div>
                <div class="score-bar-wrap">
                  <div class="score-bar"><div class="score-fill llama" style="width:${val.llama * 10}%"></div></div>
                  <div class="score-val">${val.llama}</div>
                </div>
                <div class="score-bar-wrap">
                  <div class="score-bar"><div class="score-fill ollama" style="width:${val.ollama * 10}%"></div></div>
                  <div class="score-val">${val.ollama}</div>
                </div>
              </div>`;
          }).join("")}
        </div>
      </div>
      <p style="font-size:0.75rem;color:var(--text-muted);padding-bottom:0.5rem">Scores are editorial assessments based on research (1–10 per category, 10 = best). See each category for sourced evidence.</p>
    </div>`;
  main.insertAdjacentHTML("beforeend", introHtml);
}

// ============================================================
// CATEGORIES
// ============================================================
function renderCategories() {
  const container = document.getElementById("categories-container");
  const navList = document.getElementById("nav-list");

  DATA.categories.forEach(cat => {
    // Nav item
    const li = document.createElement("li");
    li.innerHTML = `<a href="#cat-${cat.id}" class="nav-item">${cat.icon} ${cat.label}</a>`;
    navList.appendChild(li);

    // Category section
    const section = document.createElement("section");
    section.className = "category-section";
    section.id = `cat-${cat.id}`;
    section.setAttribute("data-cat", cat.id);

    section.innerHTML = `
      <div class="category-heading">
        <span class="category-icon">${cat.icon}</span>
        <span class="category-title">${esc(cat.label)}</span>
      </div>
      <p class="category-description">${esc(cat.description)}</p>
      <div class="comparison-grid">
        <div class="comparison-label">
          <span class="label-text">Summary &amp; key points</span>
        </div>
        ${renderCard(cat, "llamacpp")}
        ${renderCard(cat, "ollama")}
      </div>
    `;

    container.appendChild(section);

    // Wire expand buttons
    section.querySelectorAll(".card-expand-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const tool = btn.dataset.tool;
        const data = cat[tool];
        openModal(cat, tool, data);
      });
    });
  });
}

function renderCard(cat, tool) {
  const d = cat[tool];
  const verdict = d.verdict || "neutral";
  const verdictLabel = verdict === "advantage" ? "Advantage" : verdict === "limited" ? "Limited" : "Neutral";

  // Show first 4 detail chips
  const chips = (d.details || []).slice(0, 4).map((detail, i) => {
    const highlight = i === 0 ? " highlight" : "";
    return `<span class="detail-chip${highlight}">${esc(detail)}</span>`;
  }).join("");

  // Source refs
  const srcRefs = (d.sources || []).map(sid => {
    const src = sourceMap[sid];
    if (!src) return "";
    return `<a href="${esc(src.url)}" target="_blank" rel="noopener" title="${esc(src.label)}">[${src.index}]</a>`;
  }).join(" ");

  return `
    <div class="comparison-card verdict-${verdict}">
      <span class="card-verdict ${verdict}">${verdictLabel}</span>
      <p class="card-summary">${esc(d.summary)}</p>
      <div class="card-details-preview">${chips}</div>
      <button class="card-expand-btn" data-tool="${tool}" data-cat="${cat.id}">
        All ${(d.details || []).length} details →
      </button>
      ${srcRefs ? `<div class="card-sources">Sources: ${srcRefs}</div>` : ""}
    </div>`;
}

// ============================================================
// MODAL
// ============================================================
function openModal(cat, tool, data) {
  const overlay = document.getElementById("modal-overlay");
  const content = document.getElementById("modal-content");
  const toolName = tool === "llamacpp" ? "llama.cpp" : "Ollama";
  const verdict = data.verdict || "neutral";
  const verdictLabel = verdict === "advantage" ? "✅ Advantage" : verdict === "limited" ? "⚠️ Limited" : "⚪ Neutral";

  const srcLinks = (data.sources || []).map(sid => {
    const src = sourceMap[sid];
    if (!src) return "";
    return `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.label)}</a>`;
  }).join(" · ");

  const detailItems = (data.details || []).map(d =>
    `<li><em>${esc(d)}</em></li>`
  ).join("");

  content.innerHTML = `
    <div class="modal-title">
      ${cat.icon} ${esc(cat.label)} — <span style="color:${tool === "llamacpp" ? "var(--accent-llama)" : "var(--accent-ollama)"}">${toolName}</span>
      <span class="card-verdict ${verdict}" style="position:static;margin-left:0.5rem">${verdictLabel}</span>
    </div>
    <p class="modal-summary">${esc(data.summary)}</p>
    <ul class="modal-detail-list">${detailItems}</ul>
    ${srcLinks ? `<div style="margin-top:1rem;font-size:0.75rem;color:var(--text-muted)">Sources: ${srcLinks}</div>` : ""}`;

  overlay.style.display = "flex";
}

document.getElementById("modal-close").addEventListener("click", () => {
  document.getElementById("modal-overlay").style.display = "none";
});
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target === document.getElementById("modal-overlay")) {
    document.getElementById("modal-overlay").style.display = "none";
  }
});

// ============================================================
// VERDICT
// ============================================================
function renderVerdict() {
  const v = DATA.verdict;

  document.getElementById("verdict-content").innerHTML = `
    <div class="verdict-summary-box">${esc(v.summary)}</div>`;

  document.getElementById("use-case-grid").innerHTML = `
    <div class="use-case-card">
      <div class="use-case-title llamacpp">⚡ Choose llama.cpp when…</div>
      <ul class="use-case-list">
        ${v.use_llamacpp_when.map(u => `<li>${esc(u)}</li>`).join("")}
      </ul>
    </div>
    <div class="use-case-card">
      <div class="use-case-title ollama">🦙 Choose Ollama when…</div>
      <ul class="use-case-list">
        ${v.use_ollama_when.map(u => `<li>${esc(u)}</li>`).join("")}
      </ul>
    </div>`;

  document.getElementById("openness-box").innerHTML =
    `<strong>On Openness:</strong> ${esc(v.openness_verdict)}`;
}

// ============================================================
// SOURCES
// ============================================================
function renderSources() {
  const list = document.getElementById("sources-list");
  list.innerHTML = DATA.meta.sources.map((src, i) => `
    <div class="source-item">
      <span class="source-num">${i + 1}</span>
      <div class="source-label">
        <a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.label)}</a>
      </div>
    </div>`).join("");
}

// ============================================================
// SCROLL SPY (highlight active nav item)
// ============================================================
function initScrollSpy() {
  const sections = document.querySelectorAll("[data-cat]");
  const navItems = document.querySelectorAll(".nav-item[href^='#cat-']");

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        navItems.forEach(a => {
          a.classList.toggle("active", a.getAttribute("href") === `#${id}`);
        });
      }
    });
  }, { rootMargin: "-20% 0px -70% 0px" });

  sections.forEach(s => observer.observe(s));
}

// ============================================================
// HELPERS
// ============================================================
function esc(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


// ============================================================
// BENCHMARK MODULE
// ============================================================

// State for the benchmark section
const bench = {
  running:    false,
  ollamaModels: [],   // populated from probe
  llamaTools:   [],   // populated from probe
};

// Wait until DOM is ready, then wire up benchmark UI
document.addEventListener("DOMContentLoaded", () => {
  benchInit();
});

function benchInit() {
  // Load existing history on page open
  benchLoadHistory();

  // Wire "Run Benchmark" button
  document.getElementById("bench-run-btn").addEventListener("click", benchRun);

  // Wire refresh button
  document.getElementById("bench-history-refresh").addEventListener("click", benchLoadHistory);

  // When backend radio changes, update model hint
  document.querySelectorAll('input[name="bench-backend"]').forEach(radio => {
    radio.addEventListener("change", benchUpdateModelHint);
  });

  // Populate model hints once probe data arrives
  // We patch probeInstallations by also calling benchPopulateHints when it resolves.
  // We do this by hooking into the live-banner rendering which fires after probe.
  const origRenderLiveBanner = window.__origRenderLiveBanner || renderLiveBanner;
  window.__benchHookInstalled = true;
}

/**
 * Populate model hints for both backends.
 * Ollama: uses /api/probe/ollama for model names.
 * llama.cpp: uses /api/probe/llamacpp/models which resolves Ollama blobs
 *            + scans common GGUF directories.
 */
async function benchPopulateHints() {
  try {
    const [llcProbe, olProbe, llcModels] = await Promise.all([
      fetch("/api/probe/llamacpp").then(r => r.json()),
      fetch("/api/probe/ollama").then(r => r.json()),
      fetch("/api/probe/llamacpp/models").then(r => r.json()),
    ]);
    bench.ollamaModels  = (olProbe.models || []).map(m => m.name);
    bench.llamaTools    = (llcProbe.tools || []).map(t => t.path);
    bench.llamaGgufModels = llcModels.models || [];   // [{name, path, source, size_gb}]
    benchUpdateModelHint();
  } catch (_) { /* silently ignore */ }
}

// Auto-populate hints after page loads (slight delay to avoid racing the probe)
setTimeout(benchPopulateHints, 2000);

function benchUpdateModelHint() {
  const backend = document.querySelector('input[name="bench-backend"]:checked')?.value || "ollama";
  const hintEl  = document.getElementById("bench-model-hint");

  if (backend === "ollama") {
    if (bench.ollamaModels.length) {
      hintEl.innerHTML = "Installed models: " +
        bench.ollamaModels.map(m =>
          `<span class="hint-chip" onclick="document.getElementById('bench-model').value='${esc(m)}'">${esc(m)}</span>`
        ).join("") +
        " <span style='opacity:.5'>(click to fill)</span>";
    } else {
      hintEl.textContent = "Enter a model name as listed by: ollama list";
    }
  } else {
    // llama.cpp panel
    const ggufModels = bench.llamaGgufModels || [];
    if (ggufModels.length) {
      const chips = ggufModels.map(m => {
        const label   = m.name;
        const sizeTip = m.size_gb ? ` (${m.size_gb} GB)` : "";
        const src     = m.source === "ollama" ? " 🦙" : "";
        // Safe JS string: the path goes into a JS string literal inside onclick
        const safePath = m.path.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        return `<span class="hint-chip" title="${esc(m.path)}${sizeTip}"
          onclick="document.getElementById('bench-model').value='${safePath}'"
          >${esc(label)}${esc(src)}${esc(sizeTip)}</span>`;
      }).join("");
      const binaryNote = bench.llamaTools.length
        ? `Binary: <code style="color:var(--accent-llama)">${esc(bench.llamaTools[0])}</code> &nbsp;·&nbsp; `
        : "";
      hintEl.innerHTML = binaryNote + "Available models: " + chips +
        " <span style='opacity:.5'>(click to fill path)</span>";
    } else if (bench.llamaTools.length) {
      hintEl.innerHTML = "Binary: <code style='color:var(--accent-llama)'>" +
        esc(bench.llamaTools[0]) + "</code> — enter a full .gguf path as the model.";
    } else {
      hintEl.textContent = "Enter the full path to a .gguf model file, e.g. /Users/me/models/llama3.2.Q4_K_M.gguf";
    }
  }
}

async function benchRun() {
  if (bench.running) return;

  const backend   = document.querySelector('input[name="bench-backend"]:checked')?.value || "ollama";
  const model     = document.getElementById("bench-model").value.trim();
  const prompt    = document.getElementById("bench-prompt").value.trim();
  const n_predict = parseInt(document.getElementById("bench-n-predict").value, 10) || 128;
  const errEl     = document.getElementById("bench-error");
  const resultCard = document.getElementById("bench-result-card");

  // Client-side validation
  errEl.style.display = "none";
  if (!model) {
    benchShowError("Please enter a model name or path.");
    return;
  }
  if (!prompt) {
    benchShowError("Please enter a prompt.");
    return;
  }

  // UI: running state
  bench.running = true;
  const btn        = document.getElementById("bench-run-btn");
  const btnText    = document.getElementById("bench-btn-text");
  const btnSpinner = document.getElementById("bench-btn-spinner");
  btn.disabled = true;
  btnText.style.display    = "none";
  btnSpinner.style.display = "";
  resultCard.style.display = "none";

  // Show a live elapsed-time ticker so the user knows the run is progressing,
  // not frozen.  llama.cpp on CPU can legitimately take 60-180 s.
  let elapsed = 0;
  const ticker = setInterval(() => {
    elapsed += 1;
    btnSpinner.textContent = `⏳ Running… ${elapsed}s`;
  }, 1000);

  // Hard client-side timeout matches BENCH_TIMEOUT + 10 s buffer.
  const FETCH_TIMEOUT_MS = 310_000;
  const controller = new AbortController();
  const timeoutId  = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch("/api/bench", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backend, model, prompt, n_predict }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const data = await res.json();

    if (!res.ok || data.error) {
      benchShowError(data.error || `Server error ${res.status}`);
      return;
    }

    benchRenderResult(data);
    benchLoadHistory();     // refresh history table
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === "AbortError") {
      benchShowError(
        `Benchmark timed out after ${FETCH_TIMEOUT_MS / 1000}s. ` +
        "Try a smaller model, fewer tokens, or check the server log."
      );
    } else {
      benchShowError(`Network error: ${err.message}`);
    }
  } finally {
    clearInterval(ticker);
    bench.running = false;
    btn.disabled = false;
    btnText.style.display    = "";
    btnSpinner.style.display = "none";
    btnSpinner.textContent   = ""; // reset ticker text
  }
}

function benchShowError(msg) {
  const errEl = document.getElementById("bench-error");
  errEl.textContent = msg;
  errEl.style.display = "";
}

function benchRenderResult(data) {
  const m = data.metrics || {};
  const card = document.getElementById("bench-result-card");
  card.style.display = "";

  // Header
  document.getElementById("bench-result-header").innerHTML =
    `<strong>${esc(data.backend === "ollama" ? "🦙 Ollama" : "⚡ llama.cpp")}</strong> · ` +
    `<strong>${esc(data.model)}</strong><br>` +
    `<span style="font-size:0.72rem">${esc(data.timestamp)} · ${esc(String(data.n_predict))} tokens requested · ` +
    `Prompt: "${esc((data.prompt || "").slice(0, 80))}${(data.prompt || "").length > 80 ? "…" : ""}"</span>`;

  // Metrics tiles
  const metrics = [
    {
      label: "Tokens / sec",
      value: m.tokens_per_second != null ? m.tokens_per_second.toFixed(2) : null,
      unit: "tok/s",
      primary: true,
    },
    {
      label: "Time to First Token",
      value: m.time_to_first_token_ms != null ? _fmtMs(m.time_to_first_token_ms) : null,
      unit: "",
    },
    {
      label: "Total Time",
      value: _fmtMs(m.total_time_ms ?? m.wall_time_ms),
      unit: "",
    },
    {
      label: "Eval Time",
      value: m.eval_time_ms != null ? _fmtMs(m.eval_time_ms) : null,
      unit: "",
    },
    {
      label: "Prompt Eval Time",
      value: m.prompt_eval_time_ms != null ? _fmtMs(m.prompt_eval_time_ms) : null,
      unit: "",
    },
    {
      label: "Tokens Generated",
      value: m.tokens_generated != null ? String(m.tokens_generated) : null,
      unit: "tokens",
    },
    // llama.cpp extras
    ...(m.load_time_ms != null ? [{
      label: "Model Load Time",
      value: _fmtMs(m.load_time_ms),
      unit: "",
    }] : []),
    ...(m.prompt_tokens_per_second != null ? [{
      label: "Prompt Tok/s",
      value: m.prompt_tokens_per_second.toFixed(2),
      unit: "tok/s",
    }] : []),
  ];

  document.getElementById("bench-metrics-grid").innerHTML = metrics.map(met => `
    <div class="bench-metric${met.primary ? " primary" : ""}">
      <div class="bench-metric-label">${esc(met.label)}</div>
      ${met.value != null
        ? `<div class="bench-metric-value">${esc(met.value)}</div>
           ${met.unit ? `<div class="bench-metric-unit">${esc(met.unit)}</div>` : ""}`
        : `<div class="bench-metric-na">—</div>`
      }
    </div>`).join("");
}

async function benchLoadHistory() {
  try {
    const res = await fetch("/api/bench/history");
    const history = await res.json();
    benchRenderHistory(history.slice(0, 10));  // show last 10 in UI
  } catch (_) { /* silently ignore */ }
}

function benchRenderHistory(rows) {
  const tbody = document.getElementById("bench-history-body");
  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="bench-empty">No runs yet — run your first benchmark above.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map((r, idx) => {
    const m    = r.metrics || {};
    const tps  = m.tokens_per_second;
    const tpsClass = tps == null ? "" : tps >= 30 ? "bench-tps-good" : tps >= 10 ? "bench-tps-mid" : "bench-tps-slow";
    const tpsStr   = tps != null ? tps.toFixed(1) : "—";
    const ttft = m.time_to_first_token_ms;
    const totalMs = m.total_time_ms ?? m.wall_time_ms;

    return `<tr class="${idx === 0 ? "bench-new-row" : ""}">
      <td style="font-size:0.72rem;color:var(--text-muted)">${esc((r.timestamp || "").replace("T", " ").replace("Z", ""))}</td>
      <td class="${r.backend === "ollama" ? "bench-badge-ollama" : "bench-badge-llamacpp"}">${r.backend === "ollama" ? "🦙 Ollama" : "⚡ llama.cpp"}</td>
      <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.model)}">${esc(r.model)}</td>
      <td class="${tpsClass}">${tpsStr}</td>
      <td>${totalMs != null ? esc(_fmtMs(totalMs)) : "—"}</td>
      <td>${ttft != null ? esc(_fmtMs(ttft)) : "—"}</td>
      <td>${m.tokens_generated != null ? esc(String(m.tokens_generated)) : "—"}</td>
    </tr>`;
  }).join("");
}

/** Format milliseconds as a human-readable string: e.g. 1234 ms → "1.23 s", 45 ms → "45 ms" */
function _fmtMs(ms) {
  if (ms == null) return "—";
  if (ms >= 1000) return (ms / 1000).toFixed(2) + " s";
  return ms.toFixed(0) + " ms";
}
