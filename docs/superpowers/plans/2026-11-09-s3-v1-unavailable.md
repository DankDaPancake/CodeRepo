# Kiểm chứng S3 v1 và thử lại unavailable — Kế hoạch triển khai

**Mục tiêu:** Cung cấp hai notebook Colab có thể kiểm tra metadata của 1.000 paper và thử lại version unavailable, lưu kết quả riêng để nhóm xem trước.

**Kiến trúc:** Các hàm Python dùng chung xử lý đầu vào, provenance, phân loại và kết quả; notebook là giao diện cấu hình và thực thi. Dùng downloader, discovery, limiter và checkpoint sẵn có khi phù hợp; không sửa run gốc. Phép đo tích hợp chỉ chạy trên bản sao và phải báo riêng các giai đoạn.

**Công nghệ:** Python, pytest, notebook Colab, Drive, arXiv API/OAI.

## Ràng buộc
- Đọc trạng thái cuối theo (arxiv_id, version) từ đủ năm journal; lưu hash và provenance. Không im lặng bỏ lỗi dữ liệu.
- Mẫu S3 chọn ngẫu nhiên 1.000 ID duy nhất với seed và lưu tập mẫu; thiếu mẫu thì dừng.
- Discovery trực tiếp, không dùng snapshot/cache làm nguồn xác minh; phân loại phù hợp, mâu thuẫn, chưa kết luận theo ngày và timestamp có múi giờ đáng tin; không khẳng định nội dung S3 đã xác minh.
- Retry đúng version, giữ provenance các run, phân biệt ok, no_tex, unavailable, corrupt và lỗi chưa kết luận; resume an toàn; không ghi đè corpus gốc.
- Tích hợp thử trên bản sao sau khi có dữ liệu khôi phục; báo thời gian restore, cập nhật, checkpoint, restore kiểm tra và xác minh hash, journal, QA. Không tự cập nhật run gốc.

## Công việc

1. **Đầu vào và lấy mẫu:** Viết test RED cho journal thiếu/hỏng, record cuối, trùng ID và lấy mẫu có seed; triển khai bộ đọc và lấy mẫu, chạy test GREEN.
2. **Kiểm tra metadata:** Test ngày version trước/sau bundle, thiếu ngày, timestamp mơ hồ, discovery lỗi và đối chiếu snapshot. Triển khai discovery trực tiếp, phân loại bảo thủ, xuất chi tiết/tổng hợp và provenance; chạy test.
3. **Thử lại unavailable:** Test gộp provenance, HTTP 404/410 và lỗi tạm thời, no_tex/corrupt, lưu an toàn và resume. Triển khai retry vào run riêng với limiter và downloader, xuất báo cáo; chạy test.
4. **Notebook và hướng dẫn:** Tạo hai notebook với preflight, cấu hình Drive rõ ràng, mặc định không chạy mạng, hướng dẫn và output; kiểm tra cấu trúc và smoke test offline.
5. **Đo tích hợp trên bản sao:** Cung cấp quy trình đo có kiểm tra để tạo bản sao độc lập, thử tích hợp vài kết quả, đo từng pha và xác minh restore/QA. Không vận hành trên run thật hay hứa ước lượng khi chưa đo trên Drive.
6. **Kiểm tra cuối:** Chạy test liên quan và test toàn repo nếu môi trường cho phép; rà diff và ghi rõ kiểm thử thực tế, giới hạn mạng/Drive. Không merge hay sửa corpus gốc.
