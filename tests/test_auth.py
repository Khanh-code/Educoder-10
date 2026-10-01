from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auth import AuthService, PermissionDenied, ValidationError


class AuthAndRBACTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = AuthService(Path(self.tmp.name) / "test.db")
        self.admin = self.auth.bootstrap_admin("admin", "Admin", "AdminPass123")
        self.teacher = self.auth.create_user(self.admin.id, "teacher1", "Cô An", "teacher", "Teacher1234")
        self.student = self.auth.create_user(self.admin.id, "student1", "Bạn Bình", "student", "Student1234")

    def tearDown(self):
        self.tmp.cleanup()

    def test_authentication_and_wrong_password(self):
        self.assertEqual(self.auth.authenticate("student1", "Student1234").id, self.student.id)
        self.assertIsNone(self.auth.authenticate("student1", "wrong-password"))

    def test_teacher_cannot_create_accounts(self):
        with self.assertRaises(PermissionDenied):
            self.auth.create_user(self.teacher.id, "xstudent", "X", "student", "Password1234")

    def test_teacher_sees_only_own_class_students(self):
        classroom = self.auth.create_class(self.admin.id, "10A1", self.teacher.id)
        self.auth.add_student_to_class(self.admin.id, classroom["id"], self.student.id)
        rows = self.auth.class_students(self.teacher.id, classroom["id"])
        self.assertEqual([x["username"] for x in rows], ["student1"])

        teacher2 = self.auth.create_user(self.admin.id, "teacher2", "Thầy B", "teacher", "Teacher5678")
        with self.assertRaises(PermissionDenied):
            self.auth.class_students(teacher2.id, classroom["id"])

        with self.assertRaises(ValidationError):
            self.auth.set_role(self.admin.id, self.teacher.id, "student")

        self.auth.reassign_class(self.admin.id, classroom["id"], teacher2.id)
        self.assertEqual(self.auth.class_students(teacher2.id, classroom["id"])[0]["username"], "student1")

    def test_only_admin_can_create_class(self):
        with self.assertRaises(PermissionDenied):
            self.auth.create_class(self.teacher.id, "Lớp tự tạo")
        with self.assertRaises(PermissionDenied):
            self.auth.create_class(self.student.id, "Lớp tự tạo")
        with self.assertRaises(ValidationError):
            self.auth.create_class(self.admin.id, "10A2", self.student.id)  # phụ trách phải là giáo viên
        classroom = self.auth.create_class(self.admin.id, "10A2", self.teacher.id)
        self.assertEqual([c["name"] for c in self.auth.list_classes(self.teacher.id)], ["10A2"])
        self.assertTrue(classroom["join_code"])

    def test_only_admin_can_add_students_to_class(self):
        classroom = self.auth.create_class(self.admin.id, "10A3", self.teacher.id)
        with self.assertRaises(PermissionDenied):
            self.auth.add_student_to_class(self.student.id, classroom["id"], self.student.id)
        with self.assertRaises(PermissionDenied):
            self.auth.add_student_to_class(self.teacher.id, classroom["id"], self.student.id)
        with self.assertRaises(ValidationError):
            self.auth.add_student_to_class(self.admin.id, classroom["id"], self.teacher.id)
        self.auth.add_student_to_class(self.admin.id, classroom["id"], self.student.id)
        self.assertEqual([c["name"] for c in self.auth.list_classes(self.student.id)], ["10A3"])

    def test_student_cannot_read_other_profile(self):
        student2 = self.auth.create_user(self.admin.id, "student2", "Bạn C", "student", "Student5678")
        with self.assertRaises(PermissionDenied):
            self.auth.load_profile(self.student.id, student2.id)

    def test_cannot_disable_last_admin(self):
        with self.assertRaises(ValidationError):
            self.auth.set_user_status(self.admin.id, self.admin.id, False)


if __name__ == "__main__":
    unittest.main()
