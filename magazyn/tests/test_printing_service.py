import base64
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from magazyn.services.printing import CupsPrinter, PrintCommandError


def _ok_process(args, **kwargs):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")


@patch("magazyn.services.printing.subprocess.run")
def test_print_label_base64_uses_cups_host_and_cleans_temp_file(mock_run):
    mock_run.side_effect = _ok_process
    printer = CupsPrinter(printer_name="Zebra", cups_server="cups.local", cups_port=631)

    printer.print_label_base64(base64.b64encode(b"label").decode("ascii"), "../pdf")

    cmd = mock_run.call_args.args[0]
    assert cmd[:5] == ["lp", "-h", "cups.local:631", "-d", "Zebra"]
    assert cmd[-1].endswith(".pdf")
    assert not Path(cmd[-1]).exists()


@patch("magazyn.services.printing.subprocess.run")
def test_print_text_raises_on_lp_error(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout=b"",
        stderr=b"printer offline",
    )
    printer = CupsPrinter(printer_name="Zebra")

    with pytest.raises(PrintCommandError, match="printer offline"):
        printer.print_text("test")


@patch("magazyn.services.printing.subprocess.run")
def test_print_text_uses_default_printer_command(mock_run):
    mock_run.side_effect = _ok_process
    printer = CupsPrinter(printer_name="Zebra")

    printer.print_text("test")

    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["lp", "-d", "Zebra"]
    assert cmd[-1].endswith(".txt")
    assert not Path(cmd[-1]).exists()