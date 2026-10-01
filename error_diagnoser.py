"""Chẩn đoán lỗi code của học sinh: chỉ đúng DÒNG, nói rõ LỖI GÌ và CÁCH SỬA.

Không dùng AI để đoán. Mọi kết luận đều dựa trên dữ kiện thật:
  - thông báo lỗi của chính trình thông dịch Python (compile / stderr),
  - phân tích cây cú pháp (AST) của code học sinh,
  - so sánh kết quả chạy thật với kết quả mong đợi của test.

Kết quả là một dict ngắn gọn:
    {"line": 3, "code_line": "if n%2 = 0:",
     "problem": "...", "fix": "...", "example": "if n%2 == 0:"}
"""

from __future__ import annotations

import ast
import builtins
import difflib
import re
from typing import Any

COMMON_NAMES = [
    "print", "input", "int", "float", "str", "len", "range", "abs", "max", "min",
    "sum", "round", "list", "sorted", "bool", "True", "False", "None", "map", "set",
]
BLOCK_KEYWORDS = ("if", "elif", "else", "for", "while", "def", "try", "except", "finally", "with", "class")


def _diag(line: int | None, code_line: str, problem: str, fix: str, example: str = "") -> dict[str, Any]:
    return {
        "line": line,
        "code_line": code_line.strip(),
        "problem": problem,
        "fix": fix,
        "example": example.rstrip("\n").rstrip(),
    }


def _line_text(lines: list[str], line: int | None) -> str:
    if line and 1 <= line <= len(lines):
        return lines[line - 1]
    return ""


def _first_word(text: str) -> str:
    match = re.match(r"\s*([A-Za-z_]+)", text)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# 1. LỖI CÚ PHÁP / THỤT LỀ (bắt bằng compile, KHÔNG chạy code)
# ---------------------------------------------------------------------------

def _fix_assign_in_condition(text: str) -> str:
    """Đổi dấu '=' đơn (không thuộc ==, <=, >=, !=) đầu tiên thành '=='."""
    return re.sub(r"(?<![=!<>])=(?!=)", "==", text, count=1)


def _fixes_line(lines: list[str], line_no: int, new_lines: list[str]) -> bool:
    """Thay dòng line_no bằng new_lines rồi cho Python kiểm tra lại.
    Đúng nếu hết lỗi, hoặc lỗi còn lại nằm ở dòng SAU đoạn vừa sửa (lỗi khác)."""
    candidate = lines[: line_no - 1] + new_lines + lines[line_no:]
    try:
        compile("\n".join(candidate) + "\n", "<check>", "exec")
        return True
    except SyntaxError as err:
        return bool(err.lineno) and err.lineno > line_no - 1 + len(new_lines)


def _indent_of(text: str) -> str:
    return text[: len(text) - len(text.lstrip())]


def _missing_colon(err: SyntaxError, lines: list[str]) -> dict[str, Any] | None:
    """Thiếu ':' sau if/elif/else/for/while/def, kể cả khi học sinh viết gộp
    lệnh lên cùng dòng (vd `else print("AM")`). Mọi cách sửa đều được kiểm chứng."""
    line = err.lineno
    text = _line_text(lines, line)
    word = _first_word(text)
    if not line or word not in ("if", "elif", "else", "for", "while", "def"):
        return None
    indent = _indent_of(text)
    body = text.strip()
    candidates: list[tuple[str, str]] = []
    if word == "else":
        candidates.append(("else", body[4:].strip()))
    if err.offset and 1 < err.offset <= len(text):
        idx = err.offset - 1
        candidates.append((text[:idx].strip(), text[idx:].strip()))
    candidates.append((body.rstrip(":").rstrip(), ""))
    for header, rest in candidates:
        header = header.rstrip(":").rstrip()
        rest = rest.rstrip()
        if rest.endswith(":") and not rest.endswith("::"):
            rest = rest[:-1].rstrip()
        if not header or header == word and word != "else":
            continue
        new_lines = [indent + header + ":"] + ([indent + "    " + rest] if rest else [])
        if not _fixes_line(lines, line, new_lines):
            continue
        example = "\n".join(l[len(indent):] if l.startswith(indent) else l for l in new_lines)
        if rest:
            misplaced = " (không phải ở cuối dòng)" if body.endswith(":") else ""
            return _diag(line, text, f"Thiếu dấu `:` ngay sau `{header}`{misplaced}.",
                         f"Đặt `:` ngay sau `{header}`, rồi đưa lệnh `{rest}` xuống dòng dưới và thụt vào 4 dấu cách.",
                         example)
        return _diag(line, text, f"Thiếu dấu `:` ở cuối dòng `{word}`.", "Thêm dấu `:` vào cuối dòng.", example)
    return None


def diagnose_syntax(code: str) -> dict[str, Any] | None:
    try:
        compile(code, "<student>", "exec")
        return None
    except SyntaxError as err:  # IndentationError, TabError là lớp con
        lines = code.splitlines()
        diag = _syntax_rules(err, lines)
        # Chỉ hiện dòng sửa mẫu khi Python xác nhận nó thật sự hết lỗi
        if diag.get("example") and diag.get("line"):
            indent = _indent_of(_line_text(lines, diag["line"]))
            ex_lines = diag["example"].split("\n")
            first_indent = _indent_of(ex_lines[0])
            new_lines = [(indent if not first_indent else "") + l if i == 0 else
                         (indent + l if not l.startswith(indent) or not indent else l)
                         for i, l in enumerate(ex_lines)]
            if not _fixes_line(lines, diag["line"], new_lines):
                diag["example"] = ""
        return diag


def _syntax_rules(err: SyntaxError, lines: list[str]) -> dict[str, Any]:
    msg = (err.msg or "").strip()
    low = msg.lower()
    line = err.lineno
    text = _line_text(lines, line)
    stripped = text.strip()
    word = _first_word(text)

    # ---- Thụt lề
    if isinstance(err, TabError) or "inconsistent use of tabs" in low:
        return _diag(line, text, "Dòng này trộn phím Tab và dấu cách khi thụt lề.",
                     "Xóa phần thụt lề rồi gõ lại bằng đúng 4 dấu cách.")
    if "expected an indented block" in low:
        m = re.search(r"after '(\w+)' statement on line (\d+)", msg)
        kw, head = (m.group(1), int(m.group(2))) if m else ("", None)
        head_txt = f" `{kw}` ở dòng {head}" if head else ""
        base = _indent_of(_line_text(lines, head)) if head else ""
        return _diag(line, text, f"Lệnh bên trong khối{head_txt} chưa được thụt vào.",
                     "Thụt dòng này vào 4 dấu cách so với dòng có dấu `:` phía trên.",
                     base + "    " + stripped)
    if "unexpected indent" in low:
        return _diag(line, text, "Dòng này bị thụt lề thừa.",
                     "Xóa khoảng trắng đầu dòng để thẳng hàng với dòng phía trên.", stripped)
    if "unindent does not match" in low:
        return _diag(line, text, "Thụt lề của dòng này không khớp với các dòng cùng khối.",
                     "Dùng đúng 4 dấu cách cho mỗi cấp thụt lề, các dòng cùng khối phải thẳng hàng.")

    # ---- Lỗi viết hoa từ khóa: If, Else, For, While, Def...
    if word and word != word.lower() and word.lower() in BLOCK_KEYWORDS:
        return _diag(line, text, f"Python phân biệt chữ hoa/thường: không có từ khóa `{word}`.",
                     f"Viết thường thành `{word.lower()}`.", text.replace(word, word.lower(), 1))

    # ---- 'else if' thay vì 'elif'
    if re.match(r"\s*else\s+if\b", text):
        return _diag(line, text, "Python không dùng `else if`.", "Viết liền thành `elif`.",
                     re.sub(r"else\s+if", "elif", text, count=1))

    # ---- '=' trong điều kiện
    if "instead of '='" in low or ("cannot assign" in low and word in ("if", "elif", "while")):
        return _diag(line, text, "Điều kiện đang dùng `=` (phép GÁN), không phải phép SO SÁNH.",
                     "Đổi `=` thành `==` để so sánh bằng.", _fix_assign_in_condition(text))

    # ---- Thiếu dấu ':' (kể cả viết gộp: `else print(...)`, `if x > 0 print(...)`)
    if "expected ':'" in low or ("invalid syntax" in low and word in ("if", "elif", "else", "for", "while", "def")):
        colon = _missing_colon(err, lines)
        if colon:
            return colon
    if "expected ':'" in low:
        return _diag(line, text, f"Thiếu dấu `:` trong dòng `{word or stripped}`.",
                     "Dấu `:` phải đặt ngay sau điều kiện (hoặc sau `else`), trước các lệnh bên trong.")

    # ---- Ngoặc
    if "was never closed" in low:
        ch = re.search(r"'(.)' was never closed", msg)
        opener = ch.group(1) if ch else "("
        closer = {"(": ")", "[": "]", "{": "}"}.get(opener, ")")
        missing = text.count(opener) - text.count(closer)
        example = text.rstrip() + closer * max(missing, 1) if missing > 0 else ""
        return _diag(line, text, f"Mở ngoặc `{opener}` nhưng chưa đóng.",
                     f"Thêm `{closer}` vào đúng vị trí. Số ngoặc mở và đóng phải bằng nhau.", example)
    if low.startswith("unmatched") or "does not match opening parenthesis" in low:
        return _diag(line, text, "Thừa dấu ngoặc đóng hoặc đóng sai loại ngoặc.",
                     "Đếm lại: mỗi `(` phải có đúng một `)`, `[` đi với `]`.")

    # ---- Chuỗi / dấu nháy
    if "unterminated string" in low or "unterminated triple-quoted" in low or "eol while scanning" in low:
        return _diag(line, text, "Chuỗi chữ thiếu dấu nháy đóng.",
                     "Mở bằng `\"` thì phải đóng bằng `\"`, mở bằng `'` thì đóng bằng `'`.")

    # ---- Ký tự lạ (dấu nháy cong, gõ Telex...)
    if "invalid character" in low or "invalid non-printable" in low:
        ch = re.search(r"'(.)'", msg)
        shown = f" `{ch.group(1)}`" if ch else ""
        return _diag(line, text, f"Có ký tự lạ{shown} trong code (thường do bộ gõ tiếng Việt hoặc dấu nháy cong “ ”).",
                     "Tắt bộ gõ tiếng Việt và gõ lại ký tự đó; dấu nháy phải là `\"` hoặc `'`.")

    # ---- print không ngoặc (kiểu Python 2)
    if "missing parentheses in call to 'print'" in low:
        return _diag(line, text, "Lệnh `print` thiếu dấu ngoặc.", "Đặt nội dung cần in trong ngoặc: `print(...)`.",
                     re.sub(r"print\s+(.*)", r"print(\1)", text, count=1))

    # ---- 2n, 3x ...
    if "invalid decimal literal" in low:
        fixed = re.sub(r"(\d)([A-Za-z_])", r"\1*\2", text, count=1)
        return _diag(line, text, "Viết số liền với tên biến (ví dụ `2n`). Python không tự hiểu là phép nhân.",
                     "Thêm dấu `*` giữa số và biến, ví dụ `2*n`.", fixed if fixed != text else "")

    # ---- Thiếu dấu phẩy
    if "forgot a comma" in low:
        return _diag(line, text, "Thiếu dấu `,` giữa các giá trị.", "Thêm dấu phẩy để ngăn cách các giá trị.")

    # ---- else/elif đặt sai chỗ
    if word in ("else", "elif") and "invalid syntax" in low:
        return _diag(line, text, f"`{word}` không đi liền sau một khối `if`.",
                     f"`{word}` phải thẳng hàng với `if` tương ứng và nằm ngay sau khối lệnh của `if`.")

    if "'return' outside function" in low:
        return _diag(line, text, "`return` chỉ dùng được bên trong hàm (`def`).",
                     "Thụt dòng `return` vào trong thân hàm, hoặc dùng `print` nếu không viết hàm.")
    if "expected 'in'" in low:
        return _diag(line, text, "Vòng `for` thiếu từ khóa `in`.", "Viết theo mẫu: `for i in range(n):`.")
    if "cannot assign to function call" in low:
        return _diag(line, text, "Không thể gán giá trị cho một lời gọi hàm.",
                     "Tên biến phải đứng bên trái dấu `=`, ví dụ `n = int(input())`.")
    if "cannot assign to literal" in low:
        return _diag(line, text, "Bên trái dấu `=` phải là tên biến, không phải con số hay chuỗi.",
                     "Đổi chỗ: `ten_bien = gia_tri`.")

    # ---- Không khớp quy tắc nào: vẫn chỉ đúng dòng + cột
    col = f", cột {err.offset}" if err.offset else ""
    return _diag(line, text, f"Câu lệnh viết sai cú pháp{col}.",
                 f"Kiểm tra từng ký tự quanh vị trí{col or ' này'}: dấu `:`, ngoặc, dấu nháy, toán tử. (Python báo: {msg})")


# ---------------------------------------------------------------------------
# 2. LỖI KHI CHẠY (dựa trên stderr thật)
# ---------------------------------------------------------------------------

def _defined_names(code: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            names.update(a.arg for a in node.args.args)
    return names


def _expected_words(exercise: dict) -> set[str]:
    words: set[str] = set()
    for test in exercise.get("tests", []):
        words.update(re.findall(r"[A-Za-z_]+", str(test.get("output", ""))))
    words.update(re.findall(r"\b[A-Z][A-Z_]{1,}\b", exercise.get("description", "")))
    return words


def diagnose_runtime(exercise: dict, code: str, error_type: str, stderr: str, line: int | None) -> dict[str, Any]:
    lines = code.splitlines()
    if line and line > len(lines):  # lỗi xảy ra ở dòng test gọi hàm, không phải trong code học sinh
        line = None
    text = _line_text(lines, line)
    last = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    msg = last.split(":", 1)[1].strip() if ":" in last else last

    if error_type == "NameError":
        m = re.search(r"name '(\w+)' is not defined", msg)
        name = m.group(1) if m else "?"
        if name in _expected_words(exercise) or (name.isupper() and len(name) > 1):
            return _diag(line, text, f"`{name}` là chữ cần in nhưng thiếu dấu nháy nên Python tưởng là tên biến.",
                         f"Đặt trong dấu nháy: `\"{name}\"`.", text.replace(name, f'"{name}"', 1))
        if name.lower() in COMMON_NAMES and name != name.lower():
            return _diag(line, text, f"Python phân biệt hoa/thường: `{name}` khác `{name.lower()}`.",
                         f"Viết thường thành `{name.lower()}`.", text.replace(name, name.lower(), 1))
        candidates = sorted(_defined_names(code)) + COMMON_NAMES + [n for n in dir(builtins) if n.islower()]
        close = difflib.get_close_matches(name, candidates, n=1, cutoff=0.75)
        if close and close[0] != name:
            return _diag(line, text, f"Tên `{name}` chưa được định nghĩa. Có thể em viết nhầm `{close[0]}`.",
                         f"Sửa `{name}` thành `{close[0]}`.", text.replace(name, close[0], 1))
        return _diag(line, text, f"Biến `{name}` được dùng khi chưa có giá trị.",
                     f"Gán giá trị cho `{name}` ở phía trên dòng này (ví dụ `{name} = 0` hoặc `{name} = int(input())`).")

    if error_type == "UnboundLocalError":
        m = re.search(r"'(\w+)'", msg)
        name = m.group(1) if m else "biến"
        return _diag(line, text, f"Trong hàm, `{name}` được dùng trước khi gán giá trị.",
                     f"Gán giá trị ban đầu cho `{name}` ở đầu thân hàm.")

    if error_type == "TypeError":
        str_int = (
            "can only concatenate str" in msg
            or ("'str' and 'int'" in msg) or ("'int' and 'str'" in msg)
            or ("'str' and 'float'" in msg) or ("'float' and 'str'" in msg)
            or "not all arguments converted during string formatting" in msg
        )
        if str_int:
            if "print(" in text and re.search(r"[\"']", text) and "+" in text:
                return _diag(line, text, "Đang dùng `+` để nối chữ với số.",
                             "Trong `print`, ngăn cách chữ và số bằng dấu phẩy: `print(\"Kết quả:\", s)`, "
                             "hoặc đổi số thành chữ bằng `str(s)`.")
            return _diag(line, text, "Đang tính toán với dữ liệu kiểu chuỗi (`input()` luôn trả về chuỗi).",
                         "Đổi sang số khi nhập: `int(input())` hoặc `float(input())`.")
        if "not callable" in msg:
            m = re.search(r"'(\w+)' object is not callable", msg)
            kind = m.group(1) if m else ""
            shadow = [n for n in _defined_names(code) if n in ("sum", "max", "min", "len", "list", "str", "int", "input", "print", "abs", "round")]
            if shadow:
                return _diag(line, text, f"Em đã đặt tên biến trùng tên hàm có sẵn `{shadow[0]}` nên không gọi được hàm đó nữa.",
                             f"Đổi tên biến, ví dụ `{shadow[0]}` → `tong` hoặc `{shadow[0]}_1`.")
            return _diag(line, text, f"Đang gọi `(...)` trên một giá trị kiểu `{kind}` như thể nó là hàm.",
                         "Nếu muốn nhân, thêm dấu `*`, ví dụ `2*(n+1)` thay vì `2(n+1)`.")
        if "is not iterable" in msg:
            return _diag(line, text, "Vòng `for` đang duyệt trực tiếp một con số.",
                         "Muốn lặp n lần hoặc từ 0 đến n-1, dùng `range(n)`: `for i in range(n):`.")
        if "is not subscriptable" in msg:
            return _diag(line, text, "Đang dùng `[ ]` lấy phần tử của một giá trị không phải danh sách/chuỗi.",
                         "Kiểm tra biến trước dấu `[` có đúng là danh sách/chuỗi không.")
        m = re.search(r"missing (\d+) required positional argument", msg)
        if m:
            return _diag(line, text, "Gọi hàm thiếu đối số.", "Truyền đủ số đối số như khi định nghĩa hàm với `def`.")
        m = re.search(r"takes (\d+) positional arguments? but (\d+) (?:was|were) given", msg)
        if m:
            return _diag(line, text, f"Hàm được định nghĩa nhận {m.group(1)} tham số nhưng lại được gọi với {m.group(2)} đối số.",
                         "Sửa dòng `def` cho đúng số tham số đề bài yêu cầu.")
        return _diag(line, text, "Phép toán đang dùng sai kiểu dữ liệu.", f"Kiểm tra kiểu int/float/str của các biến. (Python báo: {msg})")

    if error_type == "ValueError":
        m = re.search(r"invalid literal for (int|float)\(\)(?: with base 10)?: '(.*)'", msg)
        if m:
            func, raw = m.group(1), m.group(2)
            if len(raw.split()) > 1:
                n = len(raw.split())
                names = ", ".join("abcdefgh"[:n]) if n <= 8 else "a, b"
                return _diag(line, text, f"Dữ liệu nhập có {n} giá trị trên CÙNG MỘT DÒNG, nhưng `{func}(input())` chỉ đọc được 1 giá trị.",
                             "Tách dòng nhập bằng `split()` rồi đổi kiểu từng phần.",
                             f"{names} = map({func}, input().split())")
            if func == "int" and re.fullmatch(r"-?\d+\.\d*", raw):
                return _diag(line, text, f"Dữ liệu `{raw}` là số thập phân, `int()` không đọc được.",
                             "Dùng `float(input())`.", text.replace("int(", "float(", 1))
            if raw == "":
                return _diag(line, text, "`input()` đọc phải một dòng trống.",
                             "Kiểm tra số lần gọi `input()` có khớp số dòng dữ liệu không.")
            return _diag(line, text, f"Không đổi được `{raw}` sang số.", "Chỉ dùng `int()`/`float()` với dữ liệu là số.")
        if "not enough values to unpack" in msg or "too many values to unpack" in msg:
            return _diag(line, text, "Số biến bên trái `=` không khớp số giá trị nhận được.",
                         "Đếm lại: có bao nhiêu giá trị trên dòng nhập thì cần bấy nhiêu biến.")
        return _diag(line, text, "Giá trị không hợp lệ.", f"(Python báo: {msg})")

    if error_type == "EOFError":
        return _diag(line, text, "Chương trình gọi `input()` nhiều lần hơn số dòng dữ liệu.",
                     "Nếu các số nằm trên cùng một dòng, dùng một lệnh `input().split()` thay vì nhiều lệnh `input()`.")
    if error_type == "ZeroDivisionError":
        return _diag(line, text, "Có phép chia (hoặc chia lấy dư) cho 0.",
                     "Kiểm tra mẫu số khác 0 bằng `if` trước khi chia.")
    if error_type == "IndexError":
        return _diag(line, text, "Truy cập vị trí không tồn tại trong danh sách/chuỗi.",
                     "Chỉ số hợp lệ từ `0` đến `len(a) - 1`. Kiểm tra `range(...)` của vòng lặp và trường hợp danh sách rỗng.")
    if error_type == "KeyError":
        return _diag(line, text, "Truy cập khóa không có trong từ điển.", "Kiểm tra khóa tồn tại bằng `if khoa in d:` trước khi dùng.")
    if error_type == "RecursionError":
        return _diag(line, text, "Hàm gọi lại chính nó mãi không dừng.", "Thêm điều kiện dừng (`if ...: return ...`) ở đầu hàm.")
    if error_type == "AttributeError":
        m = re.search(r"'(\w+)' object has no attribute '(\w+)'", msg)
        if m:
            return _diag(line, text, f"Kiểu `{m.group(1)}` không có phương thức `.{m.group(2)}()`.",
                         "Kiểm tra lại kiểu của biến và tên phương thức (ví dụ `.split()` chỉ dùng cho chuỗi).")
    return _diag(line, text, f"Chương trình bị lỗi khi chạy ({error_type}).", f"(Python báo: {msg or error_type})")


# ---------------------------------------------------------------------------
# 3. CHẠY QUÁ LÂU
# ---------------------------------------------------------------------------

def diagnose_timeout(code: str) -> dict[str, Any]:
    lines = code.splitlines()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                cond_names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                changed: set[str] = set()
                has_break = False
                for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                        targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                        for t in targets:
                            changed.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
                    if isinstance(sub, (ast.Break, ast.Return)):
                        has_break = True
                if isinstance(node.test, ast.Constant) and node.test.value and not has_break:
                    return _diag(node.lineno, _line_text(lines, node.lineno), "`while True` không có lệnh `break` nên lặp mãi.",
                                 "Thêm `break` khi đạt điều kiện dừng, hoặc viết điều kiện dừng ngay sau `while`.")
                if cond_names and not (cond_names & changed) and not has_break:
                    names = ", ".join(f"`{n}`" for n in sorted(cond_names))
                    return _diag(node.lineno, _line_text(lines, node.lineno),
                                 f"Biến {names} trong điều kiện `while` không thay đổi bên trong vòng lặp nên vòng lặp không bao giờ dừng.",
                                 "Cập nhật biến điều khiển trong thân vòng lặp, ví dụ `n = n // 10` hoặc `i += 1`.")
    return _diag(None, "", "Chương trình chạy quá 3 giây, có thể có vòng lặp vô hạn.",
                 "Kiểm tra điều kiện dừng của `while` và biến điều khiển có thay đổi sau mỗi vòng không.")


# ---------------------------------------------------------------------------
# 4. CHẠY ĐƯỢC NHƯNG SAI KẾT QUẢ
# ---------------------------------------------------------------------------

def _norm(value: str) -> str:
    return " ".join(str(value).strip().split())


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _describe_case(values: list[str]) -> str:
    """Mô tả trường hợp đặc biệt mà không lộ nguyên test ẩn."""
    joined = " ".join(values)
    if any(v in ("[]", "''", '""', "") for v in values) or "[]" in joined:
        return "danh sách/chuỗi rỗng"
    nums = [_to_float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", joined)]
    nums = [n for n in nums if n is not None]
    if any(n == 0 for n in nums):
        return "có số 0"
    if any(n < 0 for n in nums):
        return "có số âm"
    if any(n == 1 for n in nums):
        return "giá trị bằng 1"
    return "trường hợp đặc biệt/biên"


def _first_line_of(code: str, node_types: tuple) -> int | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    found = [n.lineno for n in ast.walk(tree) if isinstance(n, node_types)]
    return min(found) if found else None


def _print_inside_loop(code: str) -> int | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for loop in ast.walk(tree):
        if isinstance(loop, (ast.For, ast.While)):
            for sub in ast.walk(ast.Module(body=loop.body, type_ignores=[])):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "print":
                    return sub.lineno
    return None


def diagnose_wrong_output(exercise: dict, code: str, test_index: int, stdin: str, expected: str,
                          got: str, public: bool) -> dict[str, Any]:
    lines = code.splitlines()
    exp, out = _norm(expected), _norm(got)
    where = f"Với dữ liệu vào `{stdin.strip()}`" if public else f"Ở một test ẩn ({_describe_case(stdin.split())})"

    if not out:
        return _diag(None, "", "Chương trình chạy xong nhưng không in ra gì.",
                     "Dùng `print(...)` để in kết quả cuối cùng.")
    if out.lower() == exp.lower():
        return _diag(None, "", f"Sai chữ hoa/thường: đề yêu cầu in `{exp}`, em in `{out}`.",
                     f"In đúng từng chữ như đề: `{exp}`.")
    if out.strip("'\"") == exp:
        return _diag(None, "", "Kết quả in ra bị thừa dấu nháy.", "In trực tiếp giá trị, không bọc thêm dấu nháy.")
    e_num, o_num = _to_float(exp), _to_float(out)
    if e_num is not None and o_num is not None:
        if e_num == o_num:
            if "." in out and "." not in exp:
                return _diag(None, "", f"Kết quả cần là số nguyên (`{exp}`) nhưng em in số thực (`{out}`).",
                             "Dùng phép chia nguyên `//` thay cho `/`, hoặc đổi bằng `int(...)`.")
            if "." in exp and "." not in out:
                return _diag(None, "", f"Kết quả cần là số thực (`{exp}`) nhưng em in số nguyên (`{out}`).",
                             "Dùng phép chia `/` hoặc `float(...)`.")
        decimals = len(exp.split(".")[1]) if "." in exp else 0
        if decimals and round(o_num, decimals) == e_num:
            return _diag(None, "", f"Kết quả chưa được làm tròn {decimals} chữ số thập phân.",
                         f"Dùng `round(x, {decimals})` trước khi in.")
        detail = f"{where}, em in `{out}` nhưng đúng phải là `{exp}`." if public else f"{where}, kết quả em in chưa đúng."
        if "range(" in code and "loops" in exercise.get("skill", ""):
            return _diag(None, "", detail,
                         "Kiểm tra giới hạn `range(a, b)`: vòng lặp dừng TRƯỚC `b`. Tính tay một lượt để so sánh.")
        return _diag(None, "", detail, "Tính tay với dữ liệu này rồi so với công thức/các bước trong code.")

    got_lines = [l for l in got.strip().splitlines() if l.strip()]
    exp_lines = [l for l in expected.strip().splitlines() if l.strip()]
    if len(got_lines) > len(exp_lines):
        loop_print = _print_inside_loop(code)
        if loop_print and exp in out:
            return _diag(loop_print, _line_text(lines, loop_print),
                         "Lệnh `print` nằm trong vòng lặp nên in ra nhiều lần.",
                         "Bỏ thụt lề để đưa `print` ra ngoài vòng lặp, chỉ in một lần sau khi tính xong.",
                         _line_text(lines, loop_print).strip())
    if exp in out and out != exp:
        extra = out.replace(exp, "").strip()
        return _diag(None, "", f"In thừa nội dung `{extra}`." if public else "In thừa chữ/giải thích bên cạnh kết quả.",
                     "Chỉ in đúng kết quả mà đề yêu cầu, không thêm chữ hay dấu câu.")

    detail = f"{where}, em in `{out}` nhưng đúng phải là `{exp}`." if public else f"{where}, kết quả em in chưa đúng."
    if_line = _first_line_of(code, (ast.If,))
    if if_line:
        return _diag(if_line, _line_text(lines, if_line), detail,
                     "Điều kiện rẽ nhánh đang cho kết quả sai với trường hợp này. Kiểm tra toán tử so sánh "
                     "(`>`, `>=`, `==`) và thứ tự các nhánh `if/elif/else`.")
    return _diag(None, "", detail, "Tính tay với dữ liệu này rồi so với từng bước trong code.")


def _split_assert(assert_src: str) -> tuple[str, str] | None:
    try:
        node = ast.parse(assert_src.strip()).body[0]
    except (SyntaxError, IndexError):
        return None
    if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) and len(node.test.comparators) == 1:
        return ast.unparse(node.test.left), ast.unparse(node.test.comparators[0])
    return None


def diagnose_wrong_return(exercise: dict, code: str, assert_src: str, actual_repr: str | None,
                          public: bool) -> dict[str, Any]:
    lines = code.splitlines()
    parts = _split_assert(assert_src)
    call, expected = parts if parts else (assert_src, "?")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    has_return = bool(tree) and any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(tree))

    if actual_repr == "None" and expected != "None":
        print_line = None
        if tree:
            for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "print":
                        print_line = sub.lineno
                        break
        if print_line and not has_return:
            text = _line_text(lines, print_line)
            return _diag(print_line, text, "Hàm đang `print` kết quả chứ không `return` nên giá trị trả về là `None`.",
                         "Đổi `print(...)` thành `return ...`.", re.sub(r"print\((.*)\)\s*$", r"return \1", text.strip()))
        if not has_return:
            return _diag(None, "", "Hàm chưa có lệnh `return` nên luôn trả về `None`.",
                         "Thêm `return <kết quả>` ở cuối hàm (còn `pass` thì xóa đi).")
        return _diag(None, "", (f"`{call}` trả về `None` nhưng đúng phải là `{expected}`." if public
                                else f"Ở một test ẩn ({_describe_case([call])}), hàm trả về `None`."),
                     "Có nhánh trong hàm kết thúc mà chưa gặp `return`. Kiểm tra mọi nhánh `if/else` đều có `return`.")

    if public:
        got = f"`{actual_repr}`" if actual_repr is not None else "giá trị khác"
        problem = f"`{call}` đang trả về {got} nhưng đúng phải là `{expected}`."
    else:
        problem = f"Ở một test ẩn ({_describe_case([call])}), hàm trả về kết quả chưa đúng."
    if actual_repr in ("True", "False") and expected in ("True", "False"):
        return _diag(None, "", problem, "Điều kiện kiểm tra trong hàm đang cho kết quả ngược. Xem lại toán tử so sánh và các trường hợp đặc biệt.")
    if actual_repr is not None and expected != "None" and _to_float(actual_repr) is not None and _to_float(expected) is not None:
        return _diag(None, "", problem, "Tính tay với đối số này rồi so với từng bước trong hàm (giá trị khởi tạo, điều kiện vòng lặp).")
    if expected == "None":
        return _diag(None, "", problem, "Đề yêu cầu trả về `None` trong trường hợp này. Thêm `if` xử lý riêng rồi `return None`.")
    return _diag(None, "", problem, "Tính tay với đối số này rồi so với từng bước trong hàm.")


# ---------------------------------------------------------------------------
# 5. ĐIỂM VÀO CHUNG
# ---------------------------------------------------------------------------

def diagnose(exercise: dict, code: str, details: list, runner: Any, public_count: int = 2) -> dict[str, Any] | None:
    """details: danh sách RunResult theo thứ tự test (grader dừng ở lỗi đầu tiên)."""
    if not code.strip():
        return _diag(None, "", "Em chưa viết code.", "Bắt đầu từ: nhập dữ liệu → xử lý → in kết quả.")

    syntax = diagnose_syntax(code)
    if syntax:
        return syntax

    kind = exercise.get("kind", "io")
    tests = exercise.get("tests", [])
    for index, result in enumerate(details):
        test = tests[index] if index < len(tests) else {}
        public = index < public_count
        if result.error_type == "BlockedCode":
            return _diag(None, "", result.blocked_reason or "Code dùng lệnh không được phép.",
                         "Chỉ dùng các lệnh Python cơ bản; không mở file, không import thư viện hệ thống.")
        if result.error_type == "TimeoutError" or (not result.ok and not result.stderr.strip() and not result.error_type):
            return diagnose_timeout(code)
        if kind == "function":
            if result.error_type == "AssertionError":
                parts = _split_assert(test.get("assert", ""))
                actual = None
                if parts and runner is not None:
                    probe = runner.run(code.rstrip() + f"\n\nprint(repr({parts[0]}))\n")
                    if probe.ok and probe.output:
                        actual = probe.output.strip().splitlines()[-1]
                return diagnose_wrong_return(exercise, code, test.get("assert", ""), actual, public)
            if not result.ok:
                return diagnose_runtime(exercise, code, result.error_type or "RuntimeError", result.stderr, result.line)
            continue
        if not result.ok:
            return diagnose_runtime(exercise, code, result.error_type or "RuntimeError", result.stderr, result.line)
        if _norm(result.output) != _norm(test.get("output", "")):
            return diagnose_wrong_output(exercise, code, index, test.get("input", ""), test.get("output", ""),
                                         result.output, public)
    return None
