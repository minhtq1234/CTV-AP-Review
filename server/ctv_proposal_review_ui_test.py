from html.parser import HTMLParser
import subprocess

from ctv_proposal_review_ui import UI_CSS, UI_HTML, UI_JS


class _StructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.inline_handlers = []
        self.remote_refs = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        self.inline_handlers.extend(name for name, _value in attrs if name.startswith("on"))
        for attribute in ("src", "href", "action"):
            value = values.get(attribute, "")
            if value.startswith(("http://", "https://", "//")):
                self.remote_refs.append(value)


def test_static_ui_uses_selected_c_layout_and_complete_review_controls():
    parser = _StructureParser()
    parser.feed(UI_HTML)

    assert {
        "participant-source-nav",
        "document-preview",
        "assignment-controls",
        "progress-status",
        "unresolved-status",
        "roster-options",
        "participant-options",
        "decision-control",
        "role-control",
        "scope-control",
        "draft-button",
        "cancel-button",
        "summary-button",
        "proposal-digest",
        "decision-records",
        "issue-list",
        "approve-button",
    } <= parser.ids
    assert 'id="approve-button" type="button" disabled' in UI_HTML
    assert "grid-template-columns" in UI_CSS
    assert "participant-source-nav" in UI_CSS
    assert "document-preview" in UI_CSS
    assert "assignment-controls" in UI_CSS


def test_static_ui_is_self_contained_and_builds_private_data_with_text_content():
    combined = "\n".join((UI_HTML, UI_CSS, UI_JS))
    parser = _StructureParser()
    parser.feed(UI_HTML)

    assert parser.inline_handlers == []
    assert parser.remote_refs == []
    assert "eval(" not in UI_JS
    assert "new Function" not in UI_JS
    assert "innerHTML" not in UI_JS
    assert "outerHTML" not in UI_JS
    assert "textContent" in UI_JS
    assert "document.createElement" in UI_JS
    assert "fetch(" in UI_JS
    assert "X-CSRF-Token" in UI_JS
    assert "allowedDecisions" in UI_JS
    assert "allowedRoles" in UI_JS
    assert "restoreActiveControls" in UI_JS
    assert "renderDecisionSummary" in UI_JS
    assert "URL.createObjectURL" in UI_JS
    assert "URL.revokeObjectURL" in UI_JS
    assert UI_JS.count("fetch(`/api/preview?unitId=") == 1
    assert "image.src = `/api/preview" not in UI_JS
    assert "PRIVATE-ROSTER-079123456789" not in combined
    assert "https://" not in combined
    assert "http://" not in combined


def test_active_unit_and_source_enable_decision_and_apply():
    harness = r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName;
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = id === "decision-control" || id === "role-control" || id === "approve-button";
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) {
    this.children.push(child);
    if (this.tagName === "select" && this.children.length === 1) this.value = child.value;
    return child;
  }
  removeChild(child) {
    this.children.splice(this.children.indexOf(child), 1);
    return child;
  }
  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }
  dispatchEvent(event) {
    (this.listeners[event.type] || []).forEach((listener) => listener(event));
  }
  setAttribute(name, value) { this[name] = value; }
  querySelectorAll(selector) {
    const descendants = [];
    const visit = (node) => {
      (node.children || []).forEach((child) => {
        descendants.push(child);
        visit(child);
      });
    };
    visit(this);
    if (selector === "input") return descendants.filter((node) => node.tagName === "input");
    if (selector === "input:checked") return descendants.filter((node) => node.tagName === "input" && node.checked);
    return [];
  }
}

const ids = [
  "roster-options", "participant-list", "unit-list", "source-list",
  "participant-options", "decision-control", "role-control", "scope-control",
  "reason-control", "apply-button", "active-unit-title", "preview-title",
  "preview-content", "decision-records", "issue-list", "summary-counts",
  "proposal-digest", "approve-button", "progress-status", "unresolved-status",
  "message", "summary-button", "draft-button", "cancel-button",
];
const selectIds = new Set(["decision-control", "role-control", "scope-control", "reason-control"]);
const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(selectIds.has(id) ? "select" : "div", id)]));
elements["scope-control"].value = "individual";
elements["reason-control"].value = "irrelevant";

const document = {
  getElementById: (id) => elements[id],
  createElement: (tagName) => new FakeElement(tagName),
  createTextNode: (value) => ({ textContent: String(value), children: [] }),
  querySelectorAll: () => [],
};
const window = { addEventListener: () => {}, setInterval: () => 0 };
const URL = { createObjectURL: () => "blob:preview", revokeObjectURL: () => {} };
const applied = [];
let state = {
  csrfToken: "csrf-token",
  units: [{
    unitId: "unit-0001", evidenceId: "evidence-0001", unitKind: "pdf-page",
    suggestedRole: "service-contract", issueCodes: [],
  }],
  sources: [
    { evidenceId: "evidence-0001", issueCodes: [] },
    { evidenceId: "evidence-0002", issueCodes: ["source-unreadable"] },
  ],
  participants: [],
  review: {
    unitDecisions: [{
      unitId: "unit-0001", evidenceId: "evidence-0001", unitKind: "pdf-page",
      suggestedRole: "service-contract", issueCodes: [],
      allowedDecisions: ["accepted", "reassigned", "excluded", "unresolved"],
      allowedRoles: ["service-contract", "other-supporting-evidence"],
      decision: { decision: "unresolved" },
    }],
    sourceDispositions: [{
      evidenceId: "evidence-0002", issueCodes: ["source-unreadable"],
      allowedDecisions: ["excluded", "unresolved"], allowedRoles: [],
      decision: { decision: "unresolved" },
    }],
    issueCodes: ["source-unreadable"],
  },
  summary: {
    counts: { units: 1, accepted: 0, reassigned: 0, excluded: 0, unresolved: 2 },
    readyToPrepare: false, proposalDigest: "0".repeat(64),
  },
};

const response = (payload, contentType = "application/json") => ({
  ok: true,
  headers: { get: () => contentType },
  json: async () => structuredClone(payload),
});
async function fetch(route, options = {}) {
  if (route === "/api/state") return new Promise(() => {});
  if (route.startsWith("/api/preview?")) return response({ rows: [] });
  if (route === "/api/unit" || route === "/api/source") {
    const payload = JSON.parse(options.body);
    applied.push({ route, payload });
    const records = route === "/api/unit" ? state.review.unitDecisions : state.review.sourceDispositions;
    const key = route === "/api/unit" ? "unitId" : "evidenceId";
    const record = records.find((item) => item[key] === payload[key]);
    record.decision = payload.decision === "excluded"
      ? { decision: "excluded", reason: payload.reason }
      : { decision: payload.decision };
    return response(state);
  }
  throw new Error(`unexpected fetch: ${route}`);
}

const context = vm.createContext({ document, window, URL, fetch, setInterval: () => 0, console });
vm.runInContext(fs.readFileSync(0, "utf8"), context);
context.__state = state;

(async () => {
  await vm.runInContext(`(async () => {
    applyState(__state);
    await selectUnit(__state.units[0]);
    if (byId("decision-control").disabled) throw new Error("active unit decision stayed disabled");
    byId("decision-control").value = "excluded";
    byId("decision-control").dispatchEvent({ type: "change" });
    await applyDecision();

    selectSource(__state.sources[1]);
    if (byId("decision-control").disabled) throw new Error("active source decision stayed disabled");
    byId("decision-control").value = "excluded";
    byId("decision-control").dispatchEvent({ type: "change" });
    await applyDecision();
  })()`, context);
  const expected = [
    { route: "/api/unit", payload: { unitId: "unit-0001", decision: "excluded", reason: "irrelevant" } },
    { route: "/api/source", payload: { evidenceId: "evidence-0002", decision: "excluded", reason: "irrelevant" } },
  ];
  if (JSON.stringify(applied) !== JSON.stringify(expected)) {
    throw new Error(`unexpected applied payloads: ${JSON.stringify(applied)}`);
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
'''
    result = subprocess.run(
        ["node", "-e", harness],
        input=UI_JS,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
