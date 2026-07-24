const state = {
  control: null,
  latestReplay: null,
  selectedTrace: null,
  activeView: "control",
  tourStep: 0,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const formatDate = (value, compact = false) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", compact
    ? { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }
    : { dateStyle: "medium", timeStyle: "short" }).format(date);
};

const formatNumber = (value, digits = 3) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  return number > 0 ? `+${number.toFixed(digits)}` : number.toFixed(digits);
};

const fetchJSON = async (url, options = {}) => {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
};

const notify = (message, error = false) => {
  const toast = document.createElement("div");
  toast.className = `toast${error ? " is-error" : ""}`;
  toast.textContent = message;
  $("#toast-region").appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
};

const setButtonLoading = (button, loading, label) => {
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = button.textContent.trim();
  }
  button.disabled = loading;
  button.textContent = loading ? label : button.dataset.originalLabel;
};

const switchView = (viewName) => {
  state.activeView = viewName;
  $$(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === viewName);
  });
  $$(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === `view-${viewName}`);
  });
  const active = $(`#view-${viewName}`);
  $("#page-title").textContent = active?.dataset.title || "Danex";
  window.scrollTo({ top: 0, behavior: "smooth" });
};

$$(".nav-item").forEach((item) => {
  item.addEventListener("click", () => switchView(item.dataset.view));
});

const appendSetting = (container, label, value) => {
  const item = document.createElement("div");
  item.className = "setting";
  const name = document.createElement("span");
  name.textContent = label;
  const settingValue = document.createElement("strong");
  settingValue.textContent = value;
  item.append(name, settingValue);
  container.appendChild(item);
};

const renderProfile = (profile, prefix) => {
  const name = $(`#${prefix}-profile-name`);
  const version = $(`#${prefix}-profile-version`);
  const date = $(`#${prefix}-profile-date`);
  const settingsBox = $(`#${prefix}-settings`);
  settingsBox.innerHTML = "";
  if (!profile) {
    name.textContent = prefix === "candidate" ? "No pending candidate" : "No active profile";
    version.textContent = "—";
    date.textContent = "—";
    return;
  }
  name.textContent = profile.name;
  version.textContent = profile.version;
  date.textContent = formatDate(profile.created_at, true);
  appendSetting(settingsBox, "RRF k", profile.settings.rank_constant);
  appendSetting(settingsBox, "Top K", profile.settings.top_k);
  appendSetting(settingsBox, "Lexical", `${profile.settings.lexical_weight}×`);
  appendSetting(settingsBox, "Dense", `${profile.settings.dense_weight}×`);
  appendSetting(settingsBox, "Max churn", `${Math.round(profile.settings.max_citation_churn * 100)}%`);
  appendSetting(settingsBox, "NDCG floor", profile.settings.min_ndcg_delta);
};

const renderEvents = (events = []) => {
  const container = $("#profile-events");
  container.innerHTML = "";
  if (!events.length) {
    container.innerHTML = '<div class="empty-compact">No profile changes recorded.</div>';
    return;
  }
  events.slice(0, 6).forEach((event) => {
    const item = document.createElement("div");
    item.className = "event-item";
    const action = document.createElement("strong");
    action.textContent = event.action.replaceAll("_", " ");
    const version = document.createElement("span");
    version.textContent = event.profile_version;
    const meta = document.createElement("small");
    meta.textContent = `${event.actor} · ${formatDate(event.timestamp, true)}`;
    item.append(action, version, meta);
    container.appendChild(item);
  });
};

const verdictBadgeClass = (verdict) => {
  if (verdict === "PASS" || verdict === "safe") return "badge-pass";
  if (verdict === "BLOCK" || verdict === "block") return "badge-block";
  if (verdict === "REVIEW" || verdict === "review") return "badge-review";
  return "badge-neutral";
};

const renderGate = (replay) => {
  const card = $("#quality-gate");
  const verdict = replay?.verdict || null;
  card.classList.remove("is-pass", "is-review", "is-block");
  if (verdict) card.classList.add(`is-${verdict.toLowerCase()}`);
  $("#gate-verdict").textContent = verdict || "Not evaluated";
  $("#gate-description").textContent = verdict === "PASS"
    ? "All configured retrieval thresholds passed. Candidate promotion is available."
    : verdict === "REVIEW"
      ? "No known-answer regression, but evidence ordering requires operator review."
      : verdict === "BLOCK"
        ? "The candidate failed at least one release threshold and cannot be promoted."
        : "Run the replay before promoting retrieval configuration.";

  const checksBox = $("#gate-checks");
  checksBox.innerHTML = "";
  const checks = replay?.metrics?.checks || [
    { label: "NDCG regression", actual: "Awaiting measurement", passed: null },
    { label: "Citation churn", actual: "Awaiting measurement", passed: null },
    { label: "P95 latency", actual: "Awaiting measurement", passed: null },
  ];
  checks.forEach((check) => {
    const item = document.createElement("div");
    item.className = `gate-check ${check.passed === null ? "is-pending" : check.passed ? "is-pass" : "is-fail"}`;
    const status = document.createElement("span");
    const copy = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = check.label;
    const value = document.createElement("small");
    value.textContent = check.passed === null
      ? check.actual
      : `actual ${check.actual} · threshold ${check.threshold}`;
    copy.append(label, value);
    item.append(status, copy);
    checksBox.appendChild(item);
  });
};

const renderReplay = (replay) => {
  state.latestReplay = replay || null;
  const body = $("#replay-table-body");
  body.innerHTML = "";
  if (!replay?.items?.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "Run the golden replay to compare the candidate profile.";
    row.appendChild(cell);
    body.appendChild(row);
    $("#replay-mode").textContent = "Awaiting replay";
    $("#replay-mode").className = "badge badge-neutral";
    $("#promote-button").disabled = true;
    renderGate(null);
    return;
  }

  replay.items.forEach((item) => {
    const row = document.createElement("tr");
    const question = document.createElement("td");
    question.className = "query-cell";
    question.textContent = item.question;
    const current = document.createElement("td");
    current.className = "source-cell";
    current.textContent = item.current_top_source || "No source";
    current.title = item.current_top_source || "";
    const candidate = document.createElement("td");
    candidate.className = "source-cell";
    candidate.textContent = item.candidate_top_source || "No source";
    candidate.title = item.candidate_top_source || "";
    const delta = document.createElement("td");
    delta.textContent = item.ndcg_delta === null ? "n/a" : formatNumber(item.ndcg_delta);
    delta.className = item.ndcg_delta > 0 ? "delta-positive" : item.ndcg_delta < 0 ? "delta-negative" : "delta-neutral";
    const classification = document.createElement("td");
    const diffBadge = document.createElement("span");
    diffBadge.className = `badge ${verdictBadgeClass(item.risk)}`;
    diffBadge.textContent = item.classification;
    classification.appendChild(diffBadge);
    const risk = document.createElement("td");
    const riskBadge = document.createElement("span");
    riskBadge.className = `badge ${verdictBadgeClass(item.risk)}`;
    riskBadge.textContent = item.risk;
    risk.appendChild(riskBadge);
    row.append(question, current, candidate, delta, classification, risk);
    body.appendChild(row);
  });

  $("#replay-mode").textContent = `${replay.metrics.mode} · ${replay.metrics.query_count} queries`;
  $("#replay-mode").className = `badge ${verdictBadgeClass(replay.verdict)}`;
  $("#promote-button").disabled = replay.verdict !== "PASS";
  $("#metric-gate").textContent = replay.verdict;
  $("#metric-gate-detail").textContent = `${replay.metrics.query_count} queries · ${replay.metrics.regressions} regressions`;
  $("#metric-ndcg").textContent = formatNumber(replay.metrics.avg_ndcg_delta);
  renderGate(replay);
};

const renderTraceOptions = (traces = []) => {
  const select = $("#trace-select");
  select.innerHTML = "";
  if (!traces.length) {
    const option = document.createElement("option");
    option.textContent = "No traces recorded";
    option.value = "";
    select.appendChild(option);
    renderTrace(null);
    return;
  }
  traces.forEach((trace) => {
    const option = document.createElement("option");
    option.value = trace.query_id;
    option.textContent = `${trace.query_id} · ${trace.question.slice(0, 45)}`;
    select.appendChild(option);
  });
  renderTrace(traces[0]);
};

const renderTrace = (trace) => {
  state.selectedTrace = trace || null;
  $("#trace-empty").hidden = Boolean(trace);
  $("#trace-content").hidden = !trace;
  if (!trace) return;
  $("#trace-question").textContent = trace.question;
  $("#trace-id").textContent = `${trace.query_id} · ${trace.profile_version}`;

  const timeline = $("#trace-timeline");
  timeline.innerHTML = "";
  trace.stages.forEach((stage) => {
    const item = document.createElement("div");
    item.className = `trace-stage${stage.status === "skipped" ? " is-skipped" : ""}`;
    const label = document.createElement("strong");
    label.textContent = stage.label;
    const duration = document.createElement("span");
    duration.textContent = `${stage.duration_ms ?? 0} ms`;
    const detail = document.createElement("small");
    detail.textContent = stage.candidates !== undefined ? `${stage.candidates} candidates` : stage.detail || stage.status;
    item.append(label, duration, detail);
    timeline.appendChild(item);
  });

  const ranking = $("#trace-ranking");
  ranking.innerHTML = "";
  (trace.results || []).slice(0, 6).forEach((result) => {
    const item = document.createElement("div");
    item.className = "ranking-item";
    const line = document.createElement("div");
    const source = document.createElement("strong");
    source.textContent = `#${result.rank} ${result.source}`;
    const score = document.createElement("code");
    score.textContent = result.score;
    line.append(source, score);
    const channels = document.createElement("small");
    channels.textContent = `${(result.channels || []).join(" + ")} · ${Object.entries(result.contributions || {}).map(([key, value]) => `${key} ${value}`).join(" · ")}`;
    item.append(line, channels);
    ranking.appendChild(item);
  });
};

const renderControl = (payload) => {
  state.control = payload;
  const active = payload.active_profile;
  const candidate = payload.candidate_profile;
  $("#runtime-profile").textContent = active?.version || "No active profile";
  $("#metric-active-profile").textContent = active?.version || "—";
  $("#metric-active-detail").textContent = active?.name || "No active configuration";
  $("#metric-chunks").textContent = payload.indexed_chunks ?? "—";
  $("#pipeline-rrf").textContent = active ? `RRF k=${active.settings.rank_constant} · top ${active.settings.top_k}` : "Controlled by profile";
  renderProfile(active, "active");
  renderProfile(candidate, "candidate");
  renderEvents(payload.profile_events || []);
  renderReplay(payload.latest_replay);
  renderTraceOptions(payload.traces || []);
};

const loadControlPlane = async () => {
  try {
    const payload = await fetchJSON("/api/v1/retrieval/control-plane");
    renderControl(payload);
  } catch (error) {
    notify(`Control plane unavailable: ${error.message}`, true);
  }
};

const runReplay = async () => {
  const button = $("#run-replay-button");
  setButtonLoading(button, true, "Running replay…");
  $("#metric-gate").textContent = "Evaluating";
  $("#metric-gate-detail").textContent = "Comparing active and candidate rankings";
  try {
    const candidate = state.control?.candidate_profile?.version || "rag-2026.08-candidate";
    const replay = await fetchJSON("/api/v1/retrieval/replay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidate_profile: candidate,
        include_golden: true,
        include_history: true,
        include_dense: $("#include-dense").checked,
        limit: 20,
      }),
    });
    renderReplay(replay);
    notify(`Replay ${replay.replay_id} completed with verdict ${replay.verdict}.`);
    $("#replay-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    notify(`Replay failed: ${error.message}`, true);
    $("#metric-gate").textContent = "Replay failed";
    $("#metric-gate-detail").textContent = error.message;
  } finally {
    setButtonLoading(button, false, "");
  }
};

const promoteCandidate = async () => {
  const version = state.latestReplay?.candidate_profile;
  if (!version) return;
  const button = $("#promote-button");
  setButtonLoading(button, true, "Promoting…");
  try {
    await fetchJSON(`/api/v1/retrieval/profiles/${encodeURIComponent(version)}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "portfolio-operator" }),
    });
    notify(`${version} promoted with replay evidence.`);
    await loadControlPlane();
  } catch (error) {
    notify(`Promotion blocked: ${error.message}`, true);
  } finally {
    setButtonLoading(button, false, "");
  }
};

$("#run-replay-button").addEventListener("click", runReplay);
$("#promote-button").addEventListener("click", promoteCandidate);
$("#refresh-control-button").addEventListener("click", loadControlPlane);
$("#trace-select").addEventListener("change", async (event) => {
  if (!event.target.value) return;
  try {
    const trace = await fetchJSON(`/api/v1/retrieval/traces/${encodeURIComponent(event.target.value)}`);
    renderTrace(trace);
  } catch (error) {
    notify(`Trace unavailable: ${error.message}`, true);
  }
});

const setQueryStatus = (text, working = false) => {
  const status = $("#status-pill");
  status.innerHTML = "";
  const dot = document.createElement("span");
  dot.className = "status-dot";
  if (working) dot.style.background = "var(--amber)";
  status.append(dot, document.createTextNode(text));
};

const renderSources = (sources = []) => {
  const container = $("#sources");
  container.innerHTML = "";
  const values = sources.length ? sources : ["No source channel"];
  values.forEach((source) => {
    const pill = document.createElement("span");
    pill.className = "source-pill";
    pill.textContent = source;
    container.appendChild(pill);
  });
};

const renderCitations = (citations = []) => {
  const container = $("#citations");
  container.innerHTML = "";
  citations.forEach((citation) => {
    const card = document.createElement("article");
    card.className = "citation";
    card.tabIndex = 0;
    const topline = document.createElement("div");
    topline.className = "citation-topline";
    const title = document.createElement("strong");
    title.textContent = `#${citation.rank ?? "—"} ${citation.source}`;
    const channelBox = document.createElement("div");
    channelBox.className = "citation-channels";
    (citation.channels || []).forEach((channel) => {
      const badge = document.createElement("span");
      badge.className = `badge ${channel === "dense" ? "badge-blue" : "badge-neutral"}`;
      badge.textContent = channel;
      channelBox.appendChild(badge);
    });
    topline.append(title, channelBox);
    const snippet = document.createElement("p");
    snippet.textContent = citation.snippet;
    const expanded = document.createElement("div");
    expanded.className = "citation-expanded";
    expanded.hidden = true;
    Object.entries(citation.contributions || {}).forEach(([channel, value]) => {
      const contribution = document.createElement("div");
      contribution.className = "citation-contribution";
      contribution.textContent = `${channel} contribution · ${value}`;
      expanded.appendChild(contribution);
    });
    card.append(topline, snippet, expanded);
    const toggle = () => { expanded.hidden = !expanded.hidden; };
    card.addEventListener("click", toggle);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
    container.appendChild(card);
  });
};

const runQuery = async () => {
  const question = $("#question").value.trim();
  if (!question) {
    notify("Enter a question before running the governed query.", true);
    return;
  }
  const button = $("#ask-button");
  setButtonLoading(button, true, "Executing retrieval…");
  setQueryStatus("Running", true);
  $("#answer").textContent = "Executing lexical and dense evidence routing…";
  $("#answer").classList.add("muted");
  try {
    const payload = await fetchJSON("/api/v1/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        db_target: $("#db-target").value,
        session_id: "portfolio-demo",
        synthesize: $("#enable-synthesis").checked,
      }),
    });
    $("#answer").textContent = payload.answer || "No answer returned.";
    $("#answer").classList.remove("muted");
    $("#answer-query-id").textContent = payload.query_id || "No trace";
    $("#meta-route").textContent = payload.meta?.route || "—";
    $("#meta-profile").textContent = payload.meta?.retrieval_profile_version || "—";
    $("#meta-latency").textContent = payload.meta?.latency_ms ? `${payload.meta.latency_ms} ms` : "—";
    $("#signal-confidence").textContent = payload.confidence_score ?? "—";
    renderSources(payload.sources || []);
    renderCitations(payload.citations || []);
    setQueryStatus("Completed");
    notify(`Query ${payload.query_id} recorded in the flight recorder.`);
    await Promise.all([loadQueryHistory(), loadEvalSummary(), loadControlPlane()]);
  } catch (error) {
    $("#answer").textContent = `Query failed: ${error.message}`;
    $("#answer").classList.add("muted");
    setQueryStatus("Error");
    notify(`Query failed: ${error.message}`, true);
  } finally {
    setButtonLoading(button, false, "");
  }
};

$("#ask-button").addEventListener("click", runQuery);
$("#question").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runQuery();
});
$("#examples").addEventListener("change", (event) => {
  if (event.target.value) $("#question").value = event.target.value;
});
$$("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => { $("#question").value = button.dataset.prompt; });
});

const renderList = (container, items, emptyText, renderItem) => {
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  items.forEach((item) => container.appendChild(renderItem(item)));
};

const loadQueryHistory = async () => {
  try {
    const payload = await fetchJSON("/api/v1/history/queries");
    renderList($("#query-history"), payload.history || [], "No governed queries recorded.", (item) => {
      const card = document.createElement("div");
      card.className = "list-card";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.question;
      const meta = document.createElement("span");
      meta.textContent = `${item.route} · ${item.retrieval_profile_version || "legacy"} · ${item.latency_ms} ms`;
      const preview = document.createElement("small");
      preview.textContent = item.answer_preview || "";
      content.append(title, meta, preview);
      const date = document.createElement("code");
      date.textContent = formatDate(item.timestamp, true);
      card.append(content, date);
      return card;
    });
  } catch (error) {
    notify(`Query history unavailable: ${error.message}`, true);
  }
};

const loadEvalSummary = async () => {
  try {
    const payload = await fetchJSON("/api/v1/evals/summary");
    $("#eval-queries").textContent = payload.queries ?? "—";
    $("#eval-latency").textContent = payload.avg_latency_ms ? `${payload.avg_latency_ms} ms` : "—";
    $("#eval-score").textContent = payload.avg_top_score ?? "—";
  } catch {
    $("#eval-queries").textContent = "—";
    $("#eval-latency").textContent = "—";
    $("#eval-score").textContent = "—";
  }
};

const deleteKnowledgeFile = async (filename) => {
  try {
    await fetchJSON(`/api/v1/ingest/files/${encodeURIComponent(filename)}?rebuild=true`, { method: "DELETE" });
    notify(`${filename} removed; both indexes are rebuilding.`);
    await Promise.all([loadKnowledge(), loadControlPlane()]);
  } catch (error) {
    notify(`Delete failed: ${error.message}`, true);
  }
};

const loadKnowledge = async () => {
  try {
    const payload = await fetchJSON("/api/v1/ingest/history");
    $("#knowledge-count").textContent = `${payload.files?.length || 0} files`;
    renderList($("#knowledge-files"), payload.files || [], "No approved knowledge files.", (item) => {
      const card = document.createElement("div");
      card.className = "list-card";
      const content = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = item.name;
      const meta = document.createElement("span");
      meta.textContent = `${Math.max(Math.round(item.size / 1024), 1)} KB · updated ${formatDate(item.updated_at, true)}`;
      content.append(name, meta);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete + rebuild";
      remove.addEventListener("click", () => deleteKnowledgeFile(item.name));
      card.append(content, remove);
      return card;
    });
    renderList($("#ingestion-history"), payload.history || [], "No ingestion events recorded.", (item) => {
      const card = document.createElement("div");
      card.className = "list-card";
      const content = document.createElement("div");
      const action = document.createElement("strong");
      action.textContent = `${item.action} · ${item.status}`;
      const files = document.createElement("span");
      files.textContent = item.files?.length ? item.files.join(", ") : "Full index";
      content.append(action, files);
      const date = document.createElement("code");
      date.textContent = formatDate(item.timestamp, true);
      card.append(content, date);
      return card;
    });
  } catch (error) {
    notify(`Knowledge state unavailable: ${error.message}`, true);
  }
};

const rebuildIndexes = async () => {
  const button = $("#rebuild-button");
  setButtonLoading(button, true, "Rebuilding…");
  try {
    await fetchJSON("/api/v1/ingest/rebuild", { method: "POST" });
    $("#ingest-status").textContent = "Dense and lexical rebuild accepted.";
    notify("Index rebuild accepted.");
    await loadKnowledge();
  } catch (error) {
    notify(`Rebuild failed: ${error.message}`, true);
  } finally {
    setButtonLoading(button, false, "");
  }
};

const uploadFiles = async () => {
  const files = $("#upload-files").files;
  if (!files?.length) {
    notify("Choose at least one approved source file.", true);
    return;
  }
  const button = $("#upload-button");
  setButtonLoading(button, true, "Uploading…");
  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));
  try {
    const payload = await fetchJSON("/api/v1/ingest/upload?rebuild=true", { method: "POST", body: form });
    $("#ingest-status").textContent = `${payload.saved.length} files accepted; rebuild started.`;
    notify("Knowledge sources accepted for controlled ingestion.");
    await loadKnowledge();
  } catch (error) {
    notify(`Upload failed: ${error.message}`, true);
  } finally {
    setButtonLoading(button, false, "");
  }
};

$("#rebuild-button").addEventListener("click", rebuildIndexes);
$("#upload-button").addEventListener("click", uploadFiles);

const tourSteps = [
  {
    view: "control",
    target: "#control-hero",
    title: "Start with the control plane",
    copy: "This is the operating surface for retrieval changes, not a generic analytics dashboard.",
  },
  {
    view: "control",
    target: "#retrieval-pipeline",
    title: "Inspect the retrieval plan",
    copy: "FTS5 and FAISS produce independent rankings. RRF fuses them using an immutable profile.",
  },
  {
    view: "control",
    target: "#run-replay-button",
    title: "Replay before rollout",
    copy: "Run the committed golden set and recent history against both active and candidate profiles.",
  },
  {
    view: "control",
    target: "#replay-results",
    title: "Review every ranking diff",
    copy: "Changed top sources, NDCG, citation churn and risk are visible per query—not hidden in one average.",
  },
  {
    view: "query",
    target: "#view-query .workspace-grid",
    title: "Finish with the flight recorder",
    copy: "Run a governed query, then return to Control plane to inspect its complete retrieval trace.",
  },
];

const clearTourHighlight = () => {
  $(".tour-highlight")?.classList.remove("tour-highlight");
};

const renderTourStep = () => {
  const step = tourSteps[state.tourStep];
  switchView(step.view);
  clearTourHighlight();
  const target = $(step.target);
  target?.classList.add("tour-highlight");
  target?.scrollIntoView({ behavior: "smooth", block: "center" });
  $("#tour-progress").textContent = `${state.tourStep + 1} / ${tourSteps.length}`;
  $("#tour-title").textContent = step.title;
  $("#tour-copy").textContent = step.copy;
  $("#tour-back").disabled = state.tourStep === 0;
  $("#tour-next").textContent = state.tourStep === tourSteps.length - 1 ? "Finish" : "Next";
};

const startTour = () => {
  state.tourStep = 0;
  $("#tour-popover").hidden = false;
  renderTourStep();
};

const closeTour = () => {
  clearTourHighlight();
  $("#tour-popover").hidden = true;
};

$("#tour-button").addEventListener("click", startTour);
$("#tour-close").addEventListener("click", closeTour);
$("#tour-back").addEventListener("click", () => {
  if (state.tourStep > 0) {
    state.tourStep -= 1;
    renderTourStep();
  }
});
$("#tour-next").addEventListener("click", () => {
  if (state.tourStep >= tourSteps.length - 1) {
    closeTour();
    return;
  }
  state.tourStep += 1;
  renderTourStep();
});

void Promise.all([
  loadControlPlane(),
  loadKnowledge(),
  loadQueryHistory(),
  loadEvalSummary(),
]);
