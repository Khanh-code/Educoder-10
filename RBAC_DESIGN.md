# Thiết kế phân quyền EDUCODER 10

## 1. Ma trận quyền

| Chức năng | Admin | Giáo viên | Học sinh |
|---|:---:|:---:|:---:|
| Tạo, khóa/mở tài khoản | ✓ | – | – |
| Đổi vai trò người dùng | ✓ | – | – |
| Đặt lại mật khẩu tạm | ✓ | – | – |
| Xem audit log | ✓ | – | – |
| Xem tất cả lớp | ✓ | – | – |
| Chuyển lớp cho giáo viên khác | ✓ | – | – |
| Tạo lớp, phân công giáo viên | ✓ | – | – |
| Thêm học sinh vào lớp | ✓ | – | – |
| Xem tiến độ lớp phụ trách | – | ✓ | – |
| Xem chi tiết từng học sinh trong lớp phụ trách | – | ✓ | – |
| Xem lớp giáo viên khác | ✓ | – | – |
| Làm test, luyện code | – | – | ✓ |
| Xem/sửa hồ sơ của chính mình | – | – | ✓ |

Nguyên tắc là **deny by default**. Các hàm trong `AuthService` kiểm tra vai trò
và quan hệ sở hữu trước khi truy vấn hoặc cập nhật. Menu theo vai trò chỉ giúp
giao diện gọn hơn, không được xem là biện pháp bảo mật.

## 2. Luồng sử dụng

1. Lần chạy đầu, tạo admin đầu tiên trong giao diện hoặc bằng `init_admin.py`.
2. Admin tạo tài khoản giáo viên và học sinh với mật khẩu tạm.
3. Người dùng đăng nhập lần đầu và bắt buộc đổi mật khẩu.
4. Admin tạo lớp và phân công giáo viên phụ trách.
5. Admin thêm học sinh vào lớp (học sinh không tự vào lớp).
6. Mỗi lần học sinh hoàn thành test hoặc nộp code, hồ sơ Agent được lưu theo
   `user_id`.
7. Giáo viên xem thống kê tổng hợp của học sinh thuộc lớp mình; dịch vụ từ chối
   yêu cầu đọc học sinh ngoài phạm vi lớp.
8. Admin có thể khóa tài khoản, đổi vai trò, chuyển lớp và xem audit log.

## 3. Các kiểm soát đã cài đặt

- Mật khẩu băm Argon2 khi cài `pwdlib[argon2]`; không lưu mật khẩu rõ.
- Mật khẩu tối thiểu 10 ký tự, có chữ và số.
- Tên đăng nhập duy nhất, không phân biệt hoa thường.
- Tài khoản mới buộc đổi mật khẩu ở lần đăng nhập đầu.
- Tài khoản bị khóa không thể đăng nhập; trạng thái được kiểm tra lại mỗi rerun.
- Không cho tự khóa tài khoản đang đăng nhập hoặc vô hiệu hóa admin cuối cùng.
- Không cho đổi vai trò giáo viên khi họ còn phụ trách lớp; admin phải chuyển lớp.
- Hồ sơ học sinh chỉ được cập nhật bởi chính học sinh hoặc admin.
- Giáo viên chỉ đọc hồ sơ khi có quan hệ `class_members` với lớp mình sở hữu.
- Audit log ghi thao tác và đối tượng nhưng không ghi mật khẩu.
- SQLite bật foreign key và WAL, mỗi thao tác mở kết nối riêng.

## 4. Cấu trúc file

- `auth.py`: schema SQLite, xác thực, RBAC và audit.
- `app.py`: cổng đăng nhập và màn hình riêng theo vai trò.
- `init_admin.py`: khởi tạo admin từ terminal với mật khẩu nhập ẩn.
- `tests/test_auth.py`: các test đăng nhập và chống vượt quyền.
- `data/educoder.db`: dữ liệu chạy thực tế, được loại khỏi Git.

## 5. Chạy demo

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Kịch bản trình bày ngắn:

1. Đăng nhập admin, tạo một giáo viên và một học sinh.
2. Admin tạo lớp và phân công giáo viên; đăng nhập giáo viên, đổi mật khẩu và xem lớp được phân công.
3. Admin thêm học sinh vào lớp; đăng nhập học sinh, đổi mật khẩu, vào “Lớp của tôi” để xem lớp của mình.
4. Học sinh làm test/nộp bài code.
5. Đăng nhập lại giáo viên để xem lượt làm, số bài giải và mức thành thạo.
6. Trở lại admin để minh họa khóa tài khoản, chuyển lớp và audit log.

## 6. Khi triển khai thật

Bản hiện tại phù hợp prototype/lab nội bộ. Khi đưa lên Internet cần:

- Dùng OIDC/SSO của trường; bật MFA cho admin và giáo viên.
- Dùng PostgreSQL, migration, backup mã hóa và khóa bí mật do hệ thống secrets quản lý.
- Rate limit đăng nhập ở reverse proxy, khóa tạm theo tài khoản và cảnh báo bất thường.
- Cookie phiên `Secure`, `HttpOnly`, `SameSite`; CSRF protection nếu tách API/web.
- Tách dịch vụ chấm code sang sandbox cô lập (Judge0/gVisor/Firecracker/Pyodide).
- Chính sách đồng ý của phụ huynh/nhà trường, tối thiểu hóa dữ liệu và thời hạn xóa.
- Test tích hợp cho mọi endpoint; không chỉ dựa vào việc ẩn nút Streamlit.

