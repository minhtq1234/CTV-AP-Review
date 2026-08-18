"""Generated acceptance for the complete exception-first CTV package flow."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import http.client
from io import BytesIO
import json
from pathlib import Path
import stat
from urllib.parse import urlsplit

import fitz
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

from ctv_inspection_workbook import _canonical_package_workbook_bytes
from ctv_intake_cli import main as intake_main
from ctv_proposal_review import run_local_review
from intake_contract_v2 import MAX_PACKAGE_BYTES
from intake_package_validator import _PackageReader
from validate_intake_package import main as validate_main


_PERSON_ONE = "SYNTHETIC ALPHA"
_PERSON_TWO = "SYNTHETIC BRAVO"
_IDENTITY_ONE = "ALPHAID"
_IDENTITY_TWO = "BRAVOID"
_PRIVATE_MARKERS = (
    _PERSON_ONE,
    _PERSON_TWO,
    _IDENTITY_ONE,
    _IDENTITY_TWO,
    "SYNTHETIC-PRIVATE-TAX-ALPHA",
    "SYNTHETIC-PRIVATE-TAX-BRAVO",
    "SYNTHETIC-PRIVATE-BANK-ALPHA",
    "SYNTHETIC-PRIVATE-BANK-BRAVO",
)


def _workbook_bytes(rows: tuple[tuple[object, ...], ...]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Synthetic roster"
    for row in rows:
        worksheet.append(row)
    fixed = datetime(1980, 1, 1)
    workbook.properties.created = fixed
    workbook.properties.modified = fixed
    return _canonical_package_workbook_bytes(
        workbook,
        max_bytes=25 * 1024 * 1024,
    )


def _pdf_bytes(*pages: str) -> bytes:
    document = fitz.open()
    stream = BytesIO()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(
                fitz.Rect(72, 72, 520, 770),
                text,
                fontsize=12,
            )
        document.set_metadata({})
        fixed_id = "abcdef0123456789abcdef0123456789"
        document.xref_set_key(-1, "ID", f"[<{fixed_id}><{fixed_id}>]")
        document.save(stream, no_new_id=1)
        return stream.getvalue()
    finally:
        document.close()


def _identity_image_bytes() -> bytes:
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:  # Pillow versions before scalable default fonts.
        font = ImageFont.load_default()
    lines = (
        "CAN CUOC CONG DAN",
        "MAT TRUOC",
        _PERSON_ONE,
        _IDENTITY_ONE,
        "0" * 12,
    )
    for index, line in enumerate(lines):
        draw.text((100, 90 + index * 145), line, fill="black", font=font)
    stream = BytesIO()
    image.save(stream, format="PNG", compress_level=9, optimize=False)
    image.close()
    return stream.getvalue()


def _write_generated_source(source: Path) -> int:
    source.mkdir(mode=0o700)
    (source / "a-roster.xlsx").write_bytes(
        _workbook_bytes(
            (
                (
                    "name",
                    "identity",
                    "faCode",
                    "taxId",
                    "birthDate",
                    "bankAccount",
                    "serviceFee",
                    "product",
                    "So tien",
                ),
                (
                    _PERSON_ONE,
                    _IDENTITY_ONE,
                    "FA-SYNTHETIC-EXCEPTION",
                    "SYNTHETIC-PRIVATE-TAX-ALPHA",
                    "1990-01-01",
                    "SYNTHETIC-PRIVATE-BANK-ALPHA",
                    "100",
                    "Synthetic Product Alpha",
                    "100",
                ),
                (
                    _PERSON_TWO,
                    _IDENTITY_TWO,
                    "FA-SYNTHETIC-EXCEPTION",
                    "SYNTHETIC-PRIVATE-TAX-BRAVO",
                    "1990-01-02",
                    "SYNTHETIC-PRIVATE-BANK-BRAVO",
                    "200",
                    "Synthetic Product Bravo",
                    "200",
                ),
            )
        )
    )

    (source / "b-participants.pdf").write_bytes(
        _pdf_bytes(
            "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A BEN B CHU KY "
            f"{_PERSON_ONE} {_IDENTITY_ONE} NOI DUNG CHI TIET TRANG MOT",
            "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A BEN B CHU KY "
            f"{_PERSON_ONE} {_IDENTITY_ONE} NOI DUNG CHI TIET TRANG HAI",
            "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A BEN B CHU KY "
            f"{_PERSON_TWO} {_IDENTITY_TWO} NOI DUNG CHI TIET TRANG BA",
            "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A BEN B CHU KY "
            f"{_PERSON_TWO} {_IDENTITY_TWO} NOI DUNG CHI TIET TRANG BON",
        )
    )

    shared = _pdf_bytes(
        "HOP DONG DICH VU BEN A BEN B NOI DUNG DICH VU CHU KY "
        "NOI DUNG CHI TIET AP DUNG CHUNG CHO TOAN BO HO SO",
    )
    (source / "c-shared-contract.pdf").write_bytes(shared)
    (source / "d-shared-contract-copy.pdf").write_bytes(shared)

    (source / "e-ambiguous-pages.pdf").write_bytes(
        _pdf_bytes(
            "HOP DONG DICH VU BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU "
            "BEN A BEN B NOI DUNG DICH VU CHU KY AMBIGUOUS PAGE ONE",
            "HOP DONG DICH VU BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU "
            "BEN A BEN B NOI DUNG DICH VU CHU KY AMBIGUOUS PAGE TWO",
        )
    )
    (source / "f-identity.png").write_bytes(_identity_image_bytes())
    (source / "g-unsupported.bin").write_bytes(
        b"SYNTHETIC-UNSUPPORTED-PRIVATE-CONTENT"
    )
    return 10


def _filesystem_state(root: Path) -> tuple[tuple[object, ...], ...]:
    paths = (root, *sorted(root.rglob("*"), key=lambda item: item.as_posix()))
    entries = []
    for path in paths:
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        entries.append(
            (
                relative,
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_size,
                metadata.st_mtime_ns,
                sha256(path.read_bytes()).hexdigest()
                if stat.S_ISREG(metadata.st_mode)
                else None,
            )
        )
    return tuple(entries)


def _request(parsed, method, target, *, cookie=None, csrf=None, body=None):
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    headers = {}
    if cookie is not None:
        headers["Cookie"] = cookie
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    encoded = body
    if type(body) is dict:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://127.0.0.1:{parsed.port}"
    connection.request(method, target, body=encoded, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    result = response.status, response.getheaders(), payload
    connection.close()
    return result


def _json(payload: bytes) -> dict:
    result = json.loads(payload.decode("utf-8"))
    assert type(result) is dict
    return result


def _header(headers, name: str) -> str:
    values = [value for key, value in headers if key.lower() == name.lower()]
    assert len(values) == 1
    return values[0]


def _post(parsed, route: str, cookie: str, csrf: str, body: dict) -> dict:
    status, _headers, payload = _request(
        parsed,
        "POST",
        route,
        cookie=cookie,
        csrf=csrf,
        body=body,
    )
    assert status == 200, (route, status, payload)
    return _json(payload)


def _review_driver(
    output: Path,
    generated_unit_count: int,
    *,
    expect_empty_output: bool,
):
    def review(state):
        def drive(browser_url: str) -> bool:
            parsed = urlsplit(browser_url)
            assert (parsed.scheme, parsed.hostname, parsed.path) == (
                "http",
                "127.0.0.1",
                "/bootstrap",
            )
            status, headers, payload = _request(
                parsed,
                "GET",
                f"{parsed.path}?{parsed.query}",
            )
            assert status == 303
            assert payload == b""
            cookie = _header(headers, "Set-Cookie").split(";", 1)[0]

            status, _headers, html = _request(parsed, "GET", "/", cookie=cookie)
            assert status == 200
            assert b'id="exception-list"' in html
            assert b'id="organized-groups"' in html
            assert b'id="unit-list"' not in html

            status, _headers, payload = _request(
                parsed,
                "GET",
                "/api/state",
                cookie=cookie,
            )
            assert status == 200
            current = _json(payload)
            assert set(current) == {
                "csrfToken",
                "participants",
                "roster",
                "review",
                "summary",
            }
            assert set(current["review"]) == {
                "exceptions",
                "organizedGroups",
                "coverage",
                "issueCodes",
                "resolvedExclusions",
            }
            assert current["summary"]["counts"]["units"] == generated_unit_count
            assert current["roster"] == {
                "status": "selected",
                "rosterUnitId": "unit-0001",
                "candidateUnitIds": ["unit-0001"],
                "candidateSummaries": [
                    {
                        "rosterUnitId": "unit-0001",
                        "participantCount": 2,
                        "eligible": True,
                        "issueCodes": [],
                    }
                ],
                "participantHandles": ["participant-0001", "participant-0002"],
                "issueCodes": [],
            }
            assert current["review"]["coverage"] == {
                "groups": 7,
                "automaticallyOrganizedUnits": 8,
                "exceptionClusters": 2,
                "exceptionUnits": 2,
                "unaccountedUnits": 0,
            }
            assert current["review"]["issueCodes"] == [
                "source-unsupported",
                "unit-issue-present",
            ]
            assert current["review"]["exceptions"] == [
                {
                    "exceptionId": "exception-0001",
                    "kind": "unit-cluster",
                    "issueCode": "unit-issue-present",
                    "allowedActions": ["assign", "exclude"],
                    "similarityKey": current["review"]["exceptions"][0][
                        "similarityKey"
                    ],
                    "groupIds": ["group-0005"],
                    "memberUnitIds": ["unit-0008", "unit-0009"],
                },
                {
                    "exceptionId": "exception-0002",
                    "kind": "source",
                    "issueCode": "source-unsupported",
                    "recommendedAction": "exclude",
                    "allowedActions": ["exclude"],
                    "similarityKey": current["review"]["exceptions"][1][
                        "similarityKey"
                    ],
                    "evidenceId": "evidence-0007",
                },
            ]
            assert [
                {
                    key: group[key]
                    for key in (
                        "groupId",
                        "evidenceId",
                        "unitKind",
                        "memberUnitIds",
                        "firstUnitIndex",
                        "lastUnitIndex",
                        "role",
                        "target",
                        "state",
                        "issueCodes",
                    )
                }
                for group in current["review"]["organizedGroups"]
            ] == [
                {
                    "groupId": "group-0001",
                    "evidenceId": "evidence-0001",
                    "unitKind": "worksheet",
                    "memberUnitIds": ["unit-0001"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 1,
                    "role": "payment-roster",
                    "target": {"scope": "case", "participantHandles": []},
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
                {
                    "groupId": "group-0002",
                    "evidenceId": "evidence-0002",
                    "unitKind": "pdf-page",
                    "memberUnitIds": ["unit-0002", "unit-0003"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 2,
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0001"],
                    },
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
                {
                    "groupId": "group-0003",
                    "evidenceId": "evidence-0002",
                    "unitKind": "pdf-page",
                    "memberUnitIds": ["unit-0004", "unit-0005"],
                    "firstUnitIndex": 3,
                    "lastUnitIndex": 4,
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0002"],
                    },
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
                {
                    "groupId": "group-0004",
                    "evidenceId": "evidence-0003",
                    "unitKind": "pdf-page",
                    "memberUnitIds": ["unit-0006"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 1,
                    "role": "service-contract",
                    "target": {"scope": "case", "participantHandles": []},
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
                {
                    "groupId": "group-0007",
                    "evidenceId": "evidence-0004",
                    "unitKind": "pdf-page",
                    "memberUnitIds": ["unit-0007"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 1,
                    "role": "",
                    "target": {"scope": "case", "participantHandles": []},
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
                {
                    "groupId": "group-0005",
                    "evidenceId": "evidence-0005",
                    "unitKind": "pdf-page",
                    "memberUnitIds": ["unit-0008", "unit-0009"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 2,
                    "role": "unknown",
                    "target": {"scope": "case", "participantHandles": []},
                    "state": "exception",
                    "issueCodes": ["unit-issue-present"],
                },
                {
                    "groupId": "group-0006",
                    "evidenceId": "evidence-0006",
                    "unitKind": "image",
                    "memberUnitIds": ["unit-0010"],
                    "firstUnitIndex": 1,
                    "lastUnitIndex": 1,
                    "role": "identity-front",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0001"],
                    },
                    "state": "automatically-organized",
                    "issueCodes": [],
                },
            ]
            assert "unitDecisions" not in current["review"]
            assert "units" not in current
            if expect_empty_output:
                assert not any(output.iterdir())

            csrf = current["csrfToken"]
            initial_exception_ids = {
                item["exceptionId"] for item in current["review"]["exceptions"]
            }
            assert len(initial_exception_ids) == 2
            for exception in tuple(current["review"]["exceptions"]):
                if exception["kind"] == "source":
                    request = {
                        "exceptionId": exception["exceptionId"],
                        "action": "exclude",
                        "reason": "irrelevant",
                        "applyToSimilar": False,
                    }
                else:
                    assert len(exception["groupIds"]) == 1
                    affected_group = next(
                        group
                        for group in current["review"]["organizedGroups"]
                        if group["groupId"] == exception["groupIds"][0]
                    )
                    assert affected_group["unitKind"] == "pdf-page"
                    assert (
                        affected_group["lastUnitIndex"]
                        - affected_group["firstUnitIndex"]
                    ) == 1
                    request = {
                        "exceptionId": exception["exceptionId"],
                        "action": "assign",
                        "role": "acceptance-record",
                        "target": {
                            "scope": "individual",
                            "participantHandles": ["participant-0002"],
                        },
                        "applyToSimilar": False,
                    }
                current = _post(
                    parsed,
                    "/api/exception",
                    cookie,
                    csrf,
                    request,
                )

            assert current["review"]["exceptions"] == []
            assert current["review"]["coverage"]["exceptionClusters"] == 0
            assert current["review"]["coverage"]["unaccountedUnits"] == 0
            resolved_group = next(
                group
                for group in current["review"]["organizedGroups"]
                if group["groupId"] == "group-0005"
            )
            assert resolved_group["effectiveResolution"] == {
                "action": "assign",
                "role": "acceptance-record",
                "target": {
                    "scope": "individual",
                    "participantHandles": ["participant-0002"],
                },
            }
            assert current["review"]["resolvedExclusions"] == [
                {
                    "exceptionId": "exception-0002",
                    "kind": "source",
                    "evidenceId": "evidence-0007",
                    "issueCode": "source-unsupported",
                    "reason": "irrelevant",
                }
            ]
            if expect_empty_output:
                assert not any(output.iterdir())

            status, _headers, payload = _request(
                parsed,
                "GET",
                "/api/state",
                cookie=cookie,
            )
            assert status == 200
            refreshed = _json(payload)
            assert refreshed["review"] == current["review"]
            assert refreshed["review"]["exceptions"] == []
            assert any(
                group.get("effectiveResolution", {}).get("role")
                == "acceptance-record"
                for group in refreshed["review"]["organizedGroups"]
            )
            assert len(refreshed["review"]["resolvedExclusions"]) == 1

            summary = _post(parsed, "/api/summary", cookie, csrf, {})
            assert summary["readyToPrepare"] is True
            assert summary["counts"] == {
                "sources": 7,
                "units": 10,
                "participants": 2,
                "accepted": 7,
                "reassigned": 2,
                "excluded": 2,
                "unresolved": 0,
            }
            approved = _post(
                parsed,
                "/api/approve",
                cookie,
                csrf,
                {"expectedProposalDigest": summary["proposalDigest"]},
            )
            assert approved["outcome"] == "approved"
            assert approved["counts"] == summary["counts"]
            assert approved["participantHandles"] == [
                "participant-0001",
                "participant-0002",
            ]
            assert approved["issueCodes"] == [
                "source-unsupported",
                "unit-issue-present",
            ]
            assert [
                {
                    key: item[key]
                    for key in item
                    if key != "unitId"
                }
                | {"unitId": item["unitId"]}
                for item in approved["unitAssignments"]
            ] == [
                {
                    "unitId": "unit-0001",
                    "decision": "accepted",
                    "role": "payment-roster",
                    "target": {"scope": "case", "participantHandles": []},
                },
                {
                    "unitId": "unit-0002",
                    "decision": "accepted",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0001"],
                    },
                },
                {
                    "unitId": "unit-0003",
                    "decision": "accepted",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0001"],
                    },
                },
                {
                    "unitId": "unit-0004",
                    "decision": "accepted",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0002"],
                    },
                },
                {
                    "unitId": "unit-0005",
                    "decision": "accepted",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0002"],
                    },
                },
                {
                    "unitId": "unit-0006",
                    "decision": "accepted",
                    "role": "service-contract",
                    "target": {"scope": "case", "participantHandles": []},
                },
                {
                    "unitId": "unit-0007",
                    "decision": "excluded",
                    "reason": "duplicate",
                },
                {
                    "unitId": "unit-0008",
                    "decision": "reassigned",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0002"],
                    },
                },
                {
                    "unitId": "unit-0009",
                    "decision": "reassigned",
                    "role": "acceptance-record",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0002"],
                    },
                },
                {
                    "unitId": "unit-0010",
                    "decision": "accepted",
                    "role": "identity-front",
                    "target": {
                        "scope": "individual",
                        "participantHandles": ["participant-0001"],
                    },
                },
            ]
            assert approved["sourceDispositions"] == [
                {
                    "evidenceId": "evidence-0007",
                    "decision": "excluded",
                    "reason": "irrelevant",
                }
            ]
            return True

        return run_local_review(state, browser_open=drive)

    return review


def _published_tree_sha256(package: Path) -> str:
    paths = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    reader, failure = _PackageReader.open(package)
    assert reader is not None and failure is None
    try:
        tree, failure = reader.snapshot_tree(
            paths,
            max_bytes_by_path={path: 256 * 1024 * 1024 for path in paths},
            max_total_bytes=MAX_PACKAGE_BYTES,
        )
        assert tree is not None and failure is None
        return tree.tree_sha256
    finally:
        reader.close()


def test_generated_exception_first_cli_http_writer_validator_and_collision(
    tmp_path,
    capsys,
):
    source = tmp_path / "source"
    output = tmp_path / "output"
    generated_unit_count = _write_generated_source(source)
    output.mkdir(mode=0o700)
    source_before = _filesystem_state(source)

    argv = [
        "package",
        "prepare",
        "--source-root",
        str(source),
        "--output-root",
        str(output),
        "--json",
    ]
    driver = _review_driver(
        output,
        generated_unit_count,
        expect_empty_output=True,
    )
    assert intake_main(argv, package_review_driver=driver) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    envelope = json.loads(captured.out)
    assert envelope["status"] == "succeeded"
    assert envelope["result"]["outcome"] == "prepared"
    assert envelope["result"]["validation"]["outcome"] == "valid"
    assert envelope["result"]["counts"]["assignments"] == 9
    assert envelope["result"]["counts"]["exclusions"] == 2
    assert _filesystem_state(source) == source_before
    for private in (*_PRIVATE_MARKERS, str(source), str(output)):
        assert private not in captured.out

    package = output / envelope["result"]["packageDirectoryName"]
    assert package.is_dir()
    manifest = json.loads((package / "case-manifest.json").read_bytes())
    assignments_bytes = (package / "assignments.json").read_bytes()
    assignments = json.loads(assignments_bytes)
    artifacts = {
        item["artifactId"]: item for item in manifest["artifacts"]
    }
    assert [
        item["participantHandle"] for item in assignments["participants"]
    ] == ["participant-0001", "participant-0002"]
    assert len(
        {item["rosterRowId"] for item in assignments["participants"]}
    ) == 2

    def assignment_semantics(item):
        locator = dict(item["outputLocator"])
        artifact = artifacts[locator.pop("artifactId")]
        locator["artifactPath"] = artifact["path"]
        return {
            key: item[key]
            for key in (
                "unitId",
                "sourceUnitIndex",
                "unitKind",
                "decision",
                "role",
                "target",
            )
        } | {"outputLocator": locator}

    assert [assignment_semantics(item) for item in assignments["units"]] == [
        {
            "unitId": "unit-0001",
            "sourceUnitIndex": 1,
            "unitKind": "worksheet",
            "decision": "accepted",
            "role": "payment-roster",
            "target": {"scope": "case", "participantHandles": []},
            "outputLocator": {
                "kind": "roster",
                "worksheetIndex": 1,
                "artifactPath": "roster.xlsx",
            },
        },
        {
            "unitId": "unit-0002",
            "sourceUnitIndex": 1,
            "unitKind": "pdf-page",
            "decision": "accepted",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0001"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 2,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0003",
            "sourceUnitIndex": 2,
            "unitKind": "pdf-page",
            "decision": "accepted",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0001"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 3,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0004",
            "sourceUnitIndex": 3,
            "unitKind": "pdf-page",
            "decision": "accepted",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0002"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 4,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0005",
            "sourceUnitIndex": 4,
            "unitKind": "pdf-page",
            "decision": "accepted",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0002"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 5,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0006",
            "sourceUnitIndex": 1,
            "unitKind": "pdf-page",
            "decision": "accepted",
            "role": "service-contract",
            "target": {"scope": "case", "participantHandles": []},
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 1,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0008",
            "sourceUnitIndex": 1,
            "unitKind": "pdf-page",
            "decision": "reassigned",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0002"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 6,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0009",
            "sourceUnitIndex": 2,
            "unitKind": "pdf-page",
            "decision": "reassigned",
            "role": "acceptance-record",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0002"],
            },
            "outputLocator": {
                "kind": "pdf-page",
                "targetPage": 7,
                "artifactPath": "input.pdf",
            },
        },
        {
            "unitId": "unit-0010",
            "sourceUnitIndex": 1,
            "unitKind": "image",
            "decision": "accepted",
            "role": "identity-front",
            "target": {
                "scope": "individual",
                "participantHandles": ["participant-0001"],
            },
            "outputLocator": {
                "kind": "image",
                "artifactPath": "evidence/evidence-0001.png",
            },
        },
    ]
    assert [
        {
            "recordType": item["recordType"],
            "recordId": item["recordId"] if item["recordType"] == "unit" else None,
            "reason": item["reason"],
            "decisionType": next(
                decision["type"]
                for decision in manifest["decisions"]
                if decision["decisionId"] == item["decisionId"]
            ),
        }
        for item in assignments["exclusions"]
    ] == [
        {
            "recordType": "unit",
            "recordId": "unit-0007",
            "reason": "excluded-by-user",
            "decisionType": "exclude-unit",
        },
        {
            "recordType": "source",
            "recordId": None,
            "reason": "unsupported",
            "decisionType": "exclude-source",
        },
    ]
    for private in (*_PRIVATE_MARKERS, str(source), str(output)):
        assert private.encode("utf-8") not in assignments_bytes
    assert _published_tree_sha256(package) == envelope["result"][
        "publishedTreeSha256"
    ]

    assert validate_main([str(package), "--source-root", str(source)]) == 0
    validation_capture = capsys.readouterr()
    assert validation_capture.err == ""
    validation = json.loads(validation_capture.out)
    assert validation["outcome"] == "valid"
    assert validation["errors"] == []
    for private in (*_PRIVATE_MARKERS, str(source), str(output)):
        assert private not in validation_capture.out

    output_before_collision = _filesystem_state(output)
    collision_driver = _review_driver(
        output,
        generated_unit_count,
        expect_empty_output=False,
    )
    assert intake_main(argv, package_review_driver=collision_driver) == 2
    collision_capture = capsys.readouterr()
    assert collision_capture.err == ""
    collision = json.loads(collision_capture.out)
    assert collision["status"] == "failed"
    assert [item["code"] for item in collision["errors"]] == [
        "package-output-collision"
    ]
    assert _filesystem_state(output) == output_before_collision
    assert _filesystem_state(source) == source_before
    assert not list(output.glob(".ctv-staging-*"))
