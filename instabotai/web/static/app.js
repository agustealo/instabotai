"use strict";

(function loadConsumerModules() {
  const core = document.createElement("script");
  core.src = "/assets/app-core.js";
  core.async = false;
  core.addEventListener("load", () => {
    if (document.readyState !== "loading") initialize();

    const campaigns = document.createElement("script");
    campaigns.src = "/assets/campaigns-shell.js";
    campaigns.async = false;
    document.head.append(campaigns);
  });
  document.head.append(core);
})();
