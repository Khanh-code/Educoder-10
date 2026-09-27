from __future__ import annotations

import unittest

from educoder_core import ContentRepository, EDUCODERAgent, SafePythonRunner


class EDUCODERCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = ContentRepository()
        cls.agent = EDUCODERAgent(cls.repo)

    def test_diagnostic_is_prerequisite_ordered(self):
        questions = self.repo.diagnostic_sample(10, seed=42)
        answers = {q["id"]: q["answer_index"] for q in questions}
        result = self.agent.evaluate_diagnostic(questions, answers)
        self.assertEqual(result.score, 10)
        self.assertEqual(result.level, "Vững")
        self.assertTrue(result.recommended_path)

    def test_runner_accepts_basic_input_program(self):
        result = SafePythonRunner().run("n = int(input())\nprint(n * 2)\n", "6\n")
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "12")

    def test_runner_blocks_file_access(self):
        result = SafePythonRunner().run("print(open('secret.txt').read())")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "BlockedCode")

    def test_runner_allows_math_but_blocks_os(self):
        allowed = SafePythonRunner().run("import math\nprint(math.isqrt(81))")
        blocked = SafePythonRunner().run("import os\nprint(os.getcwd())")
        self.assertTrue(allowed.ok)
        self.assertEqual(allowed.output, "9")
        self.assertFalse(blocked.ok)

    def test_io_grading(self):
        exercise = self.repo.exercise_by_id("c01_even_odd")
        code = "n = int(input())\nprint('CHAN' if n % 2 == 0 else 'LE')\n"
        grade = self.agent.grader.grade(exercise, code)
        self.assertTrue(grade.passed)
        self.assertEqual(grade.passed_tests, grade.total_tests)

    def test_function_grading(self):
        exercise = self.repo.exercise_by_id("f01_square")
        grade = self.agent.grader.grade(exercise, "def square(x):\n    return x * x\n")
        self.assertTrue(grade.passed)

    def test_wrong_output_classification(self):
        exercise = self.repo.exercise_by_id("v02_seconds")
        grade = self.agent.grader.grade(exercise, "m = int(input())\nprint(m)\n")
        self.assertFalse(grade.passed)
        self.assertEqual(grade.error_category, "WrongOutput")

    def test_agent_increases_difficulty_after_two_correct(self):
        state = self.agent.new_state("Lan")
        state.current_skill = "functions"
        exercise = self.repo.exercise_by_id("f01_square")
        code = "def square(x):\n    return x * x\n"
        self.agent.submit(state, exercise, code)
        _, decision = self.agent.submit(state, exercise, code)
        self.assertIn(decision["action"], {"harder_same_skill", "advance_skill"})


if __name__ == "__main__":
    unittest.main()
