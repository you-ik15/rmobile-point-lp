#!/usr/bin/env python3
"""Decide whether this Actions run should update the site, and to which month.

Scheduled runs proceed only when tomorrow in Asia/Tokyo is the 1st
(the cron itself fires at 23:00 JST on the 28th–31st). The month written
into the page is the next calendar month in Asia/Tokyo, unless a manual
run passes target_month.

Manual runs default to a dry run. Only an explicit dry_run=false uploads.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_REMOTE_PATH = "/rmobile-point.com/public_html/index.html"


@dataclass(frozen=True)
class Plan:
    proceed: bool
    dry_run: bool
    target_month: int
    computed_month: int
    month_source: str
    remote_path: str
    stamp: str
    now_jst: str
    skip_reason: str


def next_month_number(now: datetime) -> int:
    if now.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    local = now.astimezone(JST)
    return 1 if local.month == 12 else local.month + 1


def tomorrow_is_first(now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    local = now.astimezone(JST)
    return (local + timedelta(days=1)).day == 1


def resolve_plan(
    now: datetime,
    event_name: str,
    dry_run_raw: str,
    target_month_raw: str,
    remote_path_raw: str,
    default_remote_path: str = DEFAULT_REMOTE_PATH,
) -> Plan:
    local = now.astimezone(JST)
    computed = next_month_number(local)
    target_text = target_month_raw.strip()
    if target_text:
        if not re.fullmatch(r"0?[1-9]|1[0-2]", target_text):
            raise ValueError(f"target_month は 1〜12 の整数にしてください（受け取った値: {target_text!r}）")
        target = int(target_text)
        month_source = "input"
    else:
        target = computed
        month_source = "computed"

    remote = remote_path_raw.strip() or default_remote_path.strip()
    if not remote or any(ord(ch) < 32 for ch in remote):
        raise ValueError("FTP のリモートパスが空か、制御文字を含んでいます。")

    if event_name == "schedule":
        # A schedule must never upload on the 28th–30th of a 31-day month.
        proceed = tomorrow_is_first(local)
        dry_run = False
        skip_reason = "" if proceed else "日本時間で明日が1日ではないため、定時実行をスキップしました。"
    elif event_name == "workflow_dispatch":
        proceed = True
        dry_run = _parse_dry_run(dry_run_raw, default=True)
        skip_reason = ""
    else:
        # Unknown triggers stay on the safe side: show the diff, do not upload.
        proceed = True
        dry_run = True
        skip_reason = ""

    return Plan(
        proceed=proceed,
        dry_run=dry_run,
        target_month=target,
        computed_month=computed,
        month_source=month_source,
        remote_path=remote,
        stamp=local.strftime("%Y-%m-%d_%H%M"),
        now_jst=local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        skip_reason=skip_reason,
    )


def _parse_dry_run(raw: str, default: bool) -> bool:
    text = raw.strip().lower()
    if text == "":
        return default
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"dry_run は true または false にしてください（受け取った値: {raw!r}）")


def _write_output(name: str, value: str) -> None:
    """Write a single-line output. Multiline values would change the comparison in the workflow."""
    if any(ord(char) < 32 for char in f"{name}{value}"):
        raise ValueError(f"output {name} contains a control character")
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _write_summary(plan: Plan) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    mode = "dry run（アップロードしない・コミットしない）" if plan.dry_run else "本番（FTP へアップロードし、main へコミット）"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("## 実行パラメータ\n\n")
        handle.write(f"- 時刻 (JST): {plan.now_jst}\n")
        handle.write(f"- モード: {mode}\n")
        handle.write(f"- 対象月: {plan.target_month}（{plan.month_source}、日本時間の翌月は {plan.computed_month}）\n")
        handle.write(f"- リモートパス: `{plan.remote_path}`\n")
        if not plan.proceed:
            handle.write(f"\n## スキップ\n\n{plan.skip_reason}\n")


def main() -> int:
    try:
        plan = resolve_plan(
            now=datetime.now(JST),
            event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
            dry_run_raw=os.environ.get("INPUT_DRY_RUN", ""),
            target_month_raw=os.environ.get("INPUT_TARGET_MONTH", ""),
            remote_path_raw=os.environ.get("INPUT_REMOTE_PATH", ""),
            default_remote_path=os.environ.get("FTP_REMOTE_PATH", DEFAULT_REMOTE_PATH),
        )
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    _write_output("proceed", "true" if plan.proceed else "false")
    _write_output("dry_run", "true" if plan.dry_run else "false")
    _write_output("target_month", str(plan.target_month))
    _write_output("computed_month", str(plan.computed_month))
    _write_output("month_source", plan.month_source)
    _write_output("remote_path", plan.remote_path)
    _write_output("stamp", plan.stamp)
    _write_summary(plan)

    print(
        "PLAN"
        f" proceed={str(plan.proceed).lower()}"
        f" dry_run={str(plan.dry_run).lower()}"
        f" target_month={plan.target_month}"
        f" month_source={plan.month_source}"
        f" stamp={plan.stamp}"
        f" remote_path={plan.remote_path}"
    )
    if plan.skip_reason:
        print(plan.skip_reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
