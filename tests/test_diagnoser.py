"""Kiểm thử bộ chẩn đoán lỗi: phải chỉ đúng dòng và đúng loại lỗi của học sinh."""
import unittest

from educoder_core import ContentRepository, DeterministicGrader

REPO = ContentRepository()
GRADER = DeterministicGrader()


def diag(exercise_id: str, code: str) -> dict:
    grade = GRADER.grade(REPO.exercise_by_id(exercise_id), code)
    assert not grade.passed, "Code mẫu sai lại được chấm đúng"
    assert grade.diagnosis, "Không có chẩn đoán"
    return grade.diagnosis


class DiagnoserTests(unittest.TestCase):
    def test_assign_instead_of_compare(self):
        d = diag("c01_even_odd", 'n = int(input())\nif n%2 = 0:\n    print("CHAN")\nelse: print("LE")\n')
        self.assertEqual(d["line"], 2)
        self.assertIn("==", d["fix"])
        self.assertEqual(d["example"], 'if n%2 == 0:')

    def test_missing_colon(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0\n    print('CHAN')\nelse:\n    print('LE')\n")
        self.assertEqual(d["line"], 2)
        self.assertIn(":", d["problem"])
        self.assertEqual(d["example"], "if n % 2 == 0:")

    def test_else_merged_on_one_line(self):
        # Học sinh viết gộp: dấu ':' phải ngay sau else, không phải cuối dòng
        code = 'n = int(input())\nif n == 0:\n    print("KHONG")\nelif n > 0:\n    print("DUONG")\nelse print("AM"):\n'
        d = diag("c02_positive", code)
        self.assertEqual(d["line"], 6)
        self.assertIn("ngay sau `else`", d["problem"])
        self.assertEqual(d["example"], 'else:\n    print("AM")')

    def test_if_merged_on_one_line(self):
        d = diag("c02_positive", 'n = int(input())\nif n == 0 print("KHONG")\nelif n > 0:\n    print("DUONG")\nelse:\n    print("AM")\n')
        self.assertEqual(d["line"], 2)
        self.assertEqual(d["example"], 'if n == 0:\n    print("KHONG")')

    def test_for_merged_on_one_line(self):
        d = diag("l01_sum_n", "n = int(input())\ns = 0\nfor i in range(1, n+1) s += i\nprint(s)\n")
        self.assertEqual(d["example"], "for i in range(1, n+1):\n    s += i")

    def test_examples_always_compile(self):
        """Mọi dòng sửa mẫu hiển thị cho học sinh phải được Python chấp nhận."""
        from error_diagnoser import _fixes_line
        broken = [
            ("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    if n > 0\n        print('CHAN')\n    else:\n        print('CHAN')\nelse:\n    print('LE')\n"),
            ("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    if n > 0:\n    print('CHAN')\n    else:\n        print('CHAN')\nelse:\n    print('LE')\n"),
            ("c01_even_odd", "n = int(input())\nIf n % 2 == 0:\n    print('CHAN')\nelse:\n    print('LE')\n"),
            ("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    print('CHAN'\nelse:\n    print('LE')\n"),
        ]
        for eid, code in broken:
            d = diag(eid, code)
            if d["example"]:
                lines = code.splitlines()
                indent = lines[d["line"] - 1][: len(lines[d["line"] - 1]) - len(lines[d["line"] - 1].lstrip())]
                ex = d["example"].split("\n")
                new = [(l if l.startswith(indent) and indent and l[:1] == " " else indent + l) if i == 0 or not l.startswith(indent) else l
                       for i, l in enumerate(ex)]
                if ex[0][:1] == " ":
                    new[0] = ex[0]
                self.assertTrue(_fixes_line(lines, d["line"], new), (code, d))

    def test_missing_indent(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0:\nprint('CHAN')\nelse:\n    print('LE')\n")
        self.assertEqual(d["line"], 3)
        self.assertTrue(d["example"].startswith("    print"))

    def test_missing_quotes(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    print(CHAN)\nelse:\n    print(LE)\n")
        self.assertEqual(d["line"], 3)
        self.assertIn("nháy", d["problem"])

    def test_typo_in_print(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    prnt('CHAN')\nelse:\n    print('LE')\n")
        self.assertIn("print", d["fix"])

    def test_forgot_int_conversion(self):
        d = diag("c01_even_odd", "n = input()\nif n % 2 == 0:\n    print('CHAN')\nelse:\n    print('LE')\n")
        self.assertIn("int(input())", d["fix"])

    def test_else_if(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    print('CHAN')\nelse if n % 2 == 1:\n    print('LE')\n")
        self.assertIn("elif", d["fix"])

    def test_lowercase_output(self):
        d = diag("c01_even_odd", "n = int(input())\nif n % 2 == 0:\n    print('chan')\nelse:\n    print('le')\n")
        self.assertIn("hoa/thường", d["problem"])

    def test_several_values_on_one_line(self):
        d = diag("v01_rectangle_area", "a = int(input())\nb = int(input())\nprint(a*b)\n")
        self.assertEqual(d["line"], 1)
        self.assertIn("split()", d["example"])

    def test_not_rounded(self):
        d = diag("v03_average", "a, b, c = map(float, input().split())\nprint((a+b+c)/3)\n")
        self.assertIn("round", d["fix"])

    def test_print_inside_loop(self):
        d = diag("l01_sum_n", "n = int(input())\ns = 0\nfor i in range(1, n+1):\n    s += i\n    print(s)\n")
        self.assertEqual(d["line"], 5)

    def test_off_by_one_range(self):
        d = diag("l01_sum_n", "n = int(input())\ns = 0\nfor i in range(1, n):\n    s += i\nprint(s)\n")
        self.assertIn("range", d["fix"])

    def test_infinite_while(self):
        d = diag("l03_digits", "n = int(input())\ns = 0\nwhile n > 0:\n    s += n % 10\nprint(s)\n")
        self.assertEqual(d["line"], 3)
        self.assertIn("`n`", d["problem"])

    def test_print_instead_of_return(self):
        d = diag("f01_square", "def square(x):\n    print(x*x)\n")
        self.assertEqual(d["line"], 2)
        self.assertEqual(d["example"], "return x*x")

    def test_function_wrong_value_shows_actual(self):
        d = diag("f03_gcd", "def gcd(a, b):\n    while b != 0:\n        a, b = b, a % b\n    return b\n")
        self.assertIn("`0`", d["problem"])
        self.assertIn("`6`", d["problem"])

    def test_hidden_test_is_not_revealed(self):
        d = diag("c02_positive", "n = int(input())\nif n >= 0:\n    print('DUONG')\nelif n < 0:\n    print('AM')\nelse:\n    print('KHONG')\n")
        self.assertIn("test ẩn", d["problem"])
        self.assertIn("số 0", d["problem"])
        self.assertNotIn("KHONG", d["problem"])

    def test_assertion_error_category(self):
        grade = GRADER.grade(REPO.exercise_by_id("f01_square"), "def square(x):\n    return x*2\n")
        self.assertEqual(grade.error_category, "AssertionError")


if __name__ == "__main__":
    unittest.main()
