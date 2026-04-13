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
    const snippet = document.createElement("div");
    snippet.textContent = citation.snippet || "";
    wrapper.appendChild(title);
    wrapper.appendChild(snippet);
    citationsBox.appendChild(wrapper);
  });
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
  } catch (error) {
    setIngestStatus(`Upload failed: ${error.message}`);
  }
};

uploadButton.addEventListener("click", uploadFiles);
rebuildButton.addEventListener("click", rebuildIndex);
