"use strict";

const campaignState = {
  campaigns: [],
  jobs: [],
  evidenceCounter: 0,
  initialized: false,
  editingCampaignId: null,
  editingVersion: null,
  jobFilter: "review",
  jobCampaign: "",
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

function suggestedCampaignName(objective) {
  return objective.split(/[.!?\n]/)[0].trim().slice(0, 90);
}

async function stageCampaignDraft({ objective, evidence = [], seedUrls = [], sourceLabel }) {
  if (typeof objective !== "string" || objective.trim().length < 3 ||
      objective.trim().length > 2000 || !Array.isArray(evidence) || evidence.length > 100 ||
      !Array.isArray(seedUrls) || seedUrls.length > 20) {
    showFlash("The goal or evidence list cannot be transferred into a campaign.", "error");
    return false;
  }
  if (seedUrls.some((url) => typeof url !== "string" || url.length > 500)) {
    showFlash("Some research source URLs are too long to import.", "error");
    return false;
  }
  if (evidence.some((item) => !item.evidence_id || !item.source || !item.content ||
      item.evidence_id.length > 120 || item.source.length > 500 || item.content.length > 12000 ||
      !Number.isFinite(Number(item.confidence)))) {
    showFlash("Some selected evidence is invalid. Review its source, text, and confidence.", "error");
    return false;
  }
  const form = $("#campaign-form");
  if (!form || !campaignState.initialized) {
    showFlash("The campaign editor is unavailable. Reload the page and try again.", "error");
    return false;
  }
  const yes = await confirmConsumerAction({
    title: "Prepare a supervised campaign draft?",
    description: "This replaces unsaved text in the campaign form, not saved campaigns. " +
      "No Instagram action will be planned, approved or executed.",
    details: "From: " + sourceLabel + "\nGoal: " + objective.trim() +
      "\nEvidence items: " + evidence.length +
      "\nSource URLs: " + seedUrls.length +
      "\nNext: review and explicitly create the draft.",
    confirmLabel: "Prepare draft",
  });
  if (!yes) return false;
  resetCampaignEditor();
  $("#campaign-name").value = suggestedCampaignName(objective);
  $("#campaign-objective").value = objective.trim();
  $("#campaign-mode").value = "supervised";
  $("#campaign-research-seeds").value = seedUrls.join("\n");
  $("#campaign-evidence-list").replaceChildren();
  for (const item of evidence) addCampaignEvidence(item);
  if (!evidence.length) addCampaignEvidence();
  $("#campaign-form-note").textContent = evidence.length
    ? "Review imported unverified source text. Saving creates a draft only."
    : "Add supporting evidence or enable research with valid seed URLs before saving.";
  openView("campaigns");
  form.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "start",
  });
  $("#campaign-name").focus({ preventScroll: true });
  showFlash("Draft inputs prepared for your review. Nothing has been created or sent.", "good");
  return true;
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
  const buttons = [$("#refresh-campaigns"), $("#refresh-jobs")];
  buttons.forEach((button) => setBusy(button, true, "Refreshing…"));
  try {
    const [campaigns, jobs] = await Promise.all([
      api("/api/campaigns?limit=200"),
      api("/api/campaign-jobs?limit=200"),
    ]);
    campaignState.campaigns = campaigns;
    campaignState.jobs = jobs;
    renderCampaignMetrics();
    renderCampaignList();
    renderCampaignControls();
    renderCampaignJobs();
  } catch (error) {
    if (showErrors) showFlash(`Could not load campaign workspace: ${error.message}`, "error");
  } finally {
    buttons.forEach((button) => setBusy(button, false));
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

function jobDecisionConsequence(label) {
  const descriptions = {
    Approve: "Authorizes this specific action for the execution queue. A worker may perform the Instagram write later after policy checks. Approval is not publication.",
    Reject: "Rejects this proposed action; the rejected job cannot be executed.",
    Execute: "Requests an Instagram write now. This may publish an image, reply to a comment, or change moderation. Policy is checked again; failure or retry is possible.",
    Cancel: "Requests cancellation of a pending or scheduled job. A job already claimed by a worker may be too late to cancel.",
  };
  return descriptions[label] || "Review this operation and its effect before proceeding.";
}

function jobExecutionFeedback(result) {
  if (result.status === "succeeded") {
    return {kind: "good", message: "Instagram provider reported successful execution. Business impact still needs a separate recorded outcome."};
  }
  if (result.status === "retry_wait") {
    return {kind: "error", message: "Instagram execution did not succeed. The job is waiting for a policy-controlled retry."};
  }
  if (result.status === "failed") {
    return {kind: "error", message: "Instagram execution failed. Review the job error and provider details; nothing is confirmed delivered."};
  }
  return {kind: "info", message: "Execution request returned " + humanize(result.status) +
    ". Check the activity list for an authoritative result."};
}

function confirmJobChange(job, label, destructive = false) {
  const campaign = campaignById(job.campaign_id);
  const proposed = summarizeProposedAction(job.action);
  const provider = state.runtime && state.runtime.instagram
    ? state.runtime.instagram.provider : "Unknown";
  return () => confirmConsumerAction({
    title: `${label}: ${proposed.title}?`,
    description: jobDecisionConsequence(label),
    details: [
      "Campaign: " + (campaign ? campaign.name : shortId(job.campaign_id)),
      "Instagram provider: " + provider,
      "Proposed action: " + proposed.title,
      "Proposed text: " + proposed.message,
      proposed.context,
      "Reason from AI: " + (job.action.reason || "Not supplied"),
      "AI confidence: " + formatPercent(job.action.confidence) +
        " (not proof of accuracy or permission)",
      "Job status: " + humanize(job.status),
      "Scheduled: " + formatDate(job.scheduled_for),
      "Target: " + (job.action.target_id || "Not specified"),
      "Full action payload:",
      JSON.stringify(job.action.payload, null, 2),
    ].join("\n"),
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
  const rewardLabel = element("label", "outcome-field");
  rewardLabel.append(element("span", null, "Business result score (0 to 1)"));
  const reward = element("input", "outcome-reward");
  reward.type = "number";
  reward.min = "0";
  reward.max = "1";
  reward.step = "0.05";
  reward.placeholder = "Choose a score";
  reward.required = true;
  reward.setAttribute("aria-describedby", "outcome-score-help-" + job.job_id);
  rewardLabel.append(reward);
  const help = element("span", "outcome-score-help",
    "0 = no observed business benefit; 1 = fully achieved your goal. Do not guess. " +
    "Record an observed result separately from provider delivery.");
  help.id = "outcome-score-help-" + job.job_id;
  rewardLabel.append(help);
  const noteLabel = element("label", "outcome-field");
  noteLabel.append(element("span", null, "What actually happened?"));
  const note = element("input", "outcome-note-input");
  note.type = "text";
  note.maxLength = 4000;
  note.required = true;
  note.placeholder = "Describe an observed result and where you verified it";
  noteLabel.append(note);
  const submit = element("button", "button button-secondary button-small", "Record outcome");
  submit.type = "submit";
  form.append(rewardLabel, noteLabel, submit);
  form.setAttribute("aria-label", "Record observed business result for " +
    summarizeProposedAction(job.action).title);
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

// The review inbox reads the canonical jobs endpoint. It never decides approvals itself.
const CAMPAIGN_JOB_STAGES = {
  review: ["pending_approval"],
  scheduled: ["scheduled", "retry_wait", "leased"],
  history: ["succeeded", "failed", "rejected", "cancelled"],
};

function campaignJobStage(job) {
  if (CAMPAIGN_JOB_STAGES.review.includes(job.status)) return "review";
  if (CAMPAIGN_JOB_STAGES.scheduled.includes(job.status)) return "scheduled";
  return "history";
}

function visibleCampaignJobs() {
  return campaignState.jobs
    .filter((job) => !campaignState.jobCampaign || job.campaign_id === campaignState.jobCampaign)
    .filter((job) => campaignState.jobFilter === "all" ||
      campaignJobStage(job) === campaignState.jobFilter)
    .slice()
    .sort((a, b) => String(b.updated_at || b.created_at).localeCompare(
      String(a.updated_at || a.created_at),
    ));
}

function jobStageCopy(job) {
  switch (job.status) {
    case "pending_approval": return "Your decision is required. No execution is authorized by this state.";
    case "scheduled": return "Approved and scheduled. The backend still checks policy when execution starts.";
    case "retry_wait": return "Execution is awaiting an authorized retry; inspect the error and attempt count.";
    case "leased": return "The worker has claimed this job. Its outcome is not confirmed yet.";
    case "succeeded": return job.outcome_reward === null
      ? "Provider execution succeeded. Business impact has not been recorded."
      : "The observed business outcome was recorded separately from provider success.";
    case "failed": return "Execution failed. Review the error; this is not a successful action.";
    case "rejected": return "A reviewer rejected this proposed action. It was not executed.";
    case "cancelled": return "This job was cancelled before execution.";
    default: return "Check the job details to understand this state.";
  }
}

function renderCampaignControls() {
  const select = $("#campaign-job-campaign-select");
  if (!select) return;
  const selected = campaignState.campaigns.some(
    (campaign) => campaign.campaign_id === campaignState.jobCampaign,
  ) ? campaignState.jobCampaign : "";
  campaignState.jobCampaign = selected;
  const all = element("option", null, "All campaigns");
  all.value = "";
  const options = campaignState.campaigns.map((campaign) => {
    const option = element("option", null, campaign.name);
    option.value = campaign.campaign_id;
    return option;
  });
  select.replaceChildren(all, ...options);
  select.value = selected;

  const scopedJobs = campaignState.jobs.filter(
    (job) => !selected || job.campaign_id === selected,
  );
  for (const stage of ["review", "scheduled", "history", "all"]) {
    const count = scopedJobs.filter(
      (job) => stage === "all" || campaignJobStage(job) === stage,
    ).length;
    const label = $("[data-job-count='" + stage + "']");
    if (label) label.textContent = String(count);
    const button = $("[data-job-filter='" + stage + "']");
    if (button) {
      const active = campaignState.jobFilter === stage;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("button-secondary", active);
      button.classList.toggle("button-ghost", !active);
    }
  }

  const summary = $("#campaign-job-summary");
  const awaiting = scopedJobs.filter((job) => job.status === "pending_approval").length;
  const needsOutcome = scopedJobs.filter(
    (job) => job.status === "succeeded" && job.outcome_reward === null,
  ).length;
  const failures = scopedJobs.filter((job) => job.status === "failed").length;
  summary.replaceChildren(
    metricCard("Needs your approval", String(awaiting), "Proposed writes not yet authorized"),
    metricCard("Awaiting outcome", String(needsOutcome), "Provider success is not business success"),
    metricCard("Failed actions", String(failures), "Inspect errors before planning again"),
  );
  const messages = {
    review: "Only pending approvals are shown. Inspect the full payload and confirm each decision.",
    scheduled: "Scheduled, retrying, or actively leased actions. The worker may change these states.",
    history: "Provider results, failures, rejections, cancellations, and recorded business outcomes.",
    all: "All returned jobs, newest updates first.",
  };
  $("#campaign-job-context").textContent =
    messages[campaignState.jobFilter] +
    " Showing the most recent " + campaignState.jobs.length + " of up to 200 returned jobs.";
}

function selectCampaignJobFilter(stage) {
  if (!["review", "scheduled", "history", "all"].includes(stage)) return;
  campaignState.jobFilter = stage;
  renderCampaignControls();
  renderCampaignJobs();
}

function summarizeProposedAction(action) {
  const payload = action.payload || {};
  const target = String(action.target_id || payload.comment_id || "Not specified");
  const asText = (value) => typeof value === "string" && value.trim() ? value.trim() : "Not supplied";
  if (action.action_type === "publish_image") {
    return {
      title: "Publish an image",
      message: asText(payload.caption),
      context: "Image URL: " + asText(payload.image_url),
    };
  }
  if (action.action_type === "reply_to_comment") {
    return {
      title: "Reply to an Instagram comment",
      message: asText(payload.message),
      context: "Comment: " + target,
    };
  }
  if (action.action_type === "hide_comment") {
    return {
      title: payload.hide === false ? "Unhide an Instagram comment" : "Hide an Instagram comment",
      message: "Moderation target: " + target,
      context: "Check the full action payload before approving.",
    };
  }
  return {
    title: "Review proposed Instagram action",
    message: String(action.reason || "Reason not supplied"),
    context: "Check the full action payload before approving.",
  };
}

function renderActionPreview(action) {
  const proposed = summarizeProposedAction(action);
  const box = element("div", "campaign-action-preview");
  box.append(
    element("span", "campaign-preview-label", "Proposed Instagram action"),
    element("strong", "campaign-preview-title", proposed.title),
    element("p", "campaign-preview-message", proposed.message),
    element("p", "campaign-preview-context", proposed.context),
  );
  return box;
}

function renderCampaignJobs() {
  const target = $("#campaign-job-list");
  const visible = visibleCampaignJobs();
  if (!visible.length) {
    const messages = {
      review: "Nothing awaits your approval. New proposals will appear here after planning.",
      scheduled: "Nothing is scheduled or retrying. Approved work will appear here.",
      history: "No completed actions or results yet. This history fills in after execution.",
      all: "No campaign jobs yet. Create and plan a campaign to propose the first action.",
    };
    target.replaceChildren(element("div", "empty-state", messages[campaignState.jobFilter]));
    return;
  }

  const cards = visible.map((job) => {
    const campaign = campaignById(job.campaign_id);
    const card = element("article", "campaign-job-card");
    card.dataset.jobId = job.job_id;
    if (job.status === "pending_approval") card.classList.add("needs-review");
    const headingId = "job-heading-" + job.job_id;
    card.setAttribute("aria-labelledby", headingId);
    const header = element("div", "campaign-card-header");
    const copy = element("div");
    copy.append(
      element("strong", "campaign-name", campaign ? campaign.name : shortId(job.campaign_id)),
      element("p", "campaign-objective", `${humanize(job.action.action_type)} · ${job.action.reason}`),
    );
    const campaignHeading = copy.querySelector(".campaign-name");
    campaignHeading.id = headingId;
    header.append(copy, pill(humanize(job.status), campaignStatusKind(job.status)));
    card.append(
      element("p", "campaign-job-explanation", jobStageCopy(job)),
      renderActionPreview(job.action),
    );
    if (job.status === "pending_approval") {
      card.append(element("p", "campaign-approval-consequence",
        "Approval authorizes a future Instagram write, not just saving a draft. " +
        "Review the proposed text, target, and full payload before deciding."));
    }

    const meta = element("div", "campaign-meta job-meta");
    [
      ["AI confidence", formatPercent(job.action.confidence)],
      ["Approval", humanize(job.action.approval)],
      ["Scheduled", formatDate(job.scheduled_for)],
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
      actions.append(campaignActionButton("Execute", "button-danger", async () => {
        const result = await api(`/api/campaign-jobs/${job.job_id}/execute`, {
          method: "POST", body: "{}",
        });
        const feedback = jobExecutionFeedback(result);
        showFlash(feedback.message, feedback.kind);
      }, confirmJobChange(job, "Execute", true)));
    }
    if (["pending_approval", "scheduled", "retry_wait"].includes(job.status)) {
      actions.append(campaignActionButton("Cancel", "button-ghost", async () => {
        await api(`/api/campaign-jobs/${job.job_id}/cancel`, { method: "POST", body: "{}" });
        showFlash("Campaign job cancelled.", "good");
      }, confirmJobChange(job, "Cancel", true)));
    }

    for (const button of actions.querySelectorAll("button")) {
      button.setAttribute("aria-label", button.textContent + " " +
        summarizeProposedAction(job.action).title + " in " +
        (campaign ? campaign.name : shortId(job.campaign_id)));
    }
    const details = element("details", "job-details");
    const summary = element("summary", null, "Technical details: payload, IDs, provider state and evidence");
    const body = element("div", "job-detail-grid");
    body.append(
      section("Action payload", element("pre", "code-block", JSON.stringify(job.action.payload, null, 2))),
      section("Attempts", `${job.attempt_count}/${job.max_attempts}`),
      section("Decision ID", job.decision_id),
      section("Job ID", job.job_id),
      section("Idempotency key", job.action.idempotency_key),
    );
    if (job.last_error) body.append(section("Last error", job.last_error));
    if (job.provider_result !== null) {
      body.append(section("Provider result", element("pre", "code-block", JSON.stringify(job.provider_result, null, 2))));
    }
    details.append(summary, body);

    card.prepend(header);
    if (job.last_error && ["failed", "retry_wait"].includes(job.status)) {
      card.append(element("p", "campaign-job-error",
        "Execution error: " + job.last_error));
    }
    card.append(meta, actions, details, renderJobOutcome(job));
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
  $("#refresh-jobs").addEventListener("click", () => refreshCampaignWorkspace(true));
  $$(".campaign-job-filters [data-job-filter]").forEach((button) => {
    button.addEventListener("click", () => selectCampaignJobFilter(button.dataset.jobFilter));
  });
  $("#campaign-job-campaign-select").addEventListener("change", (event) => {
    campaignState.jobCampaign = event.target.value;
    renderCampaignControls();
    renderCampaignJobs();
  });
  const nav = $('.nav-item[data-view="campaigns"]');
  if (nav) nav.addEventListener("click", () => refreshCampaignWorkspace(true));
  toggleCampaignResearchFields();
  syncCampaignCadence();
}

document.addEventListener("DOMContentLoaded", initializeCampaignWorkspace);
