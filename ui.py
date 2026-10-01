"""Thành phần giao diện dùng chung của EDUCODER 10.

Ý tưởng thiết kế: "sổ tay lập trình Python".
- Màu lấy từ logo Python: xanh #2B5B84 cho thao tác chính, vàng #FFD43B chỉ dùng
  như bút dạ quang để đánh dấu "chặng em đang học".
- Phông Be Vietnam Pro (hiển thị dấu tiếng Việt tốt) và JetBrains Mono cho code,
  được đóng gói trong static/fonts nên chạy được cả khi không có Internet.
Màu cơ bản và phông được khai báo trong .streamlit/config.toml; file này bổ sung
phần CSS mà theme của Streamlit chưa hỗ trợ và các khối HTML nhỏ.
"""

from __future__ import annotations

import re
from html import escape

import streamlit as st

INK = "#17233A"
MUTED = "#5B6B82"
BLUE = "#2B5B84"
BLUE_SOFT = "#E7EEF6"
YELLOW = "#FFD43B"
LINE = "#DCE3EC"
GREEN = "#1F8A5B"

_CSS = f"""
<style>
/* ---------- Khung trang ---------- */
[data-testid="stMainBlockContainer"] {{ max-width: 1180px; padding-top: 2.4rem; padding-bottom: 4rem; }}
header[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ letter-spacing: -0.01em; color: {INK}; }}
p, li {{ line-height: 1.6; }}

/* ---------- Thanh bên ---------- */
section[data-testid="stSidebar"] {{ border-right: 1px solid #E3E8EF; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: 1.2rem; }}
.ec-brand {{ display: flex; align-items: center; gap: .65rem; margin: 0 0 1.4rem; }}
.ec-brand-mark {{ width: 38px; height: 38px; border-radius: 10px; background: {BLUE};
  display: grid; place-items: center; position: relative; flex: none; }}
.ec-brand-mark span {{ color: #fff; font-weight: 700; font-size: .95rem; font-family: "JetBrains Mono", monospace; }}
.ec-brand-mark::after {{ content: ""; position: absolute; left: 8px; right: 8px; bottom: 7px; height: 3px;
  border-radius: 2px; background: {YELLOW}; }}
.ec-brand-name {{ font-weight: 700; font-size: 1.12rem; color: {INK}; line-height: 1.1; }}
.ec-brand-sub {{ font-size: .8rem; color: {MUTED}; }}
.ec-user {{ display: flex; align-items: center; gap: .65rem; padding: .7rem .75rem; border-radius: .7rem;
  background: #F2F5F9; margin-bottom: 1.1rem; }}
.ec-avatar {{ width: 34px; height: 34px; border-radius: 50%; background: {BLUE_SOFT}; color: {BLUE};
  font-weight: 700; display: grid; place-items: center; font-size: .9rem; flex: none; }}
.ec-user-name {{ font-weight: 600; font-size: .92rem; color: {INK}; line-height: 1.2; }}
.ec-user-role {{ font-size: .78rem; color: {MUTED}; }}

/* Menu điều hướng: biến radio thành danh sách mục (Streamlit 1.64) */
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has([data-testid="stRadio"]),
section[data-testid="stSidebar"] [data-testid="stRadio"],
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] {{ width: 100% !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ display: flex; flex-direction: column; gap: 2px; width: 100%; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div {{ width: 100%; margin: 0; padding: 0; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {{
  display: flex; width: 100%; margin: 0; padding: .5rem .75rem; border-radius: .6rem; cursor: pointer;
  transition: background .12s ease; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {{ background: #F2F5F9; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:not([data-testid="stMarkdownContainer"]) {{ display: none; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {{
  background: {BLUE_SOFT}; box-shadow: inset 3px 0 0 {BLUE}; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p {{ color: #1E4468; font-weight: 600; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {{ font-size: .95rem; color: {INK}; margin: 0; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p span[role="img"] {{ margin-right: .45rem; color: {MUTED}; font-size: 1.15rem; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p span[role="img"] {{ color: {BLUE}; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {{ outline: none !important; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] * {{ outline: none !important; }}

.ec-now {{ margin-top: 1.4rem; padding-top: 1rem; border-top: 1px solid #E3E8EF; }}
.ec-now-label {{ font-size: .8rem; color: {MUTED}; margin-bottom: .2rem; }}
.ec-now-skill {{ font-weight: 600; color: {INK}; margin-bottom: .5rem; }}
.ec-bar {{ height: 6px; border-radius: 3px; background: #E6EBF2; overflow: hidden; }}
.ec-bar > div {{ height: 100%; border-radius: 3px; background: {BLUE}; }}
.ec-now-meta {{ font-size: .78rem; color: {MUTED}; margin-top: .35rem; }}

/* ---------- Tiêu đề trang ---------- */
.ec-page-title {{ font-size: 2rem; font-weight: 700; color: {INK}; margin: 0; line-height: 1.2; }}
.ec-page-sub {{ color: {MUTED}; margin: .35rem 0 1.4rem; max-width: 70ch; }}

/* ---------- Nhãn nhỏ (kỹ năng, độ khó) ---------- */
.ec-chips {{ display: flex; flex-wrap: wrap; gap: .45rem; margin: .2rem 0 .9rem; }}
.ec-chip {{ display: inline-flex; align-items: center; gap: .4rem; font-size: .82rem; padding: .22rem .65rem;
  border-radius: 999px; background: #fff; border: 1px solid {LINE}; color: {MUTED}; }}
.ec-chip b {{ color: {INK}; font-weight: 600; }}
.ec-dots {{ display: inline-flex; gap: 3px; }}
.ec-dots i {{ width: 7px; height: 7px; border-radius: 50%; background: #D3DBE6; display: inline-block; }}
.ec-dots i.on {{ background: {BLUE}; }}
.ec-task code {{ font-family: "JetBrains Mono", monospace; font-size: .88em; background: #EEF2F7; color: #1E4468;
  padding: .05rem .35rem; border-radius: .3rem; }}
.ec-task {{ border-left: 3px solid {BLUE}; background: #fff; padding: .85rem 1.1rem; border-radius: 0 .6rem .6rem 0;
  margin-bottom: 1.2rem; color: {INK}; }}

/* ---------- Khung code trên trang chủ ---------- */
.ec-hero-title {{ font-size: 2.35rem; font-weight: 700; line-height: 1.15; color: {INK}; margin: .4rem 0 .8rem; }}
.ec-hero-text {{ color: {MUTED}; font-size: 1.05rem; max-width: 46ch; margin-bottom: 1.2rem; }}
.ec-code {{ background: #14243A; border-radius: .9rem; overflow: hidden; box-shadow: 0 18px 40px -24px rgba(20,36,58,.55); }}
.ec-code-bar {{ display: flex; align-items: center; gap: .4rem; padding: .65rem .9rem; background: #0F1C2E; }}
.ec-code-bar i {{ width: 10px; height: 10px; border-radius: 50%; background: #2A3B55; display: inline-block; }}
.ec-code-bar span {{ margin-left: .5rem; color: #8DA2C0; font-size: .8rem; font-family: "JetBrains Mono", monospace; }}
.ec-code-src {{ padding: 1rem 1.2rem .6rem; }}
.ec-code .ln {{ color: #E6EDF7; font-family: "JetBrains Mono", monospace; font-size: .92rem; line-height: 1.8;
  white-space: pre-wrap; }}
.ec-code .k {{ color: #7FB2E5; }} .ec-code .s {{ color: {YELLOW}; }} .ec-code .f {{ color: #9BD8B4; }}
.ec-code .c {{ color: #6F84A3; }}
.ec-code-out {{ border-top: 1px solid #22344F; padding: .7rem 1.2rem .9rem; color: #C9D6E8;
  font-family: "JetBrains Mono", monospace; font-size: .9rem; }}
.ec-code-out em {{ font-style: normal; color: #6F84A3; margin-right: .5rem; }}

/* ---------- Đường lộ trình (ngang, trang chủ) ---------- */
.ec-track {{ display: grid; grid-template-columns: repeat(6, 1fr); position: relative; margin: .6rem 0 .4rem; }}
.ec-track::before {{ content: ""; position: absolute; left: 8.3%; right: 8.3%; top: 17px; height: 2px; background: {LINE}; }}
.ec-stop {{ text-align: center; position: relative; padding: 0 .35rem; }}
.ec-node {{ width: 36px; height: 36px; border-radius: 50%; margin: 0 auto .55rem; display: grid; place-items: center;
  font-weight: 700; font-size: .9rem; background: #fff; border: 2px solid {LINE}; color: {MUTED}; position: relative; }}
.ec-stop.done .ec-node {{ background: {BLUE}; border-color: {BLUE}; color: #fff; }}
.ec-stop.now .ec-node {{ background: {YELLOW}; border-color: {YELLOW}; color: {INK}; box-shadow: 0 0 0 5px rgba(255,212,59,.28); }}
.ec-stop-name {{ font-size: .85rem; font-weight: 600; color: {INK}; line-height: 1.3; }}
.ec-stop-pct {{ font-size: .78rem; color: {MUTED}; margin-top: .15rem; }}

/* ---------- Dòng thời gian lộ trình (dọc) ---------- */
.ec-tl {{ position: relative; margin: .4rem 0 1.4rem; }}
.ec-tl-item {{ display: grid; grid-template-columns: 44px 1fr; gap: 1rem; position: relative; padding-bottom: 1.1rem; }}
.ec-tl-item:not(:last-child)::before {{ content: ""; position: absolute; left: 21px; top: 40px; bottom: 0; width: 2px; background: {LINE}; }}
.ec-tl-item.done:not(:last-child)::before {{ background: {BLUE}; }}
.ec-tl-item .ec-node {{ margin: 0; width: 40px; height: 40px; }}
.ec-tl-item.done .ec-node {{ background: {BLUE}; border-color: {BLUE}; color: #fff; }}
.ec-tl-item.now .ec-node {{ background: {YELLOW}; border-color: {YELLOW}; color: {INK}; box-shadow: 0 0 0 5px rgba(255,212,59,.28); }}
.ec-tl-body {{ background: #fff; border: 1px solid {LINE}; border-radius: .75rem; padding: .85rem 1.1rem; }}
.ec-tl-item.now .ec-tl-body {{ border-color: #E9C53A; }}
.ec-tl-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }}
.ec-tl-name {{ font-weight: 600; color: {INK}; }}
.ec-tl-state {{ font-size: .8rem; color: {MUTED}; white-space: nowrap; display: inline-flex; gap: .6rem; }}
.ec-tl-state b {{ color: {INK}; font-weight: 600; }}
.ec-tl-desc {{ font-size: .88rem; color: {MUTED}; margin: .15rem 0 .55rem; }}

/* ---------- Thanh thành thạo theo kỹ năng ---------- */
.ec-skills {{ background: #fff; border: 1px solid {LINE}; border-radius: .75rem; padding: .4rem 1.1rem; margin-bottom: 1rem; }}
.ec-skill {{ display: grid; grid-template-columns: minmax(180px, 1.3fr) 3fr 52px; align-items: center; gap: 1rem;
  padding: .65rem 0; border-bottom: 1px solid #EEF2F7; }}
.ec-skill:last-child {{ border-bottom: 0; }}
.ec-skill-name {{ font-size: .92rem; color: {INK}; }}
.ec-skill-pct {{ text-align: right; font-weight: 600; font-size: .9rem; color: {INK}; }}
.ec-skill.done .ec-bar > div {{ background: {GREEN}; }}

/* ---------- Lỗi hay mắc ---------- */
.ec-err {{ display: grid; grid-template-columns: 1fr 70px; gap: .2rem 1rem; padding: .8rem 0; border-bottom: 1px solid #EEF2F7; }}
.ec-err:last-child {{ border-bottom: 0; }}
.ec-err-name {{ font-weight: 600; color: {INK}; }}
.ec-err-count {{ text-align: right; font-weight: 600; color: {INK}; }}
.ec-err-tip {{ grid-column: 1 / -1; font-size: .87rem; color: {MUTED}; }}
.ec-err-tip code {{ font-family: "JetBrains Mono", monospace; font-size: .82rem; background: #EEF2F7; color: #1E4468;
  padding: .05rem .3rem; border-radius: .3rem; }}
.ec-err .ec-bar {{ grid-column: 1 / -1; margin-top: .3rem; }}
.ec-err .ec-bar > div {{ background: #C98A1B; }}

/* ---------- Không làm mờ trang khi Streamlit chạy lại (tránh "chớp" màn hình) ---------- */
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}
[data-testid="stStatusWidget"] {{ visibility: hidden; }}

/* ---------- Thành phần Streamlit ---------- */
[data-testid="stMetric"] {{ background: #fff; border: 1px solid {LINE}; border-radius: .75rem; padding: .85rem 1rem; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-size: .85rem; }}
[data-testid="stMetricValue"] {{ font-size: 1.6rem; font-weight: 600; color: {INK}; }}
[data-testid="stExpander"] details {{ background: #fff; }}
div[data-testid="stForm"] {{ background: #fff; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: #fff; }}

/* ---------- Đăng nhập ---------- */
.ec-login-head {{ text-align: center; margin: 3.5rem 0 1.4rem; }}
.ec-login-head .ec-brand {{ justify-content: center; margin-bottom: 1.6rem; }}
.ec-login-title {{ font-size: 1.7rem; font-weight: 700; color: {INK}; margin: 0; }}
.ec-login-sub {{ color: {MUTED}; margin-top: .35rem; }}
.ec-foot {{ text-align: center; color: {MUTED}; font-size: .8rem; margin-top: 1.2rem; }}

@media (max-width: 900px) {{
  .ec-track {{ grid-template-columns: repeat(3, 1fr); row-gap: 1.2rem; }}
  .ec-track::before {{ display: none; }}
  .ec-hero-title {{ font-size: 1.9rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def brand(subtitle: str = "Học Python lớp 10") -> str:
    return (
        "<div class='ec-brand'><div class='ec-brand-mark'><span>E10</span></div>"
        f"<div><div class='ec-brand-name'>EDUCODER</div><div class='ec-brand-sub'>{escape(subtitle)}</div></div></div>"
    )


def initials(full_name: str) -> str:
    """Hai chữ cái đầu của tên gọi, vd 'Lê Ngọc Minh An' -> 'MA'."""
    parts = full_name.split()
    if not parts:
        return "?"
    return "".join(p[0] for p in parts[-2:]).upper()


def sidebar_header(full_name: str, role_label: str, username: str) -> None:
    _html(
        brand()
        + "<div class='ec-user'>"
        f"<div class='ec-avatar'>{escape(initials(full_name))}</div>"
        f"<div><div class='ec-user-name'>{escape(full_name)}</div>"
        f"<div class='ec-user-role' title='Tài khoản: {escape(username)}'>{escape(role_label)}</div></div></div>"
    )


def sidebar_now(skill: str, mastery: float, difficulty: int) -> None:
    pct = max(0, min(100, round(mastery * 100)))
    _html(
        "<div class='ec-now'>"
        "<div class='ec-now-label'>Em đang học</div>"
        f"<div class='ec-now-skill'>{escape(skill)}</div>"
        f"<div class='ec-bar'><div style='width:{pct}%'></div></div>"
        f"<div class='ec-now-meta'>Thành thạo {pct}%, độ khó {difficulty}/3</div></div>"
    )


def page_header(title: str, subtitle: str | None = None) -> None:
    sub = f"<p class='ec-page-sub'>{escape(subtitle)}</p>" if subtitle else "<div style='height:1rem'></div>"
    _html(f"<h1 class='ec-page-title'>{escape(title)}</h1>{sub}")


def difficulty_dots(level: int) -> str:
    level = int(level)
    dots = "".join(f"<i class='{'on' if i < level else ''}'></i>" for i in range(3))
    return f"<span class='ec-dots'>{dots}</span>"


def exercise_meta(skill: str, difficulty: int, extra: str | None = None) -> None:
    chips = [
        f"<span class='ec-chip'>Kỹ năng <b>{escape(skill)}</b></span>",
        f"<span class='ec-chip'>Độ khó {difficulty_dots(difficulty)}</span>",
    ]
    if extra:
        chips.append(f"<span class='ec-chip'>{escape(extra)}</span>")
    _html(f"<div class='ec-chips'>{''.join(chips)}</div>")


def task_box(text: str) -> None:
    """Khung đề bài; `x` được hiển thị dạng code."""
    _html(f"<div class='ec-task'>{_inline_code(text)}</div>")


def code_greeting(name: str, skill: str) -> None:
    """Khung code 'chào' đúng tên học sinh và kỹ năng đang học (điểm nhấn trang chủ)."""
    short = name.split()[-1] if name.split() else name
    n, s = escape(short), escape(skill)
    _html(
        "<div class='ec-code'><div class='ec-code-bar'><i></i><i></i><i></i><span>bai_hom_nay.py</span></div>"
        "<div class='ec-code-src'>"
        "<div class='ln'><span class='c'># Chương trình đầu tiên của hôm nay</span></div>"
        f"<div class='ln'>ten = <span class='s'>\"{n}\"</span></div>"
        f"<div class='ln'>ky_nang = <span class='s'>\"{s}\"</span></div>"
        f"<div class='ln'><span class='f'>print</span>(<span class='k'>f</span><span class='s'>\"Chào {{ten}}! Hôm nay mình luyện {{ky_nang}}.\"</span>)</div>"
        "</div>"
        f"<div class='ec-code-out'><em>&gt;&gt;&gt;</em>Chào {n}! Hôm nay mình luyện {s}.</div></div>"
    )


def _state(mastery: float, is_current: bool) -> str:
    if mastery >= 0.82:
        return "done"
    return "now" if is_current else ""


def path_track(skills: list[dict], mastery: dict, current: str) -> None:
    stops = []
    for i, skill in enumerate(skills, 1):
        value = float(mastery.get(skill["id"], 0.0))
        state = _state(value, skill["id"] == current)
        mark = "✓" if state == "done" else str(i)
        stops.append(
            f"<div class='ec-stop {state}'><div class='ec-node'>{mark}</div>"
            f"<div class='ec-stop-name'>{escape(skill['name'])}</div>"
            f"<div class='ec-stop-pct'>{round(value * 100)}%</div></div>"
        )
    _html(f"<div class='ec-track'>{''.join(stops)}</div>")


def path_timeline(skills: list[dict], mastery: dict, current: str) -> None:
    items = []
    for i, skill in enumerate(skills, 1):
        value = float(mastery.get(skill["id"], 0.0))
        state = _state(value, skill["id"] == current)
        label = {"done": "Đã vững", "now": "Em đang học"}.get(state, "Chưa vững" if value > 0 else "Chưa học")
        mark = "✓" if state == "done" else str(i)
        pct = round(value * 100)
        items.append(
            f"<div class='ec-tl-item {state}'><div class='ec-node'>{mark}</div>"
            "<div class='ec-tl-body'><div class='ec-tl-head'>"
            f"<span class='ec-tl-name'>{escape(skill['name'])}</span>"
            f"<span class='ec-tl-state'>{label}<b>{pct}%</b></span></div>"
            f"<div class='ec-tl-desc'>{escape(skill['description'])}</div>"
            f"<div class='ec-bar'><div style='width:{pct}%'></div></div></div></div>"
        )
    _html(f"<div class='ec-tl'>{''.join(items)}</div>")


def login_header() -> None:
    _html(
        "<div class='ec-login-head'>" + brand() +
        "<h1 class='ec-login-title'>Đăng nhập</h1>"
        "<p class='ec-login-sub'>Dùng tài khoản thầy cô đã cấp cho em.</p></div>"
    )


def login_footer() -> None:
    _html("<p class='ec-foot'>Quên mật khẩu? Hãy báo thầy cô hoặc quản trị viên để được đặt lại.</p>")


def skill_bars(skills: list[dict], mastery: dict) -> None:
    """Bảng thành thạo: tên kỹ năng, thanh tiến độ mảnh, phần trăm. Đã vững (>=82%) tô xanh lá."""
    rows = []
    for skill in skills:
        value = float(mastery.get(skill["id"], 0.0))
        pct = round(value * 100)
        done = " done" if value >= 0.82 else ""
        rows.append(
            f"<div class='ec-skill{done}'><span class='ec-skill-name'>{escape(skill['name'])}</span>"
            f"<div class='ec-bar'><div style='width:{pct}%'></div></div>"
            f"<span class='ec-skill-pct'>{pct}%</span></div>"
        )
    _html(f"<div class='ec-skills'>{''.join(rows)}</div>")


def _inline_code(text: str) -> str:
    """Escape HTML rồi đổi `x` thành <code>x</code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(text))


def error_rows(items: list[tuple[str, str, int]]) -> None:
    """items: (tên lỗi, giải thích, số lần), đã sắp xếp. Thanh màu hổ phách so với lỗi nhiều nhất."""
    if not items:
        return
    top = max(c for _, _, c in items) or 1
    rows = []
    for name, tip, count in items:
        rows.append(
            f"<div class='ec-err'><span class='ec-err-name'>{escape(name)}</span>"
            f"<span class='ec-err-count'>{count} lần</span>"
            + (f"<span class='ec-err-tip'>{_inline_code(tip)}</span>" if tip else "")
            + f"<div class='ec-bar'><div style='width:{round(100 * count / top)}%'></div></div></div>"
        )
    _html(f"<div class='ec-skills'>{''.join(rows)}</div>")
