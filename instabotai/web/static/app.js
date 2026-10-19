"use strict";

(function loadConsumerModules() {
  window.__instabotaiDomReady = document.readyState === "complete";
  if (!window.__instabotaiDomReady) {
    document.addEventListener("DOMContentLoaded", () => {
      window.__instabotaiDomReady = true;
    }, { once: true });
  }

  const core = document.createElement("script");
  core.src = "/assets/app-core.js";
  core.async = false;
  core.addEventListener("load", () => {
    if (window.__instabotaiDomReady) initialize();

    const campaigns = document.createElement("script");
    campaigns.src = "/assets/campaigns-shell.js";
    campaigns.async = false;
    document.head.append(campaigns);

    const setup = document.createElement("script");
    setup.src = "/assets/setup.js";
    setup.async = false;
    document.head.append(setup);

    const library = document.createElement("script");
    library.src = "/assets/evidence-library.js";
    library.async = false;
    document.head.append(library);
  });
  document.head.append(core);
})();
