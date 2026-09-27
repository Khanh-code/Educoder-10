# Nguồn GitHub đã khảo sát và quyết định thiết kế

## 1. dglabsxyz/adaptive-genai-learning-tutor

URL: https://github.com/dglabsxyz/adaptive-genai-learning-tutor

Điểm tham khảo: chu trình diagnostic → path → exercise → deterministic grade →
progress; tách Agent orchestration khỏi quyền chấm điểm. README hiển thị MIT,
nhưng snapshot được khảo sát không có file LICENSE rõ ràng, vì vậy EDUCODER 10
chỉ học ý tưởng kiến trúc, không sao chép mã nguồn.

## 2. mohddarwix/SmartCode

URL: https://github.com/mohddarwix/SmartCode

Điểm tham khảo: sandbox-first grading, hidden/public tests, gợi ý tăng dần,
mastery tracking và recommendation. Repository có giấy phép MIT. EDUCODER 10
viết lại một phiên bản nhỏ phù hợp lớp 10 và Streamlit, không mang theo backend,
frontend hoặc database của SmartCode.

## 3. AyushGit2k5/ai-programming-tutor

URL: https://github.com/AyushGit2k5/ai-programming-tutor

Điểm tham khảo: progressive hints và nguyên tắc không đưa lời giải ngay. Snapshot
không có file LICENSE rõ ràng, nên không sao chép mã nguồn.

## 4. Google Research MBPP

URL: https://github.com/google-research/google-research/tree/master/mbpp

MBPP có khoảng 1.000 bài Python cơ bản, mỗi bài gồm mô tả, lời giải tham chiếu và
test case. File `sanitized-mbpp.json` được đóng gói nguyên bản theo Apache License
2.0 và chỉ xuất hiện ở góc giáo viên. Nội dung chưa được xem là phù hợp tự động
với Chương trình GDPT 2018; giáo viên phải duyệt và Việt hóa.

## Quyết định cho EDUCODER 10

- Viết mới Agent nhỏ, dễ chạy và dễ giải thích trong một học phần.
- Dùng ngân hàng Việt hóa riêng cho luồng học chính.
- Dùng MBPP làm nguồn mở rộng, không làm dữ liệu chẩn đoán mặc định.
- Chấm bằng test xác định; LLM chỉ diễn đạt gợi ý.
- Chạy code bằng tiến trình con có timeout và AST allowlist; production phải thay
  bằng sandbox cô lập thật.

