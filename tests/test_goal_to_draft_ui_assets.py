"""Client-side goal and research handoff regression checks."""

import shutil
import subprocess
from pathlib import Path

import pytest


ASSETS = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"


def test_handoff_never_runs_a_provider_action() -> None:
    core = (ASSETS / "app-core.js").read_text(encoding="utf-8")
    campaign = (ASSETS / "campaigns.js").read_text(encoding="utf-8")
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
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
        [node, "-e", harness, str(ASSETS / "app-core.js"), str(ASSETS / "campaigns.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
