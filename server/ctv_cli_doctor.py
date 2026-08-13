"""Pure local dependency and secure-open capability probes for the CTV CLI."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import platform
from types import ModuleType
from typing import Callable

from ctv_local_ocr import OcrCapability, probe_local_ocr


DEPENDENCY_PROBES = (
    ("fitz", "fitz", ("open",)),
    ("openpyxl", "openpyxl", ("load_workbook",)),
    ("pydantic", "pydantic", ("BaseModel.model_validate",)),
    ("Pillow", "PIL.Image", ("open",)),
    ("intake-package-validator", "intake_package_validator", ("VALIDATOR_VERSION",)),
)


@dataclass(frozen=True)
class DoctorIssue:
    code: str
    dependency: str


@dataclass(frozen=True)
class DoctorResult:
    python_version: str
    validator_version: str | None
    checked: tuple[str, ...]
    issues: tuple[DoctorIssue, ...]
    local_ocr: OcrCapability

    @property
    def ready(self) -> bool:
        return not self.issues


def _required_attribute(module: ModuleType, dotted_name: str) -> object | None:
    value: object = module
    for name in dotted_name.split("."):
        try:
            value = getattr(value, name)
        except AttributeError:
            return None
    return value


def _has_required_capability(module: ModuleType, dotted_name: str) -> bool:
    value = _required_attribute(module, dotted_name)
    if value is None:
        return False
    if dotted_name in {"open", "load_workbook", "BaseModel.model_validate"}:
        return callable(value)
    return isinstance(value, str)


def run_doctor(
    import_module: Callable[[str], ModuleType] = importlib.import_module,
    local_ocr_probe: Callable[[], OcrCapability] = probe_local_ocr,
) -> DoctorResult:
    """Inspect local dependencies without parsing files or opening user paths."""
    issues: list[DoctorIssue] = []
    checked: list[str] = []
    validator_version: str | None = None

    for dependency, module_name, attributes in DEPENDENCY_PROBES:
        checked.append(dependency)
        try:
            module = import_module(module_name)
        except ModuleNotFoundError:
            issues.append(DoctorIssue("dependency-missing", dependency))
            continue
        except ImportError:
            issues.append(DoctorIssue("dependency-incompatible", dependency))
            continue

        if not all(_has_required_capability(module, attribute) for attribute in attributes):
            issues.append(DoctorIssue("dependency-incompatible", dependency))
            continue

        if dependency != "intake-package-validator":
            continue

        validator_version = _required_attribute(module, "VALIDATOR_VERSION")
        if getattr(module, "_SUPPORTS_SECURE_RELATIVE_OPEN", None) is not True:
            issues.append(DoctorIssue("secure-open-unavailable", dependency))

    checked.append("local-ocr")
    try:
        local_ocr = local_ocr_probe()
    except Exception:
        local_ocr = OcrCapability(False, None)

    return DoctorResult(
        python_version=platform.python_version(),
        validator_version=validator_version,
        checked=tuple(checked),
        issues=tuple(issues),
        local_ocr=local_ocr,
    )
