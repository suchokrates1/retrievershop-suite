import base64
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from magazyn.services.printing import CupsPrinter, PrintCommandError, PrintJobTimeoutError


def _proc(args, *, returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def _lp_ok(args, **kwargs):
    return _proc(args, stdout=b"request id is Zebra-123 (1 file(s))\n")


def _lpstat_active_then_done():
    calls = {"n": 0}

    def side_effect(args, **kwargs):
        cmd = args[0] if args else ""
        if cmd == "lp":
            return _lp_ok(args)
        if cmd == "lpstat":
            calls["n"] += 1
            if calls["n"] == 1:
                return _proc(args, stdout=b"Zebra-123             root  1234   Mon 01 Jan 2026\n")
            return _proc(args, stdout=b"")
        return _proc(args)

    return side_effect


@patch("magazyn.services.printing.time.sleep", return_value=None)
@patch("magazyn.services.printing.subprocess.run")
def test_print_label_base64_uses_cups_host_waits_and_cleans_temp_file(mock_run, _sleep):
    mock_run.side_effect = _lpstat_active_then_done()
    printer = CupsPrinter(
        printer_name="Zebra",
        cups_server="cups.local",
        cups_port=631,
        poll_interval_seconds=0.01,
    )

    printer.print_label_base64(base64.b64encode(b"label").decode("ascii"), "../pdf")

    lp_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "lp"]
    assert lp_calls
    cmd = lp_calls[0]
    assert cmd[:5] == ["lp", "-h", "cups.local:631", "-d", "Zebra"]
    assert cmd[-1].endswith(".pdf")
    assert not Path(cmd[-1]).exists()

    lpstat_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "lpstat"]
    assert lpstat_calls
    assert lpstat_calls[0][:5] == ["lpstat", "-h", "cups.local:631", "-o", "Zebra"]


@patch("magazyn.services.printing.subprocess.run")
def test_print_text_raises_on_lp_error(mock_run):
    mock_run.return_value = _proc([], returncode=1, stderr=b"printer offline")
    printer = CupsPrinter(printer_name="Zebra", wait_for_completion=False)

    with pytest.raises(PrintCommandError, match="printer offline"):
        printer.print_text("test")


@patch("magazyn.services.printing.time.sleep", return_value=None)
@patch("magazyn.services.printing.subprocess.run")
def test_print_text_waits_for_job_completion(mock_run, _sleep):
    mock_run.side_effect = _lpstat_active_then_done()
    printer = CupsPrinter(printer_name="Zebra", poll_interval_seconds=0.01)

    printer.print_text("test")

    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:3] == ["lp", "-d", "Zebra"]
    assert cmd[-1].endswith(".txt")
    assert not Path(cmd[-1]).exists()


@patch("magazyn.services.printing.time.sleep", return_value=None)
@patch("magazyn.services.printing.subprocess.run")
def test_timeout_recovers_and_retries_once(mock_run, _sleep):
    state = {"lp": 0, "lpstat": 0}

    def side_effect(args, **kwargs):
        cmd = args[0]
        if cmd == "lp":
            state["lp"] += 1
            job = b"request id is Zebra-1 (1 file(s))\n" if state["lp"] == 1 else (
                b"request id is Zebra-2 (1 file(s))\n"
            )
            return _proc(args, stdout=job)
        if cmd == "lpstat":
            state["lpstat"] += 1
            # Pierwszy job wisi zawsze; drugi znika od razu.
            if state["lp"] == 1:
                return _proc(args, stdout=b"Zebra-1 root\n")
            return _proc(args, stdout=b"")
        # cancel / cupsdisable / cupsenable
        return _proc(args)

    mock_run.side_effect = side_effect
    printer = CupsPrinter(
        printer_name="Zebra",
        job_timeout_seconds=0.05,
        poll_interval_seconds=0.01,
        max_attempts=2,
    )

    mono = {"t": 0.0}

    def fake_mono():
        mono["t"] += 0.04
        return mono["t"]

    with patch("magazyn.services.printing.time.monotonic", side_effect=fake_mono):
        printer.print_label_base64(base64.b64encode(b"x").decode("ascii"), "pdf")

    assert state["lp"] == 2
    cancel_cmds = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "cancel"]
    disable_cmds = [
        c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "cupsdisable"
    ]
    enable_cmds = [
        c.args[0] for c in mock_run.call_args_list if c.args[0][0] == "cupsenable"
    ]
    assert cancel_cmds
    assert disable_cmds
    assert enable_cmds


@patch("magazyn.services.printing.time.sleep", return_value=None)
@patch("magazyn.services.printing.subprocess.run")
def test_timeout_both_attempts_raises(mock_run, _sleep):
    def side_effect(args, **kwargs):
        cmd = args[0]
        if cmd == "lp":
            return _proc(args, stdout=b"request id is Zebra-9 (1 file(s))\n")
        if cmd == "lpstat":
            return _proc(args, stdout=b"Zebra-9 still here\n")
        return _proc(args)

    mock_run.side_effect = side_effect
    printer = CupsPrinter(
        printer_name="Zebra",
        job_timeout_seconds=0.05,
        poll_interval_seconds=0.01,
        max_attempts=2,
    )
    mono = {"t": 0.0}

    def fake_mono():
        mono["t"] += 0.04
        return mono["t"]

    with patch("magazyn.services.printing.time.monotonic", side_effect=fake_mono):
        with pytest.raises(PrintJobTimeoutError, match="Zebra-9"):
            printer.print_label_base64(base64.b64encode(b"x").decode("ascii"), "pdf")


def test_from_env_reads_timeouts(monkeypatch):
    monkeypatch.setenv("CUPS_JOB_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("CUPS_PRINT_MAX_ATTEMPTS", "3")
    printer = CupsPrinter.from_env(printer_name="Xprinter")
    assert printer.job_timeout_seconds == 90.0
    assert printer.max_attempts == 3


def test_parse_job_id():
    assert CupsPrinter._parse_job_id("request id is Xprinter-470 (1 file(s))\n") == (
        "Xprinter-470"
    )
    assert CupsPrinter._parse_job_id("something else") is None
