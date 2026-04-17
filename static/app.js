const statusPill = document.getElementById("status-pill");
const askButton = document.getElementById("ask-button");
const questionInput = document.getElementById("question");
const dbTargetSelect = document.getElementById("db-target");
const examplesSelect = document.getElementById("examples");
const answerBox = document.getElementById("answer");
const sourcesBox = document.getElementById("sources");
const metaDb = document.getElementById("meta-db");
const metaModel = document.getElementById("meta-model");
const metaLatency = document.getElementById("meta-latency");
const metaRoute = document.getElementById("meta-route");
const signalSql = document.getElementById("signal-sql");
const signalVector = document.getElementById("signal-vector");
const signalConfidence = document.getElementById("signal-confidence");
const citationsBox = document.getElementById("citations");
const uploadInput = document.getElementById("upload-files");
const uploadButton = document.getElementById("upload-button");
const rebuildButton = document.getElementById("rebuild-button");
const ingestStatus = document.getElementById("ingest-status");
const queryHistoryBox = document.getElementById("query-history");
const ingestionHistoryBox = document.getElementById("ingestion-history");
const knowledgeFilesBox = document.getElementById("knowledge-files");
const evalQueries = document.getElementById("eval-queries");
const evalLatency = document.getElementById("eval-latency");
const evalScore = document.getElementById("eval-score");

const formatDate = (value) => {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
};

const setStatus = (text) => {
  statusPill.textContent = text;
};

const resetMeta = () => {
  metaDb.textContent = "db: -";
  metaModel.textContent = "model: -";
  metaLatency.textContent = "latency: -";
  metaRoute.textContent = "route: -";
  signalSql.textContent = "-";
  signalVector.textContent = "-";
  signalConfidence.textContent = "-";
  sourcesBox.innerHTML = "";
  citationsBox.innerHTML = "";
};

const renderSources = (sources = []) => {
  sourcesBox.innerHTML = "";
  if (!sources.length) {
    const pill = document.createElement("div");
    pill.className = "source-pill";
    pill.textContent = "No sources";
    sourcesBox.appendChild(pill);
    return;
  }
  sources.forEach((source) => {
    const pill = document.createElement("div");
    pill.className = "source-pill";
    pill.textContent = source;
    sourcesBox.appendChild(pill);
  });
};

const renderCitations = (citations = []) => {
  citationsBox.innerHTML = "";
  if (!citations.length) {
    return;
  }
  citations.forEach((citation) => {
    const wrapper = document.createElement("div");
    wrapper.className = "citation";
    const title = document.createElement("strong");
    title.textContent = citation.source || "Source";
    const score = document.createElement("div");
    score.className = "citation-score";
    const scoreValue = citation.score ?? "-";
    score.textContent = `score: ${scoreValue}`;
    const snippet = document.createElement("div");
    snippet.textContent = citation.snippet || "";
    const expanded = document.createElement("div");
    expanded.className = "citation-expanded";
    expanded.textContent = citation.snippet || "";
    expanded.hidden = true;
    wrapper.appendChild(title);
    wrapper.appendChild(score);
    wrapper.appendChild(snippet);
    wrapper.appendChild(expanded);
    wrapper.addEventListener("click", () => {
      expanded.hidden = !expanded.hidden;
    });
    citationsBox.appendChild(wrapper);
  });
};

const renderListCards = (container, items, emptyText, renderCard) => {
  container.innerHTML = "";
  if (!items.length) {
    container.textContent = emptyText;
    container.classList.add("muted");
    return;
  }
  container.classList.remove("muted");
  items.forEach((item) => container.appendChild(renderCard(item)));
};

const createCard = () => {
  const card = document.createElement("div");
  card.className = "list-card";
  return card;
};

const renderQueryHistory = (items = []) => {
  renderListCards(queryHistoryBox, items, "No queries yet.", (item) => {
    const card = createCard();
    const topline = document.createElement("div");
    topline.className = "topline";
    topline.innerHTML = `<strong>${item.question || "Question"}</strong><span class="meta-line">${item.route || "-"}</span>`;
    const meta = document.createElement("div");
    meta.className = "meta-line";
    meta.textContent = `${formatDate(item.timestamp)} | ${item.db_target || "-"} | ${item.latency_ms || "-"} ms`;
    const preview = document.createElement("div");
    preview.className = "preview";
    preview.textContent = item.answer_preview || "";
    card.appendChild(topline);
    card.appendChild(meta);
    card.appendChild(preview);
    return card;
  });
};

const renderIngestionHistory = (items = []) => {
  renderListCards(ingestionHistoryBox, items, "No ingestion events yet.", (item) => {
    const card = createCard();
    const topline = document.createElement("div");
    topline.className = "topline";
    topline.innerHTML = `<strong>${item.action || "event"}</strong><span class="meta-line">${item.status || "-"}</span>`;
    const meta = document.createElement("div");
    meta.className = "meta-line";
    const files = item.files?.length ? item.files.join(", ") : "no files";
    meta.textContent = `${formatDate(item.timestamp)} | ${files}`;
    card.appendChild(topline);
    card.appendChild(meta);
    return card;
  });
};

const deleteKnowledgeFile = async (filename) => {
  setIngestStatus(`Deleting ${filename}...`);
  try {
    const response = await fetch(`/api/v1/ingest/files/${encodeURIComponent(filename)}?rebuild=true`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    setIngestStatus(`Deleted ${filename}. Rebuild started.`);
    await Promise.all([loadIngestionHistory(), loadEvalSummary()]);
  } catch (error) {
    setIngestStatus(`Delete failed: ${error.message}`);
  }
};

const renderKnowledgeFiles = (items = []) => {
  renderListCards(knowledgeFilesBox, items, "No files loaded.", (item) => {
    const card = createCard();
    const topline = document.createElement("div");
    topline.className = "topline";
    topline.innerHTML = `<strong>${item.name}</strong><span class="meta-line">${item.size} bytes</span>`;
    const meta = document.createElement("div");
    meta.className = "meta-line";
    meta.textContent = `updated ${formatDate(item.updated_at)}`;
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    const button = document.createElement("button");
    button.className = "ghost";
    button.textContent = "Delete + rebuild";
    button.addEventListener("click", () => deleteKnowledgeFile(item.name));
    actions.appendChild(button);
    card.appendChild(topline);
    card.appendChild(meta);
    card.appendChild(actions);
    return card;
  });
};

const loadQueryHistory = async () => {
  try {
    const response = await fetch("/api/v1/history/queries");
    const payload = await response.json();
    renderQueryHistory(payload.history || []);
  } catch {
    queryHistoryBox.textContent = "Failed to load query history.";
    queryHistoryBox.classList.add("muted");
  }
};

const loadIngestionHistory = async () => {
  try {
    const response = await fetch("/api/v1/ingest/history");
    const payload = await response.json();
    renderIngestionHistory(payload.history || []);
    renderKnowledgeFiles(payload.files || []);
  } catch {
    ingestionHistoryBox.textContent = "Failed to load ingestion history.";
    ingestionHistoryBox.classList.add("muted");
  }
};

const loadEvalSummary = async () => {
  try {
    const response = await fetch("/api/v1/evals/summary");
    const payload = await response.json();
    evalQueries.textContent = payload.queries ?? "-";
    evalLatency.textContent = payload.avg_latency_ms ? `${payload.avg_latency_ms} ms` : "-";
    evalScore.textContent = payload.avg_top_score ?? "-";
  } catch {
    evalQueries.textContent = "-";
    evalLatency.textContent = "-";
    evalScore.textContent = "-";
  }
};

const ask = async () => {
  const question = questionInput.value.trim();
  if (!question) {
    answerBox.textContent = "Please enter a question.";
    answerBox.classList.add("muted");
    return;
  }

  answerBox.textContent = "Running query...";
  answerBox.classList.add("muted");
  setStatus("Running");
  resetMeta();

  try {
    const response = await fetch("/api/v1/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        db_target: dbTargetSelect.value,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    answerBox.textContent = payload.answer || "No answer.";
    answerBox.classList.remove("muted");
    setStatus("Ready");

    const meta = payload.meta || {};
    metaDb.textContent = `db: ${meta.db_target || "-"}`;
    metaModel.textContent = `model: ${meta.model || "-"}`;
    metaLatency.textContent = `latency: ${meta.latency_ms || "-"} ms`;
    metaRoute.textContent = `route: ${meta.route || "-"}`;
    signalSql.textContent = meta.used_sql ? "yes" : "no";
    signalVector.textContent = meta.used_vector ? "yes" : "no";
    signalConfidence.textContent = payload.confidence_score ?? "-";

    renderSources(payload.sources || []);
    renderCitations(payload.citations || []);
    await Promise.all([loadQueryHistory(), loadEvalSummary()]);
  } catch (error) {
    answerBox.textContent = `Failed to query: ${error.message}`;
    answerBox.classList.add("muted");
    setStatus("Error");
  }
};

askButton.addEventListener("click", ask);
questionInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    ask();
  }
});

examplesSelect.addEventListener("change", () => {
  if (examplesSelect.value) {
    questionInput.value = examplesSelect.value;
  }
});

const setIngestStatus = (text) => {
  ingestStatus.textContent = text;
};

const rebuildIndex = async () => {
  setIngestStatus("Rebuilding index...");
  try {
    const response = await fetch("/api/v1/ingest/rebuild", { method: "POST" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    setIngestStatus("Rebuild started.");
    await loadIngestionHistory();
  } catch (error) {
    setIngestStatus(`Rebuild failed: ${error.message}`);
  }
};

const uploadFiles = async () => {
  const files = uploadInput.files;
  if (!files || !files.length) {
    setIngestStatus("Please select at least one file.");
    return;
  }
  setIngestStatus("Uploading files...");
  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append("files", file));
  try {
    const response = await fetch("/api/v1/ingest/upload?rebuild=true", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    setIngestStatus(`Uploaded: ${payload.saved?.length || 0} files. Rebuild started.`);
    await loadIngestionHistory();
  } catch (error) {
    setIngestStatus(`Upload failed: ${error.message}`);
  }
};

uploadButton.addEventListener("click", uploadFiles);
rebuildButton.addEventListener("click", rebuildIndex);

void Promise.all([loadQueryHistory(), loadIngestionHistory(), loadEvalSummary()]);
