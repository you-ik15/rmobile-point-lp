#!/usr/bin/env python3
"""Replace the three 【N月最新】 markers in index.html without touching other bytes.

The live page carries the marker in <title>, og:title, and twitter:title.
Anything other than exactly three matches is an error: callers must not upload.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

# ASCII digits only. Fullwidth numerals are left untouched and will fail the
# "exactly 3" check rather than being rewritten by accident.
PATTERN = re.compile("【([0-9]{1,2})月最新】".encode("utf-8"))


class ReplaceError(Exception):
    """The file must not be uploaded."""


def marker(month: int) -> bytes:
    if not 1 <= month <= 12:
        raise ReplaceError(f"月は 1 から 12 です（受け取った値: {month}）")
    return f"【{month}月最新】".encode("utf-8")


def replace_month_bytes(data: bytes, target_month: int) -> tuple[bytes, str]:
    """Return (new_bytes, status). status is 'updated' or 'noop'.

    On success, every byte outside the three markers is identical to `data`.
    A no-op returns the original bytes object unchanged.
    """
    replacement = marker(target_month)
    matches = list(PATTERN.finditer(data))
    if len(matches) != 3:
        found = ", ".join(m.group(1).decode("ascii") for m in matches) or "なし"
        raise ReplaceError(
            f"【N月最新】が {len(matches)} 件でした（ちょうど 3 件である必要があります）。"
            f"見つかった月: {found}。ファイルは変更していません。"
        )

    months = []
    for match in matches:
        month = int(match.group(1))
        if not 1 <= month <= 12:
            raise ReplaceError(
                f"【{month}月最新】は 1〜12 月ではないため中止しました。ファイルは変更していません。"
            )
        months.append(month)

    if all(month == target_month for month in months):
        return data, "noop"

    out = bytearray()
    cursor = 0
    for match in matches:
        out += data[cursor : match.start()]
        out += replacement
        cursor = match.end()
    out += data[cursor:]
    updated = bytes(out)

    new_matches = list(PATTERN.finditer(updated))
    if len(new_matches) != 3 or any(int(m.group(1)) != target_month for m in new_matches):
        raise ReplaceError("置換後の確認に失敗しました。結果は書き出していません。")
    if not _outside_unchanged(data, matches, updated, new_matches):
        raise ReplaceError("マーカー以外のバイトが変わったため中止しました。結果は書き出していません。")
    return updated, "updated"


def _outside_unchanged(old: bytes, old_matches: list[re.Match[bytes]], new: bytes, new_matches: list[re.Match[bytes]]) -> bool:
    old_at = 0
    new_at = 0
    for old_match, new_match in zip(old_matches, new_matches):
        if old[old_at : old_match.start()] != new[new_at : new_match.start()]:
            return False
        old_at = old_match.end()
        new_at = new_match.end()
    return old[old_at:] == new[new_at:]


def unified_diff(before: bytes, after: bytes) -> str:
    before_text = before.decode("utf-8", errors="surrogateescape")
    after_text = after.decode("utf-8", errors="surrogateescape")
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile="index.html (before)",
            tofile="index.html (after)",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace 【N月最新】 in an HTML file, preserving every other byte.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-month", required=True, type=int)
    parser.add_argument("--diff", type=Path, help="Write a unified diff to this path")
    args = parser.parse_args(argv)

    if args.input.resolve() == args.output.resolve():
        print("::error::入力と出力は別ファイルにしてください。原本を上書きしません。", file=sys.stderr)
        return 1
    if not args.input.is_file():
        print(f"::error::入力ファイルがありません: {args.input}", file=sys.stderr)
        return 1

    data = args.input.read_bytes()
    try:
        updated, status = replace_month_bytes(data, args.target_month)
    except ReplaceError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    # Write only after the checks above. No-op still copies the original bytes
    # so a later step can hash the proposed file, but the workflow must not upload.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(updated)
    diff = "" if status == "noop" else unified_diff(data, updated)
    if args.diff is not None:
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        args.diff.write_text(diff, encoding="utf-8", newline="\n")

    found = ",".join(str(int(m.group(1))) for m in PATTERN.finditer(data))
    print(f"STATUS={status} markers=3 months={found} target={args.target_month}")
    if diff:
        sys.stdout.write(diff)
    return 0 if status == "updated" else 2


if __name__ == "__main__":
    sys.exit(main())
