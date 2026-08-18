from html.parser import HTMLParser
import subprocess

from ctv_proposal_review_ui import UI_CSS, UI_HTML, UI_JS


class _StructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.id_tags = {}
        self.inline_handlers = []
        self.remote_refs = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
            self.id_tags[values["id"]] = tag
        self.inline_handlers.extend(
            name for name, _value in attrs if name.startswith("on")
        )
        for attribute in ("src", "href", "action"):
            value = values.get(attribute, "")
            if value.startswith(("http://", "https://", "//")):
                self.remote_refs.append(value)


def _run_js(harness):
    result = subprocess.run(
        ["node", "-e", harness],
        input=UI_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_static_ui_is_exception_first_in_the_fixed_reading_order():
    parser = _StructureParser()
    parser.feed(UI_HTML)

    required = {
        "exception-workspace",
        "exception-heading",
        "exception-list",
        "exception-detail",
        "organized-evidence",
        "organized-heading",
        "organized-groups",
        "coverage-and-approval",
        "coverage-heading",
        "coverage-summary",
        "resolved-exclusions",
        "approve-button",
    }
    assert required <= set(parser.ids)
    assert parser.id_tags["organized-groups"] == "div"
    assert parser.id_tags["coverage-summary"] == "dl"
    assert parser.id_tags["approve-button"] == "button"
    assert parser.ids.index("exception-workspace") < parser.ids.index(
        "organized-evidence"
    ) < parser.ids.index("coverage-and-approval")
    assert 'id="approve-button"' in UI_HTML
    assert "Approve complete proposal" in UI_HTML
    assert 'id="unit-list"' not in UI_HTML
    assert "Current decisions" not in UI_HTML
    assert "participant-source-nav" not in UI_HTML
    assert "assignment-controls" not in UI_HTML


def test_static_ui_is_local_csp_safe_and_uses_accessible_native_controls():
    parser = _StructureParser()
    parser.feed(UI_HTML)
    combined = "\n".join((UI_HTML, UI_CSS, UI_JS))

    assert len(parser.ids) == len(set(parser.ids))
    assert parser.inline_handlers == []
    assert parser.remote_refs == []
    assert "eval(" not in UI_JS
    assert "new Function" not in UI_JS
    assert "innerHTML" not in UI_JS
    assert "outerHTML" not in UI_JS
    assert "insertAdjacentHTML" not in UI_JS
    assert "document.createElement" in UI_JS
    assert "textContent" in UI_JS
    assert 'aria-live="polite"' in UI_HTML
    assert 'role="status"' in UI_HTML
    assert "<details" not in UI_HTML  # group details are state-owned and dynamic
    assert "document.createElement(\"details\")" in UI_JS
    assert "addEventListener" in UI_JS
    assert "onclick" not in combined.lower()
    assert "onchange" not in combined.lower()
    assert "https://" not in combined
    assert "http://" not in combined
    assert "fetch(`/api/preview?unitId=" in UI_JS
    assert UI_JS.count("fetch(`/api/preview?unitId=") == 1
    assert "sourcePath" not in UI_JS
    assert "pageNumber" not in UI_JS
    assert "worksheetNumber" not in UI_JS
    assert "URL.createObjectURL" in UI_JS
    assert "URL.revokeObjectURL" in UI_JS
    assert "unitDecisions" not in UI_JS
    assert "PRIVATE-ROSTER-079123456789" not in combined


_DOM_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

let document;

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = String(tagName).toLowerCase();
    this.id = id;
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.attributes = {};
    this.textContent = "";
    this.className = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.open = false;
    this.type = "";
    this.src = "";
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    if (this.tagName === "select" && this.children.length === 1) {
      this.value = child.value;
    }
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }
  async trigger(type) {
    for (const listener of this.listeners[type] || []) {
      await listener({ type, target: this, preventDefault() {} });
    }
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "id") this.id = String(value);
    if (name === "class") this.className = String(value);
  }
  getAttribute(name) { return this.attributes[name] || null; }
  focus() { document.activeElement = this; }
  querySelectorAll(selector) {
    const nodes = [];
    const visit = (node) => {
      for (const child of node.children || []) {
        nodes.push(child);
        visit(child);
      }
    };
    visit(this);
    return nodes.filter((node) => matches(node, selector));
  }
}

function matches(node, selector) {
  return selector.split(",").some((raw) => {
    const item = raw.trim();
    if (item.startsWith(".")) {
      return node.className.split(/\s+/).includes(item.slice(1));
    }
    if (item === "input:checked") return node.tagName === "input" && node.checked;
    if (item === "input") return node.tagName === "input";
    if (item === "button" || item === "select" || item === "details") {
      return node.tagName === item;
    }
    const data = item.match(/^\[data-action="([^"]+)"\]$/);
    if (data) return node.getAttribute("data-action") === data[1];
    return false;
  });
}

const elementTypes = {
  "exception-heading": "h2",
  "exception-list": "div",
  "exception-detail": "section",
  "organized-heading": "h2",
  "organized-copy": "p",
  "organized-groups": "div",
  "coverage-heading": "h2",
  "coverage-summary": "dl",
  "resolved-exclusions": "div",
  "approve-button": "button",
  "progress-status": "span",
  "unresolved-status": "span",
  "batch-announcement": "div",
  "message": "div",
  "undo-button": "button",
  "draft-button": "button",
  "cancel-button": "button",
};
const elements = Object.fromEntries(
  Object.entries(elementTypes).map(([id, tag]) => [id, new FakeElement(tag, id)])
);
elements["approve-button"].disabled = true;
elements["undo-button"].disabled = true;

document = {
  activeElement: null,
  getElementById: (id) => elements[id] || null,
  createElement: (tagName) => new FakeElement(tagName),
  createTextNode: (value) => {
    const node = new FakeElement("#text");
    node.textContent = String(value);
    return node;
  },
  querySelectorAll: (selector) => Object.values(elements).flatMap((root) => {
    const values = [];
    if (matches(root, selector)) values.push(root);
    return values.concat(root.querySelectorAll(selector));
  }),
};

const window = { addEventListener: () => {}, setInterval: () => 0 };
const revoked = [];
let objectNumber = 0;
const URL = {
  createObjectURL: () => `blob:preview-${++objectNumber}`,
  revokeObjectURL: (value) => revoked.push(value),
};

function group(number, overrides = {}) {
  const digits = String(number).padStart(4, "0");
  return {
    groupId: `group-${digits}`,
    evidenceId: `evidence-${digits}`,
    unitKind: "pdf-page",
    memberUnitIds: [`unit-${digits}`],
    firstUnitIndex: 1,
    lastUnitIndex: 1,
    role: "service-contract",
    target: { scope: "individual", participantHandles: ["participant-0001"] },
    state: "automatically-organized",
    checkCodes: ["coverage-exact"],
    issueCodes: [],
    ...overrides,
  };
}

const groups = Array.from({ length: 25 }, (_unused, index) => group(index + 1));
groups[0] = group(1, {
  memberUnitIds: ["unit-0001", "unit-0002", "unit-0003"],
  firstUnitIndex: 1,
  lastUnitIndex: 3,
  state: "exception",
  issueCodes: ["role-uncertain"],
});
groups[1] = group(2, {
  memberUnitIds: ["unit-0004", "unit-0005"],
  firstUnitIndex: 1,
  lastUnitIndex: 2,
  state: "exception",
  issueCodes: ["role-uncertain"],
  target: { scope: "individual", participantHandles: ["participant-0002"] },
});

const firstException = {
  exceptionId: "exception-0001",
  kind: "unit-cluster",
  issueCode: "role-uncertain",
  recommendedAction: "assign",
  allowedActions: ["assign", "exclude", "split", "merge-next"],
  similarityKey: "similarity-same",
  groupIds: ["group-0001"],
  memberUnitIds: ["unit-0001", "unit-0002", "unit-0003"],
};
const similarException = {
  exceptionId: "exception-0002",
  kind: "unit-cluster",
  issueCode: "role-uncertain",
  recommendedAction: "assign",
  allowedActions: ["assign", "exclude", "split", "merge-next"],
  similarityKey: "similarity-same",
  groupIds: ["group-0002"],
  memberUnitIds: ["unit-0004", "unit-0005"],
};
const sourceException = {
  exceptionId: "exception-0003",
  kind: "source",
  issueCode: "source-unsupported",
  allowedActions: ["exclude"],
  similarityKey: "similarity-source",
  evidenceId: "evidence-0025",
};

function stateWith(exceptions, ready = false) {
  return {
    csrfToken: "csrf-token",
    participants: [
      { participantHandle: "participant-0001", name: "PRIVATE ALPHA", identityHint: "***-001" },
      { participantHandle: "participant-0002", name: "PRIVATE BETA", identityHint: "***-002" },
    ],
    roster: {
      status: "selected",
      rosterUnitId: "unit-0500",
      candidateUnitIds: ["unit-0500", "unit-0501"],
      candidateSummaries: [
        { rosterUnitId: "unit-0500", participantCount: 2, eligible: true, issueCodes: [] },
        { rosterUnitId: "unit-0501", participantCount: 2, eligible: true, issueCodes: [] },
      ],
      participantHandles: ["participant-0001", "participant-0002"],
      issueCodes: [],
    },
    review: {
      exceptions: structuredClone(exceptions),
      organizedGroups: structuredClone(groups),
      resolvedExclusions: [],
      coverage: {
        groups: 25,
        automaticallyOrganizedUnits: ready ? 536 : 531,
        exceptionClusters: exceptions.length,
        exceptionUnits: ready ? 0 : 5,
        unaccountedUnits: 0,
      },
      issueCodes: exceptions.map((item) => item.issueCode),
    },
    summary: {
      counts: {
        sources: 12,
        units: 536,
        participants: 2,
        accepted: ready ? 536 : 531,
        reassigned: 0,
        excluded: 0,
        unresolved: ready ? 0 : exceptions.length,
      },
      readyToPrepare: ready,
      proposalDigest: "a".repeat(64),
    },
  };
}

let currentState = stateWith([firstException, similarException, sourceException]);
let nextState = null;
const requests = [];
const previewRequests = [];

function response(payload, contentType = "application/json", ok = true) {
  return {
    ok,
    headers: { get: () => contentType },
    json: async () => structuredClone(payload),
    blob: async () => ({ kind: "preview-blob" }),
  };
}

async function fetch(route, options = {}) {
  if (route === "/api/state") return new Promise(() => {});
  if (route.startsWith("/api/preview?unitId=")) {
    previewRequests.push(route);
    return response({}, "image/png");
  }
  const payload = JSON.parse(options.body);
  requests.push({ route, payload });
  if (route === "/api/approve" || route === "/api/draft" || route === "/api/cancel") {
    return response({ version: "1.0", outcome: route.slice(5), readyToPrepare: false });
  }
  if (nextState) {
    currentState = structuredClone(nextState);
    nextState = null;
  }
  return response(currentState);
}

function descendants(root) {
  const result = [];
  const visit = (node) => {
    for (const child of node.children || []) {
      result.push(child);
      visit(child);
    }
  };
  visit(root);
  return result;
}

function withAction(action) {
  return descendants(elements["exception-detail"]).find(
    (node) => node.getAttribute("data-action") === action
  );
}

function withId(id) {
  return descendants(elements["exception-detail"]).find((node) => node.id === id);
}

const context = vm.createContext({
  document,
  window,
  URL,
  fetch,
  setInterval: () => 0,
  console,
});
vm.runInContext(fs.readFileSync(0, "utf8"), context);
context.__fixture = currentState;
context.__setFixture = (value) => { currentState = structuredClone(value); };
context.__setNext = (value) => { nextState = structuredClone(value); };
context.__stateWith = stateWith;
context.__first = firstException;
context.__similar = similarException;
context.__source = sourceException;
context.__groups = groups;
context.__elements = elements;
context.__withAction = withAction;
context.__withId = withId;
context.__requests = requests;
context.__previewRequests = previewRequests;
context.__revoked = revoked;
'''


def test_executable_dom_scales_by_exceptions_and_collapsed_groups():
    harness = _DOM_HARNESS + r'''
(async () => {
  await vm.runInContext(`(async () => { applyState(__fixture); })()`, context);
  const cards = elements["exception-list"].querySelectorAll(".exception-card");
  if (cards.length !== 3) throw new Error(`expected 3 exception cards, got ${cards.length}`);
  const details = elements["organized-groups"].querySelectorAll("details");
  if (details.length !== 25) throw new Error(`expected 25 group summaries, got ${details.length}`);
  if (details.some((item) => item.open)) throw new Error("organized evidence was not collapsed");
  if (details.some((item) => !item.children[0] || item.children[0].tagName !== "summary")) {
    throw new Error("organized evidence is not using native details and summary controls");
  }
  const reopenButtons = descendants(elements["organized-groups"]).filter(
    (node) => node.getAttribute("data-action") === "reopen-group"
  );
  if (reopenButtons.length !== 23) {
    throw new Error(`only automatic groups may reopen, got ${reopenButtons.length} controls`);
  }
  if (elements["exception-heading"].textContent !== "Review exceptions") {
    throw new Error(`wrong exception heading: ${elements["exception-heading"].textContent}`);
  }
  if (descendants(elements["exception-list"]).length >= 536) {
    throw new Error("atomic unit DOM list was rendered");
  }
  const text = descendants(elements["organized-groups"]).map((node) => node.textContent).join(" ");
  if (text.includes("unit-0536")) throw new Error("opaque atomic unit list leaked into summaries");
  if (!elements["approve-button"].disabled) throw new Error("approval enabled with exceptions");

  elements["batch-announcement"].textContent = "stale batch scope";
  const firstCard = cards[0];
  firstCard.focus();
  await firstCard.trigger("click");
  const detailHeading = descendants(elements["exception-detail"]).find(
    (node) => node.id === "exception-detail-heading"
  );
  if (!detailHeading || document.activeElement !== detailHeading || !detailHeading.parentNode) {
    throw new Error("selection did not focus the live replacement detail heading");
  }
  if (elements["batch-announcement"].textContent !== "") {
    throw new Error("selection did not clear stale batch scope text");
  }
  if (previewRequests.length !== 1 || !previewRequests[0].endsWith("unit-0001")) {
    throw new Error(`selection did not fetch one trusted preview: ${JSON.stringify(previewRequests)}`);
  }
  await vm.runInContext(`(async () => { await selectException("exception-0002"); })()`, context);
  if (previewRequests.length !== 2) throw new Error("second selection did not fetch exactly once");
  if (!revoked.includes("blob:preview-1")) throw new Error("prior object URL was not revoked");
  const image = descendants(elements["exception-detail"]).find((node) => node.tagName === "img");
  await image.trigger("error");
  if (!revoked.includes("blob:preview-2")) throw new Error("preview error did not revoke URL");
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_preserves_explicit_assignment_scope_selection():
    harness = _DOM_HARNESS + r'''
(async () => {
  await vm.runInContext(`(async () => {
    applyState(__fixture);
    await selectException("exception-0001");
  })()`, context);
  const role = withId("assign-role");
  const scope = withId("assign-scope");
  role.value = "service-contract";
  await role.trigger("change");
  scope.value = "case";
  await scope.trigger("change");
  if (scope.value !== "case") throw new Error("explicit whole-case scope was overwritten");
  const participants = descendants(elements["exception-detail"]).filter(
    (node) => node.getAttribute("data-participant-handle")
  );
  if (participants.some((input) => input.checked || !input.disabled)) {
    throw new Error("whole-case scope did not clear and disable participant choices");
  }
  await withAction("assign").trigger("click");
  const expected = {
    exceptionId: "exception-0001",
    action: "assign",
    role: "service-contract",
    target: { scope: "case", participantHandles: [] },
    applyToSimilar: false,
  };
  const actual = requests[0];
  const keys = (value) => Object.keys(value).sort().join(",");
  if (
    actual.route !== "/api/exception"
    || keys(actual.payload) !== keys(expected)
    || actual.payload.exceptionId !== expected.exceptionId
    || actual.payload.action !== expected.action
    || actual.payload.role !== expected.role
    || actual.payload.applyToSimilar !== false
    || JSON.stringify(actual.payload.target) !== JSON.stringify(expected.target)
  ) {
    throw new Error(`whole-case assignment payload was not exact: ${JSON.stringify(actual)}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_requires_an_explicit_role_when_recommendation_is_missing():
    harness = _DOM_HARNESS + r'''
(async () => {
  const unknownException = {
    exceptionId: "exception-0200", kind: "unit-cluster", issueCode: "role-uncertain",
    allowedActions: ["assign", "exclude", "split"], similarityKey: "similarity-unknown",
    groupIds: ["group-0001"], memberUnitIds: ["unit-0001", "unit-0002", "unit-0003"],
  };
  const unknownState = stateWith([unknownException]);
  unknownState.review.organizedGroups[0].role = "unknown";
  unknownState.review.organizedGroups[0].target = { scope: "case", participantHandles: [] };
  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(unknownState)});
    await selectException("exception-0200");
  })()`, context);
  const role = withId("assign-role");
  const scope = withId("assign-scope");
  const submit = withAction("assign");
  if (role.value !== "" || !submit.disabled) {
    throw new Error("unknown role invented a default assignment");
  }
  await submit.trigger("click");
  if (requests.length !== 0) throw new Error("empty role submitted an assignment request");

  role.value = "acceptance-record";
  await role.trigger("change");
  scope.value = "individual";
  await scope.trigger("change");
  const participants = descendants(elements["exception-detail"]).filter(
    (node) => node.getAttribute("data-participant-handle")
  );
  if (!submit.disabled) throw new Error("participant-free individual assignment was enabled");
  participants[1].checked = true;
  await participants[1].trigger("change");
  if (submit.disabled) throw new Error("complete explicit assignment stayed disabled");
  await submit.trigger("click");
  const actual = requests[0];
  if (
    actual.route !== "/api/exception"
    || actual.payload.role !== "acceptance-record"
    || actual.payload.target.scope !== "individual"
    || JSON.stringify(actual.payload.target.participantHandles) !== JSON.stringify(["participant-0002"])
  ) {
    throw new Error(`explicit assignment payload was not valid: ${JSON.stringify(actual)}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_renders_effective_approval_facts_and_source_exclusions():
    harness = _DOM_HARNESS + r'''
(async () => {
  const finalState = stateWith([], true);
  finalState.review.organizedGroups[0] = {
    ...finalState.review.organizedGroups[0],
    role: "unknown",
    target: { scope: "case", participantHandles: [] },
    state: "user-resolved",
    effectiveResolution: {
      action: "assign",
      role: "acceptance-record",
      target: { scope: "individual", participantHandles: ["participant-0002"] },
    },
  };
  finalState.review.resolvedExclusions = [{
    exceptionId: "exception-0300", kind: "source", evidenceId: "evidence-0025",
    issueCode: "source-unsupported", reason: "irrelevant",
  }];
  finalState.summary.counts.reassigned = 1;
  finalState.summary.counts.excluded = 1;
  await vm.runInContext(`(async () => { applyState(${JSON.stringify(finalState)}); })()`, context);

  const groupText = descendants(elements["organized-groups"])
    .map((node) => node.textContent).join(" ");
  const exclusionText = descendants(elements["resolved-exclusions"])
    .map((node) => node.textContent).join(" ");
  if (!groupText.includes("acceptance record") || !groupText.includes("PRIVATE BETA")) {
    throw new Error(`effective assignment was not rendered: ${groupText}`);
  }
  if (groupText.includes("Not assigned")) {
    throw new Error("original assignment was shown instead of the effective assignment");
  }
  if (
    !exclusionText.includes("Source 25")
    || !exclusionText.includes("source unsupported")
    || !exclusionText.includes("irrelevant")
  ) {
    throw new Error(`resolved source exclusion was not rendered: ${exclusionText}`);
  }
  if (elements["approve-button"].disabled) {
    throw new Error("approval stayed disabled after effective facts were visible");
  }
  const preview = descendants(elements["organized-groups"]).find(
    (node) => node.getAttribute("data-action") === "preview-group"
  );
  await preview.trigger("click");
  const detailText = descendants(elements["exception-detail"])
    .map((node) => node.textContent).join(" ");
  if (!detailText.includes("acceptance record") || !detailText.includes("PRIVATE BETA")) {
    throw new Error(`spot check reverted to original facts: ${detailText}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_roster_choice_requires_explicit_eligible_previewed_candidate():
    harness = _DOM_HARNESS + r'''
(async () => {
  const rosterException = {
    exceptionId: "exception-0100", kind: "roster", issueCode: "roster-ambiguous",
    recommendedAction: "choose-roster", allowedActions: ["choose-roster"],
    similarityKey: "similarity-roster",
  };
  const rosterState = stateWith([rosterException]);
  rosterState.roster.status = "ambiguous";
  rosterState.roster.rosterUnitId = null;
  rosterState.roster.candidateSummaries = [
    { rosterUnitId: "unit-0500", participantCount: 2, eligible: true, issueCodes: [] },
    { rosterUnitId: "unit-0501", participantCount: 0, eligible: false, issueCodes: ["roster-row-invalid"] },
  ];
  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(rosterState)});
    await selectException("exception-0100");
  })()`, context);
  const select = withId("roster-candidate");
  const submit = withAction("choose-roster");
  const optionText = descendants(select).map((node) => node.textContent).join(" ");
  if (select.value !== "" || !submit.disabled) {
    throw new Error("roster choice did not start at a disabled placeholder");
  }
  if (!optionText.includes("2 participants") || !optionText.includes("roster row invalid")) {
    throw new Error(`bounded candidate facts were not rendered: ${optionText}`);
  }
  select.value = "unit-0501";
  await select.trigger("change");
  if (!submit.disabled) throw new Error("ineligible roster candidate enabled submit");
  select.value = "unit-0500";
  await select.trigger("change");
  if (submit.disabled) throw new Error("eligible explicit roster candidate stayed disabled");
  if (previewRequests.length !== 1 || !previewRequests[0].endsWith("unit-0500")) {
    throw new Error(`eligible roster selection did not fetch one trusted preview: ${JSON.stringify(previewRequests)}`);
  }
  await submit.trigger("click");
  const request = requests[0];
  if (
    request.route !== "/api/exception"
    || JSON.stringify(request.payload) !== JSON.stringify({
      exceptionId: "exception-0100", action: "choose-roster",
      applyToSimilar: false, rosterUnitId: "unit-0500",
    })
  ) {
    throw new Error(`roster payload was not exact: ${JSON.stringify(request)}`);
  }
  if (!elements["undo-button"].disabled) {
    throw new Error("choose-roster exposed unsupported undo");
  }
  const beforeUndo = requests.length;
  await elements["undo-button"].trigger("click");
  if (requests.length !== beforeUndo) throw new Error("choose-roster issued an undo request");
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_missing_roster_requires_source_correction_and_draft():
    harness = _DOM_HARNESS + r'''
(async () => {
  const rosterException = {
    exceptionId: "exception-0100", kind: "roster", issueCode: "roster-missing",
    allowedActions: [], similarityKey: "similarity-roster-missing",
  };
  const missingState = stateWith([rosterException]);
  missingState.participants = [];
  missingState.roster = {
    status: "missing", rosterUnitId: null, candidateUnitIds: [],
    candidateSummaries: [], participantHandles: [], issueCodes: ["roster-missing"],
  };
  const memberIds = Array.from(
    { length: 536 },
    (_unused, index) => `unit-${String(index + 1).padStart(4, "0")}`
  );
  missingState.review.organizedGroups = Array.from({ length: 8 }, (_unused, index) => {
    const start = index * 67;
    const members = memberIds.slice(start, start + 67);
    return group(index + 1, {
      memberUnitIds: members,
      firstUnitIndex: start + 1,
      lastUnitIndex: start + members.length,
      role: "unknown",
      target: null,
      state: "exception",
      checkCodes: ["source-range-contiguous", "coverage-exact"],
      issueCodes: ["roster-missing"],
    });
  });
  missingState.review.coverage = {
    groups: 8, automaticallyOrganizedUnits: 0, exceptionClusters: 1,
    exceptionUnits: 536, unaccountedUnits: 0,
  };
  missingState.review.issueCodes = ["roster-missing"];
  missingState.summary.counts = {
    sources: 12, units: 536, participants: 0, accepted: 0,
    reassigned: 0, excluded: 0, unresolved: 536,
  };
  missingState.summary.readyToPrepare = false;

  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(missingState)});
    await selectException("exception-0100");
  })()`, context);

  const heading = elements["organized-heading"].textContent;
  const copy = elements["organized-copy"].textContent;
  const detailText = descendants(elements["exception-detail"])
    .map((node) => node.textContent).join(" ");
  const groupText = descendants(elements["organized-groups"])
    .map((node) => node.textContent).join(" ");
  if (heading !== "Evidence awaiting roster") {
    throw new Error(`missing roster heading was not blocked: ${heading}`);
  }
  if (
    !copy.includes("not automatically organized")
    || copy.includes("need no individual decision")
  ) {
    throw new Error(`missing roster group copy was not truthful: ${copy}`);
  }
  if (
    !detailText.includes("Correct or add the roster source")
    || !detailText.includes("Return draft")
    || !detailText.includes("relaunch")
    || detailText.includes("Choose one explicit action")
  ) {
    throw new Error(`missing roster recovery was not actionable: ${detailText}`);
  }
  if (withAction("choose-roster") || withAction("assign") || withAction("exclude")) {
    throw new Error("missing roster rendered action controls without an eligible action");
  }
  if (!groupText.includes("Unassigned — roster required") || groupText.includes("Whole case")) {
    throw new Error(`fallback target was misleading: ${groupText}`);
  }
  const details = elements["organized-groups"].querySelectorAll("details");
  if (details.length !== 8 || descendants(elements["organized-groups"]).length >= 536) {
    throw new Error("missing roster rendered atomic rows instead of bounded groups");
  }
  if (elements["draft-button"].disabled || !elements["approve-button"].disabled) {
    throw new Error("missing roster terminal controls were unsafe");
  }
  await elements["draft-button"].trigger("click");
  const terminalRequest = requests.at(-1);
  if (terminalRequest.route !== "/api/draft" || JSON.stringify(terminalRequest.payload) !== "{}") {
    throw new Error(`draft request was not preserved: ${JSON.stringify(terminalRequest)}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_serializes_only_state_permitted_action_fields():
    harness = _DOM_HARNESS + r'''
(async () => {
  await vm.runInContext(`(async () => {
    applyState(__fixture);
    await selectException("exception-0001");
  })()`, context);

  let similar = withId("apply-to-similar");
  if (!similar || similar.disabled || similar.checked) {
    throw new Error("permitted batch control did not start available and unchecked");
  }
  similar.checked = true;
  await similar.trigger("change");
  if (!elements["batch-announcement"].textContent.includes("2 exception")) {
    throw new Error("batch scope was not announced");
  }
  for (const action of ["accept-recommendation", "assign", "exclude", "split", "merge-next"]) {
    const control = withAction(action);
    if (!control || control.tagName !== "button" || control.type !== "button") {
      throw new Error(`${action} is not a native keyboard-activatable button`);
    }
  }
  await withAction("accept-recommendation").trigger("click");

  let role = withId("assign-role");
  let scope = withId("assign-scope");
  role.value = "acceptance-record";
  scope.value = "individual";
  await scope.trigger("change");
  const participants = descendants(elements["exception-detail"]).filter(
    (node) => node.getAttribute("data-participant-handle")
  );
  participants[0].checked = false;
  participants[1].checked = true;
  withId("apply-to-similar").checked = true;
  await withAction("assign").trigger("click");

  withId("exclude-reason").value = "irrelevant";
  withId("apply-to-similar").checked = true;
  await withAction("exclude").trigger("click");

  withId("split-before-unit").value = "unit-0002";
  await withAction("split").trigger("click");
  await withAction("merge-next").trigger("click");

  const noRecommendationState = stateWith([sourceException]);
  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(noRecommendationState)});
    await selectException("exception-0003");
  })()`, context);
  if (withAction("accept-recommendation") || !withAction("exclude")) {
    throw new Error("missing recommendation did not render only explicit alternatives");
  }

  const rosterException = {
    exceptionId: "exception-0100", kind: "roster", issueCode: "roster-ambiguous",
    recommendedAction: "choose-roster", allowedActions: ["choose-roster"],
    similarityKey: "similarity-roster",
  };
  const rosterState = stateWith([rosterException]);
  context.__setFixture(rosterState);
  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(rosterState)});
    await selectException("exception-0100");
  })()`, context);
  if (withId("apply-to-similar")) throw new Error("batch control exists for roster action");
  withId("roster-candidate").value = "unit-0501";
  await withId("roster-candidate").trigger("change");
  await withAction("choose-roster").trigger("click");

  const expected = [
    { route: "/api/exception", payload: {
      exceptionId: "exception-0001", action: "accept-recommendation", applyToSimilar: true,
    } },
    { route: "/api/exception", payload: {
      exceptionId: "exception-0001", action: "assign", role: "acceptance-record",
      target: { scope: "individual", participantHandles: ["participant-0002"] },
      applyToSimilar: true,
    } },
    { route: "/api/exception", payload: {
      exceptionId: "exception-0001", action: "exclude", reason: "irrelevant",
      applyToSimilar: true,
    } },
    { route: "/api/exception", payload: {
      exceptionId: "exception-0001", action: "split", splitBeforeUnitId: "unit-0002",
      applyToSimilar: false,
    } },
    { route: "/api/exception", payload: {
      exceptionId: "exception-0001", action: "merge-next", applyToSimilar: false,
    } },
    { route: "/api/exception", payload: {
      exceptionId: "exception-0100", action: "choose-roster", rosterUnitId: "unit-0501",
      applyToSimilar: false,
    } },
  ];
  const canonical = (value) => Array.isArray(value)
    ? value.map(canonical)
    : value && typeof value === "object"
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]))
      : value;
  if (JSON.stringify(canonical(requests)) !== JSON.stringify(canonical(expected))) {
    throw new Error(`unexpected exact payloads: ${JSON.stringify(requests)}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_reopen_clears_prior_server_undo_capability():
    harness = _DOM_HARNESS + r'''
(async () => {
  await vm.runInContext(`(async () => {
    applyState(__fixture);
    await selectException("exception-0001");
  })()`, context);
  await withAction("exclude").trigger("click");
  if (elements["undo-button"].disabled) throw new Error("resolvable exception did not enable undo");
  const reopen = descendants(elements["organized-groups"]).find(
    (node) => node.getAttribute("data-group-id") === "group-0003"
  );
  await reopen.trigger("click");
  if (!elements["undo-button"].disabled) throw new Error("reopen left a stale undo enabled");
  const beforeUndo = requests.length;
  await elements["undo-button"].trigger("click");
  if (requests.length !== beforeUndo) throw new Error("reopen allowed a stale undo network call");
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)


def test_executable_dom_undo_reopen_focus_readiness_and_terminal_cleanup():
    harness = _DOM_HARNESS + r'''
(async () => {
  await vm.runInContext(`(async () => {
    applyState(__fixture);
    await selectException("exception-0001");
  })()`, context);
  const afterFirst = stateWith([similarException, sourceException]);
  context.__setNext(afterFirst);
  await withAction("exclude").trigger("click");
  if (!revoked.includes("blob:preview-1")) throw new Error("state replacement did not revoke the active preview URL");
  const focusedCard = elements["exception-list"].querySelectorAll(".exception-card")[0];
  if (document.activeElement !== focusedCard) throw new Error("focus did not move to next exception");
  if (elements["undo-button"].disabled) throw new Error("undo was not enabled");
  await elements["undo-button"].trigger("click");

  const reopen = descendants(elements["organized-groups"]).find(
    (node) => node.getAttribute("data-group-id") === "group-0003"
  );
  await reopen.trigger("click");

  const lastState = stateWith([sourceException]);
  context.__setFixture(lastState);
  await vm.runInContext(`(async () => {
    applyState(${JSON.stringify(lastState)});
    await selectException("exception-0003");
  })()`, context);
  const ready = stateWith([], true);
  context.__setNext(ready);
  withId("exclude-reason").value = "intentionally-omitted";
  await withAction("exclude").trigger("click");
  if (elements["exception-heading"].textContent !== "Ready for approval") {
    throw new Error("zero-exception heading was not ready for approval");
  }
  if (document.activeElement !== elements["coverage-heading"]) {
    throw new Error("zero-exception focus did not move to coverage");
  }
  if (elements["approve-button"].disabled) throw new Error("ready approval stayed disabled");

  await vm.runInContext(`(async () => { await selectGroupPreview("group-0001"); })()`, context);
  await elements["approve-button"].trigger("click");
  if (!revoked.includes(`blob:preview-${objectNumber}`)) {
    throw new Error("terminal action did not revoke active preview URL");
  }

  const important = requests.filter((item) => [
    "/api/exception/undo", "/api/group/reopen", "/api/approve",
  ].includes(item.route));
  const expected = [
    { route: "/api/exception/undo", payload: { exceptionId: "exception-0001" } },
    { route: "/api/group/reopen", payload: { groupId: "group-0003" } },
    { route: "/api/approve", payload: { expectedProposalDigest: "a".repeat(64) } },
  ];
  if (JSON.stringify(important) !== JSON.stringify(expected)) {
    throw new Error(`unexpected undo/reopen/approve payloads: ${JSON.stringify(important)}`);
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    _run_js(harness)
