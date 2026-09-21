"use strict";

const state = {
  runtime: null,
  readiness: null,
  lastDecisionPayload: null,
  decisions: [],
  evidenceCounter: 0,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatPercent(value) {
  const number = Number(value || 0);
  return `${Math.round(number * 100)}%`;
}

function formatDate(value) {
  if (!value) return "N/A";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
}

function shortId(value) {
  if (!value) return "N/A";
  const text = String(value);
  return text.length > 14 ? `${text.slice(0, 8)}…${text.slice(-5)}` : text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  let body = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { message: text };
    }
  }

  if (!response.ok) {
    const message = body && body.message ? body.message : `HTTP ${response.status}`;
    const error = new Error(message);
    error.code = body && body.code ? body.code : "request_failed";
    error.status = response.status;
    throw error;
  }
  return body;
}

function showFlash(message, kind = "info") {
  const flash = $("#flash");
  flash.textContent = message;
  flash.className = `flash is-visible ${kind === "error" ? "is-error" : kind === "good" ? "is-good" : ""}`;
  window.clearTimeout(showFlash.timer);
  showFlash.timer = window.setTimeout(() => {
    flash.className = "flash";
    flash.textContent = "";
  }, 6000);
}

function setBusy(button, busy, busyLabel) {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
    button.disabled = false;
  }
}

function openView(name) {
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("is-active", view.id === `view-${name}`));
  const active = $(`#view-${name}`);
  $("#view-title").textContent = active ? active.dataset.title || name : name;
  window.scrollTo({ top: 0, behavior: "smooth" });

  if (name === "decisions") loadDecisions();
}

function pill(text, kind = "info") {
  return element("span", `pill ${kind}`, text);
}

function readinessItem(check) {
  const states = {
    pass: ["Ready", "good"],
    warn: ["Optional", "warn"],
    fail: ["Blocked", "warn"],
    skip: ["Not run", "info"],
  };
  const [label, kind] = states[check.status] || [String(check.status), "info"];
  const row = element("div", "readiness-item");
  const copy = element("div", "readiness-copy");
  const detail = check.remediation
    ? `${check.detail} ${check.remediation}`
    : check.detail;
  copy.append(element("strong", null, check.label), element("span", null, detail));
  row.append(copy, pill(label, kind));
  return row;
}

function renderReadiness(report) {
  state.readiness = report;
  const container = $("#readiness-list");
  const summary = readinessItem({
    label: "Consumer-trial gate",
    detail: report.ready
      ? `${report.live_probes ? "Live" : "Static"} readiness checks have no required blockers.`
      : `Blocked by ${report.blockers.join(", ") || "one or more required checks"}.`,
    remediation: null,
    status: report.ready ? "pass" : "fail",
  });
  container.replaceChildren(summary, ...report.checks.map(readinessItem));
}

async function loadReadiness(live = false) {
  const button = $("#run-readiness");
  if (live) setBusy(button, true, "Running live checks…");
  try {
    const report = await api(
      live ? "/api/readiness/probe" : "/api/readiness",
      live ? { method: "POST", body: "{}" } : {},
    );
    renderReadiness(report);
    if (live) {
      showFlash(
        report.ready
          ? "Live consumer-trial readiness checks passed."
          : `Consumer-trial readiness remains blocked: ${report.blockers.join(", ")}.`,
        report.ready ? "good" : "error",
      );
    }
  } catch (error) {
    $("#readiness-list").replaceChildren(
      element("div", "empty-state", `Readiness check failed: ${error.message}`),
    );
    showFlash(`Readiness check failed: ${error.message}`, "error");
  } finally {
    if (live) setBusy(button, false);
  }
}

function metricCard(label, value, detail) {
  const card = element("article", "metric-card");
  card.append(
    element("div", "metric-label", label),
    element("div", "metric-value", value),
    element("div", "metric-detail", detail),
  );
  return card;
}

async function loadRuntime() {
  const refresh = $("#refresh-runtime");
  setBusy(refresh, true, "Refreshing…");
  try {
    const runtime = await api("/api/runtime");
    state.runtime = runtime;
    renderRuntime(runtime);
    await loadReadiness(false);
    $("#health-dot").className = "status-dot good";
    $("#health-label").textContent = "Runtime online";
  } catch (error) {
    $("#health-dot").className = "status-dot bad";
    $("#health-label").textContent = "Runtime unavailable";
    showFlash(`Runtime check failed: ${error.message}`, "error");
  } finally {
    setBusy(refresh, false);
  }
}

function renderRuntime(runtime) {
  $("#model-chip").textContent = `AI: ${runtime.ai.provider} / ${runtime.ai.model}`;

  const metrics = $("#runtime-metrics");
  metrics.replaceChildren(
    metricCard(
      "AI runtime",
      runtime.ai.model,
      `${runtime.ai.provider} · critic ${runtime.ai.critic_enabled ? "on" : "off"}`,
    ),
    metricCard(
      "Decision threshold",
      formatPercent(runtime.ai.min_decision_score),
      `${runtime.ai.max_context_chars.toLocaleString()} context chars`,
    ),
    metricCard(
      "Instagram provider",
      runtime.instagram.provider,
      runtime.policy.write_approval_required ? "approval required" : "approval optional",
    ),
    metricCard(
      "Research budget",
      `${runtime.research.max_pages} pages`,
      `${formatPercent(runtime.research.confidence_threshold)} confidence target`,
    ),
  );

  renderAccountConfig(runtime);
}

function renderAccountConfig(runtime) {
  const container = $("#account-config");
  const rows = [
    ["Selected provider", runtime.instagram.provider],
    ["Graph API version", runtime.instagram.graph_api_version],
    ["Official account ID", runtime.instagram.account_configured ? "Configured" : "Not configured"],
    ["Official access token", runtime.instagram.token_configured ? "Configured" : "Not configured"],
    ["Private username", runtime.instagram.private_username_configured ? "Configured" : "Not configured"],
    ["Private password", runtime.instagram.private_password_configured ? "Configured" : "Not configured"],
    ["Approval required", runtime.policy.write_approval_required ? "Yes" : "No"],
  ];

  container.replaceChildren(...rows.map(([label, value]) => {
    const row = element("div", "config-row");
    row.append(element("strong", null, label), element("span", null, value));
    return row;
  }));
}

function addEvidence(seed = {}) {
  state.evidenceCounter += 1;
  const template = $("#evidence-template");
  const fragment = template.content.cloneNode(true);
  const card = $(".evidence-card", fragment);
  const id = $(".evidence-id", fragment);
  const source = $(".evidence-source", fragment);
  const confidence = $(".evidence-confidence", fragment);
  const content = $(".evidence-content", fragment);

  id.value = seed.evidence_id || `evidence-${state.evidenceCounter}`;
  source.value = seed.source || "";
  confidence.value = seed.confidence !== undefined ? String(seed.confidence) : "1";
  content.value = seed.content || "";

  $(".remove-evidence", fragment).addEventListener("click", () => {
    const cards = $$(".evidence-card", $("#evidence-list"));
    if (cards.length <= 1) {
      showFlash("At least one evidence item is required.", "error");
      return;
    }
    card.remove();
  });

  $("#evidence-list").append(fragment);
}

function collectEvidence() {
  return $$(".evidence-card", $("#evidence-list")).map((card) => ({
    evidence_id: $(".evidence-id", card).value.trim(),
    source: $(".evidence-source", card).value.trim(),
    content: $(".evidence-content", card).value.trim(),
    confidence: Number($(".evidence-confidence", card).value),
  }));
}

async function runAIProbe() {
  const button = $("#run-ai-probe");
  const target = $("#probe-result");
  setBusy(button, true, "Checking model…");
  target.className = "probe-result empty-state loading";
  target.textContent = "Waiting for a genuine structured response from the configured model…";
  try {
    const probe = await api("/api/ai/probe", { method: "POST", body: "{}" });
    const grid = element("div", "probe-grid");
    [
      ["Status", probe.ok ? "Connected" : "Failed"],
      ["Provider", probe.provider],
      ["Model", probe.model],
      ["Latency", `${probe.latency_ms} ms`],
    ].forEach(([label, value]) => {
      const cell = element("div", "probe-cell");
      cell.append(element("span", null, label), element("strong", null, value));
      grid.append(cell);
    });
    target.className = "probe-result";
    target.replaceChildren(grid);
    showFlash(`AI check passed: ${probe.provider} / ${probe.model}`, "good");
  } catch (error) {
    target.className = "probe-result empty-state";
    target.textContent = `AI check failed: ${error.message}`;
    showFlash(`AI check failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function submitPlan(event) {
  event.preventDefault();
  const button = $("#plan-submit");
  const target = $("#decision-result");
  let context;

  try {
    context = JSON.parse($("#plan-context").value || "{}");
    if (!context || Array.isArray(context) || typeof context !== "object") {
      throw new Error("Advanced context must be a JSON object.");
    }
  } catch (error) {
    showFlash(`Context JSON is invalid: ${error.message}`, "error");
    return;
  }

  const payload = {
    objective: $("#plan-objective").value.trim(),
    evidence: collectEvidence(),
    context,
  };

  setBusy(button, true, "Reasoning…");
  target.className = "empty-state tall loading";
  target.textContent = "Planner inference → validation → deterministic scoring → critic review…";

  try {
    const result = await api("/api/ai/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.lastDecisionPayload = result;
    $("#copy-decision").disabled = false;
    renderDecision(result);
    await loadDecisions(false);
    showFlash(
      result.decision.abstained
        ? "AI completed its review and abstained."
        : "Reviewed plan created. Any resulting action remains pending approval.",
      "good",
    );
  } catch (error) {
    target.className = "empty-state tall";
    target.textContent = `Planning failed: ${error.message}`;
    showFlash(`Planning failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function section(title, content) {
  const box = element("div", "result-section");
  box.append(element("h4", null, title));
  if (content instanceof Node) box.append(content);
  else box.append(element("p", null, content));
  return box;
}

function listNode(values, emptyText = "None") {
  if (!values || values.length === 0) return element("p", null, emptyText);
  const list = element("ul");
  values.forEach((value) => list.append(element("li", null, value)));
  return list;
}

function renderDecision(result) {
  const decision = result.decision;
  const selected = decision.selected;
  const review = decision.review;
  const root = element("div", "result-content");

  const hero = element("div", "result-hero");
  const top = element("div", "result-topline");
  top.append(
    pill(decision.abstained ? "Abstained" : "Reviewed", decision.abstained ? "warn" : "good"),
    element("div", "score", `${formatPercent(decision.score)} `),
  );
  $(".score", top).append(element("small", null, "decision score"));

  const meta = element("div", "result-meta");
  [
    ["Decision ID", decision.decision_id],
    ["Provider / model", `${decision.provider || "N/A"} / ${decision.model || "N/A"}`],
    ["Selected action", selected ? selected.action : "None"],
    ["Created", formatDate(decision.created_at)],
  ].forEach(([label, value]) => {
    const item = element("div", "meta-card");
    item.append(element("span", null, label), element("strong", null, value));
    meta.append(item);
  });
  hero.append(top, meta);
  root.append(hero);

  root.append(section("Adjudication", decision.explanation || "No explanation recorded."));

  if (selected) {
    root.append(section("Candidate rationale", selected.rationale));
    const measures = element("div", "result-meta");
    [
      ["Model confidence", formatPercent(selected.confidence)],
      ["Expected utility", formatPercent(selected.expected_utility)],
      ["Candidate risk", formatPercent(selected.risk)],
      ["Evidence refs", selected.evidence_refs.length ? selected.evidence_refs.join(", ") : "None"],
    ].forEach(([label, value]) => {
      const item = element("div", "meta-card");
      item.append(element("span", null, label), element("strong", null, value));
      measures.append(item);
    });
    root.append(section("Candidate measures", measures));
  }

  if (review) {
    const measures = element("div", "result-meta");
    [
      ["Critic support", formatPercent(review.support_score)],
      ["Critic risk", formatPercent(review.risk_score)],
      ["Critic abstain", review.should_abstain ? "Yes" : "No"],
      ["Missing evidence", String(review.missing_evidence.length)],
    ].forEach(([label, value]) => {
      const item = element("div", "meta-card");
      item.append(element("span", null, label), element("strong", null, value));
      measures.append(item);
    });
    root.append(section("Independent critic", measures));
    root.append(section("Critic objections", listNode(review.objections)));
    root.append(section("Missing evidence", listNode(review.missing_evidence)));
  }

  root.append(section("Assumptions", listNode(decision.assumptions)));
  root.append(section("Uncertainty", decision.uncertainty || "No additional uncertainty recorded."));

  if (result.planned_action) {
    const action = result.planned_action;
    const actionBox = element("div", "result-section");
    actionBox.append(
      element("h4", null, "Pending action"),
      pill(action.approval, action.approval === "approved" ? "good" : "warn"),
      element("p", null, `${action.action_type} · confidence ${formatPercent(action.confidence)}`),
    );
    const code = element("pre", "code-block", JSON.stringify(action.payload, null, 2));
    actionBox.append(code);
    root.append(actionBox);
  }

  $("#decision-result").className = "";
  $("#decision-result").replaceChildren(root);
}

async function copyDecision() {
  if (!state.lastDecisionPayload) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.lastDecisionPayload, null, 2));
    showFlash("Decision JSON copied.", "good");
  } catch (error) {
    showFlash(`Could not copy decision JSON: ${error.message}`, "error");
  }
}

async function loadDecisions(showErrors = true) {
  const button = $("#refresh-decisions");
  setBusy(button, true, "Loading…");
  try {
    state.decisions = await api("/api/ai/decisions?limit=100");
    renderDecisionList();
  } catch (error) {
    if (showErrors) showFlash(`Could not load decision journal: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderDecisionList() {
  const query = ($("#decision-search").value || "").trim().toLowerCase();
  const rows = state.decisions.filter((decision) => {
    const haystack = [
      decision.objective,
      decision.decision_id,
      decision.provider,
      decision.model,
      decision.selected ? decision.selected.action : "",
    ].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });

  const container = $("#decision-list");
  if (!rows.length) {
    container.replaceChildren(element("div", "empty-state", query ? "No matching decisions." : "No decisions journaled yet."));
    return;
  }

  container.replaceChildren(...rows.map((decision) => {
    const row = element("button", "decision-row");
    row.type = "button";
    const objective = element("div", "decision-objective");
    objective.append(
      element("strong", null, decision.objective),
      element("span", null, `${shortId(decision.decision_id)} · ${formatDate(decision.created_at)}`),
    );
    row.append(
      objective,
      element("span", "decision-cell", formatPercent(decision.score)),
      pill(decision.abstained ? "Abstained" : "Selected", decision.abstained ? "warn" : "good"),
      element("span", "decision-cell", decision.selected ? decision.selected.action : "No action"),
    );
    row.addEventListener("click", () => {
      state.lastDecisionPayload = { decision, planned_action: null };
      $("#copy-decision").disabled = false;
      renderDecision(state.lastDecisionPayload);
      openView("ai");
    });
    return row;
  }));
}

async function submitResearch(event) {
  event.preventDefault();
  const button = $("#research-submit");
  const target = $("#research-result");
  const seeds = $("#research-seeds").value
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);

  setBusy(button, true, "Researching…");
  target.className = "empty-state tall loading";
  target.textContent = "Crawling and scoring the most relevant permitted public-web pages…";

  try {
    const report = await api("/api/research", {
      method: "POST",
      body: JSON.stringify({
        objective: $("#research-objective").value.trim(),
        seed_urls: seeds,
      }),
    });
    renderResearch(report);
    showFlash(`Research completed with ${formatPercent(report.confidence)} confidence.`, "good");
  } catch (error) {
    target.className = "empty-state tall";
    target.textContent = `Research failed: ${error.message}`;
    showFlash(`Research failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderResearch(report) {
  const root = element("div", "research-summary");
  const stats = element("div", "research-stats");
  [
    ["Confidence", formatPercent(report.confidence)],
    ["Pages", String(report.pages.length)],
    ["Stopped early", report.stopped_early ? "Yes" : "No"],
  ].forEach(([label, value]) => {
    const item = element("div", "meta-card");
    item.append(element("span", null, label), element("strong", null, value));
    stats.append(item);
  });
  root.append(stats);

  report.pages.forEach((page) => {
    const card = element("article", "research-page");
    const header = element("header");
    header.append(
      element("strong", null, page.title || "Untitled page"),
      pill(formatPercent(page.relevance), page.relevance >= 0.5 ? "good" : "info"),
    );
    const link = element("a", null, page.url);
    link.href = page.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const excerpt = page.markdown.length > 700 ? `${page.markdown.slice(0, 700)}…` : page.markdown;
    card.append(header, link, element("p", null, excerpt || "No extracted text."));
    root.append(card);
  });

  if (report.blocked_urls.length) root.append(section("Blocked by research policy", listNode(report.blocked_urls)));
  if (report.failed_urls.length) root.append(section("Failed URLs", listNode(report.failed_urls)));

  $("#research-result").className = "";
  $("#research-result").replaceChildren(root);
}

async function loadProfile() {
  const button = $("#load-profile");
  const target = $("#profile-result");
  setBusy(button, true, "Reading…");
  target.className = "empty-state loading";
  target.textContent = "Reading profile through the configured Instagram provider…";

  try {
    const profile = await api("/api/account/profile");
    const grid = element("div", "profile-grid");
    Object.entries(profile).forEach(([key, value]) => {
      const field = element("div", "profile-field");
      const rendered = value !== null && typeof value === "object" ? JSON.stringify(value) : String(value ?? "N/A");
      field.append(element("span", null, key), element("strong", null, rendered));
      grid.append(field);
    });
    target.className = "";
    target.replaceChildren(grid);
  } catch (error) {
    target.className = "empty-state";
    target.textContent = `Profile read failed: ${error.message}`;
    showFlash(`Profile read failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function checkHealth() {
  try {
    await api("/healthz");
    $("#health-dot").className = "status-dot good";
    $("#health-label").textContent = "Runtime online";
  } catch {
    $("#health-dot").className = "status-dot bad";
    $("#health-label").textContent = "Runtime unavailable";
  }
}

function wireNavigation() {
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => openView(item.dataset.view)));
  $$('[data-go]').forEach((item) => item.addEventListener("click", () => openView(item.dataset.go)));
}

function initialize() {
  wireNavigation();
  $("#refresh-runtime").addEventListener("click", loadRuntime);
  $("#run-readiness").addEventListener("click", () => loadReadiness(true));
  $("#run-ai-probe").addEventListener("click", runAIProbe);
  $("#add-evidence").addEventListener("click", () => addEvidence());
  $("#plan-form").addEventListener("submit", submitPlan);
  $("#copy-decision").addEventListener("click", copyDecision);
  $("#refresh-decisions").addEventListener("click", () => loadDecisions());
  $("#decision-search").addEventListener("input", renderDecisionList);
  $("#research-form").addEventListener("submit", submitResearch);
  $("#load-profile").addEventListener("click", loadProfile);

  addEvidence({
    evidence_id: "evidence-1",
    source: "Approved business context",
    content: "",
    confidence: 1,
  });

  checkHealth();
  loadRuntime();
}

document.addEventListener("DOMContentLoaded", initialize);
