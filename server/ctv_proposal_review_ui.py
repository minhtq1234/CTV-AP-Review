"""Deterministic static assets for the ephemeral local CTV review screen."""


UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CTV proposal review</title>
  <link rel="stylesheet" href="/review.css">
  <script src="/review.js" defer></script>
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">Local review</p>
      <h1>Prepare the CTV proposal</h1>
    </div>
    <div class="status-pair" aria-live="polite">
      <span id="progress-status">0 reviewed</span>
      <span id="unresolved-status">Loading</span>
    </div>
  </header>
  <main class="review-grid">
    <aside id="participant-source-nav" aria-label="Participants and sources">
      <section>
        <h2>Roster</h2>
        <div id="roster-options"></div>
      </section>
      <section>
        <h2>Participants</h2>
        <div id="participant-list"></div>
      </section>
      <section>
        <h2>Evidence</h2>
        <div id="unit-list"></div>
        <div id="source-list"></div>
      </section>
    </aside>

    <section id="document-preview" aria-label="Document evidence preview">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Evidence</p>
          <h2 id="preview-title">Select an evidence unit</h2>
        </div>
      </div>
      <div id="preview-content" class="preview-surface"></div>
    </section>

    <aside id="assignment-controls" aria-label="Assignment controls">
      <p class="eyebrow">Decision</p>
      <h2 id="active-unit-title">No unit selected</h2>
      <label for="decision-control">Decision</label>
      <select id="decision-control" disabled></select>
      <label for="role-control">Role</label>
      <select id="role-control" disabled></select>
      <label for="scope-control">Assignment scope</label>
      <select id="scope-control">
        <option value="individual">Individual</option>
        <option value="shared">Shared</option>
        <option value="case">Whole case</option>
      </select>
      <fieldset>
        <legend>Participants</legend>
        <div id="participant-options"></div>
      </fieldset>
      <label for="reason-control">Exclusion reason</label>
      <select id="reason-control">
        <option value="duplicate">Duplicate</option>
        <option value="irrelevant">Irrelevant</option>
        <option value="unreadable-replacement-available">Unreadable, replacement available</option>
        <option value="intentionally-omitted">Intentionally omitted</option>
        <option value="other">Other</option>
      </select>
      <button id="apply-button" type="button">Apply decision</button>

      <section class="summary-panel" aria-live="polite">
        <div class="summary-heading">
          <h2>Approval summary</h2>
          <button id="summary-button" type="button" class="quiet">Refresh</button>
        </div>
        <dl id="summary-counts"></dl>
        <h3>Current decisions</h3>
        <ul id="decision-records"></ul>
        <h3>Issue codes</h3>
        <ul id="issue-list"></ul>
        <p class="digest-label">Proposal digest</p>
        <code id="proposal-digest">Not ready</code>
      </section>
      <div id="message" role="status" aria-live="polite"></div>
      <div class="terminal-actions">
        <button id="draft-button" type="button" class="quiet">Return draft</button>
        <button id="cancel-button" type="button" class="quiet">Cancel</button>
        <button id="approve-button" type="button" disabled>Approve locally</button>
      </div>
    </aside>
  </main>
</body>
</html>
"""


UI_CSS = """:root {
  color-scheme: light;
  --ink: #151515;
  --muted: #68645e;
  --line: #d8d3ca;
  --paper: #f5f1e8;
  --surface: #fffdf8;
  --accent: #1457d9;
  --warn: #9a5b00;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); }
button, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .45; }
.topbar {
  min-height: 78px; padding: 14px 22px; border-bottom: 1px solid var(--line);
  background: var(--surface); display: flex; align-items: center; justify-content: space-between;
}
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: 22px; }
h2 { margin-bottom: 10px; font-size: 16px; }
.eyebrow { margin-bottom: 4px; color: var(--accent); font-size: 11px; font-weight: 750; letter-spacing: .11em; text-transform: uppercase; }
.status-pair { display: flex; gap: 8px; }
.status-pair span { border: 1px solid var(--line); border-radius: 999px; padding: 7px 10px; background: white; font-size: 12px; }
.review-grid { display: grid; grid-template-columns: minmax(220px, 18vw) minmax(420px, 1fr) minmax(290px, 24vw); min-height: calc(100vh - 78px); }
#participant-source-nav, #assignment-controls { padding: 18px; overflow: auto; background: var(--surface); }
#participant-source-nav { border-right: 1px solid var(--line); }
#assignment-controls { border-left: 1px solid var(--line); }
#participant-source-nav section + section { margin-top: 22px; }
#document-preview { min-width: 0; padding: 22px; }
.panel-heading, .summary-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.preview-surface { min-height: 520px; border: 1px solid var(--line); background: #cbc7bf; display: grid; place-items: center; overflow: auto; }
.preview-surface img { display: block; max-width: 100%; height: auto; background: white; }
.preview-table { border-collapse: collapse; min-width: 100%; background: white; align-self: start; }
.preview-table td { border: 1px solid #e5e1d9; padding: 5px 7px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.nav-button, .participant-card { width: 100%; margin: 0 0 7px; padding: 9px; border: 1px solid var(--line); border-radius: 7px; background: white; text-align: left; }
.nav-button[aria-current="true"] { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.participant-card span { display: block; color: var(--muted); font-size: 11px; }
#assignment-controls label, #assignment-controls legend { display: block; margin: 12px 0 5px; color: var(--muted); font-size: 12px; font-weight: 650; }
#assignment-controls select, #apply-button { width: 100%; min-height: 38px; }
#assignment-controls fieldset { margin: 12px 0; padding: 9px; border: 1px solid var(--line); }
.participant-choice { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
#apply-button, #approve-button { border: 0; border-radius: 6px; padding: 10px 13px; background: var(--accent); color: white; font-weight: 700; }
.quiet { border: 1px solid var(--line); border-radius: 6px; padding: 9px 11px; background: white; color: var(--ink); }
.summary-panel { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
.summary-panel h3 { margin: 14px 0 6px; font-size: 12px; }
#summary-counts { display: grid; grid-template-columns: 1fr auto; gap: 5px 10px; margin: 0; }
#summary-counts div { display: contents; }
#summary-counts dt { color: var(--muted); }
#summary-counts dd { margin: 0; font-weight: 700; }
#decision-records, #issue-list { margin: 0; padding-left: 18px; color: var(--muted); font-size: 11px; }
#decision-records li, #issue-list li { margin-bottom: 5px; overflow-wrap: anywhere; }
.digest-label { margin: 13px 0 4px; color: var(--muted); font-size: 11px; }
#proposal-digest { display: block; overflow-wrap: anywhere; font-size: 10px; }
#message { min-height: 20px; margin-top: 10px; color: var(--warn); font-size: 12px; }
.terminal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
#approve-button { grid-column: 1 / -1; }
@media (max-width: 980px) {
  .review-grid { grid-template-columns: 220px minmax(380px, 1fr); }
  #assignment-controls { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--line); }
}
"""


UI_JS = r""""use strict";

const localReview = {
  csrfToken: "",
  units: [],
  sources: [],
  participants: [],
  review: { unitDecisions: [], sourceDispositions: [], issueCodes: [] },
  summary: null,
  activeUnitId: null,
  activeSourceId: null,
  previewObjectUrl: null,
};

const byId = (id) => document.getElementById(id);

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function textElement(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = String(value);
  if (className) element.className = className;
  return element;
}

function displayLabel(value) {
  return String(value).replaceAll("-", " ");
}

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "review-request-failed");
  return payload;
}

async function api(route, body) {
  const response = await fetch(route, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": localReview.csrfToken,
    },
    body: JSON.stringify(body),
  });
  return readJson(response);
}

function unitRecord(unitId) {
  return localReview.review.unitDecisions.find((record) => record.unitId === unitId) || null;
}

function sourceRecord(evidenceId) {
  return localReview.review.sourceDispositions.find((record) => record.evidenceId === evidenceId) || null;
}

function applyState(payload) {
  localReview.csrfToken = payload.csrfToken || localReview.csrfToken;
  localReview.units = payload.units || localReview.units;
  localReview.sources = payload.sources || localReview.sources;
  localReview.participants = payload.participants || localReview.participants;
  localReview.review = payload.review || localReview.review;
  localReview.summary = payload.summary || payload;
  renderNavigation();
  renderParticipantChoices();
  renderDecisionSummary();
  renderSummary(localReview.summary);
  restoreActiveControls();
}

function buttonFor(label, active, onClick) {
  const button = textElement("button", label, "nav-button");
  button.type = "button";
  button.setAttribute("aria-current", active ? "true" : "false");
  button.addEventListener("click", onClick);
  return button;
}

function renderNavigation() {
  const rosterOptions = byId("roster-options");
  const participantList = byId("participant-list");
  const unitList = byId("unit-list");
  const sourceList = byId("source-list");
  clearNode(rosterOptions);
  clearNode(participantList);
  clearNode(unitList);
  clearNode(sourceList);

  localReview.units.filter((unit) => unit.unitKind === "worksheet" && unit.suggestedRole === "payment-roster").forEach((unit) => {
    rosterOptions.appendChild(buttonFor(`Select ${unit.unitId}`, localReview.summary && localReview.summary.rosterUnitId === unit.unitId, async () => {
      try { applyState(await api("/api/roster", { rosterUnitId: unit.unitId })); }
      catch (error) { showMessage(error.message); }
    }));
  });

  localReview.participants.forEach((participant) => {
    const card = textElement("div", participant.name, "participant-card");
    card.appendChild(textElement("span", `${participant.participantHandle} · ${participant.identityHint}`));
    participantList.appendChild(card);
  });

  localReview.units.forEach((unit) => {
    const record = unitRecord(unit.unitId);
    const decision = record ? record.decision.decision : "unresolved";
    unitList.appendChild(buttonFor(`${unit.unitId} · ${unit.suggestedRole} · ${decision}`, localReview.activeUnitId === unit.unitId, () => selectUnit(unit)));
  });
  localReview.review.sourceDispositions.forEach((record) => {
    const source = localReview.sources.find((item) => item.evidenceId === record.evidenceId);
    if (source) {
      sourceList.appendChild(buttonFor(`${source.evidenceId} · source only · ${record.decision.decision}`, localReview.activeSourceId === source.evidenceId, () => selectSource(source)));
    }
  });
}

function renderParticipantChoices() {
  const options = byId("participant-options");
  clearNode(options);
  localReview.participants.forEach((participant) => {
    const label = document.createElement("label");
    label.className = "participant-choice";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = participant.participantHandle;
    label.appendChild(input);
    label.appendChild(document.createTextNode(`${participant.name} (${participant.participantHandle})`));
    options.appendChild(label);
  });
}

function populateSelect(select, values, selected) {
  clearNode(select);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = displayLabel(value);
    select.appendChild(option);
  });
  if (values.includes(selected)) select.value = selected;
}

function setParticipantSelection(handles) {
  const selected = new Set(handles || []);
  byId("participant-options").querySelectorAll("input").forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function activeRecord() {
  if (localReview.activeUnitId) return unitRecord(localReview.activeUnitId);
  if (localReview.activeSourceId) return sourceRecord(localReview.activeSourceId);
  return null;
}

function restoreActiveControls() {
  const record = activeRecord();
  const decisionControl = byId("decision-control");
  const roleControl = byId("role-control");
  if (!record) {
    populateSelect(decisionControl, [], "");
    populateSelect(roleControl, [], "");
    byId("apply-button").disabled = true;
    byId("scope-control").disabled = true;
    byId("reason-control").disabled = true;
    setParticipantSelection([]);
    byId("participant-options").querySelectorAll("input").forEach((input) => { input.disabled = true; });
    return;
  }
  const current = record.decision;
  populateSelect(decisionControl, record.allowedDecisions, current.decision);
  const defaultRole = current.role || (record.suggestedRole !== "unknown" ? record.suggestedRole : record.allowedRoles[0]);
  populateSelect(roleControl, record.allowedRoles, defaultRole);
  byId("scope-control").value = current.target ? current.target.scope : "individual";
  byId("reason-control").value = current.reason || "irrelevant";
  setParticipantSelection(current.target ? current.target.participantHandles : []);
  byId("apply-button").disabled = false;
  updateControlContext();
}

function updateControlContext() {
  const record = activeRecord();
  if (!record) return;
  const sourceOnly = Boolean(localReview.activeSourceId);
  const decision = byId("decision-control").value;
  const role = byId("role-control");
  const scope = byId("scope-control");
  const reason = byId("reason-control");
  const assignment = !sourceOnly && (decision === "accepted" || decision === "reassigned");

  if (decision === "accepted" && record.suggestedRole !== "unknown") {
    role.value = record.suggestedRole;
  } else if (decision === "reassigned" && record.suggestedRole !== "unknown" && role.value === record.suggestedRole) {
    const alternative = record.allowedRoles.find((value) => value !== record.suggestedRole);
    if (alternative) role.value = alternative;
  }
  role.disabled = !assignment || decision === "accepted";
  scope.disabled = !assignment;
  reason.disabled = decision !== "excluded";
  const caseTarget = scope.value === "case";
  byId("participant-options").querySelectorAll("input").forEach((input) => {
    if (caseTarget) input.checked = false;
    input.disabled = !assignment || caseTarget;
  });
}

function participantTargetLabel(handle) {
  const participant = localReview.participants.find((item) => item.participantHandle === handle);
  return participant ? `${participant.name} (${handle})` : handle;
}

function decisionText(record, id) {
  const decision = record.decision;
  const parts = [id, decision.decision];
  if (decision.role) parts.push(decision.role);
  if (decision.target) {
    parts.push(decision.target.scope);
    if (decision.target.participantHandles.length) {
      parts.push(decision.target.participantHandles.map(participantTargetLabel).join(", "));
    }
  }
  if (decision.reason) parts.push(decision.reason);
  return parts.join(" · ");
}

function renderDecisionSummary() {
  const records = byId("decision-records");
  const issues = byId("issue-list");
  clearNode(records);
  clearNode(issues);
  localReview.review.unitDecisions.forEach((record) => {
    records.appendChild(textElement("li", decisionText(record, record.unitId)));
  });
  localReview.review.sourceDispositions.forEach((record) => {
    records.appendChild(textElement("li", decisionText(record, record.evidenceId)));
  });
  const issueCodes = localReview.review.issueCodes.length ? localReview.review.issueCodes : ["none"];
  issueCodes.forEach((code) => issues.appendChild(textElement("li", code)));
}

function releasePreviewObjectUrl(expectedUrl) {
  const current = localReview.previewObjectUrl;
  if (current && (!expectedUrl || expectedUrl === current)) {
    URL.revokeObjectURL(current);
    localReview.previewObjectUrl = null;
  }
}

async function selectUnit(unit) {
  localReview.activeUnitId = unit.unitId;
  localReview.activeSourceId = null;
  byId("active-unit-title").textContent = unit.unitId;
  byId("preview-title").textContent = `${unit.unitId} · ${unit.suggestedRole}`;
  renderNavigation();
  restoreActiveControls();
  releasePreviewObjectUrl();
  const surface = byId("preview-content");
  clearNode(surface);
  try {
    const response = await fetch(`/api/preview?unitId=${encodeURIComponent(unit.unitId)}`, { credentials: "same-origin" });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || "preview-unavailable");
    }
    if (localReview.activeUnitId !== unit.unitId) return;
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.startsWith("application/json")) {
      const preview = await response.json();
      if (localReview.activeUnitId !== unit.unitId) return;
      const table = document.createElement("table");
      table.className = "preview-table";
      preview.rows.forEach((row) => {
        const tableRow = document.createElement("tr");
        row.forEach((cell) => tableRow.appendChild(textElement("td", cell)));
        table.appendChild(tableRow);
      });
      surface.appendChild(table);
    } else {
      const previewBlob = await response.blob();
      if (localReview.activeUnitId !== unit.unitId) return;
      const objectUrl = URL.createObjectURL(previewBlob);
      localReview.previewObjectUrl = objectUrl;
      const image = document.createElement("img");
      image.alt = `Preview of ${unit.unitId}`;
      image.addEventListener("load", () => releasePreviewObjectUrl(objectUrl), { once: true });
      image.addEventListener("error", () => releasePreviewObjectUrl(objectUrl), { once: true });
      image.src = objectUrl;
      surface.appendChild(image);
    }
  } catch (error) {
    if (localReview.activeUnitId === unit.unitId) surface.appendChild(textElement("p", error.message));
  }
}

function selectSource(source) {
  localReview.activeUnitId = null;
  localReview.activeSourceId = source.evidenceId;
  releasePreviewObjectUrl();
  byId("active-unit-title").textContent = source.evidenceId;
  byId("preview-title").textContent = "Source-only item has no unit preview";
  clearNode(byId("preview-content"));
  renderNavigation();
  restoreActiveControls();
}

function checkedHandles() {
  return Array.from(byId("participant-options").querySelectorAll("input:checked"), (input) => input.value);
}

function assignmentTarget() {
  const scope = byId("scope-control").value;
  const participantHandles = checkedHandles();
  if (scope === "individual" && participantHandles.length !== 1) {
    throw new Error("Select exactly one participant for an individual assignment");
  }
  if (scope === "shared" && participantHandles.length < 2) {
    throw new Error("Select at least two participants for a shared assignment");
  }
  if (scope === "case" && participantHandles.length) {
    throw new Error("Whole-case assignments cannot select participants");
  }
  return { scope, participantHandles };
}

async function applyDecision() {
  const decision = byId("decision-control").value;
  try {
    if (localReview.activeSourceId) {
      const record = sourceRecord(localReview.activeSourceId);
      if (!record || !record.allowedDecisions.includes(decision)) throw new Error("Select a valid source disposition");
      const payload = { evidenceId: localReview.activeSourceId, decision };
      if (decision === "excluded") payload.reason = byId("reason-control").value;
      applyState(await api("/api/source", payload));
      return;
    }
    const record = unitRecord(localReview.activeUnitId);
    if (!record || !record.allowedDecisions.includes(decision)) throw new Error("Select a valid unit decision");
    const payload = { unitId: record.unitId, decision };
    if (decision === "accepted" || decision === "reassigned") {
      payload.role = decision === "accepted" ? record.suggestedRole : byId("role-control").value;
      if (!record.allowedRoles.includes(payload.role)) throw new Error("Select a valid role for this evidence unit");
      payload.target = assignmentTarget();
    } else if (decision === "excluded") {
      payload.reason = byId("reason-control").value;
    }
    applyState(await api("/api/unit", payload));
  } catch (error) {
    showMessage(error.message);
  }
}

function renderSummary(summary) {
  if (!summary || !summary.counts) return;
  localReview.summary = summary;
  const counts = byId("summary-counts");
  clearNode(counts);
  Object.entries(summary.counts).forEach(([name, value]) => {
    const pair = document.createElement("div");
    pair.appendChild(textElement("dt", name));
    pair.appendChild(textElement("dd", value));
    counts.appendChild(pair);
  });
  byId("proposal-digest").textContent = summary.proposalDigest || "Not ready";
  byId("approve-button").disabled = !summary.readyToPrepare;
  const resolved = summary.counts.accepted + summary.counts.reassigned + summary.counts.excluded;
  byId("progress-status").textContent = `${resolved} resolved`;
  byId("unresolved-status").textContent = `${summary.counts.unresolved} unresolved`;
}

function showMessage(message) {
  byId("message").textContent = String(message || "");
}

async function terminal(route, body) {
  try {
    const result = await api(route, body);
    releasePreviewObjectUrl();
    showMessage(`Review finished: ${result.outcome}`);
    document.querySelectorAll("button, select, input").forEach((control) => { control.disabled = true; });
  } catch (error) {
    showMessage(error.message);
  }
}

byId("decision-control").addEventListener("change", updateControlContext);
byId("scope-control").addEventListener("change", updateControlContext);
byId("apply-button").addEventListener("click", applyDecision);
byId("summary-button").addEventListener("click", async () => {
  try { renderSummary(await api("/api/summary", {})); }
  catch (error) { showMessage(error.message); }
});
byId("draft-button").addEventListener("click", () => terminal("/api/draft", {}));
byId("cancel-button").addEventListener("click", () => terminal("/api/cancel", {}));
byId("approve-button").addEventListener("click", () => terminal("/api/approve", { expectedProposalDigest: localReview.summary.proposalDigest }));
window.addEventListener("beforeunload", () => releasePreviewObjectUrl());

window.setInterval(() => { api("/api/heartbeat", {}).catch(() => {}); }, 60000);

fetch("/api/state", { credentials: "same-origin" })
  .then(readJson)
  .then(applyState)
  .catch((error) => showMessage(error.message));
"""
