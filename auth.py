"""Xác thực, RBAC và lưu hồ sơ cho EDUCODER 10.

Mọi hàm nhạy cảm nhận ``actor_id`` và tự kiểm tra quyền. Giao diện Streamlit
không phải là ranh giới bảo mật: ẩn nút không thay thế được kiểm tra phía dữ liệu.
SQLite phù hợp demo/một trường nhỏ; khi triển khai nhiều máy chủ nên chuyển sang
PostgreSQL và một nhà cung cấp danh tính OIDC.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLES = ("admin", "teacher", "student")
ROLE_LABELS = {"admin": "Quản trị viên", "teacher": "Giáo viên", "student": "Học sinh"}


class AuthError(Exception):
    pass


class PermissionDenied(AuthError):
    pass


class ValidationError(AuthError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool


class PasswordHasher:
    """Ưu tiên Argon2 qua pwdlib; scrypt chỉ là fallback không phụ thuộc gói."""

    def __init__(self):
        try:
            from pwdlib import PasswordHash

            self._pwd = PasswordHash.recommended()
        except ImportError:
            self._pwd = None

    def hash(self, password: str) -> str:
        self.validate(password)
        if self._pwd:
            return self._pwd.hash(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()

    def verify(self, password: str, encoded: str) -> bool:
        if encoded.startswith("$argon2") and self._pwd:
            try:
                return bool(self._pwd.verify(password, encoded))
            except Exception:
                return False
        try:
            algorithm, n, r, p, salt64, digest64 = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            salt = base64.b64decode(salt64)
            expected = base64.b64decode(digest64)
            actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate(password: str) -> None:
        # Demo: cho phép mật khẩu từ 6 ký tự
        if len(password) < 6:
            raise ValidationError("Mật khẩu phải có ít nhất 6 ký tự.")
class AuthService:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.passwords = PasswordHasher()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    teacher_id INTEGER NOT NULL REFERENCES users(id),
                    join_code TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS class_members (
                    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(class_id, student_id)
                );
                CREATE TABLE IF NOT EXISTS learning_profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id INTEGER REFERENCES users(id),
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _normalize_username(username: str) -> str:
        value = username.strip().lower()
        if not (3 <= len(value) <= 50) or not all(c.isalnum() or c in "._-" for c in value):
            raise ValidationError("Tên đăng nhập dài 3–50 ký tự, chỉ gồm chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")
        return value

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        if not row:
            return None
        return User(row["id"], row["username"], row["full_name"], row["role"], bool(row["is_active"]), bool(row["must_change_password"]))

    def has_users(self) -> bool:
        with self._connect() as db:
            return bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def bootstrap_admin(self, username: str, full_name: str, password: str) -> User:
        with self._connect() as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise PermissionDenied("Hệ thống đã có tài khoản; không thể khởi tạo admin lần nữa.")
            now = self._now()
            cur = db.execute(
                "INSERT INTO users(username,password_hash,full_name,role,is_active,must_change_password,created_at,updated_at) VALUES(?,?,?,?,1,0,?,?)",
                (self._normalize_username(username), self.passwords.hash(password), full_name.strip() or "Quản trị viên", "admin", now, now),
            )
            user_id = int(cur.lastrowid)
            self._audit(db, user_id, "bootstrap_admin", "user", user_id)
        return self.get_user(user_id)  # type: ignore[return-value]

    def authenticate(self, username: str, password: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not row or not bool(row["is_active"]) or not self.passwords.verify(password, row["password_hash"]):
            return None
        return self._user(row)

    def get_user(self, user_id: int) -> User | None:
        with self._connect() as db:
            return self._user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def _require(self, actor_id: int, roles: set[str]) -> User:
        actor = self.get_user(actor_id)
        if not actor or not actor.is_active or actor.role not in roles:
            raise PermissionDenied("Bạn không có quyền thực hiện thao tác này.")
        return actor

    def _audit(self, db: sqlite3.Connection, actor_id: int | None, action: str, target_type: str, target_id: Any = None, details: dict | None = None) -> None:
        db.execute(
            "INSERT INTO audit_logs(actor_id,action,target_type,target_id,details_json,created_at) VALUES(?,?,?,?,?,?)",
            (actor_id, action, target_type, None if target_id is None else str(target_id), json.dumps(details or {}, ensure_ascii=False), self._now()),
        )

    def create_user(self, actor_id: int, username: str, full_name: str, role: str, password: str) -> User:
        self._require(actor_id, {"admin"})
        if role not in ROLES:
            raise ValidationError("Vai trò không hợp lệ.")
        now = self._now()
        try:
            with self._connect() as db:
                cur = db.execute(
                    "INSERT INTO users(username,password_hash,full_name,role,is_active,must_change_password,created_at,updated_at) VALUES(?,?,?,?,1,1,?,?)",
                    (self._normalize_username(username), self.passwords.hash(password), full_name.strip() or username.strip(), role, now, now),
                )
                user_id = int(cur.lastrowid)
                self._audit(db, actor_id, "create_user", "user", user_id, {"role": role})
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Tên đăng nhập đã tồn tại.") from exc
        return self.get_user(user_id)  # type: ignore[return-value]

    def list_users(self, actor_id: int) -> list[dict[str, Any]]:
        self._require(actor_id, {"admin"})
        with self._connect() as db:
            rows = db.execute("SELECT id,username,full_name,role,is_active,must_change_password,created_at FROM users ORDER BY role,full_name").fetchall()
        return [dict(row) for row in rows]

    def set_user_status(self, actor_id: int, target_id: int, is_active: bool) -> None:
        self._require(actor_id, {"admin"})
        if actor_id == target_id and not is_active:
            raise ValidationError("Không thể tự khóa tài khoản đang đăng nhập.")
        target = self.get_user(target_id)
        if not target:
            raise ValidationError("Không tìm thấy tài khoản.")
        if target.role == "admin" and not is_active:
            with self._connect() as db:
                active_admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]
            if active_admins <= 1:
                raise ValidationError("Không thể khóa quản trị viên hoạt động cuối cùng.")
        with self._connect() as db:
            db.execute("UPDATE users SET is_active=?,updated_at=? WHERE id=?", (int(is_active), self._now(), target_id))
            self._audit(db, actor_id, "set_user_status", "user", target_id, {"is_active": is_active})

    def set_role(self, actor_id: int, target_id: int, role: str) -> None:
        self._require(actor_id, {"admin"})
        if role not in ROLES:
            raise ValidationError("Vai trò không hợp lệ.")
        target = self.get_user(target_id)
        if not target:
            raise ValidationError("Không tìm thấy tài khoản.")
        if target.role == "teacher" and role != "teacher":
            with self._connect() as db:
                owned_classes = db.execute("SELECT COUNT(*) FROM classes WHERE teacher_id=?", (target_id,)).fetchone()[0]
            if owned_classes:
                raise ValidationError("Giáo viên đang phụ trách lớp; hãy chuyển lớp cho giáo viên khác trước khi đổi vai trò.")
        if target.role == "admin" and role != "admin":
            with self._connect() as db:
                if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0] <= 1:
                    raise ValidationError("Phải còn ít nhất một quản trị viên hoạt động.")
        with self._connect() as db:
            db.execute("UPDATE users SET role=?,updated_at=? WHERE id=?", (role, self._now(), target_id))
            self._audit(db, actor_id, "set_role", "user", target_id, {"old": target.role, "new": role})

    def reset_password(self, actor_id: int, target_id: int, temporary_password: str) -> None:
        self._require(actor_id, {"admin"})
        if not self.get_user(target_id):
            raise ValidationError("Không tìm thấy tài khoản.")
        with self._connect() as db:
            db.execute("UPDATE users SET password_hash=?,must_change_password=1,updated_at=? WHERE id=?", (self.passwords.hash(temporary_password), self._now(), target_id))
            self._audit(db, actor_id, "reset_password", "user", target_id)

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        user = self.get_user(user_id)
        if not user or not self.authenticate(user.username, current_password):
            raise ValidationError("Mật khẩu hiện tại không đúng.")
        with self._connect() as db:
            db.execute("UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?", (self.passwords.hash(new_password), self._now(), user_id))
            self._audit(db, user_id, "change_password", "user", user_id)

    def create_class(self, actor_id: int, name: str, teacher_id: int | None = None) -> dict[str, Any]:
        """Chỉ ADMIN được tạo lớp và phân công giáo viên phụ trách (teacher_id)."""
        admin = self._require(actor_id, {"admin"})
        if not name.strip():
            raise ValidationError("Tên lớp không được để trống.")
        teacher = self.get_user(teacher_id) if teacher_id else admin
        if not teacher or not teacher.is_active or teacher.role not in {"teacher", "admin"}:
            raise ValidationError("Giáo viên phụ trách phải tồn tại, đang hoạt động và có vai trò giáo viên.")
        code = secrets.token_hex(3).upper()
        with self._connect() as db:
            cur = db.execute("INSERT INTO classes(name,teacher_id,join_code,created_at) VALUES(?,?,?,?)", (name.strip(), teacher.id, code, self._now()))
            class_id = int(cur.lastrowid)
            self._audit(db, actor_id, "create_class", "class", class_id, {"name": name.strip()})
        return {"id": class_id, "name": name.strip(), "join_code": code}

    def add_student_to_class(self, actor_id: int, class_id: int, student_id: int) -> None:
        """Chỉ ADMIN được đưa học sinh vào lớp (học sinh không tự vào lớp bằng mã)."""
        self._require(actor_id, {"admin"})
        student = self.get_user(student_id)
        if not student or student.role != "student":
            raise ValidationError("Chỉ có thể thêm tài khoản học sinh vào lớp.")
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM classes WHERE id=?", (class_id,)).fetchone():
                raise ValidationError("Không tìm thấy lớp.")
            db.execute("INSERT OR IGNORE INTO class_members(class_id,student_id,joined_at) VALUES(?,?,?)", (class_id, student_id, self._now()))
            self._audit(db, actor_id, "add_student_to_class", "class", class_id, {"student_id": student_id})

    def list_classes(self, actor_id: int) -> list[dict[str, Any]]:
        actor = self._require(actor_id, {"admin", "teacher", "student"})
        with self._connect() as db:
            if actor.role == "admin":
                rows = db.execute("SELECT c.*,u.full_name teacher_name,(SELECT COUNT(*) FROM class_members m WHERE m.class_id=c.id) student_count FROM classes c JOIN users u ON u.id=c.teacher_id ORDER BY c.name").fetchall()
            elif actor.role == "teacher":
                rows = db.execute("SELECT c.*,u.full_name teacher_name,(SELECT COUNT(*) FROM class_members m WHERE m.class_id=c.id) student_count FROM classes c JOIN users u ON u.id=c.teacher_id WHERE c.teacher_id=? ORDER BY c.name", (actor_id,)).fetchall()
            else:
                rows = db.execute("SELECT c.*,u.full_name teacher_name,(SELECT COUNT(*) FROM class_members m WHERE m.class_id=c.id) student_count FROM classes c JOIN users u ON u.id=c.teacher_id JOIN class_members cm ON cm.class_id=c.id WHERE cm.student_id=? ORDER BY c.name", (actor_id,)).fetchall()
        return [dict(row) for row in rows]

    def reassign_class(self, actor_id: int, class_id: int, teacher_id: int) -> None:
        self._require(actor_id, {"admin"})
        teacher = self.get_user(teacher_id)
        if not teacher or not teacher.is_active or teacher.role != "teacher":
            raise ValidationError("Giáo viên nhận lớp phải tồn tại, đang hoạt động và có vai trò giáo viên.")
        with self._connect() as db:
            classroom = db.execute("SELECT teacher_id FROM classes WHERE id=?", (class_id,)).fetchone()
            if not classroom:
                raise ValidationError("Không tìm thấy lớp.")
            db.execute("UPDATE classes SET teacher_id=? WHERE id=?", (teacher_id, class_id))
            self._audit(db, actor_id, "reassign_class", "class", class_id, {"old_teacher_id": classroom["teacher_id"], "new_teacher_id": teacher_id})

    def class_students(self, actor_id: int, class_id: int) -> list[dict[str, Any]]:
        actor = self._require(actor_id, {"admin", "teacher"})
        with self._connect() as db:
            classroom = db.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
            if not classroom or (actor.role == "teacher" and classroom["teacher_id"] != actor_id):
                raise PermissionDenied("Bạn không quản lý lớp này.")
            rows = db.execute(
                "SELECT u.id,u.username,u.full_name,p.state_json,p.updated_at FROM class_members m JOIN users u ON u.id=m.student_id LEFT JOIN learning_profiles p ON p.user_id=u.id WHERE m.class_id=? ORDER BY u.full_name",
                (class_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            state = json.loads(item.pop("state_json")) if item.get("state_json") else {}
            item["solved"] = len(state.get("solved_ids", []))
            item["attempts"] = sum(state.get("attempts", {}).values())
            mastery = state.get("mastery", {})
            item["average_mastery"] = round(100 * sum(mastery.values()) / max(len(mastery), 1)) if mastery else 0
            result.append(item)
        return result

    def save_profile(self, actor_id: int, target_id: int, state: dict[str, Any]) -> None:
        actor = self._require(actor_id, {"student", "admin"})
        if actor.role == "student" and actor_id != target_id:
            raise PermissionDenied("Học sinh chỉ được cập nhật hồ sơ của mình.")
        with self._connect() as db:
            db.execute(
                "INSERT INTO learning_profiles(user_id,state_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at",
                (target_id, json.dumps(state, ensure_ascii=False), self._now()),
            )

    def load_profile(self, actor_id: int, target_id: int) -> dict[str, Any] | None:
        actor = self._require(actor_id, {"student", "teacher", "admin"})
        if actor.role == "student" and actor_id != target_id:
            raise PermissionDenied("Học sinh chỉ được xem hồ sơ của mình.")
        if actor.role == "teacher":
            with self._connect() as db:
                allowed = db.execute("SELECT 1 FROM classes c JOIN class_members m ON m.class_id=c.id WHERE c.teacher_id=? AND m.student_id=?", (actor_id, target_id)).fetchone()
            if not allowed:
                raise PermissionDenied("Học sinh không thuộc lớp bạn phụ trách.")
        with self._connect() as db:
            row = db.execute("SELECT state_json FROM learning_profiles WHERE user_id=?", (target_id,)).fetchone()
        return json.loads(row["state_json"]) if row else None

    def audit_logs(self, actor_id: int, limit: int = 100) -> list[dict[str, Any]]:
        self._require(actor_id, {"admin"})
        with self._connect() as db:
            rows = db.execute("SELECT a.id,u.username actor,a.action,a.target_type,a.target_id,a.details_json,a.created_at FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT ?", (min(max(limit, 1), 500),)).fetchall()
        return [dict(row) for row in rows]


def generate_temporary_password() -> str:
    return "Edu-" + secrets.token_urlsafe(8) + "7"
