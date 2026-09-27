"""Lõi Agent thích ứng cho EDUCODER 10.

Thiết kế ưu tiên ba nguyên tắc:
1. Chấm bài bằng test xác định, không giao quyền quyết định đúng/sai cho LLM.
2. Agent chọn hành động tiếp theo từ trạng thái học tập có thể giải thích.
3. Mã học sinh chạy trong tiến trình con có timeout và bộ lọc AST cơ bản.

Lưu ý: đây là sandbox phục vụ demo/đào tạo cục bộ, không phải cô lập bảo mật
đủ mạnh để chạy mã không tin cậy trên Internet công cộng.
"""

from __future__ import annotations

import ast
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


@dataclass
class DiagnosticResult:
    score: int
    total: int
    level: str
    mastery: dict[str, float]
    weak_skills: list[str]
    recommended_path: list[str]


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    stderr: str = ""
    error_type: str = ""
    line: int | None = None
    duration_ms: int = 0
    blocked_reason: str = ""


@dataclass
class GradeResult:
    passed: bool
    passed_tests: int
    total_tests: int
    score: int
    error_category: str
    feedback: str
    hint: str
    run_details: list[RunResult] = field(default_factory=list)


@dataclass
class LearnerState:
    learner_name: str = "Học sinh"
    mastery: dict[str, float] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    correct_streak: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    solved_ids: list[str] = field(default_factory=list)
    current_skill: str = "variables_io"
    current_difficulty: int = 1
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LearnerState":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in payload.items() if k in allowed})


class ContentRepository:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.curriculum = self._load("curriculum.json")
        self.diagnostic = self._load("diagnostic.json")
        self.exercises = self._load("exercises.json")
        self.skill_order = [item["id"] for item in self.curriculum["skills"]]
        self.skill_map = {item["id"]: item for item in self.curriculum["skills"]}

    def _load(self, name: str) -> Any:
        with (self.data_dir / name).open(encoding="utf-8") as handle:
            return json.load(handle)

    def diagnostic_sample(self, count: int = 10, seed: int | None = None) -> list[dict]:
        rng = random.Random(seed)
        grouped: dict[str, list[dict]] = {}
        for q in self.diagnostic:
            grouped.setdefault(q["skill"], []).append(q)
        sample: list[dict] = []
        for skill in self.skill_order:
            if grouped.get(skill):
                sample.append(rng.choice(grouped[skill]))
        remainder = [q for q in self.diagnostic if q not in sample]
        rng.shuffle(remainder)
        sample.extend(remainder[: max(0, count - len(sample))])
        rng.shuffle(sample)
        return sample[:count]

    def exercise_candidates(self, skill: str, difficulty: int) -> list[dict]:
        exact = [
            x for x in self.exercises
            if x["skill"] == skill and int(x["difficulty"]) == int(difficulty)
        ]
        if exact:
            return exact
        return [x for x in self.exercises if x["skill"] == skill]

    def exercise_by_id(self, exercise_id: str) -> dict | None:
        return next((x for x in self.exercises if x["id"] == exercise_id), None)


class OptionalLLM:
    """OpenAI-compatible client; mọi tính năng đều có fallback không LLM."""

    def __init__(self):
        self.endpoint = os.getenv("EDUCODER_LLM_ENDPOINT", "").strip()
        self.api_key = os.getenv("EDUCODER_LLM_API_KEY", "").strip()
        self.model = os.getenv("EDUCODER_LLM_MODEL", "").strip()

    @property
    def available(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def _json_chat(self, system: str, user: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        body = json.dumps({
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            return json.loads(match.group(0) if match else content)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def socratic_hint(self, exercise: dict, code: str, grade: GradeResult, hint_level: int) -> str | None:
        payload = self._json_chat(
            system=(
                "Bạn là gia sư Python cho học sinh lớp 10 Việt Nam. Chỉ đưa gợi ý Socratic, "
                "không viết lời giải hoàn chỉnh, không tiết lộ hidden tests. Trả JSON với khóa hint."
            ),
            user=json.dumps({
                "bai_tap": exercise["title"],
                "mo_ta": exercise["description"],
                "code_hoc_sinh": code[:4000],
                "loai_loi": grade.error_category,
                "phan_hoi": grade.feedback,
                "muc_goi_y": hint_level,
            }, ensure_ascii=False),
        )
        hint = payload.get("hint") if isinstance(payload, dict) else None
        return str(hint).strip() if hint else None


class SafePythonRunner:
    """Bộ chạy giới hạn dành cho bài Tin học 10.

    AST policy chỉ là lớp giảm rủi ro. Khi triển khai công khai, hãy thay bằng
    container/Firecracker/Judge0/Pyodide có cô lập thật.
    """

    ALLOWED_IMPORTS = {
        "math", "statistics", "itertools", "collections", "string", "re",
        "functools", "bisect", "decimal", "fractions",
    }
    BLOCKED_CALLS = {
        "eval", "exec", "compile", "open", "__import__", "breakpoint",
        "globals", "locals", "vars", "dir", "help", "exit", "quit",
        "getattr", "setattr", "delattr",
    }
    BLOCKED_ATTRS = {
        "system", "popen", "spawn", "fork", "remove", "unlink", "rmdir",
        "walk", "listdir", "environ", "getenv", "connect", "bind", "listen",
        "accept", "send", "recv", "write_text", "write_bytes", "read_text",
        "read_bytes", "__subclasses__", "__globals__", "__code__",
        "__class__", "__bases__", "__mro__",
    }

    def validate(self, code: str) -> tuple[bool, str]:
        if len(code) > 12_000:
            return False, "Mã nguồn vượt quá giới hạn 12.000 ký tự."
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return True, ""  # Để Python trả thông báo lỗi cú pháp có số dòng.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in self.ALLOWED_IMPORTS:
                        return False, f"Mô-đun {alias.name!r} không nằm trong danh sách cho phép."
            if isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                if module not in self.ALLOWED_IMPORTS:
                    return False, f"Mô-đun {module!r} không nằm trong danh sách cho phép."
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.BLOCKED_CALLS:
                    return False, f"Không cho phép gọi hàm {node.func.id}()."
            if isinstance(node, ast.Attribute) and node.attr in self.BLOCKED_ATTRS:
                return False, f"Không cho phép truy cập thuộc tính {node.attr!r}."
        return True, ""

    @staticmethod
    def _limit_resources() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        except (ImportError, ValueError, OSError):
            pass

    def run(self, code: str, stdin_data: str = "", timeout: float = 3.0) -> RunResult:
        allowed, reason = self.validate(code)
        if not allowed:
            return RunResult(ok=False, error_type="BlockedCode", blocked_reason=reason, stderr=reason)
        start = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="educoder10_") as workdir:
            script = Path(workdir) / "student.py"
            script.write_text(code, encoding="utf-8")
            kwargs: dict[str, Any] = {}
            if os.name != "nt":
                kwargs["preexec_fn"] = self._limit_resources
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-S", str(script)],
                    input=stdin_data,
                    text=True,
                    capture_output=True,
                    cwd=workdir,
                    timeout=timeout,
                    env={"PYTHONIOENCODING": "utf-8", "PATH": os.environ.get("PATH", "")},
                    **kwargs,
                )
                elapsed = int((time.perf_counter() - start) * 1000)
                stderr = completed.stderr.strip()
                error_type, line = self._parse_error(stderr)
                return RunResult(
                    ok=completed.returncode == 0,
                    output=completed.stdout.strip(),
                    stderr=stderr,
                    error_type=error_type,
                    line=line,
                    duration_ms=elapsed,
                )
            except subprocess.TimeoutExpired:
                return RunResult(
                    ok=False,
                    error_type="TimeoutError",
                    stderr="Chương trình chạy quá 3 giây; có thể có vòng lặp vô hạn.",
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )

    @staticmethod
    def _parse_error(stderr: str) -> tuple[str, int | None]:
        if not stderr:
            return "", None
        type_match = re.findall(r"(?m)^([A-Za-z]+(?:Error|Exception)):", stderr)
        line_match = re.findall(r'File ".*?", line (\d+)', stderr)
        return (type_match[-1] if type_match else "RuntimeError", int(line_match[-1]) if line_match else None)


class DeterministicGrader:
    def __init__(self, runner: SafePythonRunner | None = None):
        self.runner = runner or SafePythonRunner()

    def grade(self, exercise: dict, code: str, hint_level: int = 1) -> GradeResult:
        kind = exercise.get("kind", "io")
        details: list[RunResult] = []
        passed = 0
        tests = exercise.get("tests", [])
        if not code.strip():
            return GradeResult(False, 0, len(tests), 0, "EmptyCode", "Em chưa nhập chương trình.", "Hãy bắt đầu từ dữ liệu vào và kết quả cần in.")

        for case in tests:
            if kind == "function":
                test_code = code.rstrip() + "\n\n" + case["assert"] + "\nprint('__EDUCODER_PASS__')\n"
                result = self.runner.run(test_code)
                case_ok = result.ok and "__EDUCODER_PASS__" in result.output
            else:
                result = self.runner.run(code, case.get("input", ""))
                case_ok = result.ok and self._norm(result.output) == self._norm(case.get("output", ""))
            details.append(result)
            if case_ok:
                passed += 1
            elif result.error_type:
                break

        total = len(tests)
        all_passed = total > 0 and passed == total
        category = self._category(details, passed, total)
        feedback = self._feedback(category, details, passed, total)
        hint = self._hint(exercise, category, hint_level)
        score = round(100 * passed / total) if total else 0
        return GradeResult(all_passed, passed, total, score, category, feedback, hint, details)

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(value.strip().split())

    @staticmethod
    def _category(details: list[RunResult], passed: int, total: int) -> str:
        first_bad = next((x for x in details if not x.ok), None)
        if first_bad:
            return first_bad.error_type or "RuntimeError"
        if passed < total:
            return "WrongOutput"
        return "Correct"

    @staticmethod
    def _feedback(category: str, details: list[RunResult], passed: int, total: int) -> str:
        line = next((x.line for x in details if x.line), None)
        where = f" tại dòng {line}" if line else ""
        mapping = {
            "Correct": f"Đúng {passed}/{total} test. Chương trình đáp ứng yêu cầu.",
            "SyntaxError": f"Python chưa hiểu cú pháp{where}. Kiểm tra dấu ':', ngoặc và dấu nháy.",
            "IndentationError": f"Khối lệnh thụt lề chưa đúng{where}. Dùng thống nhất 4 khoảng trắng.",
            "NameError": f"Có tên biến/hàm chưa được định nghĩa hoặc viết không thống nhất{where}.",
            "TypeError": f"Phép toán đang dùng kiểu dữ liệu không phù hợp{where}. Kiểm tra int/float/str.",
            "IndexError": f"Chỉ số nằm ngoài phạm vi danh sách{where}. Chỉ số hợp lệ từ 0 đến len(a)-1.",
            "ZeroDivisionError": f"Có phép chia cho 0{where}. Cần kiểm tra mẫu số trước khi chia.",
            "AssertionError": "Hàm chạy nhưng có test chưa đúng. Kiểm tra trường hợp biên và giá trị trả về.",
            "TimeoutError": "Chương trình có thể lặp vô hạn hoặc xử lý quá lâu.",
            "BlockedCode": "Mã dùng thao tác không được phép trong môi trường học tập.",
            "WrongOutput": f"Chương trình chạy được nhưng mới đúng {passed}/{total} test. Kiểm tra định dạng và trường hợp biên.",
            "EmptyCode": "Chưa có mã để chấm.",
        }
        return mapping.get(category, f"Chương trình chưa vượt qua toàn bộ test ({passed}/{total}).")

    @staticmethod
    def _hint(exercise: dict, category: str, hint_level: int) -> str:
        hints = exercise.get("hints", [])
        if hints:
            return hints[min(max(hint_level, 1), len(hints)) - 1]
        defaults = {
            "SyntaxError": "Đọc từ dòng lỗi lên một dòng; tìm câu lệnh if/for/while/def thiếu dấu hai chấm.",
            "IndentationError": "Vẽ khối lệnh ra giấy và thụt các câu thuộc cùng khối bằng 4 khoảng trắng.",
            "NameError": "Liệt kê tên biến đã tạo và so sánh từng ký tự với tên trong dòng lỗi.",
            "WrongOutput": "Tự tính bằng tay một test nhỏ rồi in giá trị trung gian để tìm bước lệch.",
            "TimeoutError": "Kiểm tra điều kiện dừng và biến điều khiển có thay đổi trong vòng lặp không.",
        }
        return defaults.get(category, "Chia bài toán thành: dữ liệu vào → xử lý → kết quả ra.")


class EDUCODERAgent:
    """Agent quyết định bước học kế tiếp dựa trên trạng thái và kết quả thật."""

    def __init__(self, repository: ContentRepository | None = None):
        self.repo = repository or ContentRepository()
        self.grader = DeterministicGrader()
        self.llm = OptionalLLM()

    def new_state(self, learner_name: str = "Học sinh") -> LearnerState:
        return LearnerState(
            learner_name=learner_name.strip() or "Học sinh",
            mastery={skill: 0.0 for skill in self.repo.skill_order},
            attempts={skill: 0 for skill in self.repo.skill_order},
            correct_streak={skill: 0 for skill in self.repo.skill_order},
            error_counts={},
            current_skill=self.repo.skill_order[0],
        )

    def evaluate_diagnostic(self, questions: list[dict], answers: dict[str, int]) -> DiagnosticResult:
        per_skill: dict[str, list[int]] = {skill: [] for skill in self.repo.skill_order}
        score = 0
        for q in questions:
            correct = int(answers.get(q["id"], -1)) == int(q["answer_index"])
            per_skill[q["skill"]].append(1 if correct else 0)
            score += int(correct)
        mastery = {
            skill: round(sum(values) / len(values), 2) if values else 0.0
            for skill, values in per_skill.items()
        }
        weak = [s for s in self.repo.skill_order if mastery[s] < 0.6]
        path = self._path_from_mastery(mastery)
        ratio = score / max(len(questions), 1)
        level = "Mới bắt đầu" if ratio < 0.45 else "Cơ bản" if ratio < 0.7 else "Khá" if ratio < 0.9 else "Vững"
        return DiagnosticResult(score, len(questions), level, mastery, weak, path)

    def apply_diagnostic(self, state: LearnerState, result: DiagnosticResult) -> None:
        state.mastery.update(result.mastery)
        state.current_skill = result.recommended_path[0] if result.recommended_path else self.repo.skill_order[-1]
        state.current_difficulty = 1 if result.level in {"Mới bắt đầu", "Cơ bản"} else 2
        state.history.append({"event": "diagnostic", "score": result.score, "total": result.total, "level": result.level})

    def _path_from_mastery(self, mastery: dict[str, float]) -> list[str]:
        weak = [skill for skill in self.repo.skill_order if mastery.get(skill, 0.0) < 0.75]
        return weak or [self.repo.skill_order[-1]]

    def select_exercise(self, state: LearnerState, prefer_new: bool = True) -> dict:
        candidates = self.repo.exercise_candidates(state.current_skill, state.current_difficulty)
        if prefer_new:
            unseen = [x for x in candidates if x["id"] not in state.solved_ids]
            if unseen:
                candidates = unseen
        attempts = state.attempts.get(state.current_skill, 0)
        rng = random.Random(f"{state.learner_name}:{state.current_skill}:{attempts}:{len(state.history)}")
        return rng.choice(candidates)

    def submit(self, state: LearnerState, exercise: dict, code: str, hint_level: int = 1) -> tuple[GradeResult, dict]:
        grade = self.grader.grade(exercise, code, hint_level)
        skill = exercise["skill"]
        state.attempts[skill] = state.attempts.get(skill, 0) + 1
        old = state.mastery.get(skill, 0.0)
        if grade.passed:
            gain = {1: 0.14, 2: 0.18, 3: 0.22}.get(int(exercise["difficulty"]), 0.14)
            state.mastery[skill] = round(min(1.0, old + gain * (1.0 - old)), 2)
            state.correct_streak[skill] = state.correct_streak.get(skill, 0) + 1
            if exercise["id"] not in state.solved_ids:
                state.solved_ids.append(exercise["id"])
        else:
            state.mastery[skill] = round(max(0.0, old - 0.03), 2)
            state.correct_streak[skill] = 0
            state.error_counts[grade.error_category] = state.error_counts.get(grade.error_category, 0) + 1

        llm_hint = None
        if not grade.passed:
            llm_hint = self.llm.socratic_hint(exercise, code, grade, hint_level)
            if llm_hint:
                grade.hint = llm_hint

        decision = self.decide_next(state, exercise, grade)
        state.history.append({
            "event": "submission",
            "exercise_id": exercise["id"],
            "skill": skill,
            "difficulty": exercise["difficulty"],
            "passed": grade.passed,
            "score": grade.score,
            "error_category": grade.error_category,
            "mastery_before": old,
            "mastery_after": state.mastery[skill],
            "decision": decision,
        })
        return grade, decision

    def decide_next(self, state: LearnerState, exercise: dict, grade: GradeResult) -> dict:
        skill = exercise["skill"]
        mastery = state.mastery.get(skill, 0.0)
        streak = state.correct_streak.get(skill, 0)
        trace = {
            "observe": {
                "passed": grade.passed,
                "error": grade.error_category,
                "mastery": mastery,
                "streak": streak,
                "difficulty": exercise["difficulty"],
            }
        }
        if not grade.passed:
            if grade.error_category in {"SyntaxError", "IndentationError", "NameError", "TypeError", "TimeoutError"}:
                state.current_difficulty = max(1, int(exercise["difficulty"]) - 1)
                action = "similar_or_easier"
                reason = "Lỗi nền tảng cần luyện lại cùng kỹ năng với mức hỗ trợ cao hơn."
            else:
                state.current_difficulty = int(exercise["difficulty"])
                action = "similar_same_level"
                reason = "Code chạy nhưng chưa qua test; cần bài tương tự để sửa mô hình tư duy."
        elif mastery >= 0.82 and streak >= 2:
            index = self.repo.skill_order.index(skill)
            if index < len(self.repo.skill_order) - 1:
                state.current_skill = self.repo.skill_order[index + 1]
                state.current_difficulty = 1
                action = "advance_skill"
                reason = "Đạt ngưỡng thành thạo và có chuỗi hai bài đúng."
            else:
                state.current_difficulty = min(3, int(exercise["difficulty"]) + 1)
                action = "capstone_challenge"
                reason = "Đã hoàn tất kỹ năng cuối; chuyển sang thử thách tổng hợp."
        elif grade.passed and streak >= 2:
            state.current_difficulty = min(3, int(exercise["difficulty"]) + 1)
            action = "harder_same_skill"
            reason = "Hai bài liên tiếp đúng; tăng độ khó trong cùng kỹ năng."
        else:
            state.current_difficulty = int(exercise["difficulty"])
            action = "similar_same_level"
            reason = "Bài đúng đầu tiên; cần thêm một bài tương tự để củng cố."
        return {"action": action, "reason": reason, "next_skill": state.current_skill, "next_difficulty": state.current_difficulty, "trace": trace}


def load_mbpp_preview(limit: int = 30, data_dir: Path = DATA_DIR) -> list[dict]:
    """Đọc một tập MBPP chỉ để tham khảo/mở rộng; không dùng lời giải trong UI."""
    path = data_dir / "mbpp" / "sanitized-mbpp.json"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    safe_rows = []
    for row in rows:
        prompt = str(row.get("prompt", ""))
        tests = row.get("test_list") or []
        if prompt and tests:
            safe_rows.append({"task_id": row.get("task_id"), "prompt": prompt, "tests": tests[:3]})
        if len(safe_rows) >= limit:
            break
    return safe_rows


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
