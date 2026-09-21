"use strict";

(function installTrialEvidenceExport() {
  const renderJobs = renderCampaignJobs;

  function downloadEvidence(job, bundle) {
    const payload = `${JSON.stringify(bundle, null, 2)}\n`;
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `trial-evidence-${job.job_id}.json`;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function evidenceButton(job) {
    const button = element("button", "button button-small button-secondary", "Export evidence");
    button.type = "button";
    button.setAttribute("aria-label", `Export evidence for job ${shortId(job.job_id)}`);
    button.addEventListener("click", async () => {
      setBusy(button, true, "Exporting…");
      try {
        const bundle = await api(`/api/campaign-jobs/${job.job_id}/evidence`);
        downloadEvidence(job, bundle);
        showFlash(
          `Evidence bundle ${shortId(bundle.bundle_id)} exported with SHA-256 integrity metadata.`,
          "good",
        );
      } catch (error) {
        showFlash(`Evidence export failed: ${error.message}`, "error");
      } finally {
        setBusy(button, false);
      }
    });
    return button;
  }

  renderCampaignJobs = function renderCampaignJobsWithEvidenceExport() {
    renderJobs();
    const target = $("#campaign-job-list");
    const cards = $$(".campaign-job-card", target);
    cards.forEach((card, index) => {
      const job = campaignState.jobs[index];
      const actions = $(".campaign-actions", card);
      if (!job || !actions || $(".trial-evidence-export", actions)) return;
      const button = evidenceButton(job);
      button.classList.add("trial-evidence-export");
      actions.append(button);
    });
  };
})();
