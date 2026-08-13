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
      <select id="decision-control">
        <option value="unresolved">Unresolved</option>
        <option value="accepted">Accept suggestion</option>
        <option value="reassigned">Reassign role</option>
        <option value="excluded">Exclude</option>
      </select>
      <label for="role-control">Role</label>
      <select id="role-control">
        <option value="payment-roster">Payment roster</option>
        <option value="service-contract">Service contract</option>
        <option value="acceptance-record">Acceptance record</option>
        <option value="payment-tax-form">Payment tax form</option>
        <option value="identity-front">Identity front</option>
        <option value="identity-back">Identity back</option>
        <option value="shared-supporting-evidence">Shared supporting evidence</option>
        <option value="other-supporting-evidence">Other supporting evidence</option>
      </select>
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
#summary-counts { display: grid; grid-template-columns: 1fr auto; gap: 5px 10px; margin: 0; }
#summary-counts div { display: contents; }
#summary-counts dt { color: var(--muted); }
#summary-counts dd { margin: 0; font-weight: 700; }
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
  summary: null,
  activeUnitId: null,
  activeSourceId: null,
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

function applyState(payload) {
  localReview.csrfToken = payload.csrfToken || localReview.csrfToken;
  localReview.units = payload.units || localReview.units;
  localReview.sources = payload.sources || localReview.sources;
  localReview.participants = payload.participants || localReview.participants;
  localReview.summary = payload.summary || payload;
  renderNavigation();
  renderParticipantChoices();
  renderSummary(localReview.summary);
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
    unitList.appendChild(buttonFor(`${unit.unitId} · ${unit.suggestedRole}`, localReview.activeUnitId === unit.unitId, () => selectUnit(unit)));
  });
  const unitEvidence = new Set(localReview.units.map((unit) => unit.evidenceId));
  localReview.sources.filter((source) => !unitEvidence.has(source.evidenceId)).forEach((source) => {
    sourceList.appendChild(buttonFor(`${source.evidenceId} · source only`, localReview.activeSourceId === source.evidenceId, () => selectSource(source)));
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
    label.appendChild(document.createTextNode(participant.name));
    options.appendChild(label);
  });
}

async function selectUnit(unit) {
  localReview.activeUnitId = unit.unitId;
  localReview.activeSourceId = null;
  byId("active-unit-title").textContent = unit.unitId;
  byId("preview-title").textContent = `${unit.unitId} · ${unit.suggestedRole}`;
  byId("role-control").value = unit.suggestedRole === "unknown" ? "other-supporting-evidence" : unit.suggestedRole;
  renderNavigation();
  const surface = byId("preview-content");
  clearNode(surface);
  try {
    const response = await fetch(`/api/preview?unitId=${encodeURIComponent(unit.unitId)}`, { credentials: "same-origin" });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || "preview-unavailable");
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.startsWith("application/json")) {
      const preview = await response.json();
      const table = document.createElement("table");
      table.className = "preview-table";
      preview.rows.forEach((row) => {
        const tableRow = document.createElement("tr");
        row.forEach((cell) => tableRow.appendChild(textElement("td", cell)));
        table.appendChild(tableRow);
      });
      surface.appendChild(table);
    } else {
      const image = document.createElement("img");
      image.alt = `Preview of ${unit.unitId}`;
      image.src = `/api/preview?unitId=${encodeURIComponent(unit.unitId)}`;
      surface.appendChild(image);
    }
  } catch (error) {
    surface.appendChild(textElement("p", error.message));
  }
}

function selectSource(source) {
  localReview.activeUnitId = null;
  localReview.activeSourceId = source.evidenceId;
  byId("active-unit-title").textContent = source.evidenceId;
  byId("preview-title").textContent = "Source-only item has no unit preview";
  clearNode(byId("preview-content"));
  renderNavigation();
}

function checkedHandles() {
  return Array.from(byId("participant-options").querySelectorAll("input:checked"), (input) => input.value);
}

async function applyDecision() {
  const decision = byId("decision-control").value;
  try {
    if (localReview.activeSourceId) {
      const payload = { evidenceId: localReview.activeSourceId, decision };
      if (decision === "excluded") payload.reason = byId("reason-control").value;
      applyState(await api("/api/source", payload));
      return;
    }
    if (!localReview.activeUnitId) throw new Error("Select an evidence unit first");
    const payload = { unitId: localReview.activeUnitId, decision };
    if (decision === "accepted" || decision === "reassigned") {
      payload.role = byId("role-control").value;
      payload.target = { scope: byId("scope-control").value, participantHandles: checkedHandles() };
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
  const reviewed = summary.counts.units - summary.counts.unresolved;
  byId("progress-status").textContent = `${reviewed} of ${summary.counts.units} reviewed`;
  byId("unresolved-status").textContent = `${summary.counts.unresolved} unresolved`;
}

function showMessage(message) {
  byId("message").textContent = String(message || "");
}

async function terminal(route, body) {
  try {
    const result = await api(route, body);
    showMessage(`Review finished: ${result.outcome}`);
    document.querySelectorAll("button, select, input").forEach((control) => { control.disabled = true; });
  } catch (error) {
    showMessage(error.message);
  }
}

byId("apply-button").addEventListener("click", applyDecision);
byId("summary-button").addEventListener("click", async () => {
  try { renderSummary(await api("/api/summary", {})); }
  catch (error) { showMessage(error.message); }
});
byId("draft-button").addEventListener("click", () => terminal("/api/draft", {}));
byId("cancel-button").addEventListener("click", () => terminal("/api/cancel", {}));
byId("approve-button").addEventListener("click", () => terminal("/api/approve", { expectedProposalDigest: localReview.summary.proposalDigest }));

window.setInterval(() => { api("/api/heartbeat", {}).catch(() => {}); }, 60000);

fetch("/api/state", { credentials: "same-origin" })
  .then(readJson)
  .then(applyState)
  .catch((error) => showMessage(error.message));
"""
