"use strict";

const campaignState = {
  campaigns: [],
  jobs: [],
  evidenceCounter: 0,
  initialized: false,
  editingCampaignId: null,
  editingVersion: null,
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

function readableCampaignCadence(minutes) {
  const frequency = {
    1440: "Once a day",
    720: "Twice a day",
    360: "Every 6 hours",
    10080: "Once a week",
  };
  return frequency[minutes] || `Every ${minutes} minutes`;
}

function syncCampaignCadence() {
  const field = $("#campaign-cadence");
  const preset = $("#campaign-cadence-preset");
  const value = String(Number(field.value));
  const predefined = ["1440", "720", "360", "10080"].includes(value);
  preset.value = predefined ? value : "custom";
  $("#campaign-cadence-custom-field").classList.toggle("is-hidden", predefined);
  $("#campaign-cadence-help").textContent = predefined
    ? readableCampaignCadence(Number(value)) + ". Approval is still required before any write."
    : "Specify a custom interval. The backend validates the final number of minutes.";
}

function applyCampaignCadencePreset() {
  const preset = $("#campaign-cadence-preset").value;
  if (preset === "custom") {
    $("#campaign-cadence-custom-field").classList.remove("is-hidden");
    $("#campaign-cadence-help").textContent =
      "Specify a custom interval. The backend validates the final number of minutes.";
    $("#campaign-cadence").focus();
    return;
  }
  $("#campaign-cadence").value = preset;
  syncCampaignCadence();
}

function resetCampaignEditor() {
  campaignState.editingCampaignId = null;
  campaignState.editingVersion = null;
  $("#campaign-form").reset();
  $("#campaign-cadence").value = "1440";
  $("#campaign-delay").value = "0";
  syncCampaignCadence();
  $("#campaign-context").value = "{}";
  $("#campaign-evidence-list").replaceChildren();
  addCampaignEvidence();
  toggleCampaignResearchFields();
  $("#campaign-create-submit").textContent = "Create campaign";
  $("#campaign-cancel-edit").classList.add("is-hidden");
  $("#campaign-form-heading").textContent = "Create campaign";
  $("#campaign-form-note").textContent = "New campaigns start as drafts.";
}

function beginCampaignEdit(campaign) {
  if (!["draft", "paused"].includes(campaign.status)) return;
  campaignState.editingCampaignId = campaign.campaign_id;
  campaignState.editingVersion = campaign.updated_at;
  $("#campaign-name").value = campaign.name;
  $("#campaign-objective").value = campaign.objective;
  $("#campaign-mode").value = campaign.mode;
  $("#campaign-cadence").value = String(campaign.cadence_minutes);
  $("#campaign-delay").value = String(campaign.action_delay_minutes);
  syncCampaignCadence();
  $("#campaign-research-enabled").checked = campaign.research_before_plan;
  $("#campaign-research-seeds").value = campaign.research_seed_urls.join("\n");
  $("#campaign-context").value = JSON.stringify(campaign.context, null, 2);
  $("#campaign-evidence-list").replaceChildren();
  for (const item of campaign.evidence) addCampaignEvidence(item);
  if (!campaign.evidence.length) addCampaignEvidence();
  toggleCampaignResearchFields();
  $("#campaign-create-submit").textContent = "Save changes";
  $("#campaign-cancel-edit").classList.remove("is-hidden");
  $("#campaign-form-heading").textContent = "Edit campaign";
  $("#campaign-form-note").textContent =
    "Edits require draft or paused status, no open jobs, and an unchanged campaign version.";
  const form = $("#campaign-form");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  form.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  $("#campaign-name").focus({ preventScroll: true });
}

async function saveCampaignFromForm(event) {
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

  const editingId = campaignState.editingCampaignId;
  if (editingId) {
    const approved = await confirmConsumerAction({
      title: "Save campaign changes?",
      description: "Changes affect future planning only. Existing queued jobs will not be changed.",
      details: JSON.stringify(payload, null, 2),
      confirmLabel: "Save changes",
    });
    if (!approved) return;
    payload.expected_updated_at = campaignState.editingVersion;
  }
  setBusy(button, true, editingId ? "Saving…" : "Creating…");
  try {
    const campaign = await api(editingId ? `/api/campaigns/${editingId}` : "/api/campaigns", {
      method: editingId ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    resetCampaignEditor();
    await refreshCampaignWorkspace(false);
    showFlash(editingId ?
      `Campaign “${campaign.name}” updated. Future plans use the new settings.` :
      `Campaign “${campaign.name}” created as a draft.`, "good");
  } catch (error) {
    showFlash(`Campaign ${editingId ? "update" : "creation"} failed: ${error.message}`, "error");
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

function campaignActionButton(label, className, handler, confirmation = null) {
  const button = element("button", `button button-small ${className}`, label);
  button.type = "button";
  button.addEventListener("click", async () => {
    if (confirmation && !(await confirmation())) return;
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

function confirmCampaignChange(campaign, label, destructive = false) {
  return () => confirmConsumerAction({
    title: `${label} campaign?`,
    description: `This will change the state of “${campaign.name}”. Confirm the intended effect before continuing.`,
    details: `Campaign: ${campaign.name}\nObjective: ${campaign.objective}\nCurrent status: ${humanize(campaign.status)}`,
    confirmLabel: label,
    destructive,
  });
}

function confirmJobChange(job, label, destructive = false) {
  const campaign = campaignById(job.campaign_id);
  return () => confirmConsumerAction({
    title: `${label} Instagram action?`,
    description: "Review the account, scheduled time, target, and entire action payload before applying this change.",
    details: `Campaign: ${campaign ? campaign.name : shortId(job.campaign_id)}\nInstagram provider: ${state.runtime ? state.runtime.instagram.provider : "Unknown"}\nAction: ${humanize(job.action.action_type)}\nJob status: ${humanize(job.status)}\nScheduled: ${formatDate(job.scheduled_for)}\nTarget: ${job.action.target_id || "Not specified"}\nPayload:\n${JSON.stringify(job.action.payload, null, 2)}`,
    confirmLabel: label,
    destructive,
  });
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
      ["Cadence", readableCampaignCadence(campaign.cadence_minutes)],
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
      actions.append(campaignActionButton("Edit", "button-ghost", async () => {
        beginCampaignEdit(campaign);
      }));
      actions.append(campaignActionButton("Activate", "button-secondary", async () => {
        await api(`/api/campaigns/${campaign.campaign_id}/activate`, { method: "POST", body: "{}" });
        showFlash(`Campaign “${campaign.name}” activated.`, "good");
      }, confirmCampaignChange(campaign, "Activate")));
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
      }, confirmCampaignChange(campaign, "Archive", true)));
    }

    card.append(header, meta, actions);
    return card;
  });
  target.replaceChildren(...cards);
}

function canExecuteJob(job) {
  if (!state.runtime || !state.runtime.policy) return false;
  if (!["scheduled", "retry_wait"].includes(job.status)) return false;
  return job.action.approval === "approved" || !state.runtime.policy.write_approval_required;
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
        }, confirmJobChange(job, "Approve")),
        campaignActionButton("Reject", "button-secondary", async () => {
          await api(`/api/campaign-jobs/${job.job_id}/reject`, { method: "POST", body: "{}" });
          showFlash("Campaign action rejected.", "good");
        }, confirmJobChange(job, "Reject", true)),
      );
    }
    if (canExecuteJob(job)) {
      actions.append(campaignActionButton("Execute", "button-primary", async () => {
        await api(`/api/campaign-jobs/${job.job_id}/execute`, { method: "POST", body: "{}" });
        showFlash("Provider execution completed through the canonical automation service.", "good");
      }, confirmJobChange(job, "Execute", true)));
    }
    if (["pending_approval", "scheduled", "retry_wait"].includes(job.status)) {
      actions.append(campaignActionButton("Cancel", "button-ghost", async () => {
        await api(`/api/campaign-jobs/${job.job_id}/cancel`, { method: "POST", body: "{}" });
        showFlash("Campaign job cancelled.", "good");
      }, confirmJobChange(job, "Cancel", true)));
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
  $("#campaign-form").addEventListener("submit", saveCampaignFromForm);
  $("#campaign-cancel-edit").addEventListener("click", resetCampaignEditor);
  $("#campaign-add-evidence").addEventListener("click", () => addCampaignEvidence());
  $("#campaign-cadence-preset").addEventListener("change", applyCampaignCadencePreset);
  $("#campaign-cadence").addEventListener("change", syncCampaignCadence);
  $("#campaign-research-enabled").addEventListener("change", toggleCampaignResearchFields);
  $("#refresh-campaigns").addEventListener("click", () => refreshCampaignWorkspace(true));
  const nav = $('.nav-item[data-view="campaigns"]');
  if (nav) nav.addEventListener("click", () => refreshCampaignWorkspace(true));
  toggleCampaignResearchFields();
  syncCampaignCadence();
}

document.addEventListener("DOMContentLoaded", initializeCampaignWorkspace);
