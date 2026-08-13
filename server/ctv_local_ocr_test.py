import builtins
import copy
import dataclasses
import gc
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import weakref

import pytest

import ctv_local_ocr as ocr_module
from ctv_local_ocr import (
    MAX_IMAGE_BYTES,
    MAX_TSV_BYTES,
    LocalOcrSession,
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


def _open_session_with_ocr_action(ocr_action):
    def runner(argv, _input_bytes, _timeout_seconds, _output_limit):
        if argv[-1] == "--version":
            return _BoundedProcessResult("succeeded", 0, b"version\n")
        if argv[-1] == "--list-langs":
            return _BoundedProcessResult("succeeded", 0, b"vie\n")
        return ocr_action()

    return open_local_ocr(
        executable_lookup=lambda _name: PRIVATE_EXECUTABLE,
        runner=runner,
    )


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


def test_session_has_no_structural_executable_path_field_or_value():
    session, _ = _open_available_session()

    dataclass_names = (
        tuple(field.name for field in dataclasses.fields(session))
        if dataclasses.is_dataclass(session)
        else ()
    )
    slot_names = tuple(getattr(type(session), "__slots__", ()))
    dictionary = getattr(session, "__dict__", {})
    visible_names = tuple(dir(session))

    all_names = dataclass_names + slot_names + tuple(dictionary) + visible_names
    assert all("executable" not in name.lower() for name in all_names)
    assert PRIVATE_EXECUTABLE not in repr(dictionary)
    for name in visible_names:
        try:
            value = getattr(session, name)
        except Exception:
            continue
        assert PRIVATE_EXECUTABLE not in repr(value)
        assert PRIVATE_EXECUTABLE not in str(value)
        callable_value = getattr(value, "__func__", value)
        for cell in getattr(callable_value, "__closure__", ()) or ():
            try:
                closure_value = cell.cell_contents
            except ValueError:
                continue
            assert PRIVATE_EXECUTABLE not in repr(closure_value)
            assert PRIVATE_EXECUTABLE not in str(closure_value)


def test_session_exposes_no_callback_path_that_can_return_the_authority():
    session, _ = _open_available_session()

    escape = getattr(session, "_run_exclusive", None)
    escaped_authority = (
        escape(lambda authority: authority) if escape is not None else None
    )

    assert escape is None
    assert escaped_authority is None


def test_copied_session_is_untrusted_and_fails_before_process_or_budget_use():
    session, runner = _open_available_session()
    fabricated = copy.copy(session)
    calls_before = len(runner.calls)
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=fabricated,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""
    assert len(runner.calls) == calls_before
    assert budget.used_units == 0


def test_directly_fabricated_session_fails_before_process_or_budget_use():
    legitimate_session, runner = _open_available_session()
    fabricated = LocalOcrSession(legitimate_session.capability)
    calls_before = len(runner.calls)
    budget = OcrBudget(started_at=0.0)

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=fabricated,
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""
    assert len(runner.calls) == calls_before
    assert budget.used_units == 0


def test_equality_forged_session_fails_safely_before_process_io():
    session, runner = _open_available_session()
    calls_before = len(runner.calls)
    budget = OcrBudget(started_at=0.0)

    class EqualityForgedSession:
        capability = OcrCapability(True, "vie")

        def __eq__(self, other):
            return other is session

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=EqualityForgedSession(),
        budget=budget,
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""
    assert len(runner.calls) == calls_before
    assert budget.used_units == 0


def test_session_finalization_releases_registry_owned_runner_authority():
    runner = _RecordingRunner()
    session = open_local_ocr(
        executable_lookup=lambda _name: PRIVATE_EXECUTABLE,
        runner=runner,
    )
    session_reference = weakref.ref(session)
    runner_reference = weakref.ref(runner)

    del runner
    del session
    gc.collect()

    assert session_reference() is None
    assert runner_reference() is None


def test_module_registry_and_lookup_cannot_return_authority_for_custom_caps():
    session, runner = _open_available_session()
    calls_before = len(runner.calls)
    registry = getattr(ocr_module, "_SESSION_STATES", None)
    lookup = getattr(ocr_module, "_state_for_session", None)
    escaped_result = None

    if registry is not None and lookup is not None:
        state = lookup(session)
        assert registry[id(session)] is state
        escaped_result = state.authority(b"attacker-selected", 9999, 9999)

    assert registry is None
    assert lookup is None
    assert escaped_result is None
    assert len(runner.calls) == calls_before


def test_module_exports_no_registry_state_or_authority_container():
    session, _ = _open_available_session()
    forbidden_names = {
        "_SESSION_STATES",
        "_SESSION_STATES_LOCK",
        "_SessionState",
        "_state_for_session",
        "_register_session",
        "_discard_session_state",
        "_OcrAuthority",
    }

    assert forbidden_names.isdisjoint(dir(ocr_module))
    for name in dir(ocr_module):
        value = getattr(ocr_module, name)
        if isinstance(value, dict):
            assert id(session) not in value
        if not callable(value):
            continue
        callable_value = getattr(value, "__func__", value)
        for cell in getattr(callable_value, "__closure__", ()) or ():
            try:
                closure_value = cell.cell_contents
            except ValueError:
                continue
            assert not isinstance(closure_value, dict)
            assert not hasattr(closure_value, "authority")


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
    "header",
    [
        b"conf\ttext\n",
        (
            b"page_num\tlevel\tblock_num\tpar_num\tline_num\tword_num\tleft\t"
            b"top\twidth\theight\tconf\ttext\n"
        ),
        TSV_HEADER.rstrip(b"\n") + b"\textra\n",
        TSV_HEADER.replace(b"\twidth\t", b"\t"),
    ],
)
def test_tsv_rejects_noncanonical_reordered_extra_or_missing_header(header):
    column_count = len(header.rstrip(b"\n").split(b"\t"))
    if column_count == 2:
        row = b"90\tprivate-token\n"
    else:
        row = b"\t".join([b"1"] * (column_count - 2) + [b"90", b"private-token"])
        row += b"\n"
    session, _ = _open_available_session(
        _BoundedProcessResult("succeeded", 0, header + row)
    )

    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "failed"
    assert outcome.private_text == ""


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
    def timeout_action():
        raise subprocess.TimeoutExpired(
            [PRIVATE_EXECUTABLE, "private-source"], 30, output=b"private stdout"
        )

    session = _open_session_with_ocr_action(timeout_action)
    outcome = run_local_ocr(
        SYNTHETIC_PNG,
        session=session,
        budget=OcrBudget(started_at=0.0),
        monotonic=lambda: 1.0,
    )

    assert outcome.status == "timeout"
    assert outcome.private_text == ""
    assert PRIVATE_EXECUTABLE not in repr(outcome)


def test_malformed_runner_result_cannot_escape_private_exception_text():
    class MalformedResult:
        @property
        def status(self):
            raise RuntimeError("/private/source/012345678901.png")

    session = _open_session_with_ocr_action(MalformedResult)

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


class _FakeProcess:
    def __init__(self, output=b"result", *, keep_stdout_open=False, stderr_secret=None):
        stdin_read_fd, stdin_write_fd = os.pipe()
        stdout_read_fd, stdout_write_fd = os.pipe()
        self.stdin = os.fdopen(stdin_write_fd, "wb", buffering=0)
        self.stdout = os.fdopen(stdout_read_fd, "rb", buffering=0)
        self._stdin_read_fd = stdin_read_fd
        self._write_fd = stdout_write_fd
        self._keep_stdout_open = keep_stdout_open
        self._stderr_secret = stderr_secret
        self.kill_calls = 0
        self.wait_calls = 0
        self.returncode = None
        if output:
            os.write(stdout_write_fd, output)
        if not keep_stdout_open:
            os.close(stdout_write_fd)
            self._write_fd = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        if self._stdin_read_fd is not None:
            os.close(self._stdin_read_fd)
            self._stdin_read_fd = None
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

    def read_stdin(self):
        chunks = []
        while True:
            chunk = os.read(self._stdin_read_fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        os.close(self._stdin_read_fd)
        self._stdin_read_fd = None
        return b"".join(chunks)


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


class _EarlyExitProcess:
    def __init__(self):
        stdin_read_fd, stdin_write_fd = os.pipe()
        os.close(stdin_read_fd)
        stdout_read_fd, stdout_write_fd = os.pipe()
        os.close(stdout_write_fd)
        self.stdin = os.fdopen(stdin_write_fd, "wb", buffering=0)
        self.stdout = os.fdopen(stdout_read_fd, "rb", buffering=0)
        self.kill_calls = 0
        self.wait_calls = 0

    def kill(self):
        self.kill_calls += 1
        raise ProcessLookupError("already exited")

    def wait(self, timeout=None):
        self.wait_calls += 1
        return 1


class _RealBlockingPipeProcess:
    def __init__(self):
        stdin_read_fd, stdin_write_fd = os.pipe()
        stdout_read_fd, stdout_write_fd = os.pipe()
        self.stdin = os.fdopen(stdin_write_fd, "wb", buffering=0)
        self.stdout = os.fdopen(stdout_read_fd, "rb", buffering=0)
        self._stdin_read_fd = stdin_read_fd
        self._stdout_write_fd = stdout_write_fd
        self.kill_calls = 0
        self.wait_calls = 0

    def kill(self):
        self.kill_calls += 1
        raise OSError("synthetic kill failure")

    def wait(self, timeout=None):
        self.wait_calls += 1
        raise OSError("synthetic wait failure")

    def release_writer(self):
        if self._stdin_read_fd is not None:
            os.close(self._stdin_read_fd)
            self._stdin_read_fd = None

    def close_test_fds(self):
        self.release_writer()
        try:
            os.close(self._stdout_write_fd)
        except OSError:
            pass


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
    assert process.read_stdin() == b"bounded stdin"
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


def test_real_pipe_writer_returns_bounded_when_child_exits_before_reading():
    process = _EarlyExitProcess()
    started_at = time.monotonic()

    result = _run_bounded_process(
        [PRIVATE_EXECUTABLE, "--version"],
        b"x" * (1024 * 1024),
        1,
        64 * 1024,
        process_factory=lambda *_args, **_kwargs: process,
    )

    assert time.monotonic() - started_at < 0.5
    assert result.status == "failed"
    assert result._stdout == b""
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert not any(
        thread.name == "ctv-local-ocr-writer" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_real_full_pipe_writer_is_stopped_when_kill_and_wait_fail():
    process = _RealBlockingPipeProcess()
    clock = _Clock()
    selector = _SilentSelector(clock)
    result_holder = []
    finished = threading.Event()

    def invoke():
        result_holder.append(
            _run_bounded_process(
                [PRIVATE_EXECUTABLE, "--version"],
                b"x" * (1024 * 1024),
                0.01,
                64 * 1024,
                process_factory=lambda *_args, **_kwargs: process,
                selector_factory=lambda: selector,
                monotonic=clock,
            )
        )
        finished.set()

    caller = threading.Thread(target=invoke, daemon=True)
    caller.start()
    time.sleep(0.05)
    returned_without_external_pipe_release = finished.wait(timeout=0.2)
    if not returned_without_external_pipe_release:
        process.release_writer()
    caller.join(timeout=1)
    process.close_test_fds()

    assert returned_without_external_pipe_release is True
    assert result_holder[0].status == "timeout"
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert not caller.is_alive()
    assert not any(
        thread.name == "ctv-local-ocr-writer" and thread.is_alive()
        for thread in threading.enumerate()
    )
