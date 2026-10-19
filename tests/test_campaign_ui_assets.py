"""Consumer campaign workspace asset and shell regressions."""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from instabotai.settings import Settings
from instabotai.web import create_app


async def test_campaign_workspace_is_shipped_as_local_consumer_assets() -> None:
    settings = Settings(state_db_path=":memory:", ui_open_browser=False)
    transport = httpx.ASGITransport(app=create_app(settings=settings))

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        index = await client.get("/")
        loader = await client.get("/assets/app.js")
        core = await client.get("/assets/app-core.js")
        shell = await client.get("/assets/campaigns-shell.js")
        script = await client.get("/assets/campaigns.js")
        evidence = await client.get("/assets/trial-evidence.js")
        stylesheet = await client.get("/assets/campaigns.css")
        setup_script = await client.get("/assets/setup.js")
        setup_stylesheet = await client.get("/assets/setup.css")

    assert index.status_code == 200
    assert "AI Studio" in index.text
    assert loader.status_code == 200
    assert "/assets/app-core.js" in loader.text
    assert "/assets/campaigns-shell.js" in loader.text
    assert "/assets/setup.js" in loader.text
    assert "__instabotaiDomReady" in loader.text
    assert core.status_code == 200
    assert "function initialize()" in core.text
    assert "function confirmConsumerAction(" in core.text
    assert 'state.worker = await api("/api/worker")' in core.text
    assert 'kind !== "error"' in core.text
    assert "Array.isArray(body.detail)" in core.text

    assert shell.status_code == 200
    assert 'button.dataset.view = "campaigns"' in shell.text
    assert 'section.id = "view-campaigns"' in shell.text
    assert "Campaign planning and provider execution are deliberately separate" in shell.text
    assert "/assets/trial-evidence.js" in shell.text
    assert "Review what AI proposed" in shell.text

    assert script.status_code == 200
    assert "function canExecuteJob(job)" in script.text
    assert "function beginCampaignEdit(campaign)" in script.text
    assert "function readableCampaignCadence(minutes)" in script.text
    assert "function syncCampaignCadence()" in script.text
    assert 'id="campaign-cadence-preset"' in shell.text
    assert "expected_updated_at" in script.text
    assert 'method: editingId ? "PATCH" : "POST"' in script.text
    assert 'id="campaign-cancel-edit"' in shell.text
    assert "if (!state.runtime || !state.runtime.policy) return false" in script.text
    assert "confirmJobChange(job, \"Execute\", true)" in script.text
    assert "confirmCampaignChange(campaign, \"Archive\", true)" in script.text
    assert "pending_approval" in script.text
    assert "/api/campaign-jobs/" in script.text
    assert "Business outcome recorded" in script.text

    assert evidence.status_code == 200
    assert "Export evidence" in evidence.text
    assert "/evidence`" in evidence.text
    assert "application/json" in evidence.text
    assert "SHA-256 integrity metadata" in evidence.text

    assert setup_script.status_code == 200
    assert 'api("/api/consumer")' in setup_script.text
    assert 'api("/api/runtime")' in setup_script.text
    assert 'document.querySelector("#view-overview .hero [data-go]")' in setup_script.text
    assert 'api(live ? "/api/readiness/probe" : "/api/readiness"' in setup_script.text
    assert "Credentials are configured on your machine" in setup_script.text
    assert setup_stylesheet.status_code == 200
    assert ".setup-progress" in setup_stylesheet.text

    assert stylesheet.status_code == 200
    assert ".campaign-job-card" in stylesheet.text
    assert ".outcome-form" in stylesheet.text


def test_shipped_consumer_javascript_parses_when_node_is_available() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable in this environment")

    static_dir = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    for asset in (
        "app.js",
        "app-core.js",
        "campaigns-shell.js",
        "campaigns.js",
        "trial-evidence.js",
        "setup.js",
        "evidence-library.js",
    ):
        result = subprocess.run(
            [node, "--check", str(static_dir / asset)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{asset}: {result.stderr}"


def test_campaign_inbox_stage_filtering_without_backend_mock_when_node_available() -> None:
    """The inbox groups actual backend job status values, not invented lifecycle flags."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable in this environment")

    script = (
        Path(__file__).resolve().parents[1]
        / "instabotai"
        / "web"
        / "static"
        / "campaigns.js"
    )
    harness = r"""
const fs = require("node:fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const jobs = [
  ["a", "pending_approval", "campaign-a"],
  ["b", "scheduled", "campaign-a"],
  ["c", "leased", "campaign-a"],
  ["d", "retry_wait", "campaign-a"],
  ["e", "succeeded", "campaign-a"],
  ["f", "failed", "campaign-a"],
  ["g", "rejected", "campaign-b"],
  ["h", "cancelled", "campaign-b"],
].map(([job_id, status, campaign_id], idx) => ({
  job_id, status, campaign_id, outcome_reward: null,
  created_at: "2026-10-19T10:00:00Z",
  updated_at: "2026-10-19T10:" + String(idx).padStart(2, "0") + ":00Z",
}));
const assert = require("node:assert/strict");
const verify = new Function("document", "jobs", "assert", source + `
campaignState.jobs = jobs;
const check = (filter, count) => {
  campaignState.jobFilter = filter;
  assert.equal(visibleCampaignJobs().length, count, filter);
};
check("review", 1);
check("scheduled", 3);
check("history", 4);
check("all", 8);
assert.equal(visibleCampaignJobs()[0].job_id, "h", "newest updates first");
campaignState.jobCampaign = "campaign-a";
check("review", 1);
check("scheduled", 3);
check("history", 2);
check("all", 6);
assert.match(jobStageCopy(jobs[0]), /decision is required/i);
assert.match(jobStageCopy(jobs[4]), /business impact has not been recorded/i);
assert.equal(
  summarizeProposedAction({action_type: "publish_image", payload: {caption: "Launch"}}).message,
  "Launch",
);
assert.equal(
  summarizeProposedAction({
    action_type: "reply_to_comment", target_id: "123", payload: {message: "Thanks!"},
  }).context,
  "Comment: 123",
);
assert.match(
  summarizeProposedAction({action_type: "hide_comment", payload: {hide: false}}).title,
  /Unhide/,
);
`);
verify({addEventListener() {}}, jobs, assert);
"""
    result = subprocess.run(
        [node, "-e", harness, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_campaign_inbox_has_accessible_controls_and_stages() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    shell = (static_dir / "campaigns-shell.js").read_text(encoding="utf-8")
    script = (static_dir / "campaigns.js").read_text(encoding="utf-8")
    styles = (static_dir / "campaigns.css").read_text(encoding="utf-8")
    assert "Approvals and campaign activity" in shell
    assert 'aria-label="Show campaign actions by stage"' in shell
    assert 'aria-pressed="true"' in shell
    assert 'id="campaign-job-campaign-select"' in shell
    assert "function visibleCampaignJobs()" in script
    assert "function renderCampaignControls()" in script
    assert "function jobStageCopy(job)" in script
    assert "function renderActionPreview(action)" in script
    assert "Business result score (0 to 1)" in script
    assert ".campaign-job-summary" in styles


CONSUMER_ASSETS = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"


def test_handoff_never_runs_a_provider_action() -> None:
    core = (CONSUMER_ASSETS / "app-core.js").read_text(encoding="utf-8")
    campaign = (CONSUMER_ASSETS / "campaigns.js").read_text(encoding="utf-8")
    index = (CONSUMER_ASSETS / "index.html").read_text(encoding="utf-8")
    assert 'id="plan-to-campaign"' in index
    assert "function researchPageToDraftEvidence(" in core
    assert "function stageGoalAsCampaignDraft()" in core
    assert 'root.querySelectorAll(".research-pick:checked")' in core
    assert "const objective = report.objective" in core
    assert "function isSafeResearchSourceUrl(" in core
    stage = campaign.split("async function stageCampaignDraft(", 1)[1].split(
        "function beginCampaignEdit(", 1
    )[0]
    assert "api(" not in stage
    assert "confirmConsumerAction(" in stage
    assert 'openView("campaigns")' in stage
    assert '"supervised"' in stage


def test_bounded_source_conversion_and_review_only_transfer() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    harness = r"""
const fs = require("node:fs");
const assert = require("node:assert/strict");
const core = fs.readFileSync(process.argv[1], "utf8");
const campaigns = fs.readFileSync(process.argv[2], "utf8");
const doc = {addEventListener() {}};
const validation = [
  'const p={url:"https://example.org/report",markdown:"Source",relevance:0.9};',
  'const e=researchPageToDraftEvidence(p,3,0.8);',
  'assert.equal(e.evidence_id,"research-page-4");',
  'assert.equal(e.confidence,0.5);',
  'assert.equal(e.source,p.url);',
  'assert.equal(researchPageToDraftEvidence({...p,',
  'markdown:"x".repeat(13000)},0,0.8).content.length,12000);',
  'assert.equal(isSafeResearchSourceUrl("javascript:alert(1)"),false);',
  'assert.throws(()=>researchPageToDraftEvidence({...p,markdown:""},1,0.8));',
].join("\n");
new Function("document", "assert", core + "\n" + validation)(doc, assert);
const nodes = new Map();
function make() {
  return {
    value:"", textContent:"", dataset:{}, checked:false,
    classList:{add(){},remove(){},toggle(){}},
    append(...items){this.children=(this.children||[]).concat(items);},
    replaceChildren(){this.children=[];},
    reset(){},scrollIntoView(){},focus(){},setAttribute(){},addEventListener(){},
  };
}
const get = (id) => {
  if (!nodes.has(id)) nodes.set(id,make());
  return nodes.get(id);
};
const navigation = [];
let approve = true, confirmations = 0;
const stage = new Function(
  "$", "$$", "element", "document", "window", "confirmConsumerAction",
  "openView", "showFlash",
  campaigns + "\ncampaignState.initialized=true;return stageCampaignDraft;",
)(
  get, () => [], make, doc, {matchMedia(){return {matches:true};}},
  async () => {confirmations++;return approve;},
  (name) => navigation.push(name), () => {},
);
(async () => {
  const draft = {objective:"Launch the fall products.",
    evidence:[{evidence_id:"research-page-1",source:"https://example.org",
      content:"One selected source",confidence:0.4}],
    seedUrls:["https://example.org"],sourceLabel:"research"};
  assert.equal(await stage(draft),true);
  assert.equal(get("#campaign-objective").value,draft.objective);
  assert.equal(get("#campaign-mode").value,"supervised");
  assert.equal(get("#campaign-research-seeds").value,draft.seedUrls[0]);
  assert.equal(get("#campaign-evidence-list").children.length,1);
  assert.deepEqual(navigation,["campaigns"]);
  approve=false;
  assert.equal(await stage({...draft,objective:"Different goal."}),false);
  assert.equal(get("#campaign-objective").value,draft.objective);
  assert.equal(confirmations,2);
  assert.equal(await stage({...draft,seedUrls:Array(21).fill("https://example.org")}),false);
  assert.equal(confirmations,2);
})().catch((err)=>{console.error(err);process.exitCode=1;});
"""
    result = subprocess.run(
        [
            node,
            "-e",
            harness,
            str(CONSUMER_ASSETS / "app-core.js"),
            str(CONSUMER_ASSETS / "campaigns.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_evidence_library_ui_is_served_and_uses_existing_review_authority() -> None:
    static = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    loader = (static / "app.js").read_text(encoding="utf-8")
    code = (static / "evidence-library.js").read_text(encoding="utf-8")
    assert "/assets/evidence-library.js" in loader
    assert "function entryAsCampaignEvidence(entry)" in code
    assert 'method:"PATCH"' in code
    assert 'method:"DELETE"' in code
    assert 'api("/api/evidence-library"' in code
    assert '"unverified"' in code
    assert 'openView("campaigns")' in code
    assert "saveSelectedResearchToLibrary" in code
    assert "beginCampaignEdit(campaign)" in code
    assert "stageCampaignDraft({" in code
    assert "No Instagram write occurs here" in code
    assert (static / "evidence-library.css").is_file()


def test_campaign_job_filters_use_collection_selector() -> None:
    static = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    script = (static / "campaigns.js").read_text(encoding="utf-8")
    assert '$$(".campaign-job-filters [data-job-filter]").forEach(' in script
    assert '  $(".campaign-job-filters [data-job-filter]").forEach(' not in script

def test_approval_copy_and_result_classification_are_explicit() -> None:
    path = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    script = (path / "campaigns.js").read_text(encoding="utf-8")
    styles = (path / "campaigns.css").read_text(encoding="utf-8")
    assert "function jobDecisionConsequence(label)" in script
    assert "function jobExecutionFeedback(result)" in script
    assert "Authorization is not publication" not in script
    assert "Approval is not publication" in script
    assert 'reward.placeholder = "Choose a score"' in script
    assert "reward.value = \"0.5\"" not in script
    assert "note.required = true" in script
    assert "const feedback = jobExecutionFeedback(result)" in script
    assert "Provider execution completed through" not in script
    assert "aria-labelledby" in script
    assert ".campaign-approval-consequence" in styles


