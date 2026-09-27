from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from auth import AuthError, AuthService, ROLE_LABELS, ROLES, generate_temporary_password
from educoder_core import (
    ContentRepository,
    EDUCODERAgent,
    LearnerState,
    load_mbpp_preview,
    pretty_json,
)

ROOT = Path(__file__).resolve().parent


st.set_page_config(
    page_title="EDUCODER 10",
    page_icon="🐍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .hero {padding: 1.2rem 1.4rem; border-radius: 18px;
             background: linear-gradient(135deg,#0f4c81,#1580c5); color:white;}
      .hero h1 {margin:0; font-size:2.15rem}.hero p{margin:.45rem 0 0;opacity:.92}
      .agent-card {padding:1rem; border:1px solid #d9e5ee; border-radius:14px;
                   background:#f7fbfe; margin:.5rem 0}
      .metric-note {font-size:.86rem;color:#536471}
      code {font-size:.92em}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def services():
    repo = ContentRepository()
    return repo, EDUCODERAgent(repo), AuthService(ROOT / "data" / "educoder.db")


repo, agent, auth = services()


def auth_gate():
    """Khởi tạo admin lần đầu hoặc yêu cầu đăng nhập."""
    if not auth.has_users():
        st.title("🐍 EDUCODER 10")
        st.warning("Hệ thống chưa có tài khoản. Hãy tạo quản trị viên đầu tiên trên máy chủ tin cậy.")
        with st.form("bootstrap_admin"):
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
        st.title("🐍 EDUCODER 10")
        st.subheader("Đăng nhập")
        with st.form("login"):
            username = st.text_input("Tên đăng nhập")
            password = st.text_input("Mật khẩu", type="password")
            submitted = st.form_submit_button("Đăng nhập", type="primary", use_container_width=True)
        if submitted:
            user = auth.authenticate(username, password)
            if user:
                st.session_state.auth_user_id = user.id
                st.session_state.login_failures = 0
                st.rerun()
            failures = int(st.session_state.get("login_failures", 0)) + 1
            st.session_state.login_failures = failures
            st.error("Tên đăng nhập hoặc mật khẩu không đúng.")
            if failures >= 5:
                st.warning("Đã sai nhiều lần trong phiên này. Khi triển khai thật cần giới hạn theo IP/tài khoản tại reverse proxy.")
        st.stop()

    if user.must_change_password:
        st.title("🐍 EDUCODER 10")
        st.warning("Bạn đang dùng mật khẩu tạm. Hãy đổi mật khẩu trước khi tiếp tục.")
        with st.form("force_password_change"):
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


def init_state():
    if current_user.role == "student" and st.session_state.get("learner_user_id") != current_user.id:
        stored = auth.load_profile(current_user.id, current_user.id)
        st.session_state.learner = LearnerState.from_dict(stored) if stored else agent.new_state(current_user.full_name)
        st.session_state.learner_user_id = current_user.id
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


def reset_diagnostic():
    st.session_state.quiz = repo.diagnostic_sample(10, seed=random.randint(1, 10_000_000))
    st.session_state.diagnostic_result = None
    st.session_state.current_exercise_id = None
    st.session_state.last_grade = None


def render_header():
    st.markdown(
        """
        <div class="hero">
          <h1>🐍 EDUCODER 10</h1>
          <p>Trợ lý học lập trình Python cá nhân hóa cho Tin học 10 — chẩn đoán, lập lộ trình, chấm code và chọn bài thích ứng.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar():
    with st.sidebar:
        st.title("EDUCODER 10")
        st.write(f"**{current_user.full_name}**")
        st.caption(f"{ROLE_LABELS[current_user.role]} · @{current_user.username}")
        if current_user.role == "student":
            pages = ["🏠 Tổng quan", "🧭 Test đầu vào", "🗺️ Lộ trình", "⌨️ Luyện code", "📊 Tiến bộ", "🏫 Lớp của tôi"]
        elif current_user.role == "teacher":
            pages = ["👨‍🏫 Quản lý lớp", "📚 Kho bài tập"]
        else:
            pages = ["🛡️ Quản trị tài khoản", "🏫 Toàn bộ lớp", "🧾 Nhật ký hệ thống"]
        page = st.radio("Điều hướng", pages)
        st.divider()
        if current_user.role == "student":
            learner: LearnerState = st.session_state.learner
            current = learner.current_skill
            st.caption("Kỹ năng Agent đang ưu tiên")
            st.write(f"**{skill_name(current)}**")
            st.progress(float(learner.mastery.get(current, 0.0)))
            st.caption(f"Thành thạo: {learner.mastery.get(current, 0.0)*100:.0f}% · độ khó {learner.current_difficulty}/3")
        if st.button("Đăng xuất", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        return page


def home_page():
    render_header()
    st.write("")
    cols = st.columns(4)
    items = [
        ("1", "Test đầu vào", "10 câu ngẫu nhiên, phủ sáu kỹ năng"),
        ("2", "Lộ trình cá nhân", "Đi từ lỗ hổng nền tảng theo quan hệ tiên quyết"),
        ("3", "Chấm code", "Chạy test xác định trong tiến trình con có timeout"),
        ("4", "Thích ứng", "Sai → bài tương tự/dễ hơn; đúng → củng cố hoặc nâng mức"),
    ]
    for col, (no, title, desc) in zip(cols, items):
        with col:
            st.markdown(f"<div class='agent-card'><b>{no}. {title}</b><br><span class='metric-note'>{desc}</span></div>", unsafe_allow_html=True)

    st.subheader("Vì sao đây là Agent?")
    st.markdown(
        "Agent không chỉ trả lời hội thoại. Nó thực hiện vòng lặp có trạng thái: "
        "**quan sát kết quả → phân loại lỗi → cập nhật mức thành thạo → quyết định hành động tiếp theo → chọn bài mới**. "
        "LLM là thành phần tùy chọn để diễn đạt gợi ý; quyền chấm đúng/sai luôn thuộc về test case."
    )
    st.info("Bắt đầu tại mục **Test đầu vào**. Nếu muốn demo nhanh, có thể sang **Luyện code** và Agent sẽ bắt đầu từ kỹ năng đầu tiên.")


def diagnostic_page():
    st.header("🧭 Test trình độ đầu vào")
    st.caption("Mỗi lần làm lại, Agent chọn ngẫu nhiên câu hỏi nhưng vẫn bảo đảm phủ các kỹ năng chính.")
    questions = st.session_state.quiz
    with st.form("diagnostic_form"):
        answers: dict[str, int] = {}
        for index, q in enumerate(questions, 1):
            st.markdown(f"**Câu {index}. {q['question']}**")
            choice = st.radio(
                "Chọn đáp án",
                options=list(range(len(q["options"]))),
                format_func=lambda i, opts=q["options"]: opts[i],
                key=f"diag_{q['id']}",
                label_visibility="collapsed",
            )
            answers[q["id"]] = choice
            st.write("")
        submitted = st.form_submit_button("Phân tích bằng EDUCODER Agent", type="primary", use_container_width=True)
    if submitted:
        result = agent.evaluate_diagnostic(questions, answers)
        agent.apply_diagnostic(st.session_state.learner, result)
        save_profile()
        st.session_state.diagnostic_result = result
        st.session_state.current_exercise_id = None
        st.rerun()

    result = st.session_state.diagnostic_result
    if result:
        st.success(f"Kết quả: **{result.score}/{result.total}** — mức **{result.level}**")
        cols = st.columns(3)
        cols[0].metric("Điểm", f"{result.score}/{result.total}")
        cols[1].metric("Kỹ năng cần củng cố", len(result.weak_skills))
        cols[2].metric("Bắt đầu từ", skill_name(result.recommended_path[0]))
        with st.expander("Xem đáp án và giải thích"):
            for q in questions:
                st.markdown(f"- **{q['question']}**  \n  Đáp án: {q['options'][q['answer_index']]}. {q['explanation']}")
        if st.button("Tạo bộ câu hỏi mới"):
            reset_diagnostic()
            st.rerun()


def path_page():
    st.header("🗺️ Lộ trình học cá nhân hóa")
    learner: LearnerState = st.session_state.learner
    if not st.session_state.diagnostic_result:
        st.warning("Chưa có test đầu vào. Agent đang dùng lộ trình mặc định từ kiến thức nền.")
    for i, skill in enumerate(repo.curriculum["skills"], 1):
        mastery = float(learner.mastery.get(skill["id"], 0.0))
        status = "Đã vững" if mastery >= 0.82 else "Đang học" if skill["id"] == learner.current_skill else "Cần học"
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.6, 3.5, 1.2])
            c1.markdown(f"### {i}")
            c2.markdown(f"**{skill['name']}**  \n{skill['description']}")
            c3.metric(status, f"{mastery*100:.0f}%")
            st.progress(mastery)
    if st.button("Bắt đầu bài Agent đề xuất", type="primary"):
        choose_next_exercise()
        st.session_state.goto_practice = True
        st.toast("Đã chọn bài phù hợp. Mở mục Luyện code ở thanh bên.")


def practice_page():
    st.header("⌨️ Luyện code thích ứng")
    learner: LearnerState = st.session_state.learner

    with st.expander("Chọn kỹ năng thủ công"):
        selected_skill = st.selectbox(
            "Kỹ năng",
            repo.skill_order,
            index=repo.skill_order.index(learner.current_skill),
            format_func=skill_name,
        )
        selected_diff = st.slider("Độ khó", 1, 3, learner.current_difficulty)
        if st.button("Áp dụng lựa chọn"):
            learner.current_skill = selected_skill
            learner.current_difficulty = selected_diff
            choose_next_exercise()
            st.rerun()

    if not st.session_state.current_exercise_id:
        choose_next_exercise()
    exercise = repo.exercise_by_id(st.session_state.current_exercise_id)
    if not exercise:
        st.error("Không tìm thấy bài tập.")
        return

    st.markdown(f"### {exercise['title']}")
    st.caption(f"Kỹ năng: {skill_name(exercise['skill'])} · độ khó {exercise['difficulty']}/3 · kiểu chấm {exercise['kind']}")
    st.write(exercise["description"])

    left, right = st.columns([1.25, 0.9])
    editor_key = f"code_{exercise['id']}"
    if editor_key not in st.session_state:
        st.session_state[editor_key] = exercise["starter_code"]
    with left:
        code = st.text_area("Mã Python", key=editor_key, height=330)
        c1, c2 = st.columns(2)
        submit = c1.button("▶ Chạy và chấm", type="primary", use_container_width=True)
        new_problem = c2.button("↻ Đổi bài cùng mức", use_container_width=True)
        if new_problem:
            learner.attempts[learner.current_skill] = learner.attempts.get(learner.current_skill, 0) + 1
            choose_next_exercise()
            st.rerun()

    if submit:
        grade, decision = agent.submit(learner, exercise, code, st.session_state.hint_level)
        save_profile()
        st.session_state.last_grade = grade
        st.session_state.last_decision = decision
        st.rerun()

    with right:
        st.subheader("Agent feedback")
        grade = st.session_state.last_grade
        decision = st.session_state.last_decision
        if not grade:
            st.info("Nhấn **Chạy và chấm** để Agent quan sát kết quả.")
            st.markdown("**Test công khai**")
            for i, test in enumerate(exercise["tests"][:2], 1):
                if exercise["kind"] == "io":
                    st.code(f"Input: {test.get('input','').strip()}\nOutput: {test.get('output','').strip()}")
                else:
                    st.code(test["assert"], language="python")
        else:
            if grade.passed:
                st.success(f"Đúng {grade.passed_tests}/{grade.total_tests} test — {grade.score} điểm")
                st.balloons()
            else:
                st.error(f"Đúng {grade.passed_tests}/{grade.total_tests} test — {grade.error_category}")
            st.write(grade.feedback)
            if not grade.passed:
                st.warning(f"💡 Gợi ý mức {st.session_state.hint_level}: {grade.hint}")
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

            st.markdown("**Quyết định của Agent**")
            st.info(f"{decision['action']}: {decision['reason']}")
            st.caption(f"Tiếp theo: {skill_name(decision['next_skill'])} · độ khó {decision['next_difficulty']}/3")
            with st.expander("Xem Agent trace"):
                st.json(decision["trace"])
                st.json({"mastery": learner.mastery[exercise["skill"]], "error_counts": learner.error_counts})
            if st.button("Làm bài Agent đề xuất", type="primary", use_container_width=True):
                choose_next_exercise()
                st.rerun()


def progress_page():
    st.header("📊 Hồ sơ học tập")
    learner: LearnerState = st.session_state.learner
    cols = st.columns(4)
    cols[0].metric("Bài đã giải", len(learner.solved_ids))
    cols[1].metric("Lượt nộp", sum(learner.attempts.values()))
    cols[2].metric("Kỹ năng ≥ 82%", sum(v >= 0.82 for v in learner.mastery.values()))
    cols[3].metric("Loại lỗi", len(learner.error_counts))
    st.subheader("Mức thành thạo")
    for skill in repo.skill_order:
        value = float(learner.mastery.get(skill, 0.0))
        st.write(f"**{skill_name(skill)} — {value*100:.0f}%**")
        st.progress(value)
    if learner.error_counts:
        st.subheader("Lỗi thường gặp")
        st.bar_chart(learner.error_counts)
    with st.expander("Nhật ký quyết định"):
        st.json(learner.history[-20:])

    c1, c2 = st.columns(2)
    c1.download_button(
        "Tải hồ sơ JSON",
        data=pretty_json(learner.to_dict()),
        file_name="educoder10_progress.json",
        mime="application/json",
        use_container_width=True,
    )
    upload = c2.file_uploader("Khôi phục hồ sơ JSON", type=["json"])
    if upload is not None:
        try:
            st.session_state.learner = LearnerState.from_dict(json.load(upload))
            st.session_state.learner.learner_name = current_user.full_name
            save_profile()
            st.success("Đã khôi phục hồ sơ.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            st.error(f"File không hợp lệ: {exc}")


def exercise_bank_page():
    st.header("📚 Kho bài tập")
    tab1, tab2 = st.tabs(["Kho bài EDUCODER", "MBPP mở rộng"])
    with tab1:
        st.metric("Số bài Việt hóa", len(repo.exercises))
        selected = st.selectbox("Lọc kỹ năng", ["all", *repo.skill_order], format_func=lambda x: "Tất cả" if x == "all" else skill_name(x))
        rows = [x for x in repo.exercises if selected == "all" or x["skill"] == selected]
        st.dataframe([{"ID": x["id"], "Tên": x["title"], "Kỹ năng": skill_name(x["skill"]), "Độ khó": x["difficulty"], "Test": len(x["tests"])} for x in rows], use_container_width=True, hide_index=True)
    with tab2:
        st.markdown(
            "Bộ **Mostly Basic Python Problems (MBPP)** của Google Research được đóng gói nguyên bản để làm nguồn bài mở rộng. "
            "MBPP dùng tiếng Anh và không mặc nhiên phù hợp Tin học 10; giáo viên cần duyệt, Việt hóa và phân loại trước khi đưa cho học sinh."
        )
        preview = load_mbpp_preview(30)
        st.metric("Bài MBPP xem trước", len(preview))
        if preview:
            task = st.selectbox("Chọn task", preview, format_func=lambda x: f"#{x['task_id']} — {x['prompt'][:70]}")
            st.write(task["prompt"])
            st.code("\n".join(task["tests"]), language="python")
        st.caption("Nguồn: google-research/google-research/mbpp, Apache License 2.0. EDUCODER không hiển thị lời giải chuẩn cho học sinh.")


def student_classes_page():
    st.header("🏫 Lớp của tôi")
    with st.form("join_class"):
        code = st.text_input("Mã tham gia do giáo viên cung cấp")
        submitted = st.form_submit_button("Tham gia lớp")
    if submitted:
        try:
            auth.join_class(current_user.id, code)
            st.success("Đã tham gia lớp.")
        except AuthError as exc:
            st.error(str(exc))
    classes = auth.list_classes(current_user.id)
    st.dataframe([{"Lớp": x["name"], "Giáo viên": x["teacher_name"], "Sĩ số": x["student_count"]} for x in classes], use_container_width=True, hide_index=True)


def teacher_classes_page():
    st.header("👨‍🏫 Quản lý lớp")
    with st.form("create_class"):
        name = st.text_input("Tên lớp mới", placeholder="Ví dụ: 10A1 - Python")
        submitted = st.form_submit_button("Tạo lớp", type="primary")
    if submitted:
        try:
            classroom = auth.create_class(current_user.id, name)
            st.success(f"Đã tạo lớp. Mã tham gia: {classroom['join_code']}")
        except AuthError as exc:
            st.error(str(exc))
    classes = auth.list_classes(current_user.id)
    if not classes:
        st.info("Bạn chưa có lớp nào.")
        return
    selected = st.selectbox("Chọn lớp", classes, format_func=lambda x: f"{x['name']} — mã {x['join_code']}")
    st.caption(f"Mã mời học sinh: **{selected['join_code']}**")
    students = auth.class_students(current_user.id, selected["id"])
    st.dataframe([{"Học sinh": x["full_name"], "Tài khoản": x["username"], "Bài đã giải": x["solved"], "Lượt làm": x["attempts"], "Thành thạo TB": f"{x['average_mastery']}%", "Cập nhật": x["updated_at"] or "Chưa học"} for x in students], use_container_width=True, hide_index=True)


def admin_users_page():
    st.header("🛡️ Quản trị tài khoản và phân quyền")
    tab1, tab2, tab3 = st.tabs(["Tạo tài khoản", "Danh sách & vai trò", "Đặt lại mật khẩu"])
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
    st.header("🏫 Toàn bộ lớp")
    classes = auth.list_classes(current_user.id)
    st.dataframe([{"Lớp": x["name"], "Giáo viên": x["teacher_name"], "Mã": x["join_code"], "Sĩ số": x["student_count"]} for x in classes], use_container_width=True, hide_index=True)
    if classes:
        selected = st.selectbox("Xem học sinh", classes, format_func=lambda x: x["name"])
        st.dataframe(auth.class_students(current_user.id, selected["id"]), use_container_width=True, hide_index=True)
        teachers = [x for x in auth.list_users(current_user.id) if x["role"] == "teacher" and x["is_active"]]
        if teachers:
            new_teacher = st.selectbox("Chuyển lớp cho giáo viên", teachers, format_func=lambda x: f"{x['full_name']} (@{x['username']})")
            if st.button("Chuyển quyền phụ trách lớp"):
                try:
                    auth.reassign_class(current_user.id, selected["id"], new_teacher["id"])
                    st.success("Đã chuyển lớp.")
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))


def audit_page():
    st.header("🧾 Nhật ký hệ thống")
    st.caption("Theo dõi các thao tác quản trị quan trọng; nhật ký không lưu mật khẩu.")
    st.dataframe(auth.audit_logs(current_user.id), use_container_width=True, hide_index=True)


page = render_sidebar()
if page == "🏠 Tổng quan":
    home_page()
elif page == "🧭 Test đầu vào":
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

st.divider()
st.caption("EDUCODER 10 v2.0 · RBAC Admin/Giáo viên/Học sinh · Chấm bài xác định · Không chạy mã học sinh không tin cậy trên máy chủ công cộng nếu chưa có sandbox cô lập.")
