"use strict";

(function mountCampaignWorkspace() {
  if (!document.querySelector('link[href="/assets/campaigns.css"]')) {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "/assets/campaigns.css";
    document.head.append(style);
  }

  if (!document.querySelector('.nav-item[data-view="campaigns"]')) {
    const nav = document.querySelector(".nav");
    const decisionNav = document.querySelector('.nav-item[data-view="decisions"]');
    if (nav) {
      const button = document.createElement("button");
      button.className = "nav-item";
      button.dataset.view = "campaigns";
      button.innerHTML = '<span class="nav-icon">↻</span><span>Campaigns</span>';
      button.addEventListener("click", () => openView("campaigns"));
      nav.insertBefore(button, decisionNav || null);
    }
  }

  if (!document.querySelector("#view-campaigns")) {
    const decisionView = document.querySelector("#view-decisions");
    const main = document.querySelector("main.main");
    if (main) {
      const section = document.createElement("section");
      section.className = "view";
      section.id = "view-campaigns";
      section.dataset.title = "Campaigns";
      section.innerHTML = `
        <div class="metric-grid" id="campaign-metrics">
          <article class="metric-card skeleton"></article>
          <article class="metric-card skeleton"></article>
          <article class="metric-card skeleton"></article>
          <article class="metric-card skeleton"></article>
        </div>
        <div class="campaign-guardrail">
          Campaign planning and provider execution are deliberately separate. Supervised work waits
          for approval, and every write still passes the canonical policy, quota, idempotency, and
          provider execution spine. A successful provider call is not treated as a successful
          business outcome until an outcome is explicitly recorded.
        </div>
        <div class="two-column campaign-layout">
          <article class="panel campaign-create-panel">
            <div class="panel-heading"><div><p class="eyebrow">Durable automation</p><h3>Create campaign</h3><p>Build recurring work from approved evidence or bounded public-web research.</p></div></div>
            <form id="campaign-form" class="form-stack">
              <label><span>Campaign name</span><input id="campaign-name" type="text" maxlength="160" required placeholder="Fall product launch"></label>
              <label><span>Business objective</span><textarea id="campaign-objective" rows="4" maxlength="2000" required placeholder="Publish evidence-grounded launch content and learn from measured outcomes."></textarea></label>
              <div class="campaign-form-grid">
                <label><span>Authority mode</span><select id="campaign-mode"><option value="supervised" selected>Supervised</option><option value="policy_managed">Policy managed</option></select><small>Global write-approval policy remains authoritative in either mode.</small></label>
                <label><span>Planning cadence (minutes)</span><input id="campaign-cadence" type="number" min="5" max="43200" value="1440" required></label>
                <label><span>Action delay (minutes)</span><input id="campaign-delay" type="number" min="0" max="10080" value="0" required></label>
                <label class="campaign-check"><input id="campaign-research-enabled" type="checkbox"><span>Research public web before each plan</span></label>
              </div>
              <div id="campaign-research-fields" class="form-stack is-hidden"><label><span>Research seed URLs</span><textarea id="campaign-research-seeds" rows="5" placeholder="https://example.com/approved-market-report&#10;https://example.org/product-news"></textarea><small>One permitted HTTP/HTTPS URL per line.</small></label></div>
              <div class="field-header"><div><strong>Campaign evidence</strong><small>Manual evidence can be combined with research evidence.</small></div><button type="button" class="button button-ghost button-small" id="campaign-add-evidence">Add evidence</button></div>
              <div id="campaign-evidence-list" class="evidence-list"></div>
              <details class="advanced"><summary>Advanced context</summary><label><span>Bounded JSON context</span><textarea id="campaign-context" rows="6" spellcheck="false">{}</textarea></label></details>
              <div class="form-actions"><span class="form-note">New campaigns start as drafts.</span><button class="button button-primary" type="submit" id="campaign-create-submit">Create campaign</button></div>
            </form>
          </article>
          <article class="panel">
            <div class="panel-heading"><div><p class="eyebrow">Campaign lifecycle</p><h3>Planning queue</h3><p>Activate, pause, archive, or request one immediate reviewed planning pass.</p></div><button class="button button-secondary" id="refresh-campaigns">Refresh</button></div>
            <div id="campaign-list" class="campaign-list"><div class="empty-state">Open Campaigns to load durable campaign state.</div></div>
          </article>
        </div>
        <article class="panel campaign-jobs-panel">
          <div class="panel-heading"><div><p class="eyebrow">Approval and execution</p><h3>Campaign jobs</h3><p>Inspect every reviewed action, authorize it deliberately, execute through policy, export its secret-free evidence, and record the actual outcome.</p></div></div>
          <div id="campaign-job-list" class="campaign-job-list"><div class="empty-state">No campaign jobs loaded yet.</div></div>
        </article>`;
      main.insertBefore(section, decisionView || null);
    }
  }

  const initializeWorkspace = () => {
    if (document.readyState !== "loading") initializeCampaignWorkspace();
  };

  const module = document.createElement("script");
  module.src = "/assets/campaigns.js";
  module.async = false;
  module.addEventListener("load", () => {
    const evidenceModule = document.createElement("script");
    evidenceModule.src = "/assets/trial-evidence.js";
    evidenceModule.async = false;
    evidenceModule.addEventListener("load", initializeWorkspace, { once: true });
    evidenceModule.addEventListener("error", initializeWorkspace, { once: true });
    document.head.append(evidenceModule);
  });
  document.head.append(module);
})();
