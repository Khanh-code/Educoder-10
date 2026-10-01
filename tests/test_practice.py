"""Kiểm thử tính năng Luyện tập thêm: bài AI sinh ra phải qua kiểm chứng, bài 'ảo' bị loại."""
import unittest

from educoder_core import (
    ContentRepository,
    DeterministicGrader,
    OptionalLLM,
    build_verified_practice,
    generate_practice_exercise,
)

REPO = ContentRepository()
GRADER = DeterministicGrader()
IO_BASE = REPO.exercise_by_id("c02_positive")
FN_BASE = REPO.exercise_by_id("f03_gcd")  # hàm 2 tham số số nguyên

GOOD_IO = {
    "title": "Nhiệt độ",
    "description": "Nhập nhiệt độ t (số nguyên). In NONG nếu t > 30, LANH nếu t < 15, còn lại in MAT.",
    "starter_code": "t = int(input())\n# Viết if-elif-else\n",
    "reference_solution": "t = int(input())\nif t > 30:\n    print('NONG')\nelif t < 15:\n    print('LANH')\nelse:\n    print('MAT')\n",
    "hints": ["a", "b", "c"],
    "tests": [
        {"input": "35\n", "expected": "NONG"},
        {"input": "10\n", "expected": "LANH"},
        {"input": "20\n", "expected": "MAT"},
        {"input": "30\n", "expected": "MAT"},
    ],
}

GOOD_FN = {
    "title": "Số lớn hơn",
    "description": "Viết hàm lon_hon(a, b) trả về số lớn hơn, không dùng max().",
    "function_name": "lon_hon",
    "starter_code": "def lon_hon(a, b):\n    pass\n",
    "reference_solution": "def lon_hon(a, b):\n    if a > b:\n        return a\n    return b\n",
    "hints": ["a"],
    "tests": [
        {"call": "lon_hon(3, 5)", "expected": "5"},
        {"call": "lon_hon(-1, -7)", "expected": "-1"},
        {"call": "lon_hon(4, 4)", "expected": "4"},
    ],
}


EVEN_ODD_BASE = REPO.exercise_by_id("c01_even_odd")
HARDER_THAN_BASE = {  # lỗi thực tế: bài chẵn/lẻ (1 số, if-else) lại sinh ra bài "số lớn nhất của dãy"
    "title": "Số lớn nhất",
    "description": "Nhập một dãy số nguyên cách nhau bởi dấu cách. In số lớn nhất.",
    "starter_code": "chuoi_so = input()\n",
    "reference_solution": "chuoi_so = input()\nds = list(map(int, chuoi_so.split()))\nprint(max(ds))\n",
    "tests": [
        {"input": "2 3 5 1 4\n", "expected": "5"},
        {"input": "10 10 10 10\n", "expected": "10"},
        {"input": "-1 -5\n", "expected": "-1"},
    ],
}
SAME_LEVEL = {
    "title": "Chia hết cho 3",
    "description": "Nhập số nguyên n. In CO nếu n chia hết cho 3, ngược lại in KHONG.",
    "starter_code": "n = int(input())\n",
    "reference_solution": "n = int(input())\nif n % 3 == 0:\n    print('CO')\nelse:\n    print('KHONG')\n",
    "tests": [
        {"input": "9\n", "expected": "CO"},
        {"input": "7\n", "expected": "KHONG"},
        {"input": "0\n", "expected": "CO"},
    ],
}


class FakeLLM(OptionalLLM):
    def __init__(self, replies):
        super().__init__()
        self.endpoint = self.api_key = self.model = "fake"
        self.replies = list(replies)
        self.calls = 0

    def _json_chat(self, system, user, temperature=0.2):
        self.calls += 1
        self.last_call_ok = True
        return self.replies.pop(0) if self.replies else None


class PracticeTests(unittest.TestCase):
    def test_good_io_exercise_is_accepted_with_executed_outputs(self):
        ex, reason = build_verified_practice(GOOD_IO, IO_BASE, GRADER)
        self.assertIsNotNone(ex, reason)
        self.assertEqual([t["output"] for t in ex["tests"]], ["NONG", "LANH", "MAT", "MAT"])
        self.assertTrue(ex["is_practice"])

    def test_good_function_exercise_builds_asserts(self):
        ex, reason = build_verified_practice(GOOD_FN, FN_BASE, GRADER)
        self.assertIsNotNone(ex, reason)
        self.assertEqual(ex["tests"][0]["assert"], "assert lon_hon(3, 5) == 5")
        student = "def lon_hon(a, b):\n    return a if a > b else b\n"
        self.assertTrue(GRADER.grade(ex, student).passed)
        self.assertFalse(GRADER.grade(ex, "def lon_hon(a, b):\n    return a\n").passed)

    def test_hallucinated_expected_output_is_rejected(self):
        bad = {**GOOD_IO, "tests": [dict(t) for t in GOOD_IO["tests"]]}
        bad["tests"][3]["expected"] = "NONG"  # AI ghi sai: 30 không > 30
        ex, reason = build_verified_practice(bad, IO_BASE, GRADER)
        self.assertIsNone(ex)
        self.assertIn("chạy thật", reason)

    def test_hallucinated_function_value_is_rejected(self):
        bad = {**GOOD_FN, "tests": [dict(t) for t in GOOD_FN["tests"]]}
        bad["tests"][1]["expected"] = "-7"
        self.assertIsNone(build_verified_practice(bad, FN_BASE, GRADER)[0])

    def test_unsafe_test_call_is_rejected(self):
        bad = {**GOOD_FN, "tests": [{"call": "__import__('os').system('dir')", "expected": "0"}] * 3}
        self.assertIsNone(build_verified_practice(bad, FN_BASE, GRADER)[0])

    def test_broken_reference_solution_is_rejected(self):
        bad = {**GOOD_IO, "reference_solution": "t = int(input())\nprint('NONG' if t > 30 else 'MAT'"}
        self.assertIsNone(build_verified_practice(bad, IO_BASE, GRADER)[0])

    def test_single_output_test_set_is_rejected(self):
        bad = {**GOOD_IO, "tests": [{"input": "40\n", "expected": "NONG"}] * 3}
        self.assertIsNone(build_verified_practice(bad, IO_BASE, GRADER)[0])

    def test_starter_that_already_passes_is_rejected(self):
        bad = {**GOOD_IO, "starter_code": GOOD_IO["reference_solution"]}
        self.assertIsNone(build_verified_practice(bad, IO_BASE, GRADER)[0])

    def test_generator_retries_until_a_verified_exercise(self):
        wrong = {**GOOD_IO, "tests": [dict(t) for t in GOOD_IO["tests"]]}
        wrong["tests"][0]["expected"] = "LANH"
        llm = FakeLLM([wrong, GOOD_IO])
        ex, reason = generate_practice_exercise(llm, GRADER, IO_BASE)
        self.assertIsNotNone(ex, reason)
        self.assertEqual(llm.calls, 2)

    def test_harder_exercise_than_base_is_rejected(self):
        ex, reason = build_verified_practice(HARDER_THAN_BASE, EVEN_ODD_BASE, GRADER)
        self.assertIsNone(ex)
        self.assertIn("chưa học", reason)

    def test_more_input_values_than_base_is_rejected(self):
        many = {**SAME_LEVEL,
                "reference_solution": "a, b = map(int, input().split())\nif a > b:\n    print('CO')\nelse:\n    print('KHONG')\n",
                "tests": [{"input": "5 3\n", "expected": "CO"}, {"input": "1 2\n", "expected": "KHONG"}, {"input": "4 4\n", "expected": "KHONG"}]}
        ex, reason = build_verified_practice(many, EVEN_ODD_BASE, GRADER)
        self.assertIsNone(ex)
        self.assertIn("giá trị", reason)

    def test_exercise_without_target_skill_is_rejected(self):
        loop_base = REPO.exercise_by_id("l01_sum_n")
        no_loop = {**SAME_LEVEL}
        self.assertIsNone(build_verified_practice(no_loop, loop_base, GRADER)[0])

    def test_same_level_exercise_is_accepted(self):
        ex, reason = build_verified_practice(SAME_LEVEL, EVEN_ODD_BASE, GRADER)
        self.assertIsNotNone(ex, reason)

    def test_generator_without_ai_returns_message(self):
        llm = OptionalLLM()
        llm.endpoint = ""
        ex, reason = generate_practice_exercise(llm, GRADER, IO_BASE)
        self.assertIsNone(ex)
        self.assertIn("AI", reason)


if __name__ == "__main__":
    unittest.main()


SAME_AS_BASE = {  # lỗi thực tế: vừa làm "Phân loại số" xong, AI lại sinh đúng bài đó (chỉ đổi lời)
    "title": "Phân loại số nguyên",
    "description": 'Nhập số nguyên n. In "DUONG", "AM" hoặc "KHONG" tương ứng.',
    "starter_code": "n = int(input())\n# Dùng if-elif-else\n",
    "reference_solution": "n = int(input())\nif n > 0:\n    print('DUONG')\nelif n < 0:\n    print('AM')\nelse:\n    print('KHONG')\n",
    "tests": [
        {"input": "7\n", "expected": "DUONG"},
        {"input": "-2\n", "expected": "AM"},
        {"input": "0\n", "expected": "KHONG"},
    ],
}
DIVISIBLE_BY_5 = {
    "title": "Chia hết cho 5",
    "description": "Nhập số nguyên n. In CO nếu n chia hết cho 5, ngược lại in KHONG.",
    "starter_code": "n = int(input())\n",
    "reference_solution": "n = int(input())\nif n % 5 == 0:\n    print('CO')\nelse:\n    print('KHONG')\n",
    "tests": [
        {"input": "10\n", "expected": "CO"},
        {"input": "7\n", "expected": "KHONG"},
        {"input": "0\n", "expected": "CO"},
    ],
}


class NoveltyTests(unittest.TestCase):
    def test_rewording_of_base_is_rejected(self):
        ex, reason = build_verified_practice(SAME_AS_BASE, IO_BASE, GRADER)
        self.assertIsNone(ex)
        self.assertTrue("Thực chất vẫn là bài" in reason or "chép lại" in reason, reason)

    def test_same_problem_with_other_wording_and_numbers_is_rejected(self):
        reworded = {**SAME_AS_BASE, "description": "Cho một số nguyên nhập từ bàn phím, hãy cho biết số đó dương, âm hay bằng không.",
                    "tests": [{"input": "15\n", "expected": "DUONG"}, {"input": "-99\n", "expected": "AM"}, {"input": "0\n", "expected": "KHONG"}]}
        self.assertIsNone(build_verified_practice(reworded, IO_BASE, GRADER)[0])

    def test_different_problem_same_level_is_accepted(self):
        ex, reason = build_verified_practice(DIVISIBLE_BY_5, IO_BASE, GRADER)
        self.assertIsNotNone(ex, reason)

    def test_duplicate_of_bank_exercise_is_rejected(self):
        even_odd = {**DIVISIBLE_BY_5, "title": "Chẵn lẻ", "description": "Nhập n, in CHAN nếu n chẵn, ngược lại LE.",
                    "reference_solution": "n = int(input())\nprint('CHAN' if n % 2 == 0 else 'LE')\n",
                    "tests": [{"input": "4\n", "expected": "CHAN"}, {"input": "9\n", "expected": "LE"}, {"input": "0\n", "expected": "CHAN"}]}
        bank = [e for e in REPO.exercises if e["skill"] == "conditions"]
        ex, reason = build_verified_practice(even_odd, IO_BASE, GRADER, bank)
        self.assertIsNone(ex)
        self.assertIn("Chẵn hay lẻ", reason)

    def test_duplicate_of_earlier_practice_is_rejected(self):
        first, _ = build_verified_practice(DIVISIBLE_BY_5, IO_BASE, GRADER)
        again = {**DIVISIBLE_BY_5, "title": "Bội của 5", "description": "Cho n. Nếu n là bội của 5 in CO, không thì in KHONG."}
        self.assertIsNone(build_verified_practice(again, IO_BASE, GRADER, [first])[0])

    def test_generator_sends_topic_idea_and_retries_on_duplicate(self):
        seen = []

        class Recorder(FakeLLM):
            def _json_chat(self, system, user, temperature=0.2):
                seen.append(__import__("json").loads(user))
                return super()._json_chat(system, user, temperature)

        llm = Recorder([SAME_AS_BASE, DIVISIBLE_BY_5])
        ex, reason = generate_practice_exercise(llm, GRADER, IO_BASE, bank=REPO.exercises, history=[])
        self.assertIsNotNone(ex, reason)
        self.assertEqual(ex["title"], "Chia hết cho 5")
        self.assertTrue(seen[0]["y_tuong_de_bai"])
        self.assertIn("Phân loại số", seen[0]["cac_bai_da_co_khong_duoc_lap_lai"])
        self.assertIn("Phân loại số", seen[1]["luu_y_lan_truoc"])
