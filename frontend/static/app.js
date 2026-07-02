const el = (id) => document.getElementById(id);

const state = {
  payload: null,
  urlOptions: [],
  filteredUrlOptions: [],
  selectedImageUrl: "",
};

function safeNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function setStatus(msg, bad = false) {
  const s = el("status");
  s.textContent = msg;
  s.style.color = bad ? "#b42318" : "#4d6068";
}

function updateSelectedImage(url) {
  state.selectedImageUrl = url || "";
  el("uploadPreview").src = state.selectedImageUrl;
}

function populateUrlSelect(options) {
  const select = el("imageUrlSelect");
  const previousSelection = select.value || state.selectedImageUrl;
  select.innerHTML = "";

  if (!options.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No URLs found";
    select.appendChild(opt);
    updateSelectedImage("");
    return;
  }

  for (const url of options) {
    const opt = document.createElement("option");
    opt.value = url;
    opt.textContent = url;
    select.appendChild(opt);
  }

  const nextSelection = options.includes(previousSelection) ? previousSelection : options[0];
  select.value = nextSelection;
  updateSelectedImage(nextSelection);
}

async function loadReferenceImageOptions() {
  const response = await fetch("/api/reference-image-options?limit=200");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Failed to load reference image options");
  }
  state.urlOptions = data.options || [];
  applyUrlFilter(el("imageUrlSearch").value || "");
}

function applyUrlFilter(query) {
  const q = String(query || "").trim().toLowerCase();
  state.filteredUrlOptions = !q
    ? [...state.urlOptions]
    : state.urlOptions.filter((url) => url.toLowerCase().includes(q));
  populateUrlSelect(state.filteredUrlOptions);
}

// ── Payload / weights collection ─────────────────────────────────────────────

function hydrateFromPayload(payload) {
  state.payload = payload;

  el("jobId").value = payload.job_id ?? "123";
  el("intent").value = payload.intent ?? "Sales";
  el("createdAt").value = payload.created_at ?? "";
  el("topN").value = payload.top_n ?? 40;

  if (payload.image_url) {
    const select = el("imageUrlSelect");
    if (![...select.options].some((o) => o.value === payload.image_url)) {
      state.urlOptions = [payload.image_url, ...state.urlOptions.filter((u) => u !== payload.image_url)];
      applyUrlFilter(el("imageUrlSearch").value || "");

      const opt = document.createElement("option");
      opt.value = payload.image_url;
      opt.textContent = payload.image_url;
      select.appendChild(opt);
    }
    select.value = payload.image_url;
    updateSelectedImage(payload.image_url);
  }
}

function collectPayload() {
  const imageUrl = el("imageUrlSelect").value;
  if (!imageUrl) {
    throw new Error("Select a reference image URL first.");
  }
  return {
    job_id: el("jobId").value.trim(),
    image_url: imageUrl,
    intent: el("intent").value.trim(),
    created_at: el("createdAt").value.trim(),
    top_n: safeNum(el("topN").value, 40),
  };
}

function collectWeights() {
  return {
    weight_fg: safeNum(el("wFg").value, 0.7),
    weight_full: safeNum(el("wFull").value, 0.05),
    weight_trend: safeNum(el("wTrend").value, 0.1),
    weight_popular: safeNum(el("wPopular").value, 0.1),
    weight_fresh: safeNum(el("wFresh").value, 0.05),
    weight_brand: safeNum(el("wBrand")?.value, 0.0),
  };
}

// ── Results rendering ─────────────────────────────────────────────────────────

function fmt(v, d = 3) {
  if (v === null || v === undefined) return "-";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(d) : String(v);
}

function renderResults(results) {
  const grid = el("resultsGrid");
  const info = el("resultInfo");
  const preview = el("uploadPreview");
  const meta = el("meta");

  preview.src = state.selectedImageUrl || "";
  meta.innerHTML = `
    <div><strong>Job:</strong> ${results.job_id}</div>
    <div><strong>Cluster:</strong> ${results.assigned_cluster_id}</div>
    <div><strong>Pool:</strong> ${results.candidate_pool_size}</div>
    <div><strong>Weights:</strong> fg=${fmt(results.weights.weight_fg, 2)}, full=${fmt(results.weights.weight_full, 2)}, trend=${fmt(results.weights.weight_trend, 2)}, popular=${fmt(results.weights.weight_popular, 2)}, fresh=${fmt(results.weights.weight_fresh, 2)}, brand=${fmt(results.weights.weight_brand, 2)}</div>
  `;

  info.textContent = `Showing ${results.results.length} images`;

  grid.innerHTML = "";
  for (const row of results.results) {
    const card = document.createElement("article");
    card.className = "card";
    const channels = (row.source_channels || [])
      .map((c) => `<span class="chip">${c}</span>`)
      .join("");

    card.innerHTML = `
      <img src="${row.image_url || ""}" alt="${row.image_id}" loading="lazy" />
      <div class="card-body">
        <strong>#${row.position} • ${fmt(row.model_score, 4)}</strong>
        <div>Likes: ${row.likes ?? "-"} | Comments: ${row.comments ?? "-"}</div>
        <div>Trend: ${fmt(row.trend_score)} | Engage: ${fmt(row.engagement_score)} | Fresh: ${fmt(row.freshness_score)}</div>
        <div>Mode: ${row.ranking_mode}${row.is_exploration ? " • exploration" : ""}</div>
        <div class="chips">${channels}</div>
      </div>
    `;
    grid.appendChild(card);
  }
}

// ── Main run ──────────────────────────────────────────────────────────────────

async function runHeuristic() {
  try {
    setStatus("Running staging script…");
    const payload = collectPayload();
    state.payload = payload;

    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payload,
        seed: safeNum(el("seed").value, 42),
        weights: collectWeights(),
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
    }

    renderResults(data.results);
    setStatus("Run complete. Results loaded.");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Run failed", true);
  }
}

async function loadSample() {
  try {
    setStatus("Loading sample input…");
    const response = await fetch("/api/sample-input");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load sample");
    }
    hydrateFromPayload(payload);
    setStatus("Sample loaded.");
  } catch (err) {
    setStatus(err.message || "Could not load sample", true);
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

el("runBtn").addEventListener("click", runHeuristic);
el("loadSampleBtn").addEventListener("click", loadSample);
el("refreshUrlsBtn").addEventListener("click", async () => {
  try {
    setStatus("Refreshing URL list...");
    await loadReferenceImageOptions();
    setStatus("URL list refreshed.");
  } catch (err) {
    setStatus(err.message || "Failed to refresh URL list", true);
  }
});
el("imageUrlSearch").addEventListener("input", (e) => {
  applyUrlFilter(e.target.value);
});
el("imageUrlSelect").addEventListener("change", (e) => {
  updateSelectedImage(e.target.value);
});

(async () => {
  try {
    setStatus("Loading reference image options…");
    await loadReferenceImageOptions();
    await loadSample();
    setStatus("Ready");
  } catch (err) {
    setStatus(err.message || "Failed to initialize", true);
  }
})();
