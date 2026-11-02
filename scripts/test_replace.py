#!/usr/bin/env python3
"""Local checks for the monthly title replacement and the schedule guard.

Run from the repository root:

    python3 scripts/test_replace.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_run  # noqa: E402
import update_month  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
FIXTURE = ROOT / "tests" / "fixtures" / "live_index.html"
MARKER_11 = "【11月最新】".encode("utf-8")
MARKER_12 = "【12月最新】".encode("utf-8")


def _fail(message: str) -> None:
    raise AssertionError(message)


def test_fixture_november_to_december() -> str:
    original = FIXTURE.read_bytes()
    if original.count(MARKER_11) != 3:
        _fail(f"fixture should contain 【11月最新】 three times, found {original.count(MARKER_11)}")
    if b"\r\n" in original:
        _fail("fixture line endings changed; expected LF only")

    updated, status = update_month.replace_month_bytes(original, 12)
    if status != "updated":
        _fail(status)
    if updated.count(MARKER_12) != 3 or MARKER_11 in updated:
        _fail("fixture was not rewritten to 【12月最新】 in exactly three places")
    if len(updated) != len(original):
        _fail("11→12 must keep the file length (one ASCII digit either way)")

    changed = [index for index, (left, right) in enumerate(zip(original, updated)) if left != right]
    if len(changed) != 3:
        _fail(f"expected exactly 3 changed bytes, got {len(changed)}")
    for index in changed:
        if original[index : index + 1] != b"1" or updated[index : index + 1] != b"2":
            _fail(f"unexpected byte change at {index}: {original[index]} -> {updated[index]}")
        window = original[max(0, index - 12) : index + 12]
        if "月最新".encode("utf-8") not in window:
            _fail(f"changed byte at {index} is outside a month marker")

    diff = update_month.unified_diff(original, updated)
    for snippet in ("<title>", "og:title", "twitter:title", "【11月最新】", "【12月最新】"):
        if snippet not in diff:
            _fail(f"diff is missing {snippet}")
    if diff.count("【11月最新】") != 3 or diff.count("【12月最新】") != 3:
        _fail("diff should show the marker on exactly three removed and three added lines")

    again, again_status = update_month.replace_month_bytes(updated, 12)
    if again_status != "noop" or again != updated:
        _fail("a second run for the same month must be a no-op and keep the bytes")
    return diff


def test_wrap_december_to_january_preserves_crlf() -> None:
    original = (
        "<title>【12月最新】</title>\r\n"
        '<meta property="og:title" content="【12月最新】" />\r\n'
        '<meta name="twitter:title" content="【12月最新】" />\r\n'
    ).encode("utf-8")
    updated, status = update_month.replace_month_bytes(original, 1)
    if status != "updated":
        _fail(status)
    expected = (
        "<title>【1月最新】</title>\r\n"
        '<meta property="og:title" content="【1月最新】" />\r\n'
        '<meta name="twitter:title" content="【1月最新】" />\r\n'
    ).encode("utf-8")
    if updated != expected:
        _fail(updated.decode("utf-8"))
    if updated.count(b"\r\n") != 3:
        _fail("CRLF line endings were not preserved")


def test_nine_to_ten_inserts_one_digit_only() -> None:
    original = "A【9月最新】B【9月最新】C【9月最新】D".encode("utf-8") + b"\xff"
    updated, status = update_month.replace_month_bytes(original, 10)
    if status != "updated":
        _fail(status)
    expected = "A【10月最新】B【10月最新】C【10月最新】D".encode("utf-8") + b"\xff"
    if updated != expected:
        _fail("bytes outside the marker, including a non-UTF-8 tail, must survive")


def test_wrong_count_does_not_produce_output() -> None:
    for count in (0, 1, 2, 4):
        data = "【11月最新】".encode("utf-8") * count + b"tail"
        try:
            update_month.replace_month_bytes(data, 12)
        except update_month.ReplaceError:
            continue
        _fail(f"count {count} should fail")


def test_invalid_months_fail() -> None:
    try:
        update_month.replace_month_bytes("x".encode(), 0)
        _fail("month 0 should fail")
    except update_month.ReplaceError:
        pass
    try:
        update_month.replace_month_bytes("【13月最新】".encode() * 3, 1)
        _fail("month 13 in the file should fail")
    except update_month.ReplaceError:
        pass


def test_cli_exit_codes(diff_text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        output = directory / "out.html"
        diff_path = directory / "diff.patch"
        before = FIXTURE.read_bytes()
        updated = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "update_month.py"),
                "--input",
                str(FIXTURE),
                "--output",
                str(output),
                "--target-month",
                "12",
                "--diff",
                str(diff_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if updated.returncode != 0:
            _fail(updated.stderr)
        if "STATUS=updated" not in updated.stdout:
            _fail(updated.stdout)
        if diff_path.read_text(encoding="utf-8") != diff_text:
            _fail("CLI diff does not match the library diff")
        if before == output.read_bytes():
            _fail("CLI did not change the output")
        if FIXTURE.read_bytes() != before:
            _fail("CLI modified the input file")

        noop = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "update_month.py"),
                "--input",
                str(output),
                "--output",
                str(directory / "same.html"),
                "--target-month",
                "12",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if noop.returncode != 2 or "STATUS=noop" not in noop.stdout:
            _fail(f"noop exit {noop.returncode} stderr={noop.stderr}")

        bad = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "update_month.py"),
                "--input",
                str(FIXTURE),
                "--output",
                str(directory / "bad.html"),
                "--target-month",
                "13",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if bad.returncode != 1 or (directory / "bad.html").exists():
            _fail("invalid target month must exit 1 without writing output")


def test_schedule_guard() -> None:
    cases = [
        (datetime(2026, 11, 30, 23, 0, tzinfo=JST), True, 12),
        (datetime(2026, 11, 29, 23, 0, tzinfo=JST), False, 12),
        (datetime(2026, 11, 28, 23, 0, tzinfo=JST), False, 12),
        (datetime(2026, 12, 31, 23, 0, tzinfo=JST), True, 1),
        (datetime(2026, 12, 30, 23, 0, tzinfo=JST), False, 1),
        (datetime(2026, 2, 28, 23, 0, tzinfo=JST), True, 3),
        (datetime(2028, 2, 28, 23, 0, tzinfo=JST), False, 3),
        (datetime(2028, 2, 29, 23, 0, tzinfo=JST), True, 3),
        (datetime(2026, 1, 31, 23, 0, tzinfo=JST), True, 2),
        # 14:00 UTC on Nov 30 is 23:00 JST the same day. An hour later is already Dec 1 in JST.
        (datetime(2026, 11, 30, 14, 0, tzinfo=timezone.utc), True, 12),
        (datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc), False, 1),
    ]
    for now, proceed, month in cases:
        plan = plan_run.resolve_plan(now, "schedule", "", "", "")
        if plan.proceed is not proceed or plan.target_month != month or plan.dry_run:
            _fail(f"{now.isoformat()} -> proceed={plan.proceed} month={plan.target_month} dry={plan.dry_run}")
        if proceed and plan.skip_reason:
            _fail("successful schedule should not have a skip reason")
        if not proceed and "明日が1日ではない" not in plan.skip_reason:
            _fail(plan.skip_reason)


def test_manual_run_defaults_to_dry_run_and_next_month() -> None:
    now = datetime(2026, 11, 2, 20, 5, tzinfo=JST)
    plan = plan_run.resolve_plan(now, "workflow_dispatch", "", "", "")
    if not plan.proceed or not plan.dry_run or plan.target_month != 12 or plan.month_source != "computed":
        _fail(str(plan))

    override = plan_run.resolve_plan(now, "workflow_dispatch", "false", "1", "/custom/index.html")
    if override.dry_run or override.target_month != 1 or override.remote_path != "/custom/index.html":
        _fail(str(override))
    if override.month_source != "input" or override.computed_month != 12:
        _fail(str(override))

    try:
        plan_run.resolve_plan(now, "workflow_dispatch", "false", "13", "")
        _fail("month 13 should be rejected")
    except ValueError:
        pass

    padded = plan_run.resolve_plan(now, "workflow_dispatch", "true", "01", "")
    if padded.target_month != 1 or not padded.dry_run:
        _fail(str(padded))


def test_workflow_contract() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-monthly-title.yml").read_text(encoding="utf-8")
    required = [
        "contents: write",
        'cron: "0 14 28-31 * *"',
        "FTP_USERNAME",
        "FTP_PASSWORD",
        "default: true",
        "sv16829.xserver.jp",
        "/rmobile-point.com/public_html/index.html",
        "workflow_dispatch",
        "ftp_io.py",
    ]
    for snippet in required:
        if snippet not in workflow:
            _fail(f"workflow is missing {snippet}")
    if "echo \"$FTP_PASSWORD\"" in workflow or "echo \"$FTP_USERNAME\"" in workflow:
        _fail("workflow echoes FTP credentials")
    ftp_source = (ROOT / "scripts" / "ftp_io.py").read_text(encoding="utf-8")
    if "FTP_TLS" in ftp_source and "not used" not in ftp_source:
        _fail("FTP client must stay on plain FTP")
    if "set_pasv(True)" not in ftp_source:
        _fail("passive mode is not set")


def main() -> int:
    checks = [
        ("fixture 11→12", test_fixture_november_to_december),
        ("12→1 CRLF", test_wrap_december_to_january_preserves_crlf),
        ("9→10 and stray byte", test_nine_to_ten_inserts_one_digit_only),
        ("reject count other than 3", test_wrong_count_does_not_produce_output),
        ("reject invalid months", test_invalid_months_fail),
        ("schedule guard", test_schedule_guard),
        ("manual dry-run default", test_manual_run_defaults_to_dry_run_and_next_month),
        ("workflow contract", test_workflow_contract),
    ]
    diff = ""
    for name, check in checks:
        if check is test_fixture_november_to_december:
            diff = check()
        else:
            check()
        print(f"PASS {name}")
    test_cli_exit_codes(diff)
    print("PASS CLI exit codes")
    print()
    print("----- fixture diff (【11月最新】 → 【12月最新】) -----")
    sys.stdout.write(diff)
    if not diff.endswith("\n"):
        print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        sys.exit(1)
