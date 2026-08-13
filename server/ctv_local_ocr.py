"""Bounded direct-stdin access to an optional local Tesseract runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import selectors
import shutil
import subprocess
import threading
import time
from typing import Callable, Literal, Protocol, Sequence


MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_TSV_BYTES = 4 * 1024 * 1024
MAX_PROBE_BYTES = 64 * 1024
MAX_OCR_UNITS = 500
MAX_TOTAL_SECONDS = 1800
DEFAULT_OCR_TIMEOUT_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 5
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SAFE_ENV = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}

ProcessStatus = Literal["succeeded", "timeout", "failed", "over-limit"]
OcrStatus = Literal[
    "succeeded",
    "unavailable",
    "timeout",
    "failed",
    "low-confidence",
    "over-limit",
]


@dataclass(frozen=True)
class OcrCapability:
    available: bool
    language: Literal["vie"] | None

    def __post_init__(self) -> None:
        if self.available != (self.language == "vie"):
            raise ValueError("invalid OCR capability")


@dataclass(frozen=True)
class _BoundedProcessResult:
    status: ProcessStatus
    returncode: int | None
    _stdout: bytes = field(repr=False)

    def __str__(self) -> str:
        return f"BoundedProcessResult(status={self.status!r})"


class _BoundedRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        input_bytes: bytes,
        timeout_seconds: float,
        output_limit: int,
    ) -> _BoundedProcessResult: ...


@dataclass(frozen=True)
class LocalOcrSession:
    capability: OcrCapability
    _executable: str | None = field(repr=False)
    _runner: _BoundedRunner = field(repr=False)
    _lock: object = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    def __str__(self) -> str:
        return "LocalOcrSession()"


@dataclass
class OcrBudget:
    max_units: int = MAX_OCR_UNITS
    max_total_seconds: float = MAX_TOTAL_SECONDS
    used_units: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_units, bool)
            or not isinstance(self.max_units, int)
            or not 0 <= self.max_units <= MAX_OCR_UNITS
            or isinstance(self.used_units, bool)
            or not isinstance(self.used_units, int)
            or not 0 <= self.used_units <= self.max_units
            or isinstance(self.max_total_seconds, bool)
            or not isinstance(self.max_total_seconds, (int, float))
            or not 0 <= self.max_total_seconds <= MAX_TOTAL_SECONDS
            or not math.isfinite(float(self.max_total_seconds))
            or isinstance(self.started_at, bool)
            or not isinstance(self.started_at, (int, float))
            or not math.isfinite(float(self.started_at))
        ):
            raise ValueError("invalid OCR budget")


@dataclass(frozen=True)
class OcrOutcome:
    status: OcrStatus
    private_text: str = field(repr=False)

    def __post_init__(self) -> None:
        text_status = self.status in {"succeeded", "low-confidence"}
        if text_status != bool(self.private_text):
            raise ValueError("invalid OCR outcome")

    def __str__(self) -> str:
        return f"OcrOutcome(status={self.status!r})"


def _close_pipe(pipe: object | None) -> None:
    if pipe is None:
        return
    try:
        pipe.close()  # type: ignore[attr-defined]
    except Exception:
        pass


def _terminate_and_wait(process: object) -> None:
    try:
        process.kill()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        process.wait()  # type: ignore[attr-defined]
    except Exception:
        pass


def _run_bounded_process(
    argv: Sequence[str],
    input_bytes: bytes,
    timeout_seconds: float,
    output_limit: int,
    *,
    process_factory: Callable[..., object] = subprocess.Popen,
    selector_factory: Callable[[], object] = selectors.DefaultSelector,
    monotonic: Callable[[], float] = time.monotonic,
    recorder: Callable[[tuple[str, ...], bytes, float, int], None] | None = None,
) -> _BoundedProcessResult:
    """Run one fixed direct process with bounded stdin, stdout, time, and cleanup."""
    process = None
    selector = None
    stdout = None
    writer = None
    selector_registered = False
    writer_failed = threading.Event()
    status: ProcessStatus | Literal["running"] = "running"
    returncode: int | None = None
    output_parts: list[bytes] = []
    output_size = 0
    waited = False

    if recorder is not None:
        recorder(tuple(argv), input_bytes, timeout_seconds, output_limit)

    try:
        process = process_factory(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            cwd=os.path.abspath(os.sep),
            env=dict(_SAFE_ENV),
        )
        stdin = process.stdin  # type: ignore[attr-defined]
        stdout = process.stdout  # type: ignore[attr-defined]
        if stdin is None or stdout is None:
            raise RuntimeError("process pipe unavailable")

        def write_stdin() -> None:
            try:
                stdin.write(input_bytes)
                stdin.flush()
            except Exception:
                writer_failed.set()
            finally:
                _close_pipe(stdin)

        writer = threading.Thread(
            target=write_stdin,
            name="ctv-local-ocr-writer",
            daemon=False,
        )
        writer.start()

        os.set_blocking(stdout.fileno(), False)
        selector = selector_factory()
        selector.register(stdout, selectors.EVENT_READ)  # type: ignore[attr-defined]
        selector_registered = True
        deadline = monotonic() + timeout_seconds
        reached_eof = False

        while not reached_eof:
            remaining = deadline - monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            events = selector.select(remaining)  # type: ignore[attr-defined]
            if not events:
                if monotonic() >= deadline:
                    status = "timeout"
                    break
                continue

            try:
                chunk = os.read(
                    stdout.fileno(),
                    min(64 * 1024, output_limit + 1 - output_size),
                )
            except BlockingIOError:
                continue
            if not chunk:
                reached_eof = True
                continue
            output_parts.append(chunk)
            output_size += len(chunk)
            if output_size > output_limit:
                status = "over-limit"
                break

        if status == "running":
            remaining = deadline - monotonic()
            if remaining <= 0:
                status = "timeout"
            else:
                returncode = process.wait(timeout=remaining)  # type: ignore[attr-defined]
                waited = True
                status = "succeeded" if returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = "timeout"
    except Exception:
        status = "failed"
    finally:
        if process is not None and status != "succeeded":
            _terminate_and_wait(process)
            waited = True
        elif process is not None and not waited:
            try:
                returncode = process.wait()  # type: ignore[attr-defined]
            except Exception:
                status = "failed"

        if writer is not None:
            writer.join()

        if selector is not None and selector_registered and stdout is not None:
            try:
                selector.unregister(stdout)  # type: ignore[attr-defined]
            except Exception:
                pass
        if selector is not None:
            try:
                selector.close()  # type: ignore[attr-defined]
            except Exception:
                pass

        if process is not None:
            _close_pipe(getattr(process, "stdin", None))
            _close_pipe(getattr(process, "stdout", None))

    if status == "succeeded" and writer_failed.is_set():
        status = "failed"
    if status != "succeeded":
        return _BoundedProcessResult(status, returncode, b"")
    return _BoundedProcessResult("succeeded", returncode, b"".join(output_parts))


def _capability_for_executable(
    executable: str,
    runner: _BoundedRunner,
) -> OcrCapability:
    try:
        version = runner(
            [executable, "--version"],
            b"",
            PROBE_TIMEOUT_SECONDS,
            MAX_PROBE_BYTES,
        )
        languages = runner(
            [executable, "--list-langs"],
            b"",
            PROBE_TIMEOUT_SECONDS,
            MAX_PROBE_BYTES,
        )
        if (
            version.status != "succeeded"
            or version.returncode != 0
            or languages.status != "succeeded"
            or languages.returncode != 0
        ):
            return OcrCapability(False, None)
        language_lines = languages._stdout.decode("utf-8", errors="strict").splitlines()
        if "vie" not in (line.strip() for line in language_lines):
            return OcrCapability(False, None)
        return OcrCapability(True, "vie")
    except Exception:
        return OcrCapability(False, None)


def probe_local_ocr(
    executable_lookup: Callable[[str], str | None] = shutil.which,
    runner: _BoundedRunner | None = None,
) -> OcrCapability:
    """Return only the fixed public OCR capability, never runtime details."""
    try:
        executable = executable_lookup("tesseract")
    except Exception:
        return OcrCapability(False, None)
    if not executable:
        return OcrCapability(False, None)
    executable = os.path.abspath(executable)
    bounded_runner = runner or _run_bounded_process
    return _capability_for_executable(executable, bounded_runner)


def open_local_ocr(
    executable_lookup: Callable[[str], str | None] = shutil.which,
    process_factory: Callable[..., object] = subprocess.Popen,
    *,
    selector_factory: Callable[[], object] = selectors.DefaultSelector,
    monotonic: Callable[[], float] = time.monotonic,
    runner: _BoundedRunner | None = None,
    recorder: Callable[[tuple[str, ...], bytes, float, int], None] | None = None,
) -> LocalOcrSession:
    """Resolve and bind one private executable exactly once for an inspect call."""
    if runner is None:
        def bounded_runner(
            argv: Sequence[str],
            input_bytes: bytes,
            timeout_seconds: float,
            output_limit: int,
        ) -> _BoundedProcessResult:
            return _run_bounded_process(
                argv,
                input_bytes,
                timeout_seconds,
                output_limit,
                process_factory=process_factory,
                selector_factory=selector_factory,
                monotonic=monotonic,
                recorder=recorder,
            )
    else:
        bounded_runner = runner

    try:
        executable = executable_lookup("tesseract")
    except Exception:
        executable = None
    if not executable:
        return LocalOcrSession(OcrCapability(False, None), None, bounded_runner)
    executable = os.path.abspath(executable)
    capability = _capability_for_executable(executable, bounded_runner)
    return LocalOcrSession(capability, executable, bounded_runner)


def _parse_tsv(stdout: bytes) -> tuple[str, float] | None:
    try:
        lines = stdout.decode("utf-8", errors="strict").splitlines()
        if not lines:
            return None
        header = lines[0].split("\t")
        confidence_index = header.index("conf")
        text_index = header.index("text")
        tokens: list[str] = []
        confidences: list[float] = []
        for line in lines[1:]:
            if not line:
                continue
            columns = line.split("\t")
            if len(columns) != len(header):
                return None
            confidence = float(columns[confidence_index])
            if not math.isfinite(confidence):
                return None
            token = columns[text_index].strip()
            if confidence >= 0 and token:
                tokens.append(token)
                confidences.append(confidence)
        if not tokens:
            return None
        return " ".join(tokens), sum(confidences) / len(confidences)
    except (UnicodeDecodeError, ValueError):
        return None


def _run_local_ocr_bound(
    image_bytes: bytes,
    *,
    session: LocalOcrSession,
    budget: OcrBudget,
    timeout_seconds: float = DEFAULT_OCR_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> OcrOutcome:
    """Run sequential bounded OCR and retain extracted text only in private state."""
    if not session.capability.available or session._executable is None:
        return OcrOutcome("unavailable", "")
    if not image_bytes or not image_bytes.startswith(_PNG_SIGNATURE):
        return OcrOutcome("failed", "")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return OcrOutcome("over-limit", "")

    now = monotonic()
    elapsed = now - budget.started_at
    remaining_total = budget.max_total_seconds - elapsed
    if budget.used_units >= budget.max_units or remaining_total <= 0:
        return OcrOutcome("over-limit", "")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
    ):
        return OcrOutcome("failed", "")

    effective_timeout = min(
        float(timeout_seconds),
        float(DEFAULT_OCR_TIMEOUT_SECONDS),
        float(remaining_total),
    )
    if effective_timeout <= 0:
        return OcrOutcome("over-limit", "")

    budget.used_units += 1
    argv = [
        session._executable,
        "stdin",
        "stdout",
        "-l",
        "vie",
        "--psm",
        "6",
        "tsv",
    ]
    try:
        process_result = session._runner(
            argv,
            image_bytes,
            effective_timeout,
            MAX_TSV_BYTES,
        )
        if process_result.status == "timeout":
            return OcrOutcome("timeout", "")
        if process_result.status == "over-limit":
            return OcrOutcome("over-limit", "")
        if process_result.status != "succeeded" or process_result.returncode != 0:
            return OcrOutcome("failed", "")

        parsed = _parse_tsv(process_result._stdout)
        if parsed is None:
            return OcrOutcome("failed", "")
        private_text, mean_confidence = parsed
        status: OcrStatus = (
            "succeeded" if mean_confidence >= 70 else "low-confidence"
        )
        return OcrOutcome(status, private_text)
    except subprocess.TimeoutExpired:
        return OcrOutcome("timeout", "")
    except Exception:
        return OcrOutcome("failed", "")


def run_local_ocr(
    image_bytes: bytes,
    *,
    session: LocalOcrSession,
    budget: OcrBudget,
    timeout_seconds: float = DEFAULT_OCR_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> OcrOutcome:
    """Serialize all OCR work through the session's single bounded process lane."""
    with session._lock:  # type: ignore[attr-defined]
        return _run_local_ocr_bound(
            image_bytes,
            session=session,
            budget=budget,
            timeout_seconds=timeout_seconds,
            monotonic=monotonic,
        )
