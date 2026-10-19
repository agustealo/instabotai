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
        <article class="panel campaign-jobs-panel">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">Your action inbox</p>
              <h3>Approvals and campaign activity</h3>
              <p>Review what AI proposed, decide what may run, and see which actions still need real-world results.</p>
            </div>
            <button type="button" class="button button-secondary" id="refresh-jobs">Refresh activity</button>
          </div>
          <div id="campaign-job-summary" class="campaign-job-summary" aria-live="polite"></div>
          <div class="campaign-job-toolbar">
            <div class="campaign-job-filters" role="group" aria-label="Show campaign actions by stage">
              <button type="button" class="button button-small button-secondary" data-job-filter="review" aria-pressed="true">Needs approval <span data-job-count="review"></span></button>
              <button type="button" class="button button-small button-ghost" data-job-filter="scheduled" aria-pressed="false">Scheduled <span data-job-count="scheduled"></span></button>
              <button type="button" class="button button-small button-ghost" data-job-filter="history" aria-pressed="false">Results &amp; history <span data-job-count="history"></span></button>
              <button type="button" class="button button-small button-ghost" data-job-filter="all" aria-pressed="false">All <span data-job-count="all"></span></button>
            </div>
            <label class="campaign-job-campaign-filter"><span>Campaign</span>
              <select id="campaign-job-campaign-select" aria-label="Filter campaign activity by campaign">
                <option value="">All campaigns</option>
              </select>
            </label>
          </div>
          <p id="campaign-job-context" class="campaign-job-context" role="status"></p>
          <div id="campaign-job-list" class="campaign-job-list" aria-live="polite">
            <div class="empty-state">Open Campaigns to load your approval queue.</div>
          </div>
        </article>
        <div class="two-column campaign-layout">
          <article class="panel campaign-create-panel">
            <div class="panel-heading"><div><p class="eyebrow">Durable automation</p><h3 id="campaign-form-heading">Create campaign</h3><p>Build recurring work from approved evidence or bounded public-web research.</p></div></div>
            <form id="campaign-form" class="form-stack">
              <label><span>Campaign name</span><input id="campaign-name" type="text" maxlength="160" required placeholder="Fall product launch"></label>
              <label><span>Business objective</span><textarea id="campaign-objective" rows="4" maxlength="2000" required placeholder="Publish evidence-grounded launch content and learn from measured outcomes."></textarea></label>
              <div class="campaign-form-grid">
                <label><span>Authority mode</span><select id="campaign-mode"><option value="supervised" selected>Supervised</option><option value="policy_managed">Policy managed</option></select><small>Global write-approval policy remains authoritative in either mode.</small></label>
                <label><span>Plan new content</span><select id="campaign-cadence-preset"><option value="1440" selected>Once a day</option><option value="720">Twice a day</option><option value="360">Every 6 hours</option><option value="10080">Once a week</option><option value="custom">Custom interval</option></select><small id="campaign-cadence-help">Plans once per day. Approval is still required before any write.</small></label><label id="campaign-cadence-custom-field" class="is-hidden"><span>Custom interval (minutes)</span><input id="campaign-cadence" type="number" min="5" max="43200" value="1440" required><small>Minimum 5 minutes, maximum 30 days.</small></label>
                <label><span>Delay scheduled action (minutes)</span><input id="campaign-delay" type="number" min="0" max="10080" value="0" required><small>Optional wait after the plan is made. Does not bypass approval.</small></label>
                <label class="campaign-check"><input id="campaign-research-enabled" type="checkbox"><span>Research public web before each plan</span></label>
              </div>
              <div id="campaign-research-fields" class="form-stack is-hidden"><label><span>Research seed URLs</span><textarea id="campaign-research-seeds" rows="5" placeholder="https://example.com/approved-market-report&#10;https://example.org/product-news"></textarea><small>One permitted HTTP/HTTPS URL per line.</small></label></div>
              <div class="field-header"><div><strong>Campaign evidence</strong><small>Manual evidence can be combined with research evidence.</small></div><button type="button" class="button button-ghost button-small" id="campaign-add-evidence">Add evidence</button></div>
              <div id="campaign-evidence-list" class="evidence-list"></div>
              <details class="advanced"><summary>Advanced context</summary><label><span>Bounded JSON context</span><textarea id="campaign-context" rows="6" spellcheck="false">{}</textarea></label></details>
              <div class="form-actions"><span class="form-note" id="campaign-form-note">New campaigns start as drafts.</span><button class="button button-ghost is-hidden" type="button" id="campaign-cancel-edit">Cancel editing</button><button class="button button-primary" type="submit" id="campaign-create-submit">Create campaign</button></div>
            </form>
          </article>
          <article class="panel">
            <div class="panel-heading"><div><p class="eyebrow">Campaign lifecycle</p><h3>Planning queue</h3><p>Activate, pause, archive, or request one immediate reviewed planning pass.</p></div><button class="button button-secondary" id="refresh-campaigns">Refresh</button></div>
            <div id="campaign-list" class="campaign-list"><div class="empty-state">Open Campaigns to load durable campaign state.</div></div>
          </article>
        </div>
`;
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
