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
      <span id="progress-status">Loading coverage</span>
      <span id="unresolved-status">Loading exceptions</span>
    </div>
  </header>

  <main class="review-layout">
    <section id="exception-workspace" aria-labelledby="exception-heading">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Needs review</p>
          <h2 id="exception-heading" tabindex="-1">Review exceptions</h2>
        </div>
        <button id="undo-button" type="button" class="quiet" disabled>Undo last decision</button>
      </div>
      <p class="section-copy">Review only evidence that could not be organized safely.</p>
      <div id="exception-list" class="exception-list"></div>
      <section id="exception-detail" class="exception-detail" aria-label="Selected exception"></section>
    </section>

    <section id="organized-evidence" aria-labelledby="organized-heading">
      <p class="eyebrow">Optional spot check</p>
      <h2 id="organized-heading">Automatically organized evidence</h2>
      <p id="organized-copy" class="section-copy">These groups need no individual decision. Open a group only when you want to inspect it.</p>
      <div id="organized-groups"></div>
    </section>

    <aside id="coverage-and-approval" aria-labelledby="coverage-heading">
      <p class="eyebrow">Final check</p>
      <h2 id="coverage-heading" tabindex="-1">Coverage and approval</h2>
      <dl id="coverage-summary"></dl>
      <div id="resolved-exclusions" aria-label="Resolved source exclusions"></div>
      <div id="batch-announcement" class="sr-status" role="status" aria-live="polite"></div>
      <div id="message" role="status" aria-live="polite"></div>
      <button id="approve-button" type="button" disabled>Approve complete proposal</button>
      <div class="secondary-actions">
        <button id="draft-button" type="button" class="quiet">Return draft</button>
        <button id="cancel-button" type="button" class="quiet">Cancel</button>
      </div>
    </aside>
  </main>
</body>
</html>
"""


UI_CSS = """:root {
  color-scheme: light;
  --ink: #151515;
  --muted: #625f59;
  --line: #d8d3ca;
  --paper: #f5f1e8;
  --surface: #fffdf8;
  --accent: #1457d9;
  --accent-soft: #edf3ff;
  --warn: #7a4900;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); }
button, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .5; }
button:focus-visible, select:focus-visible, input:focus-visible, summary:focus-visible {
  outline: 3px solid #0b5fff; outline-offset: 2px;
}
.topbar {
  min-height: 78px; padding: 14px 22px; border-bottom: 1px solid var(--line);
  background: var(--surface); display: flex; align-items: center;
  justify-content: space-between; gap: 18px;
}
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: 22px; }
h2 { margin-bottom: 8px; font-size: 18px; }
h3 { margin-bottom: 8px; font-size: 16px; }
.eyebrow {
  margin-bottom: 4px; color: var(--accent); font-size: 11px; font-weight: 750;
  letter-spacing: .11em; text-transform: uppercase;
}
.status-pair { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.status-pair span {
  border: 1px solid var(--line); border-radius: 999px; padding: 7px 10px;
  background: white; font-size: 12px;
}
.review-layout {
  display: grid; grid-template-columns: minmax(320px, 1.15fr) minmax(300px, .95fr) minmax(260px, .65fr);
  align-items: start; gap: 18px; padding: 18px; min-height: calc(100vh - 78px);
}
#exception-workspace, #organized-evidence, #coverage-and-approval {
  min-width: 0; padding: 18px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--surface);
}
#coverage-and-approval { position: sticky; top: 18px; }
.section-heading { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.section-copy { margin-bottom: 14px; color: var(--muted); font-size: 13px; line-height: 1.45; }
.exception-list { display: grid; gap: 8px; }
.exception-card {
  width: 100%; padding: 12px; border: 1px solid var(--line); border-radius: 8px;
  background: white; color: var(--ink); text-align: left;
}
.exception-card strong, .exception-card span { display: block; }
.exception-card span { margin-top: 4px; color: var(--muted); font-size: 12px; }
.exception-card[aria-current="true"] {
  border-color: var(--accent); box-shadow: inset 4px 0 0 var(--accent); background: var(--accent-soft);
}
.empty-state { margin: 0; padding: 14px; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); }
.exception-detail { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.detail-meta { color: var(--muted); font-size: 12px; }
.action-panel { margin-top: 14px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: white; }
.action-panel label, .action-panel legend { display: block; margin: 8px 0 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
.action-panel select, .action-panel > button { width: 100%; min-height: 40px; }
.action-panel fieldset { margin: 10px 0; padding: 9px; border: 1px solid var(--line); }
.participant-choice { display: flex; align-items: center; gap: 8px; margin: 7px 0; }
.participant-choice label { margin: 0; color: var(--ink); font-weight: 500; }
.batch-control { display: flex; align-items: start; gap: 8px; margin-top: 12px; padding: 10px; border: 1px solid var(--line); border-radius: 7px; }
.batch-control label { margin: 0; color: var(--ink); font-weight: 600; }
.primary, #approve-button {
  border: 0; border-radius: 7px; padding: 10px 13px; background: var(--accent); color: white; font-weight: 750;
}
.quiet { border: 1px solid var(--line); border-radius: 7px; padding: 9px 11px; background: white; color: var(--ink); }
.preview-surface {
  min-height: 230px; margin-top: 12px; border: 1px solid var(--line); background: #e2ded6;
  display: grid; place-items: center; overflow: auto;
}
.preview-surface img { display: block; max-width: 100%; height: auto; background: white; }
.preview-table { border-collapse: collapse; width: 100%; background: white; align-self: start; }
.preview-table td { border: 1px solid #e5e1d9; padding: 5px 7px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
#organized-groups { display: grid; gap: 8px; }
#organized-groups details { border: 1px solid var(--line); border-radius: 8px; background: white; }
#organized-groups summary { padding: 11px 12px; cursor: pointer; font-weight: 700; }
.group-body { padding: 0 12px 12px; }
.group-facts, #coverage-summary, .exclusion-facts { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; margin: 0 0 12px; }
.group-facts div, #coverage-summary div, .exclusion-facts div { display: contents; }
.group-facts dt, #coverage-summary dt, .exclusion-facts dt { color: var(--muted); }
.group-facts dd, #coverage-summary dd, .exclusion-facts dd { margin: 0; font-weight: 700; text-align: right; }
#resolved-exclusions h3 { margin-top: 14px; }
#resolved-exclusions article { padding-top: 10px; border-top: 1px solid var(--line); }
.group-actions { display: flex; flex-wrap: wrap; gap: 8px; }
#message, .sr-status { min-height: 20px; margin: 10px 0; color: var(--warn); font-size: 12px; }
#approve-button { width: 100%; min-height: 44px; }
.secondary-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
@media (max-width: 1050px) {
  .review-layout { grid-template-columns: minmax(320px, 1fr) minmax(280px, .8fr); }
  #coverage-and-approval { position: static; grid-column: 1 / -1; }
}
@media (max-width: 700px) {
  .topbar { align-items: start; }
  .review-layout { grid-template-columns: 1fr; padding: 10px; }
  #coverage-and-approval { grid-column: auto; }
}
"""


UI_JS = r""""use strict";

const localReview = {
  csrfToken: "",
  participants: [],
  roster: null,
  review: { exceptions: [], organizedGroups: [], resolvedExclusions: [], coverage: {}, issueCodes: [] },
  summary: null,
  activeExceptionId: null,
  previewObjectUrl: null,
  previewSelectionKey: null,
  lastResolvedExceptionId: null,
  terminal: false,
};

const ROLE_OPTIONS = {
  "pdf-page": [
    "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
    "identity-front", "identity-back", "shared-supporting-evidence",
    "other-supporting-evidence",
  ],
  worksheet: ["payment-roster", "other-supporting-evidence"],
  image: [
    "identity-front", "identity-back", "shared-supporting-evidence",
    "other-supporting-evidence",
  ],
};

const ROLE_SCOPES = {
  "payment-roster": ["case"],
  "service-contract": ["individual", "shared", "case"],
  "acceptance-record": ["individual", "shared", "case"],
  "payment-tax-form": ["individual"],
  "identity-front": ["individual"],
  "identity-back": ["individual"],
  "shared-supporting-evidence": ["shared", "case"],
  "other-supporting-evidence": ["individual", "shared", "case"],
};

const ISSUE_LABELS = {
  "roster-ambiguous": "More than one roster could be authoritative",
  "roster-missing": "No usable payment roster was found",
  "roster-invalid": "The roster needs a human choice",
  "private-fact-incomplete": "This evidence could not be read completely",
  "participant-name-only": "Participant name matched without a matching identity",
  "participant-identity-only": "Participant identity matched without a matching name",
  "participant-no-match": "No roster participant matched this evidence",
  "participant-multiple-match": "More than one participant matched this evidence",
  "participant-identity-conflict": "Participant signals conflict",
  "target-unresolved": "The assignment target needs review",
  "role-uncertain": "The document role is uncertain",
  "role-gap-conflict": "Adjacent document roles conflict",
  "role-scope-unsupported": "The role and assignment scope do not agree",
  "packet-structure-incoherent": "The packet boundary needs review",
  "source-issue-present": "The source has a blocking issue",
  "unit-issue-present": "This evidence item has a blocking issue",
  "source-opaque": "The source could not be inspected",
  "source-unsupported": "This source type is unsupported",
  "source-unreadable": "This source is unreadable",
  "source-encrypted": "This source is encrypted",
  "source-over-limit": "This source exceeds the local safety limit",
  "source-not-applicable": "This source is not applicable to the proposal",
  "source-exact-duplicate": "This source is an exact duplicate",
};

const ACTION_LABELS = {
  assign: "Assign evidence",
  exclude: "Exclude evidence",
  split: "Split this group",
  "merge-next": "Merge with the next group",
  "choose-roster": "Choose this roster",
};

const EXCLUSION_REASONS = [
  "duplicate", "irrelevant", "unreadable-replacement-available",
  "intentionally-omitted", "other",
];

const detailControls = Object.create(null);
const byId = (id) => document.getElementById(id);

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function clearDetailControls() {
  Object.keys(detailControls).forEach((key) => { delete detailControls[key]; });
}

function registerDetailControl(id, element) {
  element.id = id;
  detailControls[id] = element;
  return element;
}

function textElement(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = String(value);
  if (className) element.className = className;
  return element;
}

function fixedLabel(value) {
  return String(value || "").replaceAll("-", " ");
}

function numericLabel(value, fallback) {
  const match = String(value || "").match(/[0-9]+$/);
  return match ? String(Number(match[0])) : fallback;
}

function appendDefinition(list, name, value) {
  const pair = document.createElement("div");
  pair.appendChild(textElement("dt", name));
  pair.appendChild(textElement("dd", value));
  list.appendChild(pair);
}

function populateSelect(select, values, selected) {
  clearNode(select);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = fixedLabel(value);
    select.appendChild(option);
  });
  if (values.includes(selected)) select.value = selected;
}

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) throw new Error("review-request-failed");
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

function showMessage(message) {
  byId("message").textContent = String(message || "");
}

function currentException() {
  return localReview.review.exceptions.find(
    (item) => item.exceptionId === localReview.activeExceptionId
  ) || null;
}

function groupForException(exception) {
  if (!exception || exception.kind !== "unit-cluster" || !exception.groupIds.length) {
    return null;
  }
  return localReview.review.organizedGroups.find(
    (group) => group.groupId === exception.groupIds[0]
  ) || null;
}

function participantLabel(handle) {
  const participant = localReview.participants.find(
    (item) => item.participantHandle === handle
  );
  return participant ? `${participant.name} (${participant.identityHint})` : handle;
}

function targetLabel(target) {
  if (!target) return "Unassigned — roster required";
  if (target.scope === "case") return "Whole case";
  if (!target.participantHandles.length) return fixedLabel(target.scope);
  return target.participantHandles.map(participantLabel).join(", ");
}

function issueLabel(code) {
  return ISSUE_LABELS[code] || fixedLabel(code) || "Review required";
}

function exceptionLocation(exception) {
  if (exception.kind === "roster") return "Roster selection";
  if (exception.kind === "source") {
    return `Source ${numericLabel(exception.evidenceId, "item")}`;
  }
  const group = groupForException(exception);
  if (!group) return `${exception.memberUnitIds.length} evidence items`;
  const range = group.firstUnitIndex === group.lastUnitIndex
    ? `item ${group.firstUnitIndex}`
    : `items ${group.firstUnitIndex}–${group.lastUnitIndex}`;
  return `Source ${numericLabel(group.evidenceId, "item")} · ${range} · ${exception.memberUnitIds.length} evidence items`;
}

function releasePreviewObjectUrl(expectedUrl) {
  const current = localReview.previewObjectUrl;
  if (current && (!expectedUrl || current === expectedUrl)) {
    URL.revokeObjectURL(current);
    localReview.previewObjectUrl = null;
  }
  if (!expectedUrl || current === expectedUrl) localReview.previewSelectionKey = null;
}

function replaceState(payload) {
  localReview.csrfToken = payload.csrfToken;
  localReview.participants = payload.participants;
  localReview.roster = payload.roster;
  localReview.review = payload.review;
  localReview.summary = payload.summary;
}

function applyState(payload, transition = {}) {
  releasePreviewObjectUrl();
  replaceState(payload);
  const exceptions = localReview.review.exceptions;
  if (Number.isInteger(transition.focusIndex)) {
    localReview.activeExceptionId = exceptions.length
      ? exceptions[Math.min(transition.focusIndex, exceptions.length - 1)].exceptionId
      : null;
  } else if (!exceptions.some((item) => item.exceptionId === localReview.activeExceptionId)) {
    localReview.activeExceptionId = null;
  }
  if (transition.clearUndo) {
    localReview.lastResolvedExceptionId = null;
  } else if (transition.lastResolvedExceptionId) {
    localReview.lastResolvedExceptionId = transition.lastResolvedExceptionId;
  }
  renderAll();
  if (Number.isInteger(transition.focusIndex)) {
    if (!exceptions.length) {
      byId("coverage-heading").focus();
    } else {
      const card = Array.from(byId("exception-list").querySelectorAll(".exception-card")).find(
        (item) => item.getAttribute("data-exception-id") === localReview.activeExceptionId
      );
      if (card) card.focus();
    }
  }
}

function renderTopStatus() {
  const coverage = localReview.review.coverage;
  const total = localReview.summary && localReview.summary.counts
    ? localReview.summary.counts.units
    : coverage.automaticallyOrganizedUnits + coverage.exceptionUnits;
  byId("progress-status").textContent = `${coverage.automaticallyOrganizedUnits} of ${total} automatically organized`;
  byId("unresolved-status").textContent = `${localReview.review.exceptions.length} exceptions need review`;
}

function renderExceptions() {
  const list = byId("exception-list");
  clearNode(list);
  const exceptions = localReview.review.exceptions;
  byId("exception-heading").textContent = exceptions.length
    ? "Review exceptions"
    : "Ready for approval";
  if (!exceptions.length) {
    list.appendChild(textElement("p", "Every evidence item is accounted for. Review coverage, then approve the complete proposal.", "empty-state"));
    return;
  }
  exceptions.forEach((exception, index) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "exception-card";
    card.setAttribute("data-exception-id", exception.exceptionId);
    card.setAttribute(
      "aria-current",
      exception.exceptionId === localReview.activeExceptionId ? "true" : "false"
    );
    card.setAttribute("aria-label", `Review exception ${index + 1}: ${issueLabel(exception.issueCode)}`);
    card.appendChild(textElement("strong", `${index + 1}. ${issueLabel(exception.issueCode)}`));
    card.appendChild(textElement("span", exceptionLocation(exception)));
    card.addEventListener("click", () => selectException(exception.exceptionId));
    list.appendChild(card);
  });
}

function matchingExceptions(exception, action) {
  const effective = action === "accept-recommendation"
    ? exception.recommendedAction
    : action;
  if (!(["assign", "exclude"].includes(effective))) return [];
  const allowed = JSON.stringify(exception.allowedActions);
  return localReview.review.exceptions.filter(
    (item) => item.exceptionId !== exception.exceptionId
      && item.kind === exception.kind
      && item.similarityKey === exception.similarityKey
      && JSON.stringify(item.allowedActions) === allowed
      && item.allowedActions.includes(effective)
  );
}

function batchCountFor(exception, action) {
  return 1 + matchingExceptions(exception, action).length;
}

function renderBatchControl(detail, exception) {
  const actions = [];
  if (exception.recommendedAction && exception.recommendedAction !== "choose-roster") {
    actions.push("accept-recommendation");
  }
  actions.push(...exception.allowedActions.filter((action) => ["assign", "exclude"].includes(action)));
  const batchAction = actions.find((action) => matchingExceptions(exception, action).length);
  if (!batchAction) return;
  const wrapper = document.createElement("div");
  wrapper.className = "batch-control";
  const input = registerDetailControl("apply-to-similar", document.createElement("input"));
  input.type = "checkbox";
  input.checked = false;
  const label = document.createElement("label");
  label.htmlFor = input.id;
  label.textContent = `Apply compatible assign or exclude actions to ${batchCountFor(exception, batchAction)} similar exceptions`;
  input.addEventListener("change", () => {
    byId("batch-announcement").textContent = input.checked
      ? `This action will affect ${batchCountFor(exception, batchAction)} exception clusters.`
      : "This action will affect one exception cluster.";
  });
  wrapper.appendChild(input);
  wrapper.appendChild(label);
  detail.appendChild(wrapper);
}

function actionButton(action, label, listener, className = "primary") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.setAttribute("data-action", action);
  button.textContent = label;
  button.addEventListener("click", listener);
  return button;
}

function appendLabeledSelect(panel, id, labelText, values, selected) {
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const select = registerDetailControl(id, document.createElement("select"));
  populateSelect(select, values, selected);
  panel.appendChild(label);
  panel.appendChild(select);
  return select;
}

function participantInputs(panel, selectedHandles) {
  const fieldset = document.createElement("fieldset");
  const legend = textElement("legend", "Participants");
  fieldset.appendChild(legend);
  localReview.participants.forEach((participant) => {
    const row = document.createElement("div");
    row.className = "participant-choice";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = `assign-${participant.participantHandle}`;
    input.value = participant.participantHandle;
    input.checked = selectedHandles.includes(participant.participantHandle);
    input.setAttribute("data-participant-handle", participant.participantHandle);
    const label = document.createElement("label");
    label.htmlFor = input.id;
    label.textContent = `${participant.name} (${participant.identityHint})`;
    row.appendChild(input);
    row.appendChild(label);
    fieldset.appendChild(row);
  });
  panel.appendChild(fieldset);
  return fieldset;
}

function updateAssignmentParticipants() {
  const scope = detailControls["assign-scope"];
  if (!scope) return;
  const caseScope = scope.value === "case";
  const participantInputs = Array.from(detailControls["assign-participants"].querySelectorAll("input"));
  participantInputs.forEach((input) => {
    if (caseScope) input.checked = false;
    input.disabled = caseScope;
  });
  updateAssignmentSubmit();
}

function updateAssignmentSubmit() {
  const role = detailControls["assign-role"];
  const scope = detailControls["assign-scope"];
  const button = detailControls["assign-submit"];
  const fieldset = detailControls["assign-participants"];
  if (!role || !scope || !button || !fieldset) return;
  const handles = Array.from(
    fieldset.querySelectorAll("input:checked"),
    (input) => input.value
  );
  const validRole = Boolean(role.value && ROLE_SCOPES[role.value]);
  const validScope = validRole
    && (ROLE_SCOPES[role.value] || []).includes(scope.value);
  const validTarget = (scope.value === "case" && handles.length === 0)
    || (scope.value === "individual" && handles.length === 1)
    || (scope.value === "shared" && handles.length >= 2);
  button.disabled = !(validRole && validScope && validTarget);
}

function updateAssignmentRole(group) {
  const role = detailControls["assign-role"];
  const scope = detailControls["assign-scope"];
  if (!role || !scope) return;
  const target = group ? group.target : { scope: "case", participantHandles: [] };
  const supported = ROLE_SCOPES[role.value] || [];
  const selected = supported.includes(scope.value)
    ? scope.value
    : supported.includes(target.scope)
      ? target.scope
      : supported[0] || "";
  populateSelect(scope, supported, selected);
  scope.disabled = !supported.length;
  updateAssignmentParticipants();
}

function appendAssignPanel(detail, exception, group) {
  const panel = document.createElement("div");
  panel.className = "action-panel";
  panel.appendChild(textElement("h4", "Assign to the right packet"));
  const kind = group ? group.unitKind : "pdf-page";
  const roles = ROLE_OPTIONS[kind] || ROLE_OPTIONS["pdf-page"];
  const selectedRole = group && roles.includes(group.role) ? group.role : "";
  const role = appendLabeledSelect(panel, "assign-role", "Document role", roles, selectedRole);
  if (!selectedRole) {
    const existing = Array.from(role.children);
    clearNode(role);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Choose a document role";
    placeholder.disabled = true;
    role.appendChild(placeholder);
    existing.forEach((option) => role.appendChild(option));
    role.value = "";
  }
  const target = group ? group.target : { scope: "case", participantHandles: [] };
  const scope = appendLabeledSelect(
    panel,
    "assign-scope",
    "Assignment scope",
    ROLE_SCOPES[selectedRole] || [],
    selectedRole ? target.scope : ""
  );
  const fieldset = participantInputs(panel, target.participantHandles || []);
  detailControls["assign-participants"] = fieldset;
  const submit = actionButton("assign", ACTION_LABELS.assign, () => submitExceptionAction("assign"));
  detailControls["assign-submit"] = submit;
  role.addEventListener("change", () => updateAssignmentRole(group));
  scope.addEventListener("change", updateAssignmentParticipants);
  Array.from(fieldset.querySelectorAll("input")).forEach((input) => {
    input.addEventListener("change", updateAssignmentSubmit);
  });
  updateAssignmentRole(group);
  panel.appendChild(submit);
  updateAssignmentSubmit();
  detail.appendChild(panel);
}

function appendExcludePanel(detail) {
  const panel = document.createElement("div");
  panel.className = "action-panel";
  panel.appendChild(textElement("h4", "Exclude from the proposal"));
  appendLabeledSelect(panel, "exclude-reason", "Reason", EXCLUSION_REASONS, "irrelevant");
  panel.appendChild(actionButton("exclude", ACTION_LABELS.exclude, () => submitExceptionAction("exclude")));
  detail.appendChild(panel);
}

function appendSplitPanel(detail, exception) {
  if (!exception.memberUnitIds || exception.memberUnitIds.length < 2) return;
  const panel = document.createElement("div");
  panel.className = "action-panel";
  panel.appendChild(textElement("h4", "Adjust the packet boundary"));
  const select = appendLabeledSelect(
    panel,
    "split-before-unit",
    "Start the next group before",
    exception.memberUnitIds.slice(1),
    exception.memberUnitIds[1]
  );
  Array.from(select.children).forEach((option, index) => {
    option.textContent = `evidence item ${index + 2}`;
  });
  panel.appendChild(actionButton("split", ACTION_LABELS.split, () => submitExceptionAction("split")));
  detail.appendChild(panel);
}

function appendRosterPanel(detail) {
  const panel = document.createElement("div");
  panel.className = "action-panel";
  panel.appendChild(textElement("h4", "Choose the authoritative roster"));
  const candidates = localReview.roster ? localReview.roster.candidateSummaries : [];
  const select = appendLabeledSelect(panel, "roster-candidate", "Roster candidate", [], "");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a roster candidate";
  placeholder.disabled = true;
  select.appendChild(placeholder);
  (candidates || []).forEach((candidate, index) => {
    const option = document.createElement("option");
    option.value = candidate.rosterUnitId;
    option.disabled = !candidate.eligible;
    const participantWord = candidate.participantCount === 1 ? "participant" : "participants";
    const issues = candidate.issueCodes.length
      ? ` · ${candidate.issueCodes.map(fixedLabel).join(", ")}`
      : " · eligible";
    option.textContent = `Roster candidate ${index + 1} · ${candidate.participantCount} ${participantWord}${issues}`;
    select.appendChild(option);
  });
  select.value = "";
  const submit = actionButton(
    "choose-roster",
    ACTION_LABELS["choose-roster"],
    () => submitExceptionAction("choose-roster")
  );
  submit.disabled = true;
  detailControls["roster-submit"] = submit;
  const surface = textElement("div", "Select an eligible roster to load its local preview.", "preview-surface");
  surface.setAttribute("aria-label", "Selected roster preview");
  detailControls["roster-preview-surface"] = surface;
  select.addEventListener("change", async () => {
    const candidate = (candidates || []).find(
      (item) => item.rosterUnitId === select.value
    );
    submit.disabled = !(candidate && candidate.eligible);
    if (candidate && candidate.eligible) {
      await loadPreview(
        candidate.rosterUnitId,
        surface,
        `roster:${candidate.rosterUnitId}`
      );
    } else {
      releasePreviewObjectUrl();
      clearNode(surface);
      surface.appendChild(textElement("p", "Select an eligible roster to load its local preview."));
    }
  });
  panel.appendChild(submit);
  panel.appendChild(surface);
  detail.appendChild(panel);
}

function renderDetail() {
  const detail = byId("exception-detail");
  clearNode(detail);
  clearDetailControls();
  const exception = currentException();
  if (!exception) {
    if (localReview.review.exceptions.length) {
      detail.appendChild(textElement("p", "Select an exception to see its preview and actions.", "empty-state"));
    }
    return;
  }
  const heading = registerDetailControl(
    "exception-detail-heading",
    textElement("h3", issueLabel(exception.issueCode))
  );
  heading.setAttribute("tabindex", "-1");
  heading.setAttribute("aria-live", "polite");
  detail.appendChild(heading);
  detail.appendChild(textElement("p", exceptionLocation(exception), "detail-meta"));
  if (exception.issueCode === "roster-missing" && !exception.allowedActions.length) {
    detail.appendChild(textElement(
      "p",
      "Correct or add the roster source, then Return draft and relaunch this review to rerun organization.",
      "detail-meta"
    ));
  } else if (exception.recommendedAction && exception.recommendedAction !== "choose-roster") {
    const panel = document.createElement("div");
    panel.className = "action-panel";
    panel.appendChild(textElement("p", `Recommended: ${ACTION_LABELS[exception.recommendedAction] || fixedLabel(exception.recommendedAction)}`));
    panel.appendChild(actionButton(
      "accept-recommendation",
      "Accept recommendation",
      () => submitExceptionAction("accept-recommendation")
    ));
    detail.appendChild(panel);
  } else if (!exception.recommendedAction && exception.allowedActions.length) {
    detail.appendChild(textElement("p", "No automatic recommendation. Choose one explicit action below.", "detail-meta"));
  }
  renderBatchControl(detail, exception);
  const group = groupForException(exception);
  if (exception.allowedActions.includes("assign")) appendAssignPanel(detail, exception, group);
  if (exception.allowedActions.includes("exclude")) appendExcludePanel(detail);
  if (exception.allowedActions.includes("split")) appendSplitPanel(detail, exception);
  if (exception.allowedActions.includes("merge-next")) {
    const panel = document.createElement("div");
    panel.className = "action-panel";
    panel.appendChild(actionButton("merge-next", ACTION_LABELS["merge-next"], () => submitExceptionAction("merge-next")));
    detail.appendChild(panel);
  }
  if (exception.allowedActions.includes("choose-roster")) appendRosterPanel(detail);
  if (exception.memberUnitIds && exception.memberUnitIds.length) {
    const surface = textElement("div", "Select this exception to load its local preview.", "preview-surface");
    surface.setAttribute("aria-label", "Selected exception preview");
    detail.appendChild(surface);
    detailControls["preview-surface"] = surface;
  }
}

function checkedParticipantHandles() {
  return Array.from(
    detailControls["assign-participants"].querySelectorAll("input:checked"),
    (input) => input.value
  );
}

function assignmentTarget() {
  const scope = detailControls["assign-scope"].value;
  const participantHandles = checkedParticipantHandles();
  if (scope === "individual" && participantHandles.length !== 1) {
    throw new Error("assignment-selection-invalid");
  }
  if (scope === "shared" && participantHandles.length < 2) {
    throw new Error("assignment-selection-invalid");
  }
  if (scope === "case" && participantHandles.length) {
    throw new Error("assignment-selection-invalid");
  }
  return { scope, participantHandles };
}

function batchValue(exception, action) {
  const control = detailControls["apply-to-similar"];
  return Boolean(
    control
    && control.checked
    && matchingExceptions(exception, action).length
  );
}

async function submitExceptionAction(action) {
  const exception = currentException();
  if (!exception || localReview.terminal) return;
  const exceptionId = exception.exceptionId;
  const focusIndex = localReview.review.exceptions.findIndex(
    (item) => item.exceptionId === exceptionId
  );
  const payload = { exceptionId, action, applyToSimilar: false };
  try {
    if (action === "accept-recommendation") {
      payload.applyToSimilar = batchValue(exception, action);
    } else if (action === "assign") {
      if (!detailControls["assign-role"].value) {
        throw new Error("assignment-selection-invalid");
      }
      payload.role = detailControls["assign-role"].value;
      payload.target = assignmentTarget();
      payload.applyToSimilar = batchValue(exception, action);
    } else if (action === "exclude") {
      payload.reason = detailControls["exclude-reason"].value;
      payload.applyToSimilar = batchValue(exception, action);
    } else if (action === "split") {
      payload.splitBeforeUnitId = detailControls["split-before-unit"].value;
    } else if (action === "choose-roster") {
      const rosterUnitId = detailControls["roster-candidate"].value;
      const candidate = (localReview.roster.candidateSummaries || []).find(
        (item) => item.rosterUnitId === rosterUnitId
      );
      if (!candidate || !candidate.eligible) {
        throw new Error("roster-selection-invalid");
      }
      payload.rosterUnitId = rosterUnitId;
    }
    const scopeCount = payload.applyToSimilar
      ? batchCountFor(exception, action)
      : 1;
    const next = await api("/api/exception", payload);
    applyState(next, {
      focusIndex,
      clearUndo: action === "choose-roster",
      lastResolvedExceptionId: action === "choose-roster" ? null : exceptionId,
    });
    byId("batch-announcement").textContent = scopeCount > 1
      ? `Applied the decision to ${scopeCount} exception clusters.`
      : "Applied the decision to one exception cluster.";
    showMessage("");
  } catch (_error) {
    showMessage("The decision could not be applied. Review state was unchanged.");
  }
}

async function loadPreview(unitId, surface, selectionKey) {
  releasePreviewObjectUrl();
  localReview.previewSelectionKey = selectionKey;
  clearNode(surface);
  surface.appendChild(textElement("p", "Loading local preview…"));
  try {
    const response = await fetch(`/api/preview?unitId=${encodeURIComponent(unitId)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("preview-unavailable");
    if (localReview.previewSelectionKey !== selectionKey) return;
    clearNode(surface);
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.startsWith("application/json")) {
      const preview = await response.json();
      if (localReview.previewSelectionKey !== selectionKey) return;
      const table = document.createElement("table");
      table.className = "preview-table";
      (preview.rows || []).forEach((row) => {
        const tableRow = document.createElement("tr");
        row.forEach((cell) => tableRow.appendChild(textElement("td", cell)));
        table.appendChild(tableRow);
      });
      surface.appendChild(table);
      return;
    }
    const blob = await response.blob();
    if (localReview.previewSelectionKey !== selectionKey) return;
    const objectUrl = URL.createObjectURL(blob);
    localReview.previewObjectUrl = objectUrl;
    const image = document.createElement("img");
    image.alt = "Local evidence preview";
    image.addEventListener("load", () => releasePreviewObjectUrl(objectUrl), { once: true });
    image.addEventListener("error", () => releasePreviewObjectUrl(objectUrl), { once: true });
    image.src = objectUrl;
    surface.appendChild(image);
  } catch (_error) {
    if (localReview.previewSelectionKey === selectionKey) {
      clearNode(surface);
      surface.appendChild(textElement("p", "Preview unavailable. The review state is unchanged."));
    }
  }
}

async function selectException(exceptionId) {
  const exception = localReview.review.exceptions.find(
    (item) => item.exceptionId === exceptionId
  );
  if (!exception || localReview.terminal) return;
  releasePreviewObjectUrl();
  byId("batch-announcement").textContent = "";
  localReview.activeExceptionId = exceptionId;
  renderExceptions();
  renderDetail();
  detailControls["exception-detail-heading"].focus();
  if (exception.memberUnitIds && exception.memberUnitIds.length) {
    await loadPreview(
      exception.memberUnitIds[0],
      detailControls["preview-surface"],
      `exception:${exceptionId}`
    );
  }
}

function renderOrganizedGroups() {
  const container = byId("organized-groups");
  clearNode(container);
  localReview.review.organizedGroups.forEach((group, index) => {
    const details = document.createElement("details");
    details.open = false;
    const summary = document.createElement("summary");
    const range = group.firstUnitIndex === group.lastUnitIndex
      ? `item ${group.firstUnitIndex}`
      : `items ${group.firstUnitIndex}–${group.lastUnitIndex}`;
    const effective = group.effectiveResolution || null;
    const role = effective && effective.action === "assign"
      ? effective.role
      : group.role;
    const target = effective && effective.action === "assign"
      ? effective.target
      : group.target;
    const decision = effective && effective.action === "exclude"
      ? `excluded · ${fixedLabel(effective.reason)}`
      : fixedLabel(role || "excluded duplicate");
    summary.textContent = `Group ${index + 1} · ${decision} · ${group.memberUnitIds.length} items`;
    details.appendChild(summary);
    const body = document.createElement("div");
    body.className = "group-body";
    const facts = document.createElement("dl");
    facts.className = "group-facts";
    appendDefinition(facts, "Source range", `Source ${numericLabel(group.evidenceId, "item")} · ${range}`);
    appendDefinition(facts, "Decision", decision);
    appendDefinition(facts, "Target", effective && effective.action === "exclude" ? "Excluded" : targetLabel(target));
    appendDefinition(facts, "State", fixedLabel(group.state));
    appendDefinition(facts, "Checks", group.checkCodes.length ? group.checkCodes.map(fixedLabel).join(", ") : "User review required");
    body.appendChild(facts);
    const actions = document.createElement("div");
    actions.className = "group-actions";
    if (group.memberUnitIds.length) {
      actions.appendChild(actionButton(
        "preview-group",
        "Preview first item",
        () => selectGroupPreview(group.groupId),
        "quiet"
      ));
    }
    if (group.state !== "exception") {
      const reopen = actionButton(
        "reopen-group",
        "Reopen for review",
        () => reopenGroup(group.groupId),
        "quiet"
      );
      reopen.setAttribute("data-group-id", group.groupId);
      actions.appendChild(reopen);
    }
    body.appendChild(actions);
    details.appendChild(body);
    container.appendChild(details);
  });
}

function renderGroupSectionContext() {
  const status = localReview.roster ? localReview.roster.status : "missing";
  if (status === "selected") {
    byId("organized-heading").textContent = "Automatically organized evidence";
    byId("organized-copy").textContent = "These groups need no individual decision. Open a group only when you want to inspect it.";
  } else if (status === "ambiguous") {
    byId("organized-heading").textContent = "Evidence awaiting roster";
    byId("organized-copy").textContent = "These groups are not automatically organized. Choose the authoritative roster to organize them safely.";
  } else {
    byId("organized-heading").textContent = "Evidence awaiting roster";
    byId("organized-copy").textContent = "These groups are not automatically organized. Correct or add the roster source, return draft, and relaunch to rerun organization.";
  }
}

async function selectGroupPreview(groupId) {
  const group = localReview.review.organizedGroups.find(
    (item) => item.groupId === groupId
  );
  if (!group || !group.memberUnitIds.length || localReview.terminal) return;
  releasePreviewObjectUrl();
  localReview.activeExceptionId = null;
  renderExceptions();
  const detail = byId("exception-detail");
  clearNode(detail);
  clearDetailControls();
  const effective = group.effectiveResolution || null;
  const role = effective && effective.action === "assign"
    ? effective.role
    : group.role;
  const target = effective && effective.action === "assign"
    ? effective.target
    : group.target;
  const decision = effective && effective.action === "exclude"
    ? `excluded · ${fixedLabel(effective.reason)}`
    : `${fixedLabel(role || "excluded duplicate")} · ${targetLabel(target)}`;
  detail.appendChild(textElement("h3", `Spot check group ${numericLabel(group.groupId, "item")}`));
  detail.appendChild(textElement("p", decision, "detail-meta"));
  const surface = textElement("div", "Loading local preview…", "preview-surface");
  surface.setAttribute("aria-label", "Organized evidence preview");
  detail.appendChild(surface);
  await loadPreview(group.memberUnitIds[0], surface, `group:${groupId}`);
}

async function reopenGroup(groupId) {
  if (localReview.terminal) return;
  const beforeIds = new Set(
    localReview.review.exceptions.map((item) => item.exceptionId)
  );
  try {
    const next = await api("/api/group/reopen", { groupId });
    const newIndex = next.review.exceptions.findIndex(
      (item) => !beforeIds.has(item.exceptionId)
    );
    applyState(next, { focusIndex: newIndex >= 0 ? newIndex : 0, clearUndo: true });
    showMessage("The group is back in the exception queue.");
  } catch (_error) {
    showMessage("The group could not be reopened. Review state was unchanged.");
  }
}

async function undoLastDecision() {
  const exceptionId = localReview.lastResolvedExceptionId;
  if (!exceptionId || localReview.terminal) return;
  try {
    const next = await api("/api/exception/undo", { exceptionId });
    localReview.lastResolvedExceptionId = null;
    const restoredIndex = next.review.exceptions.findIndex(
      (item) => item.exceptionId === exceptionId
    );
    applyState(next, { focusIndex: restoredIndex >= 0 ? restoredIndex : 0 });
    showMessage("The last exception decision was undone.");
  } catch (_error) {
    showMessage("The decision could not be undone. Review state was unchanged.");
  }
}

function renderCoverage() {
  const coverage = localReview.review.coverage;
  const summary = localReview.summary;
  const list = byId("coverage-summary");
  clearNode(list);
  appendDefinition(list, "Sources", summary.counts.sources);
  appendDefinition(list, "Atomic evidence items", summary.counts.units);
  appendDefinition(list, "Organized groups", coverage.groups);
  appendDefinition(list, "Automatically organized", coverage.automaticallyOrganizedUnits);
  appendDefinition(list, "Exception clusters", coverage.exceptionClusters);
  appendDefinition(list, "Evidence in exceptions", coverage.exceptionUnits);
  appendDefinition(list, "Unaccounted", coverage.unaccountedUnits);
  const effectiveFactsComplete = Array.isArray(localReview.review.resolvedExclusions)
    && localReview.review.organizedGroups.every(
      (group) => group.state !== "user-resolved" || Boolean(group.effectiveResolution)
    );
  const ready = effectiveFactsComplete
    && summary.readyToPrepare === true
    && localReview.review.exceptions.length === 0
    && coverage.unaccountedUnits === 0;
  byId("approve-button").disabled = !ready || localReview.terminal;
}

function renderResolvedExclusions() {
  const container = byId("resolved-exclusions");
  clearNode(container);
  const exclusions = localReview.review.resolvedExclusions || [];
  if (!exclusions.length) return;
  container.appendChild(textElement("h3", "Resolved source exclusions"));
  exclusions.forEach((item) => {
    const article = document.createElement("article");
    const facts = document.createElement("dl");
    facts.className = "exclusion-facts";
    appendDefinition(facts, "Source", `Source ${numericLabel(item.evidenceId, "item")}`);
    appendDefinition(facts, "Issue", fixedLabel(item.issueCode));
    appendDefinition(facts, "Decision", `Excluded · ${fixedLabel(item.reason)}`);
    article.appendChild(facts);
    container.appendChild(article);
  });
}

function renderUndo() {
  byId("undo-button").disabled = !localReview.lastResolvedExceptionId || localReview.terminal;
}

function renderAll() {
  renderTopStatus();
  renderExceptions();
  renderDetail();
  renderGroupSectionContext();
  renderOrganizedGroups();
  renderResolvedExclusions();
  renderCoverage();
  renderUndo();
}

async function terminal(route, body) {
  if (localReview.terminal) return;
  try {
    const result = await api(route, body);
    releasePreviewObjectUrl();
    localReview.terminal = true;
    showMessage(`Review finished: ${fixedLabel(result.outcome)}`);
    document.querySelectorAll("button, select, input").forEach((control) => {
      control.disabled = true;
    });
  } catch (_error) {
    showMessage("The terminal action could not be completed. Review remains open.");
  }
}

byId("undo-button").addEventListener("click", undoLastDecision);
byId("draft-button").addEventListener("click", () => terminal("/api/draft", {}));
byId("cancel-button").addEventListener("click", () => terminal("/api/cancel", {}));
byId("approve-button").addEventListener("click", () => terminal(
  "/api/approve",
  { expectedProposalDigest: localReview.summary.proposalDigest }
));
window.addEventListener("beforeunload", () => releasePreviewObjectUrl());

window.setInterval(() => {
  if (!localReview.terminal) api("/api/heartbeat", {}).catch(() => {});
}, 60000);

fetch("/api/state", { credentials: "same-origin" })
  .then(readJson)
  .then(applyState)
  .catch(() => showMessage("The local review state could not be loaded."));
"""
