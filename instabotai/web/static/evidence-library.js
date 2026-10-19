"use strict";

/* A consumer-facing view over the canonical evidence library API. */
const libraryState = {
  entries: [], selected: new Set(), editing: null,
  offset: 0, limit: 50, query: "", loaded: false, busy: false,
};

function libNode(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = String(content);
  return node;
}

function libButton(label, className, action) {
  const button = libNode("button", "button " + className, label);
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

function libraryShell() {
  if (document.querySelector("#view-library")) return;
  const section = libNode("section", "view");
  section.id = "view-library";
  section.dataset.title = "Evidence Library";
  section.innerHTML = [
    '<div class="library-intro">',
    '<p class="eyebrow">Reusable knowledge</p><h2>Evidence Library</h2>',
    '<p>Save sources, organize what you know, and attach reviewed copies to campaign drafts.',
    ' A review label means you examined the entry, not that an independent authority verified it.</p>',
    '</div>',
    '<div class="two-column library-columns">',
    '<article class="panel"><div class="panel-heading"><div><p class="eyebrow">Save or revise</p>',
    '<h3 id="library-form-title">Save evidence</h3>',
    '<p>Entries are unverified until you deliberately mark them reviewed.</p>',
    '</div></div>',
    '<form id="library-form" class="form-stack">',
    '<label><span>Short label</span><input id="library-title" type="text" maxlength="160" required',
    ' placeholder="Autumn product specifications"></label>',
    '<label><span>Source or reference</span><input id="library-source" type="text" maxlength="500"',
    ' required placeholder="https://example.com/report or approved brief"></label>',
    '<label><span>Evidence text</span><textarea id="library-content" rows="7"',
    ' maxlength="12000" required placeholder="Paste the specific claim or verified facts."></textarea></label>',
    '<label><span>Confidence (0 to 1)</span><input id="library-confidence" type="number"',
    ' step="0.05" min="0" max="1" value="0.5" required></label>',
    '<label><span>Tags (comma-separated)</span><input id="library-tags" type="text"',
    ' placeholder="launch, products, seasonal"></label>',
    '<label><span>Review note</span><textarea id="library-note" rows="2" maxlength="2000"',
    ' placeholder="What did you check?"></textarea></label>',
    '<div class="form-actions"><button type="button" class="button button-ghost is-hidden"',
    ' id="library-cancel-edit">Cancel editing</button>',
    '<button type="submit" class="button button-primary" id="library-save">Save unverified evidence</button>',
    '</div></form></article>',
    '<article class="panel library-attach-panel">',
    '<div class="panel-heading"><div><p class="eyebrow">Attach to a campaign</p>',
    '<h3>Use selected evidence</h3>',
    '<p>Drafts receive copies. Later library changes never rewrite existing campaigns.</p>',
    '</div></div>',
    '<p id="library-selected-count" aria-live="polite">0 entries selected</p>',
    '<label><span>Destination</span><select id="library-target">',
    '<option value="">New supervised campaign draft</option></select></label>',
    '<label id="library-objective-wrap"><span>Campaign goal</span>',
    '<textarea id="library-objective" rows="4"',
    ' placeholder="What should the campaign achieve?"></textarea></label>',
    '<button type="button" class="button button-secondary" id="library-attach">',
    'Prepare with selected evidence</button>',
    '<p class="setup-help">Unverified items remain flagged for review.',
    ' Rejected items cannot be attached. No Instagram write occurs here.</p>',
    '</article></div>',
    '<article class="panel library-entries-panel">',
    '<div class="panel-heading"><div><p class="eyebrow">Saved entries</p><h3>Browse evidence</h3>',
    '<p>Search labels or sources. Entries are sorted by most recently updated.</p></div></div>',
    '<form id="library-search-form" class="library-search">',
    '<input id="library-search" type="search" maxlength="160" aria-label="Find saved evidence"',
    ' placeholder="Search labels or sources">',
    '<button type="submit" class="button button-secondary">Search</button>',
    '<button type="button" class="button button-ghost" id="library-refresh">Refresh</button>',
    '</form>',
    '<p id="library-status" role="status" aria-live="polite"></p>',
    '<div id="library-list" class="library-list"></div>',
    '<div class="library-pager">',
    '<button type="button" class="button button-ghost" id="library-prev">Previous</button>',
    '<span id="library-page-label"></span>',
    '<button type="button" class="button button-ghost" id="library-next">Next</button>',
    '</div></article>',
  ].join("");
  const researchView = document.querySelector("#view-research");
  if (researchView) researchView.insertAdjacentElement("afterend", section);

  const nav = libNode("button", "nav-item");
  nav.type = "button";
  nav.dataset.view = "library";
  nav.append(libNode("span", "nav-icon", "▤"), libNode("span", null, "Evidence Library"));
  nav.addEventListener("click", () => {
    openView("library");
    refreshEvidenceLibrary();
  });
  const researchNav = document.querySelector('.nav-item[data-view="research"]');
  if (researchNav) researchNav.insertAdjacentElement("afterend", nav);

  const style = document.createElement("link");
  style.rel = "stylesheet";
  style.href = "/assets/evidence-library.css";
  document.head.append(style);
}

function entryAsCampaignEvidence(entry) {
  return {
    evidence_id: "library-" + entry.library_id,
    source: entry.source,
    content: entry.content,
    confidence: entry.confidence,
  };
}

function libraryTags() {
  const values = document.querySelector("#library-tags").value.split(",")
    .map((tag) => tag.trim().toLowerCase()).filter(Boolean);
  const unique = Array.from(new Set(values));
  if (unique.length > 12 || unique.some((tag) => tag.length > 40)) {
    throw new Error("Use up to 12 tags, each at most 40 characters.");
  }
  return unique;
}

function resetEvidenceEditor() {
  libraryState.editing = null;
  document.querySelector("#library-form").reset();
  document.querySelector("#library-form-title").textContent = "Save evidence";
  document.querySelector("#library-save").textContent = "Save unverified evidence";
  document.querySelector("#library-cancel-edit").classList.add("is-hidden");
}

function editLibraryEntry(entry) {
  libraryState.editing = entry;
  document.querySelector("#library-title").value = entry.title;
  document.querySelector("#library-source").value = entry.source;
  document.querySelector("#library-content").value = entry.content;
  document.querySelector("#library-confidence").value = String(entry.confidence);
  document.querySelector("#library-tags").value = entry.tags.join(", ");
  document.querySelector("#library-note").value = entry.note;
  document.querySelector("#library-form-title").textContent = "Edit saved evidence";
  document.querySelector("#library-save").textContent = "Save changes";
  document.querySelector("#library-cancel-edit").classList.remove("is-hidden");
  document.querySelector("#library-form").scrollIntoView({block:"start", behavior:"auto"});
  document.querySelector("#library-title").focus({preventScroll:true});
}

async function saveLibraryForm(event) {
  event.preventDefault();
  if (libraryState.busy) return;
  const edit = libraryState.editing;
  let payload;
  try {
    payload = {
      title: document.querySelector("#library-title").value.trim(),
      source: document.querySelector("#library-source").value.trim(),
      content: document.querySelector("#library-content").value.trim(),
      confidence: Number(document.querySelector("#library-confidence").value),
      tags: libraryTags(),
      note: document.querySelector("#library-note").value.trim(),
    };
  } catch (error) {
    showFlash(error.message, "error");
    return;
  }
  if (edit) {
    const accepted = await confirmConsumerAction({
      title:"Save evidence changes?",
      description:"Changing source, text or confidence resets the review state to Unverified.",
      details:"Entry: " + edit.title + "\nCurrent state: " + edit.review_status,
      confirmLabel:"Save changes",
    });
    if (!accepted) return;
    payload.expected_updated_at = edit.updated_at;
  } else {
    payload.origin = "manual";
  }
  libraryState.busy = true;
  try {
    await api(edit ? "/api/evidence-library/" + edit.library_id : "/api/evidence-library", {
      method:edit ? "PATCH" : "POST", body:JSON.stringify(payload),
    });
    resetEvidenceEditor();
    await refreshEvidenceLibrary();
    showFlash(edit ? "Saved evidence updated." : "Evidence saved as Unverified.", "good");
  } catch (error) {
    showFlash("Could not save evidence: " + error.message, "error");
  } finally {
    libraryState.busy = false;
  }
}

async function reviewLibraryEntry(entry, review_status) {
  const accepted = await confirmConsumerAction({
    title:review_status === "reviewed" ? "Mark this evidence reviewed?" :
      review_status === "rejected" ? "Reject this evidence?" : "Reset evidence to unverified?",
    description:"This label is your review decision, not independent factual certification.",
    details:"Entry: " + entry.title + "\nSource: " + entry.source,
    confirmLabel:review_status === "reviewed" ? "Mark reviewed" : "Update review",
    destructive:review_status === "rejected",
  });
  if (!accepted) return;
  try {
    await api("/api/evidence-library/" + entry.library_id, {
      method:"PATCH",
      body:JSON.stringify({expected_updated_at:entry.updated_at, review_status}),
    });
    await refreshEvidenceLibrary();
    showFlash("Review status updated.", "good");
  } catch (error) {
    showFlash("Review failed: " + error.message, "error");
  }
}

async function deleteLibraryEntry(entry) {
  const accepted = await confirmConsumerAction({
    title:"Delete saved evidence?",
    description:"This deletes only the library entry. Existing campaign evidence snapshots remain.",
    details:"Entry: " + entry.title,
    confirmLabel:"Delete entry", destructive:true,
  });
  if (!accepted) return;
  try {
    await api("/api/evidence-library/" + entry.library_id, {
      method:"DELETE", body:JSON.stringify({expected_updated_at:entry.updated_at}),
    });
    libraryState.selected.delete(entry.library_id);
    await refreshEvidenceLibrary();
    showFlash("Saved evidence deleted. Existing campaigns were not rewritten.", "good");
  } catch (error) {
    showFlash("Delete failed: " + error.message, "error");
  }
}

function renderLibraryEntries() {
  const target = document.querySelector("#library-list");
  target.replaceChildren();
  if (!libraryState.entries.length) {
    target.append(libNode("p", "empty-state", "No matching evidence. Save a source to start."));
  }
  for (const entry of libraryState.entries) {
    const card = libNode("article", "library-entry");
    const top = libNode("div", "library-entry-heading");
    const label = libNode("label", "library-entry-selection");
    const check = libNode("input");
    check.type = "checkbox";
    check.checked = libraryState.selected.has(entry.library_id);
    check.disabled = entry.review_status === "rejected";
    check.addEventListener("change", () => {
      if (check.checked && libraryState.selected.size >= 20) {
        check.checked = false;
        showFlash("Select at most 20 saved entries at once.", "error");
        return;
      }
      if (check.checked) libraryState.selected.add(entry.library_id);
      else libraryState.selected.delete(entry.library_id);
      updateLibrarySelection();
    });
    label.append(check, libNode("strong", null, entry.title));
    top.append(label, pill(humanize(entry.review_status),
      entry.review_status === "reviewed" ? "good" :
      entry.review_status === "rejected" ? "bad" : "warn"));
    card.append(top, libNode("p", "library-source", entry.source));
    card.append(libNode("p", "library-caption",
      entry.origin === "research" ? "Research extract • not independently verified" :
        "Manually saved reference"));
    const details = libNode("details");
    details.append(libNode("summary", null, "Read saved source text"),
      libNode("pre", "code-block library-content", entry.content));
    card.append(details);
    if (entry.tags.length) {
      card.append(libNode("p", "library-tags", "Tags: " + entry.tags.join(", ")));
    }
    if (entry.note) card.append(libNode("p", "library-note", entry.note));
    const actions = libNode("div", "library-entry-actions");
    actions.append(libButton("Edit", "button-ghost button-small", () => editLibraryEntry(entry)));
    if (entry.review_status !== "reviewed") {
      actions.append(libButton("Mark reviewed", "button-secondary button-small",
        () => reviewLibraryEntry(entry, "reviewed")));
    }
    if (entry.review_status !== "unverified") {
      actions.append(libButton("Reset review", "button-ghost button-small",
        () => reviewLibraryEntry(entry, "unverified")));
    }
    if (entry.review_status !== "rejected") {
      actions.append(libButton("Reject", "button-ghost button-small",
        () => reviewLibraryEntry(entry, "rejected")));
    }
    actions.append(libButton("Delete", "button-ghost button-small",
      () => deleteLibraryEntry(entry)));
    card.append(actions);
    target.append(card);
  }
  const more = libraryState.entries.length === libraryState.limit;
  document.querySelector("#library-prev").disabled = libraryState.offset === 0;
  document.querySelector("#library-next").disabled = !more;
  const begin = libraryState.entries.length ? libraryState.offset + 1 : 0;
  document.querySelector("#library-page-label").textContent =
    String(begin) + "–" + String(libraryState.offset + libraryState.entries.length) +
    " (searchable library)";
  document.querySelector("#library-status").textContent =
    "Showing the current page. Review labels are self-reported and editable.";
  updateLibrarySelection();
}

function updateLibrarySelection() {
  const count = libraryState.selected.size;
  document.querySelector("#library-selected-count").textContent =
    count + " entries selected (up to 20)";
  document.querySelector("#library-attach").disabled = count === 0;
}

async function loadLibraryTargets() {
  try {
    const campaigns = await api("/api/campaigns?limit=500");
    const select = document.querySelector("#library-target");
    const previous = select.value;
    const first = libNode("option", null, "New supervised campaign draft");
    first.value = "";
    const options = campaigns.filter((c) => ["draft", "paused"].includes(c.status))
      .map((campaign) => {
        const option = libNode("option", null, campaign.name + " (" + campaign.status + ")");
        option.value = campaign.campaign_id;
        return option;
      });
    select.replaceChildren(first, ...options);
    select.value = campaigns.some((c) => c.campaign_id === previous) ? previous : "";
    libraryState.campaigns = campaigns;
    document.querySelector("#library-objective-wrap").classList.toggle(
      "is-hidden", Boolean(select.value),
    );
  } catch {
    // Canonical campaign state is required for attachment, but not for browsing evidence.
    libraryState.campaigns = null;
    showFlash("Campaign destinations could not be loaded. Refresh before attaching.", "error");
  }
}

async function attachLibraryEvidence() {
  if (!libraryState.selected.size) return;
  const chosen = Array.from(libraryState.selected);
  const all = libraryState.entries;
  // Fetch each entry from the backend to avoid using a stale filtered page.
  let entries;
  try {
    entries = await Promise.all(chosen.map(
      (id) => api("/api/evidence-library/" + id),
    ));
  } catch (error) {
    showFlash("Saved evidence changed or is unavailable: " + error.message, "error");
    return;
  }
  if (entries.some((entry) => entry.review_status === "rejected")) {
    showFlash("Remove rejected evidence before attaching.", "error");
    return;
  }
  const evidence = entries.map(entryAsCampaignEvidence);
  const unverified = entries.filter((entry) => entry.review_status !== "reviewed").length;
  const target = document.querySelector("#library-target").value;
  if (!target) {
    const objective = document.querySelector("#library-objective").value.trim();
    if (objective.length < 3 || objective.length > 2000) {
      showFlash("Enter a clear campaign goal before preparing a new draft.", "error");
      return;
    }
    if (typeof stageCampaignDraft !== "function") {
      showFlash("Campaign editor is unavailable. Open Campaigns and try again.", "error");
      return;
    }
    const success = await stageCampaignDraft({
      objective, evidence, sourceLabel:"selected saved evidence (" + unverified +
        " entries not reviewed)",
    });
    if (success) showFlash("Review the imported evidence and save your draft explicitly.", "good");
    return;
  }
  const campaign = (libraryState.campaigns || []).find((item) => item.campaign_id === target);
  if (!campaign || !["draft", "paused"].includes(campaign.status)) {
    showFlash("Selected campaign is not editable. Refresh campaign destinations.", "error");
    return;
  }
  const yes = await confirmConsumerAction({
    title:"Attach selected evidence to this campaign?",
    description:"Open its existing editor and add these evidence snapshots. Changes are not saved yet.",
    details:"Campaign: " + campaign.name + "\nEntries: " + evidence.length +
      "\nUnverified: " + unverified,
    confirmLabel:"Prepare attachment",
  });
  if (!yes) return;
  if (typeof beginCampaignEdit !== "function") {
    showFlash("Campaign editor is unavailable. Reload and try again.", "error");
    return;
  }
  // Reject duplicated snapshots before adding; canonical save remains version checked.
  beginCampaignEdit(campaign);
  const existing = new Set(campaign.evidence.map((item) => item.evidence_id));
  for (const item of evidence) {
    if (!existing.has(item.evidence_id)) addCampaignEvidence(item);
  }
  openView("campaigns");
  showFlash("Evidence appended to the edit form. Save changes explicitly.", "good");
}

async function refreshEvidenceLibrary() {
  if (libraryState.busy) return;
  libraryState.busy = true;
  try {
    const params = new URLSearchParams({
      limit:String(libraryState.limit),
      offset:String(libraryState.offset),
      query:libraryState.query,
    });
    libraryState.entries = await api("/api/evidence-library?" + params.toString());
    renderLibraryEntries();
    await loadLibraryTargets();
    libraryState.loaded = true;
  } catch (error) {
    document.querySelector("#library-status").textContent =
      "Could not load saved evidence: " + error.message;
    showFlash("Evidence Library unavailable: " + error.message, "error");
  } finally {
    libraryState.busy = false;
  }
}

async function saveSelectedResearchToLibrary(report, picked) {
  if (!Array.isArray(picked) || picked.length < 1 || picked.length > 20) {
    showFlash("Select between 1 and 20 research sources.", "error");
    return;
  }
  const yes = await confirmConsumerAction({
    title:"Save selected research in your library?",
    description:"Research extracts will be saved as Unverified until you review them. " +
      "This action does not create or activate a campaign.",
    details:"Sources: " + picked.length + "\nObjective: " + report.objective,
    confirmLabel:"Save to library",
  });
  if (!yes) return;
  let stored = 0;
  for (const index of picked) {
    try {
      const page = report.pages[index];
      const evidence = researchPageToDraftEvidence(page, index, report.confidence);
      await api("/api/evidence-library", {
        method:"POST",
        body:JSON.stringify({
          title:(page.title || "Research source " + (index + 1)).slice(0, 160),
          source:evidence.source,
          content:evidence.content,
          confidence:evidence.confidence,
          origin:"research",
          tags:["research"],
        }),
      });
      stored += 1;
    } catch (error) {
      showFlash("A source could not be saved: " + error.message, "error");
    }
  }
  if (stored) {
    openView("library");
    await refreshEvidenceLibrary();
    showFlash(stored + " research source(s) saved as Unverified.", "good");
  }
}

function initializeEvidenceLibrary() {
  libraryShell();
  document.querySelector("#library-form").addEventListener("submit", saveLibraryForm);
  document.querySelector("#library-cancel-edit").addEventListener("click", resetEvidenceEditor);
  document.querySelector("#library-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    libraryState.query = document.querySelector("#library-search").value.trim();
    libraryState.offset = 0;
    refreshEvidenceLibrary();
  });
  document.querySelector("#library-refresh").addEventListener("click", refreshEvidenceLibrary);
  document.querySelector("#library-prev").addEventListener("click", () => {
    libraryState.offset = Math.max(0, libraryState.offset - libraryState.limit);
    refreshEvidenceLibrary();
  });
  document.querySelector("#library-next").addEventListener("click", () => {
    libraryState.offset += libraryState.limit;
    refreshEvidenceLibrary();
  });
  document.querySelector("#library-target").addEventListener("change", (event) => {
    document.querySelector("#library-objective-wrap").classList.toggle(
      "is-hidden", Boolean(event.target.value),
    );
  });
  document.querySelector("#library-attach").addEventListener("click", attachLibraryEvidence);
  updateLibrarySelection();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeEvidenceLibrary, {once:true});
} else {
  initializeEvidenceLibrary();
}
