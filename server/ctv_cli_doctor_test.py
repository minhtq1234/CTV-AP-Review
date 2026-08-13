from types import SimpleNamespace

import pytest

from ctv_cli_doctor import run_doctor
from ctv_local_ocr import OcrCapability


class _CallableDependency:
    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return None


def _healthy_modules():
    pdf_open = _CallableDependency()
    load_workbook = _CallableDependency()
    model_validate = _CallableDependency()
    image_open = _CallableDependency()
    validate_package = _CallableDependency()
    base_model = type("BaseModel", (), {"model_validate": classmethod(model_validate)})
    return {
        "fitz": SimpleNamespace(open=pdf_open),
        "openpyxl": SimpleNamespace(load_workbook=load_workbook),
        "pydantic": SimpleNamespace(BaseModel=base_model),
        "PIL.Image": SimpleNamespace(open=image_open),
        "intake_package_validator": SimpleNamespace(
            VALIDATOR_VERSION="1.0.0",
            _SUPPORTS_SECURE_RELATIVE_OPEN=True,
            validate_package=validate_package,
        ),
    }, (pdf_open, load_workbook, model_validate, image_open, validate_package)


def _importer(modules):
    def import_module(name):
        try:
            return modules[name]
        except KeyError as error:
            raise ModuleNotFoundError(name) from error

    return import_module


def _run_doctor(modules, capability=OcrCapability(True, "vie")):
    return run_doctor(
        import_module=_importer(modules),
        local_ocr_probe=lambda: capability,
    )


def test_doctor_reports_ready_only_when_every_probe_passes_without_calling_parsers():
    modules, callables = _healthy_modules()

    result = _run_doctor(modules)

    assert result.ready is True
    assert result.validator_version == "1.0.0"
    assert result.issues == ()
    assert result.checked == (
        "fitz",
        "openpyxl",
        "pydantic",
        "Pillow",
        "intake-package-validator",
        "local-ocr",
    )
    assert result.local_ocr == OcrCapability(available=True, language="vie")
    assert [callable_.calls for callable_ in callables] == [0, 0, 0, 0, 0]


def test_missing_dependency_is_bounded_and_retryable_by_the_cli():
    modules, _ = _healthy_modules()
    del modules["fitz"]

    result = _run_doctor(modules)

    assert result.ready is False
    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-missing", "fitz")
    ]


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    [
        ("fitz", "open"),
        ("openpyxl", "load_workbook"),
        ("pydantic", "BaseModel"),
        ("PIL.Image", "open"),
        ("intake_package_validator", "VALIDATOR_VERSION"),
    ],
)
def test_missing_required_capability_is_incompatible(module_name, attribute):
    modules, _ = _healthy_modules()
    delattr(modules[module_name], attribute)

    result = _run_doctor(modules)

    expected_dependency = {
        "fitz": "fitz",
        "openpyxl": "openpyxl",
        "pydantic": "pydantic",
        "PIL.Image": "Pillow",
        "intake_package_validator": "intake-package-validator",
    }[module_name]
    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-incompatible", expected_dependency)
    ]


def test_missing_pydantic_model_validation_is_incompatible():
    modules, _ = _healthy_modules()
    delattr(modules["pydantic"].BaseModel, "model_validate")

    result = _run_doctor(modules)

    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-incompatible", "pydantic")
    ]


def test_missing_pillow_is_a_required_dependency_failure():
    modules, _ = _healthy_modules()
    del modules["PIL.Image"]

    result = _run_doctor(modules)

    assert result.ready is False
    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-missing", "Pillow")
    ]


def test_validator_import_failure_preserves_probe_order_without_exception_text():
    modules, _ = _healthy_modules()

    def importer(name):
        if name == "intake_package_validator":
            raise ImportError("private package failure details")
        return modules[name]

    result = run_doctor(
        import_module=importer,
        local_ocr_probe=lambda: OcrCapability(True, "vie"),
    )

    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-incompatible", "intake-package-validator")
    ]
    assert all("private package failure details" not in issue.code for issue in result.issues)
    assert all("private package failure details" not in issue.dependency for issue in result.issues)


def test_issue_order_follows_probe_order_not_importer_exception_text():
    modules, _ = _healthy_modules()

    def importer(name):
        if name == "fitz":
            raise ImportError("z-last-looking-text")
        if name == "openpyxl":
            raise ImportError("a-first-looking-text")
        return modules[name]

    result = run_doctor(
        import_module=importer,
        local_ocr_probe=lambda: OcrCapability(True, "vie"),
    )

    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-incompatible", "fitz"),
        ("dependency-incompatible", "openpyxl"),
    ]


@pytest.mark.parametrize("capability", [None, False])
def test_validator_requires_secure_relative_open_capability(capability):
    modules, _ = _healthy_modules()
    if capability is None:
        delattr(modules["intake_package_validator"], "_SUPPORTS_SECURE_RELATIVE_OPEN")
    else:
        modules["intake_package_validator"]._SUPPORTS_SECURE_RELATIVE_OPEN = capability

    result = _run_doctor(modules)

    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("secure-open-unavailable", "intake-package-validator")
    ]


def test_missing_local_ocr_is_optional_and_does_not_change_existing_readiness():
    modules, _ = _healthy_modules()

    result = _run_doctor(modules, OcrCapability(False, None))

    assert result.ready is True
    assert result.issues == ()
    assert result.local_ocr == OcrCapability(available=False, language=None)
    assert result.checked[-1] == "local-ocr"


def test_fixed_vie_capability_is_reported_without_runtime_details():
    modules, _ = _healthy_modules()
    private_path = "/private/operator/tesseract"
    private_version = "tesseract private build"
    private_languages = "eng vie secret"

    result = _run_doctor(modules, OcrCapability(True, "vie"))

    assert result.ready is True
    assert result.local_ocr.available is True
    assert result.local_ocr.language == "vie"
    serialized_shape = {
        "available": result.local_ocr.available,
        "language": result.local_ocr.language,
    }
    rendered = repr(result) + repr(serialized_shape)
    assert private_path not in rendered
    assert private_version not in rendered
    assert private_languages not in rendered
    assert not hasattr(result.local_ocr, "executable")
    assert not hasattr(result.local_ocr, "version")
    assert not hasattr(result.local_ocr, "languages")
