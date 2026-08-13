from html.parser import HTMLParser

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
