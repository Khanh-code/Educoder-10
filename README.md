# EDUCODER 10 — Trợ lý học lập trình Python cá nhân hóa

EDUCODER 10 là prototype Streamlit dành cho Tin học 10. Hệ thống thực hiện một
chu trình Agent có trạng thái:

1. Chọn ngẫu nhiên 10 câu chẩn đoán nhưng vẫn phủ sáu kỹ năng.
2. Tính hồ sơ thành thạo theo từng kỹ năng.
3. Lập lộ trình theo quan hệ tiên quyết.
4. Chạy và chấm code bằng test case xác định.
5. Phân loại lỗi và sinh gợi ý theo ba mức.
6. Chọn bài tương tự, dễ hơn, khó hơn hoặc chuyển kỹ năng.
7. Lưu nhật ký quyết định và cho phép xuất/nhập hồ sơ JSON.
8. Đăng nhập và phân quyền ba cấp: quản trị viên, giáo viên, học sinh.

## Tài khoản và phân quyền

Lần chạy đầu, ứng dụng yêu cầu tạo quản trị viên đầu tiên. Có thể khởi tạo
trước bằng dòng lệnh (mật khẩu được nhập ẩn):

```bash
python init_admin.py --username admin --name "Quản trị viên EDUCODER"
```

Sau khi đăng nhập:

- **Admin** tạo/khóa tài khoản, đổi vai trò, đặt lại mật khẩu tạm, xem toàn bộ
  lớp và nhật ký quản trị. Hệ thống không cho khóa quản trị viên cuối cùng.
- **Giáo viên** tạo lớp, phát mã tham gia và xem tiến độ của học sinh trong
  đúng lớp mình phụ trách. Giáo viên không được tạo admin hay đổi vai trò.
- **Học sinh** làm test, luyện code, xem/lưu hồ sơ của chính mình và tham gia
  lớp bằng mã. Học sinh không được đọc hồ sơ của bạn khác.

Tài khoản do admin tạo phải đổi mật khẩu ở lần đăng nhập đầu. Mật khẩu được băm
bằng Argon2 qua `pwdlib`; cơ sở dữ liệu không lưu mật khẩu rõ. Dữ liệu demo nằm
ở `data/educoder.db` và file này không nên đưa lên Git.

## Chạy nhanh

Yêu cầu Python 3.11 trở lên.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Mở địa chỉ Streamlit hiển thị trong terminal, thường là
`http://localhost:8501`.

## Chạy kiểm thử

Từ thư mục dự án:

```bash
python -m unittest discover -s tests -v
```

## Chế độ LLM tùy chọn

Ứng dụng chạy đầy đủ khi không có API. Nếu muốn LLM diễn đạt gợi ý Socratic,
đặt ba biến môi trường theo `.env.example`:

- `EDUCODER_LLM_ENDPOINT`
- `EDUCODER_LLM_API_KEY`
- `EDUCODER_LLM_MODEL`

LLM **không có quyền thay đổi kết quả chấm**. Đúng/sai luôn do test case quyết
định. Khi API lỗi, hệ thống tự dùng gợi ý trong ngân hàng bài tập.

## Dữ liệu

- `data/diagnostic.json`: 18 câu trắc nghiệm Việt hóa.
- `data/exercises.json`: 24 bài thực hành, mỗi bài có 3–4 test và gợi ý tăng dần.
- `data/mbpp/sanitized-mbpp.json`: bộ MBPP gốc để giáo viên tham khảo và chọn
  bài mở rộng. MBPP dùng tiếng Anh, cần được duyệt trước khi dùng với lớp 10.

## Giới hạn an toàn quan trọng

`SafePythonRunner` chạy mã trong tiến trình con, có timeout, giới hạn tài nguyên
trên Unix và bộ lọc AST cơ bản. Đây **không phải sandbox bảo mật tuyệt đối**.
Không đưa ứng dụng hiện tại lên Internet công cộng để chạy mã không tin cậy.
Triển khai thật cần Judge0, container không đặc quyền, gVisor/Firecracker hoặc
Pyodide chạy phía trình duyệt, kèm giới hạn CPU/RAM/network/file system.

## Mô hình dữ liệu RBAC

- `users`: tài khoản, vai trò, trạng thái và cờ buộc đổi mật khẩu.
- `classes`: lớp học thuộc một giáo viên và mã tham gia ngẫu nhiên.
- `class_members`: quan hệ học sinh–lớp.
- `learning_profiles`: trạng thái Agent riêng của từng học sinh.
- `audit_logs`: dấu vết tạo tài khoản, đổi quyền, khóa tài khoản, tạo/tham gia lớp.

Quyền được kiểm tra lại trong `AuthService`, không phụ thuộc vào việc menu có
được hiển thị hay không. SQLite mở kết nối riêng cho mỗi thao tác và bật khóa
ngoại; khi triển khai nhiều tiến trình/máy chủ nên chuyển sang PostgreSQL.

## Nâng cấp tiếp theo

- SSO/OIDC của trường và xác thực đa yếu tố cho admin.
- PostgreSQL, migration, sao lưu và chính sách lưu trữ dữ liệu.
- Giao bài, hạn nộp, xuất báo cáo lớp và thông báo cho giáo viên.
- Duyệt/Việt hóa MBPP theo chuẩn kiến thức Tin học 10.
- Sandbox cô lập thật và hàng đợi chấm bài.
- So sánh chính sách Agent bằng learning gain, completion rate và thời gian.
