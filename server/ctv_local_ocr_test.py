import builtins
import os
from pathlib import Path
import subprocess
import tempfile
import threading

import pytest

from ctv_local_ocr import (
    MAX_IMAGE_BYTES,
    MAX_TSV_BYTES,
    OcrBudget,
    OcrCapability,
    _BoundedProcessResult,
    _run_bounded_process,
    open_local_ocr,
    probe_local_ocr,
    run_local_ocr,
)


SYNTHETIC_PNG = b"\x89PNG\r\n\x1a\nsynthetic-pixels"
PRIVATE_EXECUTABLE = "/private/operator tools/tesseract-secret"
SAFE_ENV = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}
TSV_HEADER = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
    b"width\theight\tconf\ttext\n"
)


def _tsv(*rows: tuple[str, str]) -> bytes:
    body = b"".join(
        (
            "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t"
            f"{confidence}\t{text}\n"
        ).encode("utf-8")
        for confidence, text in rows
    )
    return TSV_HEADER + body


class _RecordingRunner:
    def __init__(self, ocr_result: _BoundedProcessResult | None = None):
        self.calls = []
        self.ocr_result = ocr_result or _BoundedProcessResult(
            status="succeeded",
            returncode=0,
            _stdout=_tsv(("92", "Xin"), ("88", "chao")),
        )

    def __call__(self, argv, input_bytes, timeout_seconds, output_limit):
        self.calls.append((list(argv), input_bytes, timeout_seconds, output_limit))
        if argv[-1] == "--version":
            return _BoundedProcessResult(
                status="succeeded", returncode=0, _stdout=b"tesseract 5 synthetic\n"
            )
        if argv[-1] == "--list-langs":
            return _BoundedProcessResult(
                status="succeeded", returncode=0, _stdout=b"List of languages:\neng\nvie\n"
            )
        return self.ocr_result


def _open_available_session(ocr_result: _BoundedProcessResult | None = None):
    runner = _RecordingRunner(ocr_result)
    lookup_calls = []

    def lookup(name):
        lookup_calls.append(name)
        return PRIVATE_EXECUTABLE

    session = open_local_ocr(executable_lookup=lookup, runner=runner)
    assert lookup_calls == ["tesseract"]
    assert session.capability == OcrCapability(available=True, language="vie")
    return session, runner


def test_open_resolves_tesseract_once_and_session_repr_never_exposes_the_path():
    session, runner = _open_available_session()

    assert [call[0] for call in runner.calls] == [
        [PRIVATE_EXECUTABLE, "--version"],
        [PRIVATE_EXECUTABLE, "--list-langs"],
    ]
    assert PRIVATE_EXECUTABLE not in repr(session)
    assert PRIVATE_EXECUTABLE not in str(session)
    assert not hasattr(session, "executable")
    assert not hasattr(session, "executable_path")


def test_relative_lookup_result_is_privately_bound_as_an_absolute_executable(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = _RecordingRunner()

    session = open_local_ocr(
        executable_lookup=lambda _name: os.path.join("relative-tools", "tesseract"),
        runner=runner,
    )

    absolute_executable = str(tmp_path / "relative-tools" / "tesseract")
    assert [call[0] for call in runner.calls] == [
        [absolute_executable, "--version"],
        [absolute_executable, "--list-langs"],
    ]
    assert absolute_executable not in repr(session)


def test_probe_requires_both_successful_commands_and_exact_vie_language():
    calls = []

    def runner(argv, input_bytes, timeout_seconds, output_limit):
        calls.append((argv, input_bytes, timeout_seconds, output_limit))
        output = b"version\n" if argv[-1] == "--version" else b"eng\nvie-old\n"
        return _BoundedProcessResult("succeeded", 0, output)

    capability = probe_local_ocr(
        executable_lookup=lambda _name: PRIVATE_EXECUTABLE,
        runner=runner,
    )

    assert capability == OcrCapability(available=False, language=None)
    assert calls == [
        ([PRIVATE_EXECUTABLE, "--version"], b"", 5, 64 * 1024),
        ([PRIVATE_EXECUTABLE, "--list-langs"], b"", 5, 64 * 1024),
    ]


def test_run_uses_only_stdin_bytes_and_the_exact_fixed_tesseract_command():
    session, runner = _open_available_session()
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    argv, input_bytes, timeout, output_limit = runner.calls[-1]
    assert argv == [
        PRIVATE_EXECUTABLE,
        "stdin",
        "stdout",
        "-l",
        "vie",
        "--psm",
        "6",
        "tsv",
    ]
    assert input_bytes == SYNTHETIC_PNG
    assert timeout == 30
    assert output_limit == MAX_TSV_BYTES
    assert outcome.status == "succeeded"
    assert outcome.private_text == "Xin chao"
    assert budget.used_units == 1


def test_tsv_uses_only_nonempty_nonnegative_tokens_and_threshold_is_inclusive():
    result = _BoundedProcessResult(
        "succeeded",
        0,
        _tsv(("90", "Xin"), ("-1", "private"), ("80", ""), ("50", "chao")),
    )
    session, _ = _open_available_session(result)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "succeeded"
    assert outcome.private_text == "Xin chao"


def test_mean_confidence_below_seventy_is_low_confidence_but_keeps_private_text():
    session, _ = _open_available_session(
        _BoundedProcessResult("succeeded", 0, _tsv(("69", "Xin"), ("70", "chao")))
    )

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "low-confidence"
    assert outcome.private_text == "Xin chao"
    assert "Xin" not in repr(outcome)
    assert "Xin" not in str(outcome)


@pytest.mark.parametrize(
    "stdout",
    [
        b"not-tsv",
        TSV_HEADER + b"5\ttoo-few-columns\n",
        TSV_HEADER + b"5\t1\t1\t1\t1\t1\t0\t0\t1\t1\tnot-a-number\tword\n",
        TSV_HEADER + b"\xff\n",
        TSV_HEADER,
    ],
)
def test_malformed_or_empty_usable_tsv_fails_without_returning_output(stdout):
    session, _ = _open_available_session(
        _BoundedProcessResult("succeeded", 0, stdout)
    )

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""
    assert stdout.decode("utf-8", errors="ignore") not in repr(outcome)


@pytest.mark.parametrize(
    ("process_status", "expected_status"),
    [
        ("timeout", "timeout"),
        ("failed", "failed"),
        ("over-limit", "over-limit"),
    ],
)
def test_process_failures_have_empty_private_text(process_status, expected_status):
    private_stdout = b"/private/source/012345678901.png secret text"
    session, _ = _open_available_session(
        _BoundedProcessResult(process_status, None, private_stdout)
    )

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == expected_status
    assert outcome.private_text == ""
    assert private_stdout.decode() not in repr(outcome)


def test_timeout_exception_and_private_exception_text_are_safely_reduced():
    session, runner = _open_available_session()

    def timeout_runner(*_args):
        raise subprocess.TimeoutExpired(
            [PRIVATE_EXECUTABLE, "private-source"], 30, output=b"private stdout"
        )

    object.__setattr__(session, "_runner", timeout_runner)
    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "timeout"
    assert outcome.private_text == ""
    assert PRIVATE_EXECUTABLE not in repr(outcome)
    assert runner.calls[-1][0][-1] == "--list-langs"


def test_malformed_runner_result_cannot_escape_private_exception_text():
    session, _ = _open_available_session()

    class MalformedResult:
        @property
        def status(self):
            raise RuntimeError("/private/source/012345678901.png")

    object.__setattr__(session, "_runner", lambda *_args: MalformedResult())

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""


def test_missing_executable_is_unavailable_without_reserving_or_spawning():
    calls = []
    session = open_local_ocr(
        executable_lookup=lambda name: calls.append(name) or None,
        runner=lambda *_args: pytest.fail("runner must not be called"),
    )
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert calls == ["tesseract"]
    assert session.capability == OcrCapability(False, None)
    assert outcome.status == "unavailable"
    assert outcome.private_text == ""
    assert budget.used_units == 0


@pytest.mark.parametrize(
    ("budget", "now"),
    [
        (OcrBudget(max_units=500, used_units=500, started_at=0.0), 1.0),
        (OcrBudget(max_total_seconds=1800, started_at=0.0), 1800.0),
    ],
)
def test_exhausted_unit_501_or_total_deadline_never_spawns(budget, now):
    session, runner = _open_available_session()
    calls_before = len(runner.calls)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=budget,
        monotonic=lambda: now,
    )

    assert outcome.status == "over-limit"
    assert outcome.private_text == ""
    assert len(runner.calls) == calls_before


@pytest.mark.parametrize("image_bytes", [b"", b"not a png"])
def test_empty_or_non_png_input_fails_without_reserving_or_spawning(image_bytes):
    session, runner = _open_available_session()
    calls_before = len(runner.calls)
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        image_bytes,
        session=session,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""
    assert budget.used_units == 0
    assert len(runner.calls) == calls_before


def test_input_over_cap_is_over_limit_without_reserving_or_spawning():
    session, runner = _open_available_session()
    calls_before = len(runner.calls)
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_IMAGE_BYTES - 7),
        session=session,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "over-limit"
    assert budget.used_units == 0
    assert len(runner.calls) == calls_before


def test_ocr_never_calls_tempfiles_path_writes_open_or_shell_helpers(monkeypatch):
    session, _ = _open_available_session()

    def forbidden(*_args, **_kwargs):
        pytest.fail("filesystem or shell helper must not be called")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "call", forbidden)
    monkeypatch.setattr(subprocess, "check_call", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "succeeded"


def test_one_bound_session_serializes_all_ocr_processes():
    first_started = threading.Event()
    overlap = threading.Event()
    release_first = threading.Event()
    active_lock = threading.Lock()
    active = 0

    def runner(argv, _input_bytes, _timeout_seconds, _output_limit):
        nonlocal active
        if argv[-1] == "--version":
            return _BoundedProcessResult("succeeded", 0, b"version\n")
        if argv[-1] == "--list-langs":
            return _BoundedProcessResult("succeeded", 0, b"vie\n")
        with active_lock:
            active += 1
            if active > 1:
                overlap.set()
            else:
                first_started.set()
        release_first.wait(timeout=2)
        with active_lock:
            active -= 1
        return _BoundedProcessResult("succeeded", 0, _tsv(("90", "safe")))

    session = open_local_ocr(
        executable_lookup=lambda _name: PRIVATE_EXECUTABLE,
        runner=runner,
    )
    budget = OcrBudget(started_at=0.0)
    outcomes = []

    def invoke():
        outcomes.append(
            run_local_ocr(
                SYNTHETIC_PNG,
                session=session,
                budget=budget,
                monotonic=lambda: 1.0,
            )
        )

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    did_overlap = overlap.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert did_overlap is False
    assert [outcome.status for outcome in outcomes] == ["succeeded", "succeeded"]
    assert budget.used_units == 2


class _InputSink:
    def __init__(self):
        self.chunks = []
        self.closed = False

    def write(self, value):
        self.chunks.append(value)
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, output=b"result", *, keep_stdout_open=False, stderr_secret=None):
        read_fd, write_fd = os.pipe()
        self.stdin = _InputSink()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self._write_fd = write_fd
        self._keep_stdout_open = keep_stdout_open
        self._stderr_secret = stderr_secret
        self.kill_calls = 0
        self.wait_calls = 0
        self.returncode = None
        if output:
            os.write(write_fd, output)
        if not keep_stdout_open:
            os.close(write_fd)
            self._write_fd = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        if self._write_fd is not None:
            os.close(self._write_fd)
            self._write_fd = None

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self._keep_stdout_open and self.returncode is None:
            raise subprocess.TimeoutExpired("safe", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _SilentSelector:
    def __init__(self, clock):
        self.clock = clock
        self.registered = []
        self.unregistered = []
        self.closed = False

    def register(self, fileobj, events):
        self.registered.append((fileobj, events))

    def unregister(self, fileobj):
        self.unregistered.append(fileobj)

    def select(self, timeout=None):
        self.clock.now += timeout or 0.0
        return []

    def close(self):
        self.closed = True


def test_bounded_process_uses_exact_safe_process_contract_and_one_writer():
    process = _FakeProcess(
        output=b"safe stdout", stderr_secret=b"private/source/012345678901"
    )
    factory_calls = []

    def factory(argv, **kwargs):
        factory_calls.append((argv, kwargs))
        return process

    result = _run_bounded_process(
        [PRIVATE_EXECUTABLE, "--version"],
        b"bounded stdin",
        5,
        64 * 1024,
        process_factory=factory,
    )

    argv, kwargs = factory_calls[0]
    assert argv == [PRIVATE_EXECUTABLE, "--version"]
    assert kwargs == {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "shell": False,
        "close_fds": True,
        "cwd": os.path.abspath(os.sep),
        "env": SAFE_ENV,
    }
    assert process.stdin.chunks == [b"bounded stdin"]
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.wait_calls == 1
    assert process.kill_calls == 0
    assert result.status == "succeeded"
    assert result.returncode == 0
    assert result._stdout == b"safe stdout"
    assert b"safe stdout".decode() not in repr(result)
    assert PRIVATE_EXECUTABLE not in repr(result)
    assert not any(
        thread.name == "ctv-local-ocr-writer" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_bounded_process_timeout_kills_waits_joins_unregisters_and_closes():
    process = _FakeProcess(output=b"", keep_stdout_open=True)
    clock = _Clock()
    selector = _SilentSelector(clock)

    result = _run_bounded_process(
        [PRIVATE_EXECUTABLE, "--list-langs"],
        b"",
        5,
        64 * 1024,
        process_factory=lambda *_args, **_kwargs: process,
        selector_factory=lambda: selector,
        monotonic=clock,
    )

    assert result.status == "timeout"
    assert result._stdout == b""
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert selector.registered
    assert selector.unregistered == [process.stdout]
    assert selector.closed is True
    assert not any(
        thread.name == "ctv-local-ocr-writer" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_bounded_process_output_cap_kills_waits_and_returns_no_bytes():
    process = _FakeProcess(output=b"12345")

    result = _run_bounded_process(
        [PRIVATE_EXECUTABLE, "--version"],
        b"",
        5,
        4,
        process_factory=lambda *_args, **_kwargs: process,
    )

    assert result.status == "over-limit"
    assert result._stdout == b""
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert process.stdin.closed is True
    assert process.stdout.closed is True
