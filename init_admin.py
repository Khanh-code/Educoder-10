from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from auth import AuthError, AuthService


def main() -> None:
    parser = argparse.ArgumentParser(description="Khởi tạo quản trị viên đầu tiên của EDUCODER 10")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--name", default="Quản trị viên EDUCODER")
    parser.add_argument("--database", default=str(Path(__file__).parent / "data" / "educoder.db"))
    args = parser.parse_args()
    first = getpass.getpass("Mật khẩu admin (ít nhất 10 ký tự, gồm chữ và số): ")
    second = getpass.getpass("Nhập lại mật khẩu: ")
    if first != second:
        raise SystemExit("Hai mật khẩu không khớp.")
    try:
        user = AuthService(args.database).bootstrap_admin(args.username, args.name, first)
        print(f"Đã tạo admin: {user.username}")
    except AuthError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
