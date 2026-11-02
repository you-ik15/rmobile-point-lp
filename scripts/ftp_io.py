#!/usr/bin/env python3
"""Download or upload one file over plain FTP (port 21, passive mode).

Credentials come from FTP_USERNAME and FTP_PASSWORD. They are never printed.
FTP_TLS is intentionally not used: the host expects plain FTP.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from ftplib import FTP, error_perm
from pathlib import Path


def _error(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    print(f"ERROR: {message}", file=sys.stderr)


def _require_config() -> tuple[str, int, str, str, str]:
    host = os.environ.get("FTP_HOST", "").strip()
    port_text = os.environ.get("FTP_PORT", "21").strip() or "21"
    user = os.environ.get("FTP_USERNAME", "")
    password = os.environ.get("FTP_PASSWORD", "")
    remote = os.environ.get("FTP_REMOTE_PATH", "").strip()

    missing = [
        name
        for name, value in (
            ("FTP_HOST", host),
            ("FTP_USERNAME", user),
            ("FTP_PASSWORD", password),
            ("FTP_REMOTE_PATH", remote),
        )
        if value == ""
    ]
    if missing:
        hint = ""
        if "FTP_USERNAME" in missing or "FTP_PASSWORD" in missing:
            hint = " Settings → Secrets and variables → Actions に FTP_USERNAME と FTP_PASSWORD を登録してください。"
        _error("必要な設定がありません: " + ", ".join(missing) + "。" + hint)
        sys.exit(1)
    if any(char in user or char in password for char in "\r\n"):
        _error("FTP の認証情報に改行が含まれているため接続しませんでした。")
        sys.exit(1)
    if any(ord(char) < 32 for char in remote):
        _error("FTP_REMOTE_PATH に制御文字が含まれています。")
        sys.exit(1)
    try:
        port = int(port_text)
    except ValueError:
        _error("FTP_PORT は整数にしてください。")
        sys.exit(1)
    return host, port, user, password, remote


def _connect() -> tuple[FTP, str, str]:
    host, port, user, password, remote = _require_config()
    ftp = FTP()
    try:
        ftp.connect(host, port, timeout=120)
        ftp.set_pasv(True)
        ftp.login(user, password)
    except error_perm:
        _close(ftp)
        _error("FTP ログインに失敗しました。シークレット FTP_USERNAME と FTP_PASSWORD を確認してください。")
        sys.exit(1)
    except OSError as exc:
        _close(ftp)
        _error(f"{host}:{port} に接続できませんでした（{exc.__class__.__name__}）。")
        sys.exit(1)
    # set_pasv again after login; some servers reset mode.
    ftp.set_pasv(True)
    return ftp, host, remote


def _close(ftp: FTP) -> None:
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(dest: Path, *, purpose: str = "download") -> None:
    ftp, host, remote = _connect()
    partial = dest.with_name(dest.name + ".partial")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with partial.open("wb") as handle:
                ftp.retrbinary(f"RETR {remote}", handle.write)
        except error_perm as exc:
            reply = str(exc).splitlines()[0][:300]
            if reply.startswith("550"):
                if purpose == "download":
                    follow = "アップロードは行っていません。env の FTP_REMOTE_PATH か、手動実行の remote_path を確認してください。"
                else:
                    follow = "アップロード後の再取得に失敗しました。Actions の artifact backup-before-upload から戻してください。"
                _error(f"リモートファイルが見つかりません: {remote} （{host}）。{follow} FTP応答: {reply}")
            else:
                _error(f"FTP ダウンロードに失敗しました: {remote} （{host}）。FTP応答: {reply}")
            sys.exit(1)
        os.replace(partial, dest)
    finally:
        if partial.exists():
            partial.unlink()
        _close(ftp)

    data = dest.read_bytes()
    if not data:
        _error(f"ダウンロード結果が空です: {remote} （{host}）。パスがファイルを指しているか確認してください。")
        sys.exit(1)
    print(f"DOWNLOADED bytes={len(data)} sha256={_sha256(data)} path={remote} host={host} passive=true")


def upload(src: Path) -> None:
    if not src.is_file():
        _error(f"アップロードするローカルファイルがありません: {src}")
        sys.exit(1)
    data = src.read_bytes()
    if not data:
        _error("空のファイルはアップロードしません。")
        sys.exit(1)
    ftp, host, remote = _connect()
    try:
        try:
            with src.open("rb") as handle:
                ftp.storbinary(f"STOR {remote}", handle)
        except error_perm as exc:
            reply = str(exc).splitlines()[0][:300]
            _error(f"FTP アップロードに失敗しました: {remote} （{host}）。FTP応答: {reply}")
            sys.exit(1)
    finally:
        _close(ftp)
    print(f"UPLOADED bytes={len(data)} sha256={_sha256(data)} path={remote} host={host} passive=true")


def verify(expected: Path) -> None:
    if not expected.is_file():
        _error(f"照合元ファイルがありません: {expected}")
        sys.exit(1)
    actual = expected.with_name(expected.name + ".remote")
    download(actual, purpose="verify")
    left = expected.read_bytes()
    right = actual.read_bytes()
    if left != right:
        _error(
            "再ダウンロードしたファイルがアップロード内容と一致しません。"
            f" local={len(left)}:{_sha256(left)} remote={len(right)}:{_sha256(right)}"
        )
        sys.exit(1)
    print(f"VERIFIED bytes={len(left)} sha256={_sha256(left)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plain passive FTP download, upload, or verify.")
    sub = parser.add_subparsers(dest="action", required=True)

    download_cmd = sub.add_parser("download")
    download_cmd.add_argument("path", type=Path)

    upload_cmd = sub.add_parser("upload")
    upload_cmd.add_argument("path", type=Path)

    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.action == "download":
        download(args.path)
    elif args.action == "upload":
        upload(args.path)
    else:
        verify(args.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
