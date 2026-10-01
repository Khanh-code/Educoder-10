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

from error_diagnoser import diagnose as diagnose_code


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Đọc file .env đơn giản (KEY=VALUE) nếu có; không ghi đè biến đã đặt sẵn."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


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
    # Chẩn đoán chính xác: {line, code_line, problem, fix, example} (xem error_diagnoser.py)
    diagnosis: dict | None = None


from dataclasses import dataclass, asdict, field
from typing import Any

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

    # --- THÊM 3 TRƯỜNG ĐỂ LƯU KẾT QUẢ TEST ĐẦU VÀO VĨNH VIỄN ---
    diagnostic_done: bool = False
    diagnostic_result: Any = None
    diagnostic_answers: dict[str, Any] = field(default_factory=dict)
    # Lưu lại ĐÚNG bộ câu hỏi đã làm để xem lại sau khi đăng nhập lại
    diagnostic_question_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LearnerState":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        state = cls(**{k: v for k, v in payload.items() if k in allowed})
        # Khi đọc từ CSDL/JSON, kết quả test là dict -> đổi lại thành DiagnosticResult
        result = state.diagnostic_result
        if isinstance(result, dict):
            fields = {f for f in DiagnosticResult.__dataclass_fields__}
            try:
                state.diagnostic_result = DiagnosticResult(**{k: v for k, v in result.items() if k in fields})
            except TypeError:
                state.diagnostic_result = None
        if not isinstance(state.diagnostic_answers, dict):
            state.diagnostic_answers = {}
        return state

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
        self.last_call_ok = False
        # Model chạy trên máy (Ollama) có thể chậm, nên cho phép chờ lâu hơn.
        try:
            self.timeout = float(os.getenv("EDUCODER_LLM_TIMEOUT", "90"))
        except ValueError:
            self.timeout = 90.0

    @property
    def available(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def _json_chat(self, system: str, user: str, temperature: float = 0.2) -> dict[str, Any] | None:
        self.last_call_ok = False
        if not self.available:
            return None
        body = json.dumps({
            "model": self.model,
            "temperature": temperature,
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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            result = json.loads(match.group(0) if match else content)
            self.last_call_ok = True
            return result
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def socratic_hint(self, exercise: dict, code: str, grade: GradeResult, hint_level: int) -> str | None:
        payload = self._json_chat(
            system=(
                "Bạn là gia sư Python cho học sinh lớp 10 Việt Nam. Chỉ đưa gợi ý Socratic ngắn (1-2 câu), "
                "không viết lời giải hoàn chỉnh, không tiết lộ hidden tests. "
                "Trường chan_doan là kết quả phân tích CHÍNH XÁC từ trình thông dịch Python: gợi ý của bạn PHẢI "
                "khớp với chẩn đoán đó, không được nêu lỗi khác hay đoán thêm lỗi. Trả JSON với khóa hint."
            ),
            user=json.dumps({
                "bai_tap": exercise["title"],
                "mo_ta": exercise["description"],
                "code_hoc_sinh": code[:4000],
                "loai_loi": grade.error_category,
                "phan_hoi": grade.feedback,
                "muc_goi_y": hint_level,
                "chan_doan": grade.diagnosis or {},
            }, ensure_ascii=False),
        )
        hint = payload.get("hint") if isinstance(payload, dict) else None
        return str(hint).strip() if hint else None

    def advanced_solution(self, exercise: dict, code: str) -> dict[str, str] | None:
        """Nhờ LLM đề xuất cách viết gọn/tối ưu hơn cho bài HỌC SINH ĐÃ LÀM ĐÚNG.

        Trả None nếu không có API, API lỗi, hoặc LLM cho rằng bài quá cơ bản /
        code học sinh đã tối ưu. Kết quả chưa được kiểm chứng; dùng
        suggest_advanced_solution() để chạy test trước khi hiển thị.
        """
        payload = self._json_chat(
            system=(
                "Bạn là giáo viên Python dạy Tin học 10 (Chương trình GDPT 2018) ở Việt Nam. "
                "Học sinh ĐÃ giải ĐÚNG bài tập. Hãy xem có cách viết nâng cao, gọn hơn hoặc tối ưu hơn "
                "mà học sinh lớp 10 hiểu được hay không, ví dụ: toán tử 3 ngôi "
                "(print(\"DUONG\" if n > 0 else ...)), so sánh kép, cấu trúc rẽ nhánh tối ưu, "
                "hàm có sẵn (sum, max, sorted, str.count...), map/split, lát cắt [::-1], "
                "hoặc thuật toán hiệu quả hơn. "
                "Chỉ dùng Python chuẩn; nếu cần import thì chỉ dùng math, itertools, collections, bisect, functools. "
                "Code nâng cao PHẢI giữ nguyên cách nhập/xuất dữ liệu và tên hàm như đề bài, "
                "và phải khác rõ rệt so với code của học sinh. "
                "Nếu bài quá cơ bản hoặc code học sinh đã là cách tốt nhất, trả has_advanced=false. "
                "Trả về JSON với các khóa: has_advanced (bool), title (tiêu đề ngắn tiếng Việt), "
                "code (chuỗi code Python hoàn chỉnh), explanation (2-4 câu tiếng Việt, giải thích vì sao "
                "cách này hay hơn, xưng 'em')."
            ),
            user=json.dumps({
                "bai_tap": exercise["title"],
                "mo_ta": exercise["description"],
                "kieu_bai": "viết hàm" if exercise.get("kind") == "function" else "nhập/xuất dữ liệu",
                "code_mau_ban_dau": exercise.get("starter_code", ""),
                "vi_du_test": exercise.get("tests", [])[:2],
                "code_hoc_sinh_da_dung": code[:4000],
            }, ensure_ascii=False),
        )
        if not isinstance(payload, dict) or not payload.get("has_advanced"):
            return None
        adv_code = str(payload.get("code") or "").strip()
        if not adv_code:
            return None
        return {
            "title": str(payload.get("title") or "Cách viết gọn hơn").strip(),
            "code": adv_code,
            "explanation": str(payload.get("explanation") or "").strip(),
            "source": "ai",
        }


def _normalize_code(code: str) -> str:
    """Bỏ comment, dòng trống và khoảng trắng để so sánh hai đoạn code."""
    lines = []
    for line in code.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(" ".join(line.split()))
    return "\n".join(lines)


def suggest_advanced_solution(
    llm: OptionalLLM,
    grader: "DeterministicGrader",
    exercise: dict,
    student_code: str,
    allow_bank_fallback: bool = True,
) -> dict[str, str] | None:
    """Lấy cách giải nâng cao cho bài đã làm đúng.

    1. Hỏi AI dựa trên chính code của học sinh.
    2. Chạy code AI đề xuất qua bộ test xác định: chỉ hiển thị nếu đúng 100% test
       (tránh AI "bịa" lời giải sai).
    3. Nếu không có API / AI lỗi và allow_bank_fallback=True: dùng
       advanced_solution trong ngân hàng bài tập (nếu có) để app vẫn chạy offline.
    Trả None khi không có cách giải nâng cao phù hợp -> giao diện ẩn hoàn toàn.
    """
    student_norm = _normalize_code(student_code)

    if llm.available:
        suggestion = llm.advanced_solution(exercise, student_code)
        if suggestion and _normalize_code(suggestion["code"]) != student_norm:
            if grader.grade(exercise, suggestion["code"]).passed:
                return suggestion
        # AI trả lời "không có cách tốt hơn" hoặc code AI không qua test -> ẩn.
        if suggestion is None and llm.last_call_ok:
            return None

    if allow_bank_fallback:
        bank = exercise.get("advanced_solution")
        if bank and bank.get("code") and _normalize_code(bank["code"]) != student_norm:
            return {**bank, "source": "bank"}
    return None


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
                if completed.returncode != 0 and not stderr:
                    # Bị hệ điều hành dừng vì vượt giới hạn CPU (Linux/macOS) = chạy quá lâu
                    error_type = "TimeoutError"
                    stderr = "Chương trình chạy quá lâu; có thể có vòng lặp vô hạn."
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
        type_match = re.findall(r"(?m)^([A-Za-z]+(?:Error|Exception))(?::|\s*$)", stderr)
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
            return GradeResult(False, 0, len(tests), 0, "EmptyCode", "Em chưa nhập chương trình.", "Hãy bắt đầu từ dữ liệu vào và kết quả cần in.",
                               diagnosis=diagnose_code(exercise, code, [], self.runner))

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
        diagnosis = None
        if not all_passed:
            try:
                diagnosis = diagnose_code(exercise, code, details, self.runner, int(exercise.get("public_tests", 2)))
            except Exception:  # chẩn đoán lỗi không được làm hỏng việc chấm
                diagnosis = None
            if diagnosis:
                where = f"Dòng {diagnosis['line']}: " if diagnosis.get("line") else ""
                feedback = f"{where}{diagnosis['problem']} {diagnosis['fix']}"
        return GradeResult(all_passed, passed, total, score, category, feedback, hint, details, diagnosis)

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


# ---------------------------------------------------------------------------
# LUYỆN TẬP THÊM: AI sinh bài tương tự + bộ test ĐÃ KIỂM CHỨNG BẰNG CÁCH CHẠY THẬT
# ---------------------------------------------------------------------------

PRACTICE_SYSTEM_PROMPT = (
    "Bạn là giáo viên Tin học 10 ở Việt Nam, soạn bài luyện tập Python. "
    "Hãy tạo MỘT BÀI TOÁN KHÁC cùng kỹ năng, cùng dạng dữ liệu và cùng độ khó với bài gốc để học sinh luyện thêm. "
    "Bài mới phải có YÊU CẦU XỬ LÝ KHÁC (điều kiện khác, công thức khác, kết quả in ra khác), "
    "KHÔNG được chỉ đổi số liệu, đổi tên biến hay diễn đạt lại bài gốc. "
    "Ví dụ bài gốc phân loại số dương/âm/không thì bài mới có thể là: kiểm tra chẵn/lẻ, chia hết cho 5, năm nhuận... "
    "Ưu tiên dùng 'y_tuong_de_bai' nếu hợp dạng dữ liệu, và không trùng các bài trong 'cac_bai_da_co_khong_duoc_lap_lai'. "
    "BẮT BUỘC: (1) chỉ dùng kiến thức trong 'kien_thuc_duoc_dung', học sinh CHƯA học phần khác; "
    "(2) dữ liệu vào đúng như 'dang_du_lieu_vao_bat_buoc' (cùng số dòng, cùng số giá trị mỗi dòng); "
    "(3) độ dài lời giải tương đương bài gốc, không khó hơn. "
    "Ví dụ: bài gốc nhập 1 số rồi dùng if-else thì bài mới cũng chỉ nhập 1 số và dùng if-else, "
    "KHÔNG được chuyển sang nhập một dãy số hay dùng danh sách/vòng lặp. "
    "Đề bài viết tiếng Việt, rõ ràng, nêu chính xác định dạng dữ liệu vào/ra. "
    "KHÔNG dùng ký hiệu LaTeX hay $...$; tên biến viết trong dấu `...` (vd `n`), phép nhân viết ×. "
    "Chỉ dùng kiến thức lớp 10: biến, input/print, if/elif/else, for/while, chuỗi, danh sách, hàm. "
    "Không dùng import (trừ math nếu thật cần). Không dùng file, mạng, random. "
    "Trả về DUY NHẤT một JSON với các khóa:\n"
    "- title: tên bài ngắn\n"
    "- description: đề bài đầy đủ\n"
    "- starter_code: code khung cho học sinh (chưa có lời giải)\n"
    "- reference_solution: lời giải mẫu đúng hoàn toàn\n"
    "- hints: danh sách 3 gợi ý tăng dần, không lộ lời giải ngay\n"
    "- tests: danh sách 4 đến 6 test, bao gồm cả trường hợp biên.\n"
    "Nếu kieu_bai là 'io': mỗi test có dạng {\"input\": \"...\", \"expected\": \"...\"}; "
    "input là chuỗi dữ liệu nhập, ĐÚNG DẠNG như 'dang_du_lieu_vao_bat_buoc' (các dòng cách nhau bởi \\n, "
    "kết thúc bằng \\n), khớp với cách đọc input() trong lời giải mẫu; expected là kết quả in ra.\n"
    "Nếu kieu_bai là 'function': thêm khóa function_name; mỗi test có dạng "
    "{\"call\": \"ten_ham(doi_so)\", \"expected\": \"giá trị trả về viết theo cú pháp Python, vd 5, True, 'abc', [1, 2], None\"}."
)


def _parse_literal(text: str) -> Any:
    try:
        return ast.literal_eval(str(text).strip())
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return object()  # không parse được -> không bằng gì cả


def _claims_match(claimed: Any, actual_repr: str) -> bool:
    """So kết quả AI tự tuyên bố với kết quả chạy thật (dành cho bài dạng hàm)."""
    actual = _parse_literal(actual_repr)
    guess = _parse_literal(claimed) if isinstance(claimed, str) else claimed
    if isinstance(actual, float) or isinstance(guess, float):
        try:
            return abs(float(actual) - float(guess)) < 1e-9
        except (TypeError, ValueError):
            return False
    return type(actual) is type(guess) and actual == guess


def _call_is_safe(call: str, function_name: str) -> bool:
    """Chỉ chấp nhận biểu thức dạng ten_ham(<hằng số>), không cho gọi hàm khác."""
    try:
        node = ast.parse(call.strip(), mode="eval").body
    except SyntaxError:
        return False
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function_name):
        return False
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        try:
            ast.literal_eval(arg)
        except (ValueError, SyntaxError, TypeError):
            return False
    return True



# ---- KIỂM SOÁT CẤP ĐỘ: bài luyện thêm KHÔNG được dùng kiến thức chưa học ----

SKILL_ORDER = ["variables_io", "conditions", "loops", "strings_lists", "functions", "debugging"]
CONCEPT_OF_SKILL = {  # kiến thức "mới" của từng kỹ năng
    "conditions": "if",
    "loops": "loop",
    "strings_lists": "list",
    "functions": "def",
}
CONCEPT_NAMES = {
    "if": "cấu trúc rẽ nhánh if/else",
    "loop": "vòng lặp for/while",
    "list": "xâu/danh sách (len, max, split thành dãy, chỉ số [ ]...)",
    "def": "tự định nghĩa hàm (def)",
}
SKILL_ALLOWED_TEXT = {
    "variables_io": "biến, input(), print(), int(), float(), phép toán + - * / // % **, round(). KHÔNG dùng if, vòng lặp, danh sách, hàm tự viết.",
    "conditions": "biến, input/print, phép toán, so sánh, and/or/not, if/elif/else. KHÔNG dùng vòng lặp, danh sách, xâu nâng cao, hàm tự viết.",
    "loops": "biến, input/print, if/elif/else, for, range, while, biến tích lũy. KHÔNG dùng danh sách, phương thức xâu, hàm tự viết.",
    "strings_lists": "if, for/while, xâu và danh sách (len, chỉ số, cắt lát, append, split, count, lower, max/min/sum). KHÔNG tự viết hàm def.",
    "functions": "def, tham số, return, cùng mọi kiến thức trước đó.",
    "debugging": "mọi kiến thức Python cơ bản lớp 10.",
}
_LIST_FUNCS = {"len", "sum", "sorted", "list", "set", "dict", "tuple", "reversed", "enumerate", "zip", "any", "all"}
_LIST_METHODS = {"append", "count", "lower", "upper", "join", "find", "replace", "index", "insert", "pop",
                 "remove", "sort", "reverse", "strip", "startswith", "endswith", "isdigit", "isalpha", "extend"}


def _is_input_split(node: ast.AST) -> bool:
    """input().split() dùng để đọc nhiều giá trị trên 1 dòng: được phép ở mọi cấp."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split"
            and isinstance(node.func.value, ast.Call) and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "input")


def concepts_used(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)):
            used.add("if")
        elif isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            used.add("loop")
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                used.add("list")
        elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
            used.add("def")
        elif isinstance(node, (ast.List, ast.Subscript, ast.Slice)):
            used.add("list")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in _LIST_FUNCS:
                    used.add("list")
                elif f.id in ("max", "min") and len(node.args) == 1:
                    used.add("list")  # max(day_so) là kiến thức danh sách; max(a, b) thì không
                elif f.id == "map" and not (len(node.args) == 2 and _is_input_split(node.args[1])):
                    used.add("list")
            elif isinstance(f, ast.Attribute):
                if f.attr in _LIST_METHODS:
                    used.add("list")
                elif f.attr == "split" and not _is_input_split(node):
                    used.add("list")
    return used


def _io_shape(tests: list[dict]) -> list[tuple[int, list[int]]]:
    """Mỗi test -> (số dòng input, [số giá trị trên từng dòng])."""
    shapes = []
    for t in tests:
        lines = [l for l in str(t.get("input", "")).splitlines()]
        shapes.append((len(lines), [len(l.split()) for l in lines]))
    return shapes


def describe_input_shape(exercise: dict) -> str:
    if exercise.get("kind") == "function":
        sig = re.search(r"def\s+\w+\((.*?)\)", exercise.get("starter_code", ""))
        params = sig.group(1) if sig else ""
        n = len([p for p in params.split(",") if p.strip()])
        types = _function_arg_types(exercise)
        return f"Viết một hàm nhận đúng {n} tham số, kiểu đối số: {', '.join(types) or 'giống bài gốc'}."
    shapes = _io_shape(exercise.get("tests", []))
    if not shapes:
        return ""
    n_lines = shapes[0][0]
    per_line = [max(s[1][i] for s in shapes if i < len(s[1])) for i in range(n_lines)]
    parts = [f"dòng {i + 1} có {c} giá trị" for i, c in enumerate(per_line)]
    return f"Dữ liệu vào gồm đúng {n_lines} dòng ({'; '.join(parts)}), giống hệt dạng dữ liệu của bài gốc."


def _function_arg_types(exercise: dict) -> list[str]:
    for t in exercise.get("tests", []):
        src = t.get("assert") or t.get("call") or ""
        try:
            node = ast.parse(src.replace("assert ", "", 1), mode="exec").body[0].value
            call = node.left if isinstance(node, ast.Compare) else node
            if isinstance(call, ast.Call):
                return [type(ast.literal_eval(a)).__name__ for a in call.args]
        except Exception:
            continue
    return []


def check_practice_level(solution: str, tests: list[dict], base_exercise: dict) -> str:
    """Trả "" nếu bài sinh ra đúng cấp độ bài gốc, ngược lại trả lý do loại."""
    skill = base_exercise.get("skill", "")
    if skill in SKILL_ORDER and skill != "debugging":
        level = SKILL_ORDER.index(skill)
        allowed = {CONCEPT_OF_SKILL[s] for s in SKILL_ORDER[: level + 1] if s in CONCEPT_OF_SKILL}
        used = concepts_used(solution)
        if base_exercise.get("kind") == "function":
            used.discard("def")
        too_hard = sorted(used - allowed)
        if too_hard:
            names = ", ".join(CONCEPT_NAMES[c] for c in too_hard)
            return f"Lời giải dùng kiến thức chưa học ở kỹ năng này: {names}."
        required = CONCEPT_OF_SKILL.get(skill)
        if required and required != "def" and required not in used:
            return f"Bài không luyện đúng kỹ năng: lời giải không dùng {CONCEPT_NAMES[required]}."

    if base_exercise.get("kind") == "function":
        base_types = _function_arg_types(base_exercise)
        new_types = _function_arg_types({"tests": tests})
        if base_types and new_types and len(base_types) != len(new_types):
            return f"Hàm nhận {len(new_types)} đối số, bài gốc nhận {len(base_types)}."
        if base_types and new_types and sorted(base_types) != sorted(new_types) and skill != "debugging":
            return f"Kiểu dữ liệu đối số ({', '.join(new_types)}) khác bài gốc ({', '.join(base_types)})."
        return ""

    base_shapes = _io_shape(base_exercise.get("tests", []))
    new_shapes = _io_shape(tests)
    if base_shapes and new_shapes:
        base_lines = {s[0] for s in base_shapes}
        if any(s[0] not in base_lines for s in new_shapes):
            return "Số dòng dữ liệu vào khác bài gốc."
        if skill in ("variables_io", "conditions", "loops"):
            max_vals = max(max(s[1] or [0]) for s in base_shapes)
            min_vals = min(min(s[1] or [0]) for s in base_shapes)
            for s in new_shapes:
                if any(c > max_vals or c < min_vals for c in s[1]):
                    return (f"Dữ liệu vào có {max(s[1] or [0])} giá trị trên một dòng, "
                            f"bài gốc chỉ có {max_vals} (bài mới khó hơn bài gốc).")
    return ""


# ---- CHỐNG TRÙNG: bài luyện thêm phải là BÀI TOÁN KHÁC, không chỉ đổi số/đổi lời ----

TOPIC_IDEAS = {
    "variables_io": [
        "đổi đơn vị (km sang m, giờ sang phút, kg sang g)", "tính chu vi một hình", "tính tiền mua hàng",
        "đổi độ C sang độ F", "chia kẹo: mỗi bạn được mấy cái, dư mấy cái", "tính quãng đường = vận tốc × thời gian",
        "tính tuổi từ năm sinh", "tính trung bình cộng",
    ],
    "conditions": [
        "kiểm tra số chẵn/lẻ", "kiểm tra chia hết cho 3", "kiểm tra chia hết cho 5", "kiểm tra năm nhuận",
        "kiểm tra số có hai chữ số", "phân loại nhiệt độ nóng/mát/lạnh", "kiểm tra đủ 18 tuổi",
        "kiểm tra số tròn chục", "phân loại tốc độ xe (đúng luật/vượt tốc độ)", "xếp loại học lực theo điểm",
        "kiểm tra tháng thuộc quý mấy", "số lớn hơn trong hai số", "tính tiền điện theo bậc",
    ],
    "loops": [
        "tổng các số chẵn từ 1 đến n", "tích từ 1 đến n (giai thừa)", "đếm số ước của n", "in bảng cửu chương n",
        "đếm số chữ số của n", "tổng bình phương từ 1 đến n", "đảo ngược các chữ số của n",
        "đếm số chia hết cho 3 từ 1 đến n", "tổng các số lẻ từ 1 đến n", "in các số chia hết cho 5 đến n",
    ],
    "strings_lists": [
        "đếm nguyên âm trong chuỗi", "đếm số chẵn trong dãy", "tổng các phần tử của dãy", "tìm số nhỏ nhất",
        "đảo ngược chuỗi", "đếm số từ trong câu", "đếm số âm trong dãy", "viết hoa chữ cái đầu mỗi từ",
    ],
    "functions": [
        "hàm kiểm tra số chẵn", "hàm tính giai thừa", "hàm đếm ước", "hàm đổi độ C sang độ F",
        "hàm tính tổng chữ số", "hàm kiểm tra năm nhuận", "hàm tìm số lớn hơn", "hàm tính lũy thừa",
    ],
}


def _same_behavior(solution: str, kind: str, fname: str, other: dict, runner: "SafePythonRunner") -> bool:
    """True nếu lời giải mới cho ĐÚNG kết quả của bài `other` trên mọi test của nó
    -> thực chất là cùng một bài toán (chỉ đổi lời/đổi số)."""
    tests = other.get("tests") or []
    if not tests or other.get("kind", "io") != kind:
        return False
    if kind == "function":
        for t in tests:
            src = t.get("assert", "")
            m = re.match(r"\s*assert\s+(\w+)\(", src)
            if not m:
                return False
            renamed = re.sub(rf"\b{re.escape(m.group(1))}\(", f"{fname}(", src)
            r = runner.run(solution.rstrip() + "\n\n" + renamed + "\nprint('__SAME__')\n")
            if not (r.ok and "__SAME__" in r.output):
                return False
        return True
    for t in tests:
        r = runner.run(solution, t.get("input", ""))
        if not r.ok or DeterministicGrader._norm(r.output) != DeterministicGrader._norm(t.get("output", "")):
            return False
    return True


def check_novelty(solution: str, kind: str, fname: str, description: str,
                  compare_with: list[dict], runner: "SafePythonRunner") -> str:
    import difflib

    for other in compare_with:
        if not other:
            continue
        ratio = difflib.SequenceMatcher(None, description.lower(), str(other.get("description", "")).lower()).ratio()
        if ratio > 0.8:
            return f"Đề bài gần như chép lại bài \"{other.get('title', '')}\"."
        if _same_behavior(solution, kind, fname, other, runner):
            return (f"Thực chất vẫn là bài \"{other.get('title', '')}\" (chỉ đổi số/đổi lời). "
                    "Cần một bài toán có yêu cầu khác.")
    return ""


_LATEX_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\div": "÷", r"\ldots": "...", r"\dots": "...",
}


def clean_ai_text(text: Any) -> str:
    """Làm sạch chữ do AI soạn để hiển thị cho học sinh:
    '$n$' -> '`n`', '$a \\times b$' -> '`a × b`', bỏ '**' in đậm thừa."""
    value = str(text or "").strip()

    def _math(match: "re.Match[str]") -> str:
        inner = match.group(1).strip()
        for latex, symbol in _LATEX_SYMBOLS.items():
            inner = inner.replace(latex, symbol)
        inner = re.sub(r"\\(?:text|mathrm|mathit)\{([^}]*)\}", r"\1", inner)
        inner = inner.replace("{", "").replace("}", "").replace("\\", "")
        return f"`{inner.strip()}`"

    value = re.sub(r"\$\$(.+?)\$\$", _math, value, flags=re.S)
    value = re.sub(r"\$(?=\S)([^$\n]+?)(?<=\S)\$(?!\d)", _math, value)
    for latex, symbol in _LATEX_SYMBOLS.items():
        value = value.replace(latex, symbol)
    value = value.replace("**", "")
    return value


def build_verified_practice(
    raw: dict[str, Any],
    base_exercise: dict,
    grader: "DeterministicGrader",
    compare_with: list[dict] | None = None,
) -> tuple[dict | None, str]:
    """Kiểm chứng bài AI sinh ra. Trả (bài_tập, "") nếu đạt, hoặc (None, lý_do_loại).

    Nguyên tắc chống "ảo":
      1. Đáp án của mỗi test được TÍNH BẰNG CÁCH CHẠY lời giải mẫu trong sandbox,
         không lấy con số AI tự ghi.
      2. Con số AI tự ghi phải TRÙNG với kết quả chạy thật ở mọi test. Lệch dù
         một test nghĩa là AI hiểu sai đề của chính nó -> loại cả bài.
      3. Lời giải mẫu phải qua bộ chấm; code khung (starter) phải KHÔNG qua.
      4. Bộ test phải có ít nhất 2 kết quả khác nhau (tránh bài in cố định một chữ vẫn đúng).
    """
    runner = grader.runner
    kind = base_exercise.get("kind", "io")
    if not isinstance(raw, dict):
        return None, "AI không trả về JSON hợp lệ."

    title = clean_ai_text(raw.get("title"))
    description = clean_ai_text(raw.get("description"))
    solution = str(raw.get("reference_solution") or "").strip()
    starter = str(raw.get("starter_code") or "").rstrip() + "\n"
    hints = [clean_ai_text(h) for h in (raw.get("hints") or []) if str(h).strip()][:3]
    tests_in = raw.get("tests") or []
    if not (title and description and solution):
        return None, "Thiếu tiêu đề, đề bài hoặc lời giải mẫu."
    if not isinstance(tests_in, list) or not 3 <= len(tests_in) <= 8:
        return None, "Số lượng test không hợp lệ."
    allowed, reason = runner.validate(solution)
    if not allowed:
        return None, f"Lời giải mẫu dùng thao tác bị cấm: {reason}"
    try:
        ast.parse(solution)
    except SyntaxError:
        return None, "Lời giải mẫu sai cú pháp."
    level_problem = check_practice_level(solution, tests_in, base_exercise)
    if level_problem:
        return None, level_problem

    verified_tests: list[dict] = []
    outputs: list[str] = []
    if kind == "function":
        fname = str(raw.get("function_name") or "").strip()
        if not fname.isidentifier() or f"def {fname}(" not in solution:
            return None, "Tên hàm không khớp với lời giải mẫu."
        if f"def {fname}(" not in starter:
            starter = f"def {fname}(...):\n    # Viết code\n    pass\n".replace("...", _signature(solution, fname))
        for case in tests_in:
            call = str((case or {}).get("call") or "").strip()
            if not _call_is_safe(call, fname):
                return None, f"Test không hợp lệ: {call!r}"
            result = runner.run(solution + "\n\nprint(repr(" + call + "))\n")
            if not result.ok or not result.output:
                return None, f"Lời giải mẫu lỗi khi chạy {call}."
            actual = result.output.strip().splitlines()[-1]
            if not _claims_match(case.get("expected"), actual):
                return None, f"AI ghi {call} = {case.get('expected')!r} nhưng chạy thật ra {actual}."
            op = "is" if actual in ("None", "True", "False") else "=="
            verified_tests.append({"assert": f"assert {call} {op} {actual}", "call": call, "expected": actual})
            outputs.append(actual)
    else:
        for case in tests_in:
            stdin = str((case or {}).get("input") or "")
            if stdin and not stdin.endswith("\n"):
                stdin += "\n"
            result = runner.run(solution, stdin)
            if not result.ok or not result.output.strip():
                return None, f"Lời giải mẫu lỗi hoặc không in gì với input {stdin!r}."
            actual = result.output.strip()
            if DeterministicGrader._norm(str(case.get("expected", ""))) != DeterministicGrader._norm(actual):
                return None, f"AI ghi đáp án {case.get('expected')!r} nhưng chạy thật ra {actual!r}."
            verified_tests.append({"input": stdin, "output": actual})
            outputs.append(DeterministicGrader._norm(actual))

    if len(set(outputs)) < 2:
        return None, "Các test cho cùng một kết quả, không đủ để kiểm tra."

    practice = {
        "id": f"practice_{base_exercise['id']}_{random.randint(100000, 999999)}",
        "skill": base_exercise["skill"],
        "difficulty": base_exercise["difficulty"],
        "kind": kind,
        "title": title,
        "description": description,
        "starter_code": starter,
        "tests": verified_tests,
        "hints": hints or ["Xác định dữ liệu vào, cách xử lý và kết quả cần in/trả về."],
        "is_practice": True,
        "public_tests": len(verified_tests),  # bài luyện thêm: học sinh thấy toàn bộ test
        "base_exercise_id": base_exercise["id"],
    }
    if not grader.grade(practice, solution).passed:
        return None, "Lời giải mẫu không vượt qua bộ test đã sinh."
    if starter.strip() and grader.grade(practice, starter).passed:
        return None, "Code khung đã tự qua hết test (bài quá dễ/lỗi đề)."
    fname = str(raw.get("function_name") or "").strip()
    others = [base_exercise] + [x for x in (compare_with or []) if x is not base_exercise]
    duplicate = check_novelty(solution, kind, fname, description, others, runner)
    if duplicate:
        return None, duplicate
    return practice, ""


def _signature(solution: str, fname: str) -> str:
    match = re.search(rf"def {re.escape(fname)}\((.*?)\)\s*:", solution)
    return match.group(1) if match else ""


def generate_practice_exercise(
    llm: OptionalLLM,
    grader: "DeterministicGrader",
    base_exercise: dict,
    max_attempts: int = 3,
    bank: list[dict] | None = None,
    history: list[dict] | None = None,
) -> tuple[dict | None, str]:
    """Nhờ AI sinh bài tương tự bài đang làm; thử lại tối đa max_attempts lần
    cho tới khi có bài vượt qua toàn bộ bước kiểm chứng."""
    if not llm.available:
        return None, "Chưa cấu hình AI (file .env) nên chưa thể sinh bài luyện thêm."
    last_reason = "AI không phản hồi."
    skill = base_exercise.get("skill", "")
    # So trùng với: bài gốc + các bài cùng kỹ năng trong kho + các bài luyện thêm đã tạo
    compare_with = [x for x in (bank or []) if x.get("skill") == skill] + list(history or [])
    used_titles = [x.get("title", "") for x in compare_with] + [base_exercise.get("title", "")]
    ideas = [i for i in TOPIC_IDEAS.get(skill, []) if not any(i.split()[-1] in t.lower() for t in used_titles)]
    random.shuffle(ideas)
    for attempt in range(1, max_attempts + 1):
        idea = ideas[(attempt - 1) % len(ideas)] if ideas else ""
        raw = llm._json_chat(
            system=PRACTICE_SYSTEM_PROMPT,
            user=json.dumps({
                "kieu_bai": base_exercise.get("kind", "io"),
                "ky_nang": base_exercise.get("skill", ""),
                "do_kho": base_exercise.get("difficulty", 1),
                "kien_thuc_duoc_dung": SKILL_ALLOWED_TEXT.get(base_exercise.get("skill", ""), ""),
                "dang_du_lieu_vao_bat_buoc": describe_input_shape(base_exercise),
                "bai_goc": {
                    "title": base_exercise["title"],
                    "description": base_exercise["description"],
                    "starter_code": base_exercise.get("starter_code", ""),
                    "vi_du_test": base_exercise.get("tests", [])[:2],
                },
                "y_tuong_de_bai": idea,
                "cac_bai_da_co_khong_duoc_lap_lai": sorted(set(t for t in used_titles if t)),
                "lan_thu": attempt,
                "luu_y_lan_truoc": last_reason if attempt > 1 else "",
            }, ensure_ascii=False),
            temperature=0.7,
        )
        if raw is None and not llm.last_call_ok:
            return None, "Không kết nối được AI. Kiểm tra Ollama/API rồi thử lại."
        practice, reason = build_verified_practice(raw, base_exercise, grader, compare_with)
        if practice:
            return practice, ""
        last_reason = reason
    return None, f"AI chưa tạo được bài đạt yêu cầu kiểm chứng sau {max_attempts} lần ({last_reason}). Em bấm thử lại nhé."
