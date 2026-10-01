from __future__ import annotations
from streamlit_ace import st_ace

import json
import os
import random
from dataclasses import asdict
from pathlib import Path

import streamlit as st
import pandas as pd


def load_cloud_secrets() -> None:
    """Khi chạy trên Streamlit Community Cloud, cấu hình nằm trong mục Secrets.
    Chép các giá trị cấp gốc (vd EDUCODER_LLM_API_KEY) sang biến môi trường để
    phần còn lại của app đọc giống như khi chạy bằng file .env trên máy."""
    try:
        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float)) and key not in os.environ:
                os.environ[key] = str(value)
    except Exception:  # chạy trên máy không có secrets.toml
        pass


load_cloud_secrets()

# Mật khẩu ban đầu khi hệ thống tự tạo tài khoản lần đầu.
# Trên máy: mặc định 123456. Khi đưa lên mạng: đặt EDUCODER_ADMIN_PASSWORD trong Secrets.
ADMIN_INITIAL_PASSWORD = os.environ.get("EDUCODER_ADMIN_PASSWORD") or "123456"
DEFAULT_USER_PASSWORD = os.environ.get("EDUCODER_DEFAULT_PASSWORD") or "123456"


def auto_seed_data():
    """Tự động khởi tạo Admin, Giáo viên, 40 học sinh từ Excel và gán vào lớp học."""
    # 1. Khởi tạo Admin nếu hệ thống chưa có người dùng
    if not auth.has_users():
        admin = auth.bootstrap_admin("admin", "Quản trị viên EDUCODER", ADMIN_INITIAL_PASSWORD)
    else:
        admin = auth.get_user(1)

    # 2. Khởi tạo Giáo viên mẫu phụ trách lớp
    teacher = None
    existing_users = {u["username"]: u for u in auth.list_users(admin.id)}
    
    if "giaovien_tin" not in existing_users:
        try:
            teacher = auth.create_user(admin.id, "giaovien_tin", "Thầy Cô Tin Học", "teacher", DEFAULT_USER_PASSWORD)
            existing_users["giaovien_tin"] = {"id": teacher.id, "username": "giaovien_tin"}
        except Exception:
            pass
    else:
        teacher_id = existing_users["giaovien_tin"]["id"]
        teacher = auth.get_user(teacher_id)

    # 3. Tạo lớp học mặc định do Giáo viên phụ trách (nếu chưa có lớp)
    classes = auth.list_classes(admin.id)
    target_class = None
    
    if classes:
        target_class = classes[0]
    elif teacher:
        try:
            target_class = auth.create_class(admin.id, "10A1 - Tin học 10", teacher.id)
        except Exception as e:
            print("Lỗi tạo lớp học mặc định:", e)

    # 4. Đọc file Excel 40 học sinh, tạo tài khoản và tự động thêm vào lớp
    excel_path = ROOT / "data" / "danh_sach_10a1.xlsx"
    if excel_path.exists():
        try:
            df = pd.read_excel(excel_path)
            
            # Lấy danh sách ID học sinh đã có sẵn trong lớp để tránh thêm trùng
            existing_class_student_ids = set()
            if target_class:
                class_students = auth.class_students(admin.id, target_class["id"])
                existing_class_student_ids = {s["id"] for s in class_students}

            for _, row in df.iterrows():
                u_name = str(row["username"]).strip()
                f_name = str(row["full_name"]).strip()
                
                # Tạo tài khoản học sinh nếu chưa tồn tại
                student_id = None
                if u_name not in existing_users:
                    try:
                        student_obj = auth.create_user(admin.id, u_name, f_name, "student", DEFAULT_USER_PASSWORD)
                        student_id = student_obj.id
                        existing_users[u_name] = {"id": student_id, "username": u_name}
                    except Exception:
                        pass
                else:
                    student_id = existing_users[u_name]["id"]

                # Tự động gán học sinh vào lớp học
                if target_class and student_id and (student_id not in existing_class_student_ids):
                    try:
                        auth.add_student_to_class(admin.id, target_class["id"], student_id)
                        existing_class_student_ids.add(student_id)
                    except Exception:
                        pass
                        
        except Exception as e:
            print("Lỗi nạp danh sách tự động từ Excel:", e)

from auth import AuthError, AuthService, ROLE_LABELS, ROLES, generate_temporary_password
from educoder_core import (
    ContentRepository,
    EDUCODERAgent,
    LearnerState,
    pretty_json,
    generate_practice_exercise,
    suggest_advanced_solution,
)

ROOT = Path(__file__).resolve().parent


import ui

st.set_page_config(
    page_title="EDUCODER 10",
    page_icon=":material/code:",
    layout="wide",
    initial_sidebar_state="auto",
)

ui.inject_css()


def data_version() -> tuple:
    """Thời điểm sửa của các file dữ liệu bài tập. Khi file đổi (vd sau git push),
    giá trị này đổi theo nên bộ nhớ đệm services() tự nạp lại dữ liệu mới."""
    stamps = []
    for name in ("exercises.json", "diagnostic.json", "curriculum.json"):
        path = ROOT / "data" / name
        stamps.append(path.stat().st_mtime_ns if path.exists() else 0)
    return tuple(stamps)


@st.cache_resource(max_entries=1)
def services(version: tuple = ()):
    repo = ContentRepository()
    return repo, EDUCODERAgent(repo), AuthService(ROOT / "data" / "educoder.db")


repo, agent, auth = services(data_version())


def auth_gate():
    auto_seed_data()
    if not auth.has_users():
        _, mid, _ = st.columns([1, 1.2, 1])
        with mid:
            ui.login_header()
            st.warning("Hệ thống chưa có tài khoản. Hãy tạo quản trị viên đầu tiên.")
        with mid, st.form("bootstrap_admin"):
            username = st.text_input("Tên đăng nhập admin", value="admin")
            full_name = st.text_input("Họ tên", value="Quản trị viên EDUCODER")
            password = st.text_input("Mật khẩu", type="password")
            confirm = st.text_input("Nhập lại mật khẩu", type="password")
            submitted = st.form_submit_button("Khởi tạo hệ thống", type="primary")
        if submitted:
            try:
                if password != confirm:
                    raise ValueError("Hai mật khẩu không khớp.")
                user = auth.bootstrap_admin(username, full_name, password)
                st.session_state.auth_user_id = user.id
                st.rerun()
            except (AuthError, ValueError) as exc:
                st.error(str(exc))
        st.stop()

    user_id = st.session_state.get("auth_user_id")
    user = auth.get_user(int(user_id)) if user_id else None
    if not user or not user.is_active:
        st.session_state.pop("auth_user_id", None)
        _, mid, _ = st.columns([1, 1.1, 1])
        with mid:
            ui.login_header()
            with st.form("login"):
                username = st.text_input("Tên đăng nhập")
                password = st.text_input("Mật khẩu", type="password")
                submitted = st.form_submit_button("Đăng nhập", type="primary", use_container_width=True)
            ui.login_footer()
        if submitted:
            user = auth.authenticate(username, password)
            if user:
                st.session_state.auth_user_id = user.id
                st.session_state.login_failures = 0
                st.rerun()
            failures = int(st.session_state.get("login_failures", 0)) + 1
            st.session_state.login_failures = failures
            with mid:
                st.error("Tên đăng nhập hoặc mật khẩu không đúng.")
                if failures >= 5:
                    st.warning("Em đã nhập sai nhiều lần. Hãy báo thầy cô để được đặt lại mật khẩu.")
        st.stop()

    if user.must_change_password:
        _, mid, _ = st.columns([1, 1.2, 1])
        with mid:
            ui.login_header()
            st.info("Đây là lần đầu em đăng nhập. Hãy đặt mật khẩu mới của riêng em (ít nhất 6 ký tự).")
        with mid, st.form("force_password_change"):
            current = st.text_input("Mật khẩu hiện tại", type="password")
            new = st.text_input("Mật khẩu mới", type="password")
            confirm = st.text_input("Nhập lại mật khẩu mới", type="password")
            submitted = st.form_submit_button("Đổi mật khẩu", type="primary")
        if submitted:
            try:
                if new != confirm:
                    raise ValueError("Hai mật khẩu mới không khớp.")
                auth.change_password(user.id, current, new)
                st.success("Đã đổi mật khẩu.")
                st.rerun()
            except (AuthError, ValueError) as exc:
                st.error(str(exc))
        st.stop()
    return user


current_user = auth_gate()


def restore_diagnostic(learner) -> None:
    """Khôi phục kết quả test đầu vào + ĐÚNG bộ câu hỏi đã làm từ hồ sơ đã lưu."""
    result = getattr(learner, "diagnostic_result", None)
    if not (getattr(learner, "diagnostic_done", False) or result is not None):
        return
    answers = getattr(learner, "diagnostic_answers", {}) or {}
    st.session_state.diagnostic_result = result
    st.session_state.diagnostic_answers = answers
    # Hồ sơ cũ chưa lưu danh sách câu hỏi: lấy theo các câu đã trả lời
    ids = list(getattr(learner, "diagnostic_question_ids", []) or []) or list(answers.keys())
    by_id = {q["id"]: q for q in repo.diagnostic}
    questions = [by_id[i] for i in ids if i in by_id]
    if questions:
        st.session_state.quiz = questions


def init_state():
    if current_user.role == "student" and st.session_state.get("learner_user_id") != current_user.id:
        stored = auth.load_profile(current_user.id, current_user.id)
        st.session_state.learner = LearnerState.from_dict(stored) if stored else agent.new_state(current_user.full_name)
        st.session_state.learner_user_id = current_user.id

        # --- KHÔI PHỤC KẾT QUẢ TEST ĐẦU VÀO ĐỂ KHÔNG BẮT LÀM LẠI ---
        restore_diagnostic(st.session_state.learner)
    if "quiz" not in st.session_state:
        st.session_state.quiz = repo.diagnostic_sample(10, seed=random.randint(1, 10_000_000))
    if "diagnostic_result" not in st.session_state:
        st.session_state.diagnostic_result = None
    if "current_exercise_id" not in st.session_state:
        st.session_state.current_exercise_id = None
    if "last_grade" not in st.session_state:
        st.session_state.last_grade = None
    if "last_decision" not in st.session_state:
        st.session_state.last_decision = None
    if "hint_level" not in st.session_state:
        st.session_state.hint_level = 1


init_state()


def save_profile():
    if current_user.role == "student":
        auth.save_profile(current_user.id, current_user.id, st.session_state.learner.to_dict())


def skill_name(skill_id: str) -> str:
    return repo.skill_map[skill_id]["name"]


def choose_next_exercise():
    exercise = agent.select_exercise(st.session_state.learner, prefer_new=True)
    st.session_state.current_exercise_id = exercise["id"]
    st.session_state.last_grade = None
    st.session_state.last_decision = None
    st.session_state.hint_level = 1
    st.session_state.advanced_solution = None
    st.session_state.advanced_checked = False


def reset_diagnostic():
    st.session_state.quiz = repo.diagnostic_sample(10, seed=random.randint(1, 10_000_000))
    st.session_state.diagnostic_result = None
    st.session_state.current_exercise_id = None
    st.session_state.last_grade = None


# Tên hiển thị trên menu (biểu tượng Material, không dùng emoji). Khóa giữ nguyên để định tuyến.
NAV_LABELS = {
    "🧭 Test đầu vào": ":material/quiz: Bài kiểm tra đầu vào",
    "🏠 Tổng quan": ":material/home: Tổng quan",
    "🗺️ Lộ trình": ":material/route: Lộ trình",
    "⌨️ Luyện code": ":material/code: Luyện code",
    "📊 Tiến bộ": ":material/monitoring: Tiến bộ",
    "📜 Kết quả test": ":material/fact_check: Kết quả kiểm tra",
    "🏫 Lớp của tôi": ":material/groups: Lớp của em",
    "👨‍🏫 Quản lý lớp": ":material/groups: Lớp phụ trách",
    "📚 Kho bài tập": ":material/library_books: Kho bài tập",
    "🛡️ Quản trị tài khoản": ":material/manage_accounts: Tài khoản",
    "🏫 Toàn bộ lớp": ":material/school: Lớp học",
    "🧾 Nhật ký hệ thống": ":material/history: Nhật ký hệ thống",
}


def render_sidebar():
    with st.sidebar:
        ui.sidebar_header(
            current_user.full_name,
            ROLE_LABELS.get(current_user.role, current_user.role),
            current_user.username,
        )
        
        # 1. PHÂN QUYỀN TRANG THEO VAI TRÒ (Đảm bảo luôn gán giá trị cho pages)
        if current_user.role == "student":
            has_tested = st.session_state.get("diagnostic_result") is not None
            if not has_tested:
                pages = ["🧭 Test đầu vào"]
            else:
                pages = [
                    "🏠 Tổng quan",
                    "🗺️ Lộ trình",
                    "⌨️ Luyện code",
                    "📊 Tiến bộ",
                    "📜 Kết quả test",
                    "🏫 Lớp của tôi",
                ]
        elif current_user.role == "teacher":
            pages = ["👨‍🏫 Quản lý lớp", "📚 Kho bài tập"]
        else:
            # Nhánh dành cho ADMIN (hoặc bất kỳ role nào khác)
            pages = ["🛡️ Quản trị tài khoản", "🏫 Toàn bộ lớp", "🧾 Nhật ký hệ thống"]
            
        # Gắn key để các nút khác có thể chuyển trang (vd: sang Luyện code)
        if st.session_state.get("nav_page") not in pages:
            st.session_state.pop("nav_page", None)
        page = st.radio(
            "Điều hướng",
            pages,
            key="nav_page",
            format_func=lambda key: NAV_LABELS.get(key, key),
            label_visibility="collapsed",
        )

        if current_user.role == "student" and st.session_state.get("diagnostic_result") is not None:
            learner: LearnerState = st.session_state.learner
            current = learner.current_skill
            ui.sidebar_now(skill_name(current), float(learner.mastery.get(current, 0.0)), learner.current_difficulty)

        st.write("")
        if st.button("Đăng xuất", icon=":material/logout:", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
            
        return page

def home_page():
    learner: LearnerState = st.session_state.learner
    current = skill_name(learner.current_skill)
    first_name = current_user.full_name.split()[-1] if current_user.full_name.split() else current_user.full_name

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.markdown(f"<h1 class='ec-hero-title'>Chào {first_name}, mình học tiếp nhé.</h1>", unsafe_allow_html=True)
        st.markdown(
            "<p class='ec-hero-text'>Mỗi bài em viết đều được chấm ngay. Sai ở đâu, hệ thống chỉ đúng dòng đó "
            "và gợi ý cách sửa. Làm đúng thì lên bài khó hơn.</p>",
            unsafe_allow_html=True,
        )
        st.button(
            "Bắt đầu học theo lộ trình",
            type="primary",
            icon=":material/play_arrow:",
            on_click=start_learning_path,
            help="Hệ thống chọn bài phù hợp với kết quả kiểm tra năng lực và mở ngay trang Luyện code.",
        )
    with right:
        ui.code_greeting(current_user.full_name, current)

    st.write("")
    st.subheader("Lộ trình của em")
    ui.path_track(repo.curriculum["skills"], learner.mastery, learner.current_skill)

    st.write("")
    st.subheader("Ở đây em có thể")
    features = [
        (":material/quiz:", "Kiểm tra năng lực", "Bài kiểm tra ngắn cho biết em vững phần nào, còn yếu phần nào."),
        (":material/route:", "Học theo lộ trình riêng", "Bắt đầu từ phần em còn yếu, đi từng bước từ dễ đến khó."),
        (":material/code:", "Viết code, chấm ngay", "Sai thì được chỉ đúng dòng lỗi và cách sửa, có gợi ý từng mức."),
        (":material/repeat:", "Luyện tập thêm", "Làm thêm bài cùng dạng cho thật thuần thục, không ảnh hưởng điểm."),
    ]
    for row in (features[:2], features[2:]):
        cols = st.columns(2, gap="large")
        for col, (icon, title, desc) in zip(cols, row):
            col.markdown(f"**{icon}&nbsp; {title}**")
            col.caption(desc)


def diagnostic_page():
    result = st.session_state.get("diagnostic_result")
    questions = st.session_state.get("quiz", [])
    user_answers = st.session_state.get("diagnostic_answers", {})

    # ========================================================
    # CHẾ ĐỘ XEM LẠI BÀI LÀM CỦA HỌC SINH (SAU KHI ĐÃ NỘP)
    # ========================================================
    if result:
        ui.page_header("Kết quả kiểm tra đầu vào", "Xem lại từng câu: đáp án em chọn và đáp án đúng, kèm giải thích.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Số câu đúng", f"{result.score}/{result.total}")
        c2.metric("Xếp loại", result.level)
        c3.metric("Bắt đầu từ chặng", skill_name(result.recommended_path[0]))

        st.write("")
        st.subheader("Chi tiết từng câu")

        for idx, q in enumerate(questions, 1):
            chosen_idx = user_answers.get(q["id"])
            correct_idx = q["answer_index"]
            is_correct = (chosen_idx == correct_idx)

            with st.container(border=True):
                # Tiêu đề câu hỏi kèm trạng thái Đúng / Sai
                if chosen_idx is None:
                    status_badge = ":gray[:material/radio_button_unchecked: Chưa trả lời]"
                elif is_correct:
                    status_badge = ":green[:material/check_circle: Đúng]"
                else:
                    status_badge = ":red[:material/cancel: Chưa đúng]"

                st.markdown(f"{status_badge}")
                st.markdown(f"**Câu {idx}.** {q['question']}")

                # Hiển thị từng phương án và đánh dấu bài làm của học sinh
                for opt_idx, opt_text in enumerate(q["options"]):
                    if opt_idx == chosen_idx and is_correct:
                        st.markdown(f":green[:material/check: **{opt_text}**] &nbsp;:gray[em chọn, đúng]")
                    elif opt_idx == chosen_idx and not is_correct:
                        st.markdown(f":red[:material/close: **{opt_text}**] &nbsp;:gray[em chọn]")
                    elif opt_idx == correct_idx:
                        st.markdown(f":green[:material/check: **{opt_text}**] &nbsp;:gray[đáp án đúng]")
                    else:
                        st.markdown(f":gray[{opt_text}]")

                # Lời giải thích
                st.caption(f"**Giải thích:** {q['explanation']}")

        return

    # ========================================================
    # CHẾ ĐỘ LÀM BÀI TEST LẦN ĐẦU (CHƯA NỘP)
    # ========================================================
    ui.page_header(
        "Bài kiểm tra đầu vào",
        "10 câu ngắn giúp hệ thống biết em đang vững phần nào để xếp lộ trình. Em chỉ nộp được một lần, hãy làm cẩn thận.",
    )

    with st.form("diagnostic_form"):
        answers: dict[str, int | None] = {}
        for index, q in enumerate(questions, 1):
            st.markdown(f"**Câu {index}. {q['question']}**")
            choice = st.radio(
                "Chọn đáp án",
                options=list(range(len(q["options"]))),
                index=None,
                format_func=lambda i, opts=q["options"]: opts[i],
                key=f"diag_{q['id']}",
                label_visibility="collapsed",
            )
            answers[q["id"]] = choice
            st.write("")

        submitted = st.form_submit_button("Nộp bài & Hoàn thành đánh giá", type="primary", use_container_width=True)

    if submitted:
        unanswered = [idx for idx, q in enumerate(questions, 1) if answers.get(q["id"]) is None]
        if unanswered:
            st.warning(f"Em chưa trả lời câu {', '.join(map(str, unanswered))}. Hãy chọn đáp án cho đủ 10 câu rồi nộp bài.")
        else:
            result = agent.evaluate_diagnostic(questions, answers)
            agent.apply_diagnostic(st.session_state.learner, result)
            
            # --- LƯU TRỰC TIẾP VÀO HỒ SƠ HỌC SINH ĐỂ LƯU VĨNH VIỄN ---
            st.session_state.learner.diagnostic_done = True
            st.session_state.learner.diagnostic_result = result
            st.session_state.learner.diagnostic_answers = answers
            st.session_state.learner.diagnostic_question_ids = [q["id"] for q in questions]
            
            # Lưu session_state hiện tại
            st.session_state.diagnostic_result = result
            st.session_state.diagnostic_answers = answers
            st.session_state.current_exercise_id = None
            
            # Ghi xuống database / file profile
            save_profile()
            st.success("Đã nộp bài kiểm tra.")
            st.rerun()

def start_learning_path() -> None:
    """Chọn bài phù hợp theo lộ trình rồi chuyển thẳng sang trang Luyện code."""
    choose_next_exercise()
    st.session_state.nav_page = "⌨️ Luyện code"


def path_page():
    learner: LearnerState = st.session_state.learner
    ui.page_header(
        "Lộ trình",
        "Sáu chặng theo chương trình Tin học 10. Em vững chặng trước (từ 82%) thì hệ thống mở chặng sau.",
    )
    if not st.session_state.diagnostic_result:
        st.warning("Em chưa làm bài kiểm tra đầu vào nên lộ trình đang bắt đầu từ chặng đầu tiên.")
    ui.path_timeline(repo.curriculum["skills"], learner.mastery, learner.current_skill)
    st.button(
        "Bắt đầu học theo lộ trình",
        type="primary",
        icon=":material/play_arrow:",
        on_click=start_learning_path,
        help="Hệ thống chọn bài phù hợp với kết quả kiểm tra năng lực và mở ngay trang Luyện code.",
    )

import re

def extract_error_line(code: str, error_text: str) -> int | None:
    """Tự động tìm số dòng gây lỗi từ mã nguồn hoặc thông báo lỗi."""
    # 1. Thử parse cú pháp trực tiếp để bắt dòng lỗi chính xác nhất
    try:
        compile(code, "", "exec")
    except SyntaxError as e:
        return e.lineno
    except Exception:
        pass

    # 2. Tìm kiếm trong chuỗi feedback / thông báo lỗi (ví dụ: line 4, dòng 4)
    match = re.search(r"(?:line|dòng)\s+(\d+)", error_text, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None

# Tên lỗi (ngắn, dễ hiểu) + giải thích "lỗi này là gì / cách tránh" cho học sinh
ERROR_INFO = {
    "SyntaxError": ("Viết sai cú pháp", "Thiếu dấu `:`, thiếu ngoặc, thiếu dấu nháy hoặc dùng `=` thay cho `==`."),
    "IndentationError": ("Thụt lề sai", "Lệnh bên trong `if`, `for`, `while`, `def` phải thụt vào 4 dấu cách."),
    "TabError": ("Thụt lề sai", "Lệnh bên trong `if`, `for`, `while`, `def` phải thụt vào 4 dấu cách."),
    "NameError": ("Gõ sai tên biến hoặc tên lệnh", "Viết sai chính tả (vd `prnt`), dùng biến chưa tạo, hoặc quên dấu nháy khi in chữ."),
    "UnboundLocalError": ("Dùng biến khi chưa gán giá trị", "Gán giá trị ban đầu cho biến trước khi dùng."),
    "TypeError": ("Nhầm lẫn giữa chữ và số", "Quên đổi `input()` sang số bằng `int()`/`float()`, hoặc dùng `+` nối chữ với số."),
    "ValueError": ("Đọc dữ liệu nhập sai cách", "Nhiều số trên một dòng thì phải dùng `input().split()`, không dùng `int(input())`."),
    "EOFError": ("Gọi input() nhiều hơn số dòng dữ liệu", "Đếm lại số dòng dữ liệu vào; nếu các số cùng một dòng thì dùng `input().split()`."),
    "ZeroDivisionError": ("Chia cho 0", "Kiểm tra số chia khác 0 trước khi chia."),
    "IndexError": ("Lấy phần tử vượt quá danh sách", "Vị trí hợp lệ từ `0` đến `len(a) - 1`; cẩn thận danh sách rỗng."),
    "AssertionError": ("Hàm trả về kết quả sai", "Hàm chạy được nhưng giá trị `return` chưa đúng với đề bài."),
    "WrongOutput": ("In ra kết quả sai", "Code chạy được nhưng kết quả in ra chưa khớp đề: sai công thức, sai điều kiện hoặc in thừa chữ."),
    "TimeoutError": ("Vòng lặp chạy mãi không dừng", "Biến trong điều kiện `while` phải thay đổi để vòng lặp có lúc dừng."),
    "BlockedCode": ("Dùng lệnh không được phép", "Chỉ dùng các lệnh Python cơ bản đã học."),
    "EmptyCode": ("Nộp bài khi chưa viết code", "Viết code trước khi bấm Chạy và chấm."),
    "RecursionError": ("Hàm tự gọi lại mãi không dừng", "Hàm gọi lại chính nó cần có điều kiện dừng."),
    "RuntimeError": ("Chương trình bị dừng giữa chừng", "Đọc kỹ phần báo lỗi để biết dòng nào gây ra."),
    "KeyError": ("Dùng khóa không có trong từ điển", "Kiểm tra khóa có trong từ điển trước khi dùng."),
    "AttributeError": ("Dùng sai lệnh của chuỗi/danh sách", "Ví dụ `.split()` chỉ dùng cho chuỗi, `.append()` chỉ dùng cho danh sách."),
}
ERROR_LABELS = {code: info[0] for code, info in ERROR_INFO.items()}


def render_error_list(error_counts: dict) -> None:
    """Danh sách lỗi (tên dễ hiểu + giải thích + số lần), xếp từ nhiều đến ít."""
    grouped: dict[str, list] = {}
    for category, n in (error_counts or {}).items():
        name, tip = ERROR_INFO.get(category, (category, ""))
        entry = grouped.setdefault(name, [0, tip])
        entry[0] += int(n)
    if not grouped:
        return
    items = sorted(((name, tip, count) for name, (count, tip) in grouped.items()), key=lambda x: x[2], reverse=True)
    ui.error_rows(items)


def error_label(category: str) -> str:
    return ERROR_LABELS.get(category, category)


def render_diagnosis(grade, show_example: bool) -> None:
    """Hiện chẩn đoán lỗi ngắn gọn: dòng nào, lỗi gì, sửa thế nào."""
    diag = getattr(grade, "diagnosis", None)
    if not diag:
        st.write(grade.feedback)
        return
    with st.container(border=True):
        if diag.get("line") and diag.get("code_line"):
            st.markdown(f":red[:material/error: **Dòng {diag['line']}**]")
            st.code(diag["code_line"], language="python")
        elif diag.get("line"):
            st.markdown(f":red[:material/error: **Dòng {diag['line']}**]")
        st.markdown(f"**Lỗi:** {diag['problem']}")
        st.markdown(f"**Cách sửa:** {diag['fix']}")
        if diag.get("example"):
            if show_example:
                st.markdown("**Viết lại dòng đó như sau:**")
                st.code(diag["example"], language="python")
            else:
                st.caption("Bấm **Xin gợi ý rõ hơn** nếu cần xem dòng sửa mẫu.")


def mark_error_line(code: str, grade) -> None:
    """Đánh dấu dòng lỗi trong khung soạn code theo chẩn đoán."""
    diag = getattr(grade, "diagnosis", None) or {}
    line = diag.get("line")
    if line and 1 <= line <= len(code.splitlines()) and not grade.passed:
        st.session_state.last_error_line = line
        st.session_state.last_error_msg = diag.get("problem", "")
    else:
        st.session_state.last_error_line = None
        st.session_state.last_error_msg = ""


def next_step_message(decision: dict, exercise: dict, passed: bool) -> str:
    """Diễn giải quyết định của Agent thành một câu dễ hiểu cho học sinh."""
    action = decision.get("action", "")
    next_skill = skill_name(decision["next_skill"])
    old_diff, new_diff = int(exercise["difficulty"]), int(decision["next_difficulty"])
    where = f"{next_skill}, độ khó {new_diff}/3"
    if action == "advance_skill":
        return f"Em đã vững kỹ năng này! Bài tiếp theo chuyển sang kỹ năng mới: **{where}**."
    if action == "capstone_challenge":
        return f"Em đã học hết các kỹ năng! Bài tiếp theo là thử thách tổng hợp (**độ khó {new_diff}/3**)."
    if action == "harder_same_skill":
        if new_diff > old_diff:
            return f"Em làm đúng 2 bài liên tiếp. Bài tiếp theo **khó hơn** một bậc: **{where}**."
        return f"Em làm đúng 2 bài liên tiếp. Bài tiếp theo vẫn ở mức cao nhất: **{where}**."
    if passed:
        return f"Làm tốt. Bài tiếp theo **cùng mức** để em làm quen thêm: **{where}**."
    if new_diff < old_diff:
        return f"Bài tiếp theo **dễ hơn** một chút để em nắm chắc kiến thức nền: **{where}**."
    return f"Bài tiếp theo **cùng mức**, tương tự bài này để em luyện lại cách làm: **{where}**."


@st.fragment
def code_editor(code_key: str, ace_key: str, starter: str, annotations: list, markers: list) -> None:
    """Khung soạn code chạy trong một fragment.

    streamlit-ace gửi code lên máy chủ sau mỗi lần gõ. Nếu để ngoài fragment, mỗi lần
    gõ cả trang chạy lại và màn hình bị "chớp". Trong fragment, chỉ riêng khung này
    chạy lại; code mới nhất luôn nằm trong st.session_state[code_key] để nút
    "Chạy và chấm" (ngoài fragment) đọc và chấm.
    """
    if code_key not in st.session_state:
        st.session_state[code_key] = starter
    st.session_state[code_key] = st_ace(
        value=st.session_state[code_key],
        language="python",
        theme="monokai",
        keybinding="vscode",
        font_size=15,
        tab_size=4,
        show_gutter=True,
        auto_update=True,
        annotations=annotations,
        markers=markers,
        key=ace_key,
        height=340,
    )


def start_extra_practice(base_exercise: dict) -> None:
    """Nhờ AI sinh bài tương tự bài đang làm (chỉ để luyện, KHÔNG tính tiến bộ)."""
    with st.spinner("Đang soạn bài tương tự"):
        practice, reason = generate_practice_exercise(
            agent.llm, agent.grader, base_exercise,
            bank=repo.exercises,
            history=st.session_state.get("practice_history", []),
        )
    if practice:
        st.session_state.practice_ex = practice
        # Ghi nhớ các bài đã tạo trong phiên để lần sau không sinh lại bài trùng
        st.session_state.setdefault("practice_history", []).append(practice)
        st.session_state.practice_grade = None
        st.session_state.practice_hint_level = 1
        st.session_state[f"practice_code_{practice['id']}"] = practice["starter_code"]
        st.rerun()
    else:
        st.session_state.practice_error = reason


def render_extra_practice() -> None:
    """Chế độ LUYỆN TẬP THÊM.

    - Chấm bằng agent.grader.grade() trực tiếp, KHÔNG gọi agent.submit(),
      nên không đổi mastery, attempts, solved_ids, lộ trình hay hồ sơ học tập.
    - Bộ test đã được kiểm chứng bằng cách chạy lời giải mẫu (xem educoder_core).
    """
    ex = st.session_state.practice_ex
    top_l, top_r = st.columns([3, 1], vertical_alignment="center")
    with top_l:
        ui.page_header("Luyện tập thêm")
    if top_r.button("Quay lại bài chính", icon=":material/arrow_back:", use_container_width=True):
        st.session_state.practice_ex = None
        st.session_state.practice_grade = None
        st.rerun()
    st.markdown(f"### {ex['title']}")
    ui.exercise_meta(skill_name(ex["skill"]), ex["difficulty"], "Không tính vào tiến bộ")
    ui.task_box(ex["description"])

    left, right = st.columns([1.25, 0.9])
    code_key = f"practice_code_{ex['id']}"
    grade = st.session_state.get("practice_grade")

    # Đánh dấu dòng lỗi trong khung code (giống bài chính)
    annotations, markers = [], []
    diag = (getattr(grade, "diagnosis", None) or {}) if grade and not grade.passed else {}
    if diag.get("line"):
        row = diag["line"] - 1
        annotations.append({"row": row, "column": 0, "text": diag.get("problem", ""), "type": "error"})
        markers.append({"startRow": row, "startCol": 0, "endRow": row, "endCol": 200,
                        "className": "ace-error-marker", "type": "fullLine", "inFront": True})

    with left:
        code_editor(code_key, f"ace_{ex['id']}", ex["starter_code"], annotations, markers)
        code = st.session_state[code_key]
        c1, c2 = st.columns(2)
        if c1.button("Chạy và chấm", type="primary", icon=":material/play_arrow:", use_container_width=True, key="practice_submit"):
            st.session_state.practice_grade = agent.grader.grade(
                ex, code, st.session_state.get("practice_hint_level", 1)
            )
            st.rerun()
        if c2.button("Tạo bài khác", icon=":material/refresh:", use_container_width=True, key="practice_new"):
            base = repo.exercise_by_id(ex.get("base_exercise_id")) or ex
            start_extra_practice(base)
        if st.session_state.get("practice_error"):
            st.warning(st.session_state.pop("practice_error"))

    with right:
        # 1) KẾT QUẢ CHẤM + HƯỚNG DẪN SỬA (đặt trên cùng để học sinh thấy ngay)
        if grade:
            st.subheader("Kết quả")
            if grade.passed:
                st.success(f"Đúng {grade.passed_tests}/{grade.total_tests} test. Giỏi lắm!")
            else:
                st.error(f"Đúng {grade.passed_tests}/{grade.total_tests} test — {error_label(grade.error_category)}")
                level = st.session_state.get("practice_hint_level", 1)
                render_diagnosis(grade, show_example=level >= 2)
                st.warning(f"**Gợi ý mức {level}:** {agent.grader._hint(ex, grade.error_category, level)}", icon=":material/lightbulb:")
                if level < 3 and st.button("Xin gợi ý rõ hơn", key="practice_more_hint"):
                    st.session_state.practice_hint_level = level + 1
                    st.rerun()

        # 2) BỘ TEST (thu gọn sau khi đã chấm để phần hướng dẫn không bị đẩy xuống)
        details = grade.run_details if grade else []
        with st.expander("Bộ test của bài", expanded=not grade):
            for i, test in enumerate(ex["tests"], 1):
                status = ""
                if grade:
                    if i <= len(details):
                        r = details[i - 1]
                        ok = r.ok and (
                            "__EDUCODER_PASS__" in r.output if ex["kind"] == "function"
                            else agent.grader._norm(r.output) == agent.grader._norm(test.get("output", ""))
                        )
                        status = " :green[:material/check_circle:]" if ok else " :red[:material/cancel:]"
                    else:
                        status = " :gray[(chưa chạy tới)]"
                st.markdown(f"**Test {i}**{status}")
                if ex["kind"] == "function":
                    st.code(f"{test['call']}  →  {test['expected']}", language="python")
                else:
                    st.code(f"Input:\n{test['input'].rstrip()}\n\nOutput:\n{test['output']}")


def practice_page():
    ui.page_header("Luyện code", "Viết chương trình vào khung bên trái rồi bấm Chạy và chấm.")
    learner: LearnerState = st.session_state.learner

    if st.session_state.get("practice_ex"):
        render_extra_practice()
        return

    if not st.session_state.current_exercise_id:
        choose_next_exercise()
    exercise = repo.exercise_by_id(st.session_state.current_exercise_id)
    if not exercise:
        st.error("Không tìm thấy bài tập.")
        return

    st.markdown(f"### {exercise['title']}")
    ui.exercise_meta(skill_name(exercise["skill"]), exercise["difficulty"])
    ui.task_box(exercise["description"])

    left, right = st.columns([1.25, 0.9])
    editor_key = f"code_{exercise['id']}"
    if editor_key not in st.session_state:
        st.session_state[editor_key] = exercise["starter_code"]

    with left:
        # 1. Thêm CSS để tô màu nền đỏ nhạt cho toàn bộ dòng bị lỗi
        st.markdown(
            """
            
            """,
            unsafe_allow_html=True,
        )

        annotations = []
        markers = []
        error_line = st.session_state.get("last_error_line")
        error_msg = st.session_state.get("last_error_msg", "Dòng này có lỗi cú pháp hoặc thực thi")

        # 2. Nếu có dòng lỗi: vừa gắn icon X ở cột số dòng, vừa tô màu nền cả dòng đó
        if error_line is not None and error_line > 0:
            row_idx = error_line - 1  # Ace Editor đếm dòng từ 0
            
            # Icon cảnh báo đỏ ở lề
            annotations.append({
                "row": row_idx,
                "column": 0,
                "text": error_msg,
                "type": "error",
            })
            
            # Tô màu nền nguyên dòng đó (từ ký tự 0 đến hết dòng)
            markers.append({
                "startRow": row_idx,
                "startCol": 0,
                "endRow": row_idx,
                "endCol": 200,
                "className": "ace-error-marker",
                "type": "fullLine",
                "inFront": True,
            })

        # 3. Khung soạn thảo (chạy trong fragment để gõ code không làm cả trang chạy lại)
        code_editor(editor_key, f"ace_{exercise['id']}", exercise["starter_code"], annotations, markers)
        code = st.session_state[editor_key]

        submit = st.button("Chạy và chấm", type="primary", icon=":material/play_arrow:", use_container_width=True)

        # CÁCH GIẢI NÂNG CAO
        # - Làm SAI: không hiển thị, để học sinh tập trung sửa lỗi.
        # - Làm ĐÚNG: hiện nút; AI chỉ được gọi khi học sinh bấm (tiết kiệm lượt gọi AI).
        # - Bài quá cơ bản (không có cách giải nâng cao trong kho): ẩn hoàn toàn.
        last_grade = st.session_state.get("last_grade")
        advanced = st.session_state.get("advanced_solution")
        if last_grade and last_grade.passed and exercise.get("advanced_solution"):
            if advanced:
                with st.expander("Cách giải nâng cao", icon=":material/lightbulb:", expanded=True):
                    st.markdown(f"**{advanced.get('title', 'Cách viết tối ưu hơn')}**")
                    st.code(advanced.get("code", ""), language="python")
                    if advanced.get("explanation"):
                        st.info(advanced["explanation"])
            elif st.session_state.get("advanced_checked"):
                st.caption("Cách em viết đã gọn rồi, chưa có cách nào tốt hơn rõ rệt.")
            elif st.button("Xem cách giải nâng cao", icon=":material/lightbulb:", use_container_width=True):
                with st.spinner("Đang tìm cách giải gọn hơn cho bài của em..."):
                    st.session_state.advanced_solution = suggest_advanced_solution(
                        agent.llm, agent.grader, exercise, st.session_state.get("last_passed_code", code)
                    )
                st.session_state.advanced_checked = True
                st.rerun()


    if submit:
        # Kiểm tra nhanh cú pháp để lấy đúng dòng lỗi ngay khi bấm
        try:
            compile(code, "", "exec")
            st.session_state.last_error_line = None
            st.session_state.last_error_msg = ""
        except SyntaxError as e:
            st.session_state.last_error_line = e.lineno
            st.session_state.last_error_msg = e.msg or "Lỗi cú pháp tại dòng này"

        grade, decision = agent.submit(learner, exercise, code, st.session_state.hint_level)
        save_profile()
        mark_error_line(code, grade)
        st.session_state.last_grade = grade
        st.session_state.last_decision = decision
        st.session_state.advanced_solution = None
        st.session_state.advanced_checked = False
        st.session_state.celebrate = grade.passed
        if grade.passed:
            st.session_state.last_passed_code = code
        st.rerun()

    with right:
        st.subheader("Kết quả chấm")
        grade = st.session_state.last_grade
        decision = st.session_state.last_decision
        if not grade:
            st.caption("Bấm **Chạy và chấm** để xem kết quả. Dưới đây là ví dụ dữ liệu vào và kết quả mong đợi.")
            for i, test in enumerate(exercise["tests"][:2], 1):
                if exercise["kind"] == "io":
                    st.code(f"Input: {test.get('input','').strip()}\nOutput: {test.get('output','').strip()}")
                else:
                    st.code(test["assert"], language="python")
        else:
            if grade.passed:
                st.success(f"Đúng {grade.passed_tests}/{grade.total_tests} test — {grade.score} điểm")
                # Chỉ thả bóng 1 lần ngay sau khi chấm đúng, không lặp lại khi bấm nút khác
                if st.session_state.pop("celebrate", False):
                    st.balloons()
            else:
                st.error(f"Đúng {grade.passed_tests}/{grade.total_tests} test — {error_label(grade.error_category)}")
            if grade.passed:
                st.write(grade.feedback)
            else:
                render_diagnosis(grade, show_example=st.session_state.hint_level >= 2)
            if not grade.passed:
                st.warning(f"**Gợi ý mức {st.session_state.hint_level}:** {grade.hint}", icon=":material/lightbulb:")
                if st.button("Xin gợi ý rõ hơn"):
                    st.session_state.hint_level = min(3, st.session_state.hint_level + 1)
                    grade.hint = agent.grader._hint(
                        exercise, grade.error_category, st.session_state.hint_level
                    )
                    llm_hint = agent.llm.socratic_hint(
                        exercise, code, grade, st.session_state.hint_level
                    )
                    if llm_hint:
                        grade.hint = llm_hint
                    st.session_state.last_grade = grade
                    st.rerun()

            st.info(next_step_message(decision, exercise, grade.passed), icon=":material/route:")

            # LUYỆN TẬP THÊM: AI sinh bài tương tự, không tính vào tiến bộ
            if st.button("Luyện tập thêm", icon=":material/repeat:", use_container_width=True):
                if agent.llm.available:
                    start_extra_practice(exercise)
                else:
                    st.session_state.practice_error = "Chưa bật AI (file .env) nên chưa tạo được bài luyện thêm."
            if st.session_state.get("practice_error"):
                st.warning(st.session_state.pop("practice_error"))

            if st.button("Làm bài Agent đề xuất", type="primary", use_container_width=True):
                st.session_state.last_error_line = None
                choose_next_exercise()
                st.rerun()

def progress_page():
    ui.page_header("Tiến bộ", "Em đã làm được bao nhiêu, vững kỹ năng nào và hay mắc lỗi gì.")
    learner: LearnerState = st.session_state.learner
    cols = st.columns(4)
    cols[0].metric("Bài đã giải", len(learner.solved_ids))
    cols[1].metric("Lượt nộp", sum(learner.attempts.values()))
    cols[2].metric("Kỹ năng đã vững", f"{sum(v >= 0.82 for v in learner.mastery.values())}/{len(repo.skill_order)}")
    cols[3].metric("Loại lỗi đã gặp", len(learner.error_counts))
    st.write("")
    st.subheader("Mức thành thạo")
    ui.skill_bars(repo.curriculum["skills"], learner.mastery)
    if learner.error_counts:
        st.subheader("Lỗi em hay mắc")
        st.caption("Xếp từ lỗi em mắc nhiều nhất. Đọc kỹ từng lỗi để lần sau tránh nhé.")
        render_error_list(learner.error_counts)


def exercise_bank_page():
    ui.page_header("Kho bài tập", "Các bài hệ thống dùng để giao cho học sinh, lọc theo kỹ năng.")
    st.metric("Số bài tập", len(repo.exercises))
    selected = st.selectbox("Lọc kỹ năng", ["all", *repo.skill_order], format_func=lambda x: "Tất cả" if x == "all" else skill_name(x))
    rows = [x for x in repo.exercises if selected == "all" or x["skill"] == selected]
    st.dataframe([{"ID": x["id"], "Tên": x["title"], "Kỹ năng": skill_name(x["skill"]), "Độ khó": x["difficulty"], "Test": len(x["tests"])} for x in rows], use_container_width=True, hide_index=True)


def student_classes_page():
    ui.page_header("Lớp của em")
    classes = auth.list_classes(current_user.id)
    if not classes:
        st.info("Em chưa được thêm vào lớp nào. Hãy báo thầy cô để được xếp lớp.")
        return
    st.dataframe([{"Lớp": x["name"], "Giáo viên": x["teacher_name"], "Sĩ số": x["student_count"]} for x in classes], use_container_width=True, hide_index=True)


def format_time(value: str | None) -> str:
    """'2026-10-01T11:37:05+00:00' -> '01/10/2026 11:37' (giờ máy chủ); rỗng -> 'Chưa học'."""
    if not value:
        return "Chưa học"
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(str(value))
        if moment.tzinfo is not None:
            moment = moment.astimezone()
        return moment.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(value)


def teacher_classes_page():
    ui.page_header("Lớp phụ trách", "Theo dõi tiến độ của từng học sinh trong lớp thầy cô được phân công.")
    classes = auth.list_classes(current_user.id)
    if not classes:
        st.info("Bạn chưa được phân công lớp nào. Vui lòng liên hệ quản trị viên.")
        return
    selected = st.selectbox("Chọn lớp", classes, format_func=lambda x: x["name"])
    students = auth.class_students(current_user.id, selected["id"])
    st.dataframe([{"Học sinh": x["full_name"], "Tài khoản": x["username"], "Bài đã giải": x["solved"], "Lượt làm": x["attempts"], "Thành thạo TB": f"{x['average_mastery']}%", "Cập nhật": format_time(x["updated_at"])} for x in students], use_container_width=True, hide_index=True)

    if not students:
        st.info("Lớp này chưa có học sinh.")
        return
    st.divider()
    st.subheader("Xem chi tiết học sinh")
    student = st.selectbox(
        "Chọn học sinh",
        students,
        format_func=lambda x: f"{x['full_name']} (@{x['username']})",
        key="teacher_student_detail",
    )
    render_student_detail(student)


def render_student_detail(student: dict) -> None:
    """Giáo viên xem: kết quả test đầu vào, thành thạo theo kỹ năng, lỗi hay mắc, bài đã làm."""
    try:
        profile = auth.load_profile(current_user.id, student["id"])
    except AuthError as exc:
        st.error(str(exc))
        return
    if not profile:
        st.info("Học sinh này chưa bắt đầu học.")
        return
    state = LearnerState.from_dict(profile)

    history = [h for h in state.history if h.get("event") == "submission"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bài đã giải", len(state.solved_ids))
    c2.metric("Lượt nộp", len(history) or sum(state.attempts.values()))
    result = state.diagnostic_result
    c3.metric("Test đầu vào", f"{result.score}/{result.total}" if result else "Chưa làm")
    c4.metric("Đang học", skill_name(state.current_skill))

    st.markdown("**Mức thành thạo theo kỹ năng**")
    ui.skill_bars(repo.curriculum["skills"], state.mastery)

    st.markdown("**Lỗi hay mắc**")
    if state.error_counts:
        render_error_list(state.error_counts)
    else:
        st.caption("Chưa ghi nhận lỗi nào.")

    st.markdown("**Các bài đã làm**")
    if not history:
        st.caption("Chưa nộp bài nào.")
        return
    per_exercise: dict[str, dict] = {}
    for h in history:
        row = per_exercise.setdefault(h["exercise_id"], {"lan": 0, "dung": False, "loi": ""})
        row["lan"] += 1
        row["dung"] = row["dung"] or bool(h.get("passed"))
        if not h.get("passed"):
            row["loi"] = error_label(h.get("error_category", ""))
    rows = []
    for ex_id, info in per_exercise.items():
        ex = repo.exercise_by_id(ex_id) or {"title": ex_id, "skill": "", "difficulty": "?"}
        rows.append({
            "Bài": ex["title"],
            "Kỹ năng": skill_name(ex["skill"]) if ex.get("skill") in repo.skill_map else "",
            "Độ khó": f"{ex['difficulty']}/3",
            "Số lần nộp": info["lan"],
            "Kết quả": "Đã làm đúng" if info["dung"] else "Chưa đúng",
            "Lỗi gần nhất": "" if info["dung"] else info["loi"],
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


import pandas as pd

def admin_users_page():
    ui.page_header("Tài khoản")
    tab1, tab_upload, tab2, tab3 = st.tabs([
        "Tạo tài khoản", 
        "Nạp danh sách (Excel/CSV)", 
        "Danh sách & vai trò", 
        "Đặt lại mật khẩu"
    ])
    
    with tab1:
        suggested = st.session_state.get("suggested_password", generate_temporary_password())
        with st.form("create_user"):
            username = st.text_input("Tên đăng nhập")
            full_name = st.text_input("Họ tên")
            role = st.selectbox("Vai trò", ROLES, format_func=lambda x: ROLE_LABELS[x], index=2)
            password = st.text_input("Mật khẩu tạm", value=suggested)
            submitted = st.form_submit_button("Tạo tài khoản", type="primary")
        if submitted:
            try:
                created = auth.create_user(current_user.id, username, full_name, role, password)
                st.session_state.suggested_password = generate_temporary_password()
                st.success(f"Đã tạo @{created.username}. Gửi mật khẩu tạm qua kênh riêng; người dùng buộc đổi ở lần đăng nhập đầu.")
            except AuthError as exc:
                st.error(str(exc))

    with tab_upload:
        st.subheader("Nạp danh sách học sinh từ file")
        st.caption("Tải file danh sách (.csv hoặc .xlsx). Mật khẩu mặc định gán: **123456**.")
        
        sample_df = pd.DataFrame({
            "username": ["10a1_01", "10a1_02", "10a1_03"],
            "full_name": ["Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Cường"]
        })
        st.download_button(
            "Tải file mẫu CSV",
            data=sample_df.to_csv(index=False).encode("utf-8"),
            file_name="mau_danh_sach_10a1.csv",
            mime="text/csv"
        )
        
        uploaded_file = st.file_uploader("Kéo thả file danh sách học sinh vào đây", type=["csv", "xlsx"])
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                st.write("Xem trước dữ liệu:")
                st.dataframe(df.head(10), use_container_width=True)
                
                if st.button("Xác nhận tạo tài khoản", type="primary"):
                    if "username" not in df.columns or "full_name" not in df.columns:
                        st.error("File tải lên thiếu cột bắt buộc: 'username' hoặc 'full_name'")
                    else:
                        success_count = 0
                        duplicate_count = 0
                        for _, row in df.iterrows():
                            u_name = str(row["username"]).strip()
                            f_name = str(row["full_name"]).strip()
                            try:
                                auth.create_user(current_user.id, u_name, f_name, "student", DEFAULT_USER_PASSWORD)
                                success_count += 1
                            except AuthError:
                                duplicate_count += 1
                        st.success(f" Đã tạo thành công {success_count} học sinh! (Bỏ qua {duplicate_count} tài khoản đã trùng lặp).")
                        st.rerun()
            except Exception as exc:
                st.error(f"Lỗi khi đọc file: {exc}")

    users = auth.list_users(current_user.id)
    with tab2:
        st.dataframe([{"ID": x["id"], "Tài khoản": x["username"], "Họ tên": x["full_name"], "Vai trò": ROLE_LABELS[x["role"]], "Hoạt động": "Có" if x["is_active"] else "Đã khóa", "Đổi MK": "Bắt buộc" if x["must_change_password"] else "Không"} for x in users], use_container_width=True, hide_index=True)
        target = st.selectbox("Chọn tài khoản để sửa", users, format_func=lambda x: f"{x['full_name']} (@{x['username']})", key="role_target")
        c1, c2 = st.columns(2)
        new_role = c1.selectbox("Vai trò mới", ROLES, index=ROLES.index(target["role"]), format_func=lambda x: ROLE_LABELS[x])
        new_active = c2.checkbox("Tài khoản hoạt động", value=bool(target["is_active"]))
        if st.button("Lưu phân quyền và trạng thái"):
            try:
                auth.set_user_status(current_user.id, target["id"], new_active)
                auth.set_role(current_user.id, target["id"], new_role)
                st.success("Đã cập nhật.")
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))

    with tab3:
        target = st.selectbox("Tài khoản", users, format_func=lambda x: f"{x['full_name']} (@{x['username']})", key="reset_target")
        temp = st.text_input("Mật khẩu tạm mới", value=generate_temporary_password())
        if st.button("Đặt lại mật khẩu"):
            try:
                auth.reset_password(current_user.id, target["id"], temp)
                st.success("Đã đặt lại. Người dùng sẽ phải đổi mật khẩu khi đăng nhập.")
            except AuthError as exc:
                st.error(str(exc))
def all_classes_page():
    ui.page_header("Lớp học", "Tạo lớp, phân công giáo viên và thêm học sinh vào lớp.")

    tab_classes, tab_create, tab_add_student = st.tabs([
        "Danh sách lớp",
        "Tạo lớp mới",
        "Thêm học sinh vào lớp",
    ])

    # TAB 1: XEM DANH SÁCH LỚP & ĐỔI GIÁO VIÊN
    with tab_classes:
        classes = auth.list_classes(current_user.id)
        st.dataframe(
            [
                {
                    "Lớp": x["name"],
                    "Giáo viên": x["teacher_name"],
                    "Sĩ số": x["student_count"],
                }
                for x in classes
            ],
            use_container_width=True,
            hide_index=True,
        )

        if classes:
            st.divider()
            selected = st.selectbox(
                "Xem chi tiết học sinh trong lớp",
                classes,
                format_func=lambda x: x["name"],
            )
            students = auth.class_students(current_user.id, selected["id"])
            if students:
                st.dataframe(students, use_container_width=True, hide_index=True)
            else:
                st.info("Lớp này hiện chưa có học sinh nào.")

            st.subheader("Phân công / Chuyển giáo viên phụ trách")
            teachers = [
                x
                for x in auth.list_users(current_user.id)
                if x["role"] == "teacher" and x["is_active"]
            ]
            if teachers:
                c1, c2 = st.columns([3, 1])
                new_teacher = c1.selectbox(
                    "Chọn giáo viên",
                    teachers,
                    format_func=lambda x: f"{x['full_name']} (@{x['username']})",
                )
                if c2.button("Cập nhật giáo viên", type="primary"):
                    try:
                        auth.reassign_class(
                            current_user.id, selected["id"], new_teacher["id"]
                        )
                        st.success(f"Đã phân công giáo viên cho lớp {selected['name']}.")
                        st.rerun()
                    except AuthError as exc:
                        st.error(str(exc))
            else:
                st.warning("Chưa có tài khoản Giáo viên nào.")

    # TAB 2: ADMIN TẠO LỚP VÀ PHÂN CÔNG GIÁO VIÊN
    with tab_create:
        st.subheader("Tạo lớp học mới")
        teachers = [
            x
            for x in auth.list_users(current_user.id)
            if x["role"] == "teacher" and x["is_active"]
        ]

        with st.form("admin_create_class"):
            class_name = st.text_input("Tên lớp", placeholder="Ví dụ: 10A1 - Tin học 10")
            assigned_teacher = None
            if teachers:
                assigned_teacher = st.selectbox(
                    "Phân công giáo viên phụ trách",
                    teachers,
                    format_func=lambda x: f"{x['full_name']} (@{x['username']})",
                )
            else:
                st.caption("*(Chưa có giáo viên nào, lớp sẽ tạm gán cho Admin)*")

            submitted = st.form_submit_button("Tạo lớp", type="primary")

        if submitted:
            if not class_name.strip():
                st.error("Tên lớp không được để trống.")
            else:
                try:
                    teacher_id = assigned_teacher["id"] if assigned_teacher else current_user.id
                    classroom = auth.create_class(current_user.id, class_name.strip(), teacher_id)
                    st.success(f"Đã tạo lớp '{class_name}'!")
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))

    # TAB 3: ADMIN THÊM HỌC SINH TRỰC TIẾP VÀO LỚP
    with tab_add_student:
        st.subheader("Gán học sinh vào lớp học")
        classes = auth.list_classes(current_user.id)
        all_students = [
            x
            for x in auth.list_users(current_user.id)
            if x["role"] == "student" and x["is_active"]
        ]

        if not classes:
            st.info("Chưa có lớp nào, vui lòng tạo lớp trước.")
        elif not all_students:
            st.info("Chưa có tài khoản học sinh nào.")
        else:
            target_class = st.selectbox(
                "Chọn lớp cần thêm",
                classes,
                format_func=lambda x: x["name"],
                key="target_class_add",
            )
            selected_students = st.multiselect(
                "Chọn danh sách học sinh",
                all_students,
                format_func=lambda x: f"{x['full_name']} (@{x['username']})",
            )

            if st.button("Xác nhận đưa vào lớp", type="primary"):
                if not selected_students:
                    st.warning("Vui lòng chọn ít nhất một học sinh.")
                else:
                    added_count = 0
                    for hs in selected_students:
                        try:
                            auth.add_student_to_class(current_user.id, target_class["id"], hs["id"])
                            added_count += 1
                        except AuthError:
                            pass
                    st.success(f"Đã thêm {added_count} học sinh vào lớp {target_class['name']}!")
                    st.rerun()
def audit_page():
    ui.page_header("Nhật ký hệ thống")
    st.caption("Theo dõi các thao tác quản trị quan trọng; nhật ký không lưu mật khẩu.")
    st.dataframe(auth.audit_logs(current_user.id), use_container_width=True, hide_index=True)


page = render_sidebar()
if page == "🏠 Tổng quan":
    home_page()
elif page in ["🧭 Test đầu vào", "📜 Kết quả test"]:
    diagnostic_page()
elif page == "🗺️ Lộ trình":
    path_page()
elif page == "⌨️ Luyện code":
    practice_page()
elif page == "📊 Tiến bộ":
    progress_page()
elif page == "🏫 Lớp của tôi":
    student_classes_page()
elif page == "👨‍🏫 Quản lý lớp":
    teacher_classes_page()
elif page == "📚 Kho bài tập":
    exercise_bank_page()
elif page == "🛡️ Quản trị tài khoản":
    admin_users_page()
elif page == "🏫 Toàn bộ lớp":
    all_classes_page()
else:
    audit_page()


