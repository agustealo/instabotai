"use strict";

const campaignState = {
  campaigns: [],
  jobs: [],
  evidenceCounter: 0,
  initialized: false,
};

function campaignStatusKind(status) {
  if (["active", "succeeded", "scheduled"].includes(status)) return "good";
  if (["pending_approval", "retry_wait", "paused", "draft"].includes(status)) return "warn";
  if (["failed", "rejected", "cancelled", "archived"].includes(status)) return "bad";
  return "info";
}

function humanize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function campaignById(campaignId) {
  return campaignState.campaigns.find((campaign) => campaign.campaign_id === campaignId) || null;
}

function addCampaignEvidence(seed = {}) {
  campaignState.evidenceCounter += 1;
  const card = element("div", "evidence-card campaign-evidence-card");
  card.dataset.evidenceIndex = String(campaignState.evidenceCounter);

  const top = element("div", "evidence-topline");
  const id = element("input", "campaign-evidence-id");
  id.type = "text";
  id.maxLength = 120;
  id.placeholder = "Evidence ID";
  id.value = seed.evidence_id || `campaign-evidence-${campaignState.evidenceCounter}`;
  id.setAttribute("aria-label", "Campaign evidence ID");

  const remove = element("button", "icon-button", "×");
  remove.type = "button";
  remove.setAttribute("aria-label", "Remove campaign evidence");
  remove.addEventListener("click", () => card.remove());
  top.append(id, remove);

  const meta = element("div", "evidence-meta");
  const sourceLabel = element("label");
  sourceLabel.append(element("span", null, "Source"));
  const source = element("input", "campaign-evidence-source");
  source.type = "text";
  source.maxLength = 500;
  source.placeholder = "Approved brief, research report, product spec…";
  source.value = seed.source || "";
  sourceLabel.append(source);

  const confidenceLabel = element("label");
  confidenceLabel.append(element("span", null, "Confidence"));
  const confidence = element("input", "campaign-evidence-confidence");
  confidence.type = "number";
  confidence.min = "0";
  confidence.max = "1";
  confidence.step = "0.05";
  confidence.value = String(seed.confidence ?? 1);
  confidenceLabel.append(confidence);
  meta.append(sourceLabel, confidenceLabel);

  const contentLabel = element("label");
  contentLabel.append(element("span", null, "Evidence content"));
  const content = element("textarea", "campaign-evidence-content");
  content.rows = 4;
  content.maxLength = 12000;
  content.placeholder = "Only factual material the planner is allowed to rely on.";
  content.value = seed.content || "";
  contentLabel.append(content);

  card.append(top, meta, contentLabel);
  $("#campaign-evidence-list").append(card);
}

function collectCampaignEvidence() {
  return $$(".campaign-evidence-card", $("#campaign-evidence-list"))
    .map((card) => ({
      evidence_id: $(".campaign-evidence-id", card).value.trim(),
      source: $(".campaign-evidence-source", card).value.trim(),
      content: $(".campaign-evidence-content", card).value.trim(),
      confidence: Number($(".campaign-evidence-confidence", card).value),
    }))
    .filter((item) => item.evidence_id && item.source && item.content);
}

function collectCampaignContext() {
  const raw = $("#campaign-context").value.trim() || "{}";
  const value = JSON.parse(raw);
  if (!value || Array.isArray(value) || typeof value !== "object") {
    throw new Error("Campaign context must be a JSON object.");
  }
  return value;
}

function collectCampaignSeeds() {
  return $("#campaign-research-seeds").value
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

async function createCampaignFromForm(event) {
  event.preventDefault();
  const button = $("#campaign-create-submit");
  let context;
  try {
    context = collectCampaignContext();
  } catch (error) {
    showFlash(error.message, "error");
    return;
  }

  const researchBeforePlan = $("#campaign-research-enabled").checked;
  const evidence = collectCampaignEvidence();
  const researchSeedUrls = collectCampaignSeeds();
  if (!evidence.length && !(researchBeforePlan && researchSeedUrls.length)) {
    showFlash("Add complete evidence or enable research with at least one seed URL.", "error");
    return;
  }

  const payload = {
    name: $("#campaign-name").value.trim(),
    objective: $("#campaign-objective").value.trim(),
    mode: $("#campaign-mode").value,
    cadence_minutes: Number($("#campaign-cadence").value),
    action_delay_minutes: Number($("#campaign-delay").value),
    evidence,
    context,
    research_seed_urls: researchSeedUrls,
    research_before_plan: researchBeforePlan,
  };

  setBusy(button, true, "Creating…");
  try {
    const campaign = await api("/api/campaigns", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("#campaign-form").reset();
    $("#campaign-cadence").value = "1440";
    $("#campaign-delay").value = "0";
    $("#campaign-context").value = "{}";
    $("#campaign-evidence-list").replaceChildren();
    addCampaignEvidence();
    await refreshCampaignWorkspace(false);
    showFlash(`Campaign “${campaign.name}” created as a draft.`, "good");
  } catch (error) {
    showFlash(`Campaign creation failed: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function refreshCampaignWorkspace(showErrors = true) {
  const button = $("#refresh-campaigns");
  setBusy(button, true, "Refreshing…");
  try {
    const [campaigns, jobs] = await Promise.all([
      api("/api/campaigns?limit=200"),
      api("/api/campaign-jobs?limit=200"),
    ]);
    campaignState.campaigns = campaigns;
    campaignState.jobs = jobs;
    renderCampaignMetrics();
    renderCampaignList();
    renderCampaignJobs();
  } catch (error) {
    if (showErrors) showFlash(`Could not load campaign workspace: ${error.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderCampaignMetrics() {
  const target = $("#campaign-metrics");
  const active = campaignState.campaigns.filter((campaign) => campaign.status === "active").length;
  const approvals = campaignState.jobs.filter((job) => job.status === "pending_approval").length;
  const executable = campaignState.jobs.filter((job) => ["scheduled", "retry_wait"].includes(job.status)).length;
  const learned = campaignState.jobs.filter((job) => job.outcome_reward !== null).length;
  target.replaceChildren(
    metricCard("Campaigns", String(campaignState.campaigns.length), `${active} active`),
    metricCard("Approval queue", String(approvals), "human-authorized writes waiting"),
    metricCard("Execution queue", String(executable), "scheduled or retryable actions"),
    metricCard("Learned outcomes", String(learned), "explicit business results recorded"),
  );
}

function campaignActionButton(label, className, handler) {
  const button = element("button", `button button-small ${className}`, label);
  button.type = "button";
  button.addEventListener("click", async () => {
    setBusy(button, true, `${label}…`);
    try {
      await handler();
      await refreshCampaignWorkspace(false);
    } catch (error) {
      showFlash(`${label} failed: ${error.message}`, "error");
    } finally {
      setBusy(button, false);
    }
  });
  return button;
}

function renderCampaignList() {
  const target = $("#campaign-list");
  if (!campaignState.campaigns.length) {
    target.replaceChildren(element("div", "empty-state", "No campaigns yet. Create a draft to begin."));
    return;
  }

  const cards = campaignState.campaigns.map((campaign) => {
    const card = element("article", "campaign-card");
    const header = element("div", "campaign-card-header");
    const copy = element("div");
    copy.append(
      element("strong", "campaign-name", campaign.name),
      element("p", "campaign-objective", campaign.objective),
    );
    header.append(copy, pill(humanize(campaign.status), campaignStatusKind(campaign.status)));

    const meta = element("div", "campaign-meta");
    [
      ["Mode", humanize(campaign.mode)],
      ["Cadence", `${campaign.cadence_minutes} min`],
      ["Next plan", formatDate(campaign.next_run_at)],
      ["Last plan", formatDate(campaign.last_run_at)],
      ["Evidence", String(campaign.evidence.length)],
      ["Failures", String(campaign.consecutive_failures)],
    ].forEach(([label, value]) => {
      const item = element("div", "meta-card");
      item.append(element("span", null, label), element("strong", null, value));
      meta.append(item);
    });

    const actions = element("div", "campaign-actions");
    if (["draft", "paused"].includes(campaign.status)) {
      actions.append(campaignActionButton("Activate", "button-secondary", async () => {
        await api(`/api/campaigns/${campaign.campaign_id}/activate`, { method: "POST", body: "{}" });
        showFlash(`Campaign “${campaign.name}” activated.`, "good");
      }));
    }
    if (campaign.status === "active") {
      actions.append(campaignActionButton("Pause", "button-secondary", async () => {
        await api(`/api/campaigns/${campaign.campaign_id}/pause`, { method: "POST", body: "{}" });
        showFlash(`Campaign “${campaign.name}” paused.`, "good");
      }));
    }
    if (campaign.status !== "archived") {
      actions.append(campaignActionButton("Plan now", "button-primary", async () => {
        const outcome = await api(`/api/campaigns/${campaign.campaign_id}/plan-now`, {
          method: "POST",
          body: "{}",
        });
        const message = outcome.job
          ? `Reviewed decision created job ${shortId(outcome.job.job_id)}.`
          : "Planner reviewed the campaign and abstained from creating an action.";
        showFlash(message, "good");
      }));
      actions.append(campaignActionButton("Archive", "button-ghost", async () => {
        await api(`/api/campaigns/${campaign.campaign_id}/archive`, { method: "POST", body: "{}" });
        showFlash(`Campaign “${campaign.name}” archived.`, "good");
      }));
    }

    card.append(header, meta, actions);
    return card;
  });
  target.replaceChildren(...cards);
}

function canExecuteJob(job) {
  if (!state.runtime) return true;
  if (job.action.approval !== "approved" && state.runtime.policy.write_approval_required) return false;
  return ["scheduled", "retry_wait"].includes(job.status);
}

function renderJobOutcome(job) {
  const box = element("div", "outcome-box");
  if (job.outcome_reward !== null) {
    box.append(
      pill(`Learned reward ${formatPercent(job.outcome_reward)}`, "good"),
      element("p", "outcome-note", job.outcome_note || "Outcome recorded without a note."),
    );
    return box;
  }
  if (job.status !== "succeeded") return box;

  const heading = element("div", "outcome-heading");
  heading.append(
    element("strong", null, "Record business outcome"),
    element("span", null, "This is the only signal fed back into campaign learning."),
  );
  const form = element("form", "outcome-form");
  const reward = element("input", "outcome-reward");
  reward.type = "number";
  reward.min = "0";
  reward.max = "1";
  reward.step = "0.05";
  reward.value = "0.5";
  reward.required = true;
  reward.setAttribute("aria-label", "Outcome reward from zero to one");
  const note = element("input", "outcome-note-input");
  note.type = "text";
  note.maxLength = 4000;
  note.placeholder = "What happened after execution?";
  const submit = element("button", "button button-secondary button-small", "Record outcome");
  submit.type = "submit";
  form.append(reward, note, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBusy(submit, true, "Recording…");
    try {
      await api(`/api/campaign-jobs/${job.job_id}/outcome`, {
        method: "POST",
        body: JSON.stringify({ reward: Number(reward.value), note: note.value.trim() }),
      });
      await refreshCampaignWorkspace(false);
      showFlash("Business outcome recorded and made available to AI experience memory.", "good");
    } catch (error) {
      showFlash(`Outcome recording failed: ${error.message}`, "error");
    } finally {
      setBusy(submit, false);
    }
  });
  box.append(heading, form);
  return box;
}

function renderCampaignJobs() {
  const target = $("#campaign-job-list");
  if (!campaignState.jobs.length) {
    target.replaceChildren(element("div", "empty-state", "No campaign jobs have been planned yet."));
    return;
  }

  const cards = campaignState.jobs.map((job) => {
    const campaign = campaignById(job.campaign_id);
    const card = element("article", "campaign-job-card");
    const header = element("div", "campaign-card-header");
    const copy = element("div");
    copy.append(
      element("strong", "campaign-name", campaign ? campaign.name : shortId(job.campaign_id)),
      element("p", "campaign-objective", `${humanize(job.action.action_type)} · ${job.action.reason}`),
    );
    header.append(copy, pill(humanize(job.status), campaignStatusKind(job.status)));

    const meta = element("div", "campaign-meta job-meta");
    [
      ["Confidence", formatPercent(job.action.confidence)],
      ["Approval", humanize(job.action.approval)],
      ["Scheduled", formatDate(job.scheduled_for)],
      ["Attempts", `${job.attempt_count}/${job.max_attempts}`],
      ["Decision", shortId(job.decision_id)],
      ["Job", shortId(job.job_id)],
    ].forEach(([label, value]) => {
      const item = element("div", "meta-card");
      item.append(element("span", null, label), element("strong", null, value));
      meta.append(item);
    });

    const actions = element("div", "campaign-actions");
    if (job.status === "pending_approval") {
      actions.append(
        campaignActionButton("Approve", "button-primary", async () => {
          await api(`/api/campaign-jobs/${job.job_id}/approve`, { method: "POST", body: "{}" });
          showFlash("Campaign action approved and moved to the execution queue.", "good");
        }),
        campaignActionButton("Reject", "button-secondary", async () => {
          await api(`/api/campaign-jobs/${job.job_id}/reject`, { method: "POST", body: "{}" });
          showFlash("Campaign action rejected.", "good");
        }),
      );
    }
    if (canExecuteJob(job)) {
      actions.append(campaignActionButton("Execute", "button-primary", async () => {
        await api(`/api/campaign-jobs/${job.job_id}/execute`, { method: "POST", body: "{}" });
        showFlash("Provider execution completed through the canonical automation service.", "good");
      }));
    }
    if (["pending_approval", "scheduled", "retry_wait"].includes(job.status)) {
      actions.append(campaignActionButton("Cancel", "button-ghost", async () => {
        await api(`/api/campaign-jobs/${job.job_id}/cancel`, { method: "POST", body: "{}" });
        showFlash("Campaign job cancelled.", "good");
      }));
    }

    const details = element("details", "job-details");
    const summary = element("summary", null, "Inspect payload and provider state");
    const body = element("div", "job-detail-grid");
    body.append(
      section("Action payload", element("pre", "code-block", JSON.stringify(job.action.payload, null, 2))),
      section("Idempotency key", job.action.idempotency_key),
    );
    if (job.last_error) body.append(section("Last error", job.last_error));
    if (job.provider_result !== null) {
      body.append(section("Provider result", element("pre", "code-block", JSON.stringify(job.provider_result, null, 2))));
    }
    details.append(summary, body);

    card.append(header, meta, actions, details, renderJobOutcome(job));
    return card;
  });
  target.replaceChildren(...cards);
}

function toggleCampaignResearchFields() {
  const enabled = $("#campaign-research-enabled").checked;
  $("#campaign-research-fields").classList.toggle("is-hidden", !enabled);
}

function initializeCampaignWorkspace() {
  if (campaignState.initialized) return;
  campaignState.initialized = true;
  addCampaignEvidence();
  $("#campaign-form").addEventListener("submit", createCampaignFromForm);
  $("#campaign-add-evidence").addEventListener("click", () => addCampaignEvidence());
  $("#campaign-research-enabled").addEventListener("change", toggleCampaignResearchFields);
  $("#refresh-campaigns").addEventListener("click", () => refreshCampaignWorkspace(true));
  const nav = $('.nav-item[data-view="campaigns"]');
  if (nav) nav.addEventListener("click", () => refreshCampaignWorkspace(true));
  toggleCampaignResearchFields();
}

document.addEventListener("DOMContentLoaded", initializeCampaignWorkspace);
