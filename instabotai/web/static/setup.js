"use strict";

/* Read-only, canonical-readiness-driven consumer setup. No browser credential capture. */
(function mountFirstRunSetup() {
  const setupState = {
    initialized: false,
    firstLoad: true,
    info: null,
    report: null,
    worker: null,
    runtime: null,
    campaignCount: null,
    refreshing: false,
  };

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function makeButton(text, className, callback) {
    const button = make("button", "button " + className, text);
    button.type = "button";
    button.addEventListener("click", callback);
    return button;
  }

  function buildShell() {
    if (!document.querySelector("#view-setup")) {
      const section = make("section", "view setup-view");
      section.id = "view-setup";
      section.dataset.title = "Get started";
      section.innerHTML =
        '<div class="setup-intro"><p class="eyebrow">Guided local setup</p>' +
        '<h2>Get InstabotAI ready to work</h2>' +
        '<p>Connect the pieces, verify them with real checks, then start a supervised campaign. ' +
        'Credentials are configured on your machine, not entered into this browser.</p></div>' +
        '<div class="setup-progress" id="setup-progress" aria-live="polite"></div>' +
        '<div class="two-column setup-columns">' +
        '<article class="panel"><div class="panel-heading"><div>' +
        '<p class="eyebrow">Step 1</p><h3>Configure your providers</h3>' +
        '<p>Save credentials locally, then restart InstabotAI to load your changes.</p>' +
        '</div></div><div id="setup-config"></div></article>' +
        '<article class="panel"><div class="panel-heading"><div>' +
        '<p class="eyebrow">Step 2</p><h3>Check your connections</h3>' +
        '<p>Static checks verify local setup. Live checks actually contact the selected model and Instagram account, read-only.</p>' +
        '</div></div><div class="setup-controls" id="setup-controls"></div>' +
        '<div class="setup-checks" id="setup-checks"></div></article></div>' +
        '<article class="panel setup-start-panel"><div class="panel-heading"><div>' +
        '<p class="eyebrow">Step 3</p><h3>Start a supervised campaign</h3>' +
        '<p>Campaigns begin as drafts. You review actions before a write is permitted.</p>' +
        '</div></div><div id="setup-campaign"></div></article>';
      const overview = document.querySelector("#view-overview");
      if (overview) overview.insertAdjacentElement("afterend", section);
    }

    if (!document.querySelector('.nav-item[data-view="setup"]')) {
      const button = make("button", "nav-item");
      button.dataset.view = "setup";
      button.type = "button";
      button.append(make("span", "nav-icon", "✓"), make("span", null, "Get started"));
      button.addEventListener("click", () => {
        openView("setup");
        refreshSetup(false);
      });
      const first = document.querySelector('.nav-item[data-view="overview"]');
      if (first) first.insertAdjacentElement("afterend", button);
    }

    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "/assets/setup.css";
    document.head.append(style);

    const refresh = document.querySelector("#setup-controls");
    refresh.append(
      makeButton("Recheck local setup", "button-secondary", () => refreshSetup(false)),
      makeButton("Run live connections", "button-primary", () => refreshSetup(true)),
    );
  }

  function renderConfig() {
    const target = document.querySelector("#setup-config");
    target.replaceChildren();
    const path = setupState.info && setupState.info.config_file;
    const pathTitle = make("p", "setup-field-label", "Local configuration file");
    const pathValue = make("code", "setup-path", path || "Configuration path unavailable");
    const pathRow = make("div", "setup-path-row");
    pathRow.append(pathValue);
    if (path) {
      pathRow.append(makeButton("Copy path", "button-ghost button-small", () => copyText(path, "Path")));
    }

    const modelLabel = make("label", "setup-selector");
    modelLabel.append(make("span", null, "AI provider"));
    const model = make("select");
    model.id = "setup-model-provider";
    for (const [value, label] of [
      ["ollama", "Ollama (local)"],
      ["openai_compatible", "OpenAI-compatible server"],
    ]) {
      const option = make("option", null, label);
      option.value = value;
      model.append(option);
    }
    model.value = setupState.runtime && setupState.runtime.ai.provider === "openai_compatible" ?
      "openai_compatible" : "ollama";
    modelLabel.append(model);

    const instagramLabel = make("label", "setup-selector");
    instagramLabel.append(make("span", null, "Instagram provider"));
    const instagram = make("select");
    instagram.id = "setup-instagram-provider";
    for (const [value, label] of [
      ["official", "Official Instagram API"],
      ["private", "Authorized private integration"],
    ]) {
      const option = make("option", null, label);
      option.value = value;
      instagram.append(option);
    }
    instagram.value = setupState.runtime && setupState.runtime.instagram.provider === "private" ?
      "private" : "official";
    instagramLabel.append(instagram);

    const preview = make("pre", "code-block setup-template");
    preview.id = "setup-template";
    preview.setAttribute("aria-label", "Example local environment configuration");
    const update = () => {
      const lines = model.value === "ollama" ?
        ["INSTABOTAI_AI_PROVIDER=ollama", "INSTABOTAI_AI_MODEL=llama3.2:3b",
          "INSTABOTAI_AI_BASE_URL=http://127.0.0.1:11434"] :
        ["INSTABOTAI_AI_PROVIDER=openai_compatible", "INSTABOTAI_AI_MODEL=",
          "INSTABOTAI_AI_BASE_URL=", "INSTABOTAI_AI_API_KEY="];
      if (instagram.value === "official") {
        lines.push("INSTABOTAI_INSTAGRAM_PROVIDER=official",
          "INSTABOTAI_INSTAGRAM_ACCOUNT_ID=", "INSTABOTAI_INSTAGRAM_ACCESS_TOKEN=");
      } else {
        lines.push("INSTABOTAI_INSTAGRAM_PROVIDER=private",
          "INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME=", "INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD=");
      }
      lines.push("INSTABOTAI_REQUIRE_WRITE_APPROVAL=true");
      preview.textContent = lines.join("\n");
    };
    model.addEventListener("change", update);
    instagram.addEventListener("change", update);
    update();

    const instructions = make("p", "setup-help",
      "The examples contain blank credential fields, never real secrets. Select the provider " +
      "you are authorized to use, complete the values in your local configuration file, " +
      "and restart the app before checking again. Changing the selectors here does not alter your running configuration.");
    const actions = make("div", "setup-config-actions");
    actions.append(makeButton("Copy configuration example", "button-secondary",
      () => copyText(preview.textContent, "Configuration example")));
    target.append(pathTitle, pathRow, modelLabel, instagramLabel, preview, instructions, actions);
  }

  async function copyText(value, label) {
    try {
      await navigator.clipboard.writeText(value);
      showFlash(label + " copied. Complete any blank values locally.", "good");
    } catch {
      showFlash("Clipboard unavailable. Select and copy the visible text manually.", "error");
    }
  }

  function step(title, keys) {
    const report = setupState.report;
    const matching = report ? report.checks.filter((check) => keys.includes(check.key)) : [];
    const failed = matching.some((check) => check.status === "fail");
    const skipped = matching.some((check) => check.status === "skip");
    const warnings = matching.some((check) => check.status === "warn");
    const passed = matching.length === keys.length &&
      matching.every((check) => check.status === "pass");
    const label = failed ? "Needs attention" : passed ? "Verified" :
      skipped ? "Not yet checked" : warnings ? "Optional" : "Unknown";
    const kind = failed ? "bad" : passed ? "good" : "warn";
    const card = make("div", "setup-check");
    const header = make("div", "setup-check-heading");
    header.append(make("strong", null, title), pill(label, kind));
    card.append(header);
    for (const check of matching) {
      const detail = check.detail + (check.remediation ? " " + check.remediation : "");
      card.append(make("p", "setup-check-detail", detail));
    }
    return card;
  }

  function renderChecks() {
    const target = document.querySelector("#setup-checks");
    target.replaceChildren();
    const worker = setupState.worker;
    const status = make("div", "setup-check");
    const header = make("div", "setup-check-heading");
    header.append(make("strong", null, "Campaign scheduler"),
      pill(worker && worker.running ? "Running" : "Not verified",
        worker && worker.running ? "good" : "warn"));
    status.append(header, make("p", "setup-check-detail",
      !worker ? "Scheduler health could not be loaded. Do not assume campaigns will run." :
        worker.running ? "The embedded scheduler reports running. Last tick: " +
          (worker.last_tick_at ? formatDate(worker.last_tick_at) : "not completed yet") :
          "The scheduler is not running. Active campaigns will not progress automatically."));
    if (worker && worker.last_error) {
      status.append(make("p", "setup-check-error", worker.last_error));
    }
    target.append(
      step("Local runtime and durable state", ["runtime", "state"]),
      step("AI provider configuration", ["ai_configuration"]),
      step("Instagram account configuration", ["instagram_configuration"]),
      step("Human approval and write limits", ["write_approval", "write_capacity"]),
      step("Real model and Instagram connectivity", ["ai_live", "instagram_live"]),
      status,
    );
  }

  function renderProgress() {
    const target = document.querySelector("#setup-progress");
    target.replaceChildren();
    const r = setupState.report;
    const blocked = r && !r.ready;
    const workerReady = setupState.worker && setupState.worker.running;
    const verifiedLive = r && r.live_probes &&
      ["ai_live", "instagram_live"].every((key) =>
        r.checks.some((check) => check.key === key && check.status === "pass"));
    const title = !r ? "Setup has not been verified" :
      blocked ? "Finish required setup" :
      !verifiedLive ? "Configuration ready. Verify live connections." :
      !workerReady ? "Connections verified. Scheduler needs attention." :
      "Ready for a supervised campaign";
    target.append(make("strong", null, title),
      make("span", null, r && r.blockers.length ?
        r.blockers.length + " required check(s) need attention." :
        "Live verification is read-only and never authorizes Instagram writes."));
  }

  function routeToWorkspace(view) {
    return () => {
      const destination = document.querySelector("#view-" + view);
      if (!destination) {
        showFlash("That workspace has not loaded. Refresh the console and try again.", "error");
        return;
      }
      openView(view);
      if (view === "library" && typeof refreshEvidenceLibrary === "function") {
        refreshEvidenceLibrary();
      }
    };
  }

  function guidedRoute(title, description, actionLabel, view) {
    const card = make("div", "setup-route");
    const heading = make("strong", null, title);
    const explanation = make("p", null, description);
    const action = makeButton(actionLabel, "button-secondary", routeToWorkspace(view));
    action.dataset.go = view;
    card.append(heading, explanation, action);
    return card;
  }

  function renderCampaign() {
    const target = document.querySelector("#setup-campaign");
    target.replaceChildren();
    if (setupState.campaignCount > 0) {
      const existing = makeButton("Open existing campaigns", "button-primary",
        routeToWorkspace("campaigns"));
      existing.dataset.go = "campaigns";
      target.append(
        make("p", "setup-help", "You already have a campaign. Review its status, " +
          "proposed actions and results in your Campaigns workspace."),
        existing,
      );
      return;
    }
    const intro = make("p", "setup-help", setupState.campaignCount === null ?
      "Campaign history could not be loaded. You can prepare material without activating " +
        "or publishing anything." :
      "A campaign needs an objective and evidence or permitted research. Choose how " +
        "you want to begin; none of these paths publishes to Instagram.");
    const routes = make("div", "setup-routes");
    routes.append(
      guidedRoute("I have source material",
        "Save your product details or approved brief in Evidence Library, " +
        "review the source, then select it to prepare a supervised draft.",
        "Save source material", "library"),
      guidedRoute("I want to research first",
        "Investigate permitted public URLs, review the extracts, and save useful " +
        "sources before creating a campaign.",
        "Research my topic", "research"),
      guidedRoute("I have a business goal",
        "Start in AI Studio with your objective and evidence. Review the proposed " +
        "plan, then continue into the supervised campaign editor.",
        "Open AI Studio", "ai"),
    );
    const manual = make("div", "setup-manual");
    manual.append(make("span", null, "Already have your evidence prepared?"),
      makeButton("Open campaign editor", "button-ghost",
        routeToWorkspace("campaigns")));
    target.append(intro, routes, manual);
  }

  async function refreshSetup(live) {
    if (setupState.refreshing) return;
    setupState.refreshing = true;
    const buttons = document.querySelectorAll("#setup-controls button");
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const readiness = await api(live ? "/api/readiness/probe" : "/api/readiness",
        live ? { method: "POST", body: "{}" } : {});
      setupState.report = readiness;
      renderReadiness(readiness);
      const extras = await Promise.allSettled([
        api("/api/consumer"), api("/api/worker"), api("/api/campaigns?limit=1"),
        api("/api/runtime"),
      ]);
      setupState.info = extras[0].status === "fulfilled" ? extras[0].value : null;
      setupState.runtime = extras[3].status === "fulfilled" ? extras[3].value : null;
      setupState.worker = extras[1].status === "fulfilled" ? extras[1].value : null;
      setupState.campaignCount = extras[2].status === "fulfilled" ?
        extras[2].value.length : null;
      renderConfig();
      renderChecks();
      renderProgress();
      renderCampaign();

      const heroLink = document.querySelector("#view-overview .hero [data-go]");
      if (heroLink && !readiness.ready) {
        heroLink.dataset.go = "setup";
        heroLink.textContent = "Finish setup";
      } else if (heroLink) {
        heroLink.dataset.go = "campaigns";
        heroLink.textContent = "Open Campaigns";
      }

      if (setupState.firstLoad && !readiness.ready && setupState.campaignCount === 0 &&
          document.querySelector("#view-overview.is-active")) {
        openView("setup");
      }
      setupState.firstLoad = false;
      if (live) {
        showFlash(readiness.ready ?
          "Live checks completed. Review individual connection results before activating work." :
          "Live checks found setup blockers. Review the checks below.",
          readiness.ready ? "good" : "error");
      }
    } catch (error) {
      showFlash("Could not check setup: " + error.message, "error");
      const target = document.querySelector("#setup-progress");
      target.replaceChildren(make("strong", null,
        "Readiness information unavailable. No connection has been verified."));
    } finally {
      setupState.refreshing = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function initialize() {
    if (setupState.initialized) return;
    setupState.initialized = true;
    buildShell();
    refreshSetup(false);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
