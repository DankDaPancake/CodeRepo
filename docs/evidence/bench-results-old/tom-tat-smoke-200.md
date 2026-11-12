# Tóm tắt smoke test M1 — 200 ID đầu range Đăng

**Phạm vi:** `2604.20535` → `2604.20734`, chạy trên Colab CPU, chia 2 chunk × 100 ID, bật lấy references và checkpoint Drive. Code: `6c8c2b3`.

## Kết quả

- Hoàn tất **200/200 paper, 279 version**, không có lỗi QA source/references. Trong đó 266 version có TeX, 12 không có TeX và 1 source không còn truy cập được; các empty record được giữ lại.
- Tổng thời gian pipeline: **30 phút 05 giây**, trung bình **9,03 giây/ID**. Hai chunk mất khoảng 14 phút 55 giây và 15 phút 10 giây; chunk sau có nhiều version hơn (149 so với 130), chưa có bằng chứng pipeline chậm dần theo corpus.
- RAM crawler tối đa quan sát được: **49,4 MB**; disk tối đa: **40,9 MB**. CPU chủ yếu chờ mạng, chưa phải nút thắt tính toán.

## Nút thắt đã xác định

- **90 phản hồi HTTP 429**, 69 lần đứt download giữa chừng, **10 lần phải tải lại từ byte 0**. Các phần dữ liệu bị bỏ trước khi tải lại cộng khoảng **237 MB** theo offset trong log.
- Có **445 request arXiv**, trong khi đường đi không lỗi của mẫu này cần 283 request (4 metadata + 279 source).
- Log ghi nhận **318,8 giây backoff được yêu cầu**. Khoảng này đã nằm trong tổng runtime, không cộng thêm; cũng không coi là một phần thời gian độc lập với pacing.
- **Discovery chỉ 7,6 giây**; references hoàn tất sớm trong nền. Tổng checkpoint chỉ **4,14 giây**, khoảng **0,23% thời gian ca**. Lượt này không cho thấy checkpoint gây chậm đáng kể.

## Vấn đề trong code cần chú ý

1. **Đo thời gian download bị đếm trùng thời gian chờ limiter.** Đã tái hiện ngoại tuyến. Wall time từ profiler vẫn dùng được, nhưng chưa dùng `mean_download_s`/`mean_transfer_extract_s` để phân rã thời gian chính xác.
2. **Resume bỏ partial download quá sớm:** 7 lần tải lại do Range gặp 429 ba lần liên tiếp; 3 lần do chạm giới hạn 5 lần resume. Cần cân nhắc giữ offset và chờ có giới hạn thay vì tải lại toàn bộ.

## Nhờ nhóm góp ý giải pháp

- Làm sao giữ partial download qua các đợt 429 mà vẫn có deadline, kiểm tra `Content-Range` và tránh retry vô hạn?
- Có nên điều chỉnh pacing theo tình trạng 429? Cần đo lợi ích thực tế, vẫn giữ một kết nối và khoảng cách tối thiểu theo quy định arXiv.
- Kaggle metadata snapshot có thể hỗ trợ discovery khi API lỗi, nhưng discovery hiện rất nhỏ; cần tránh quét snapshot lớn ở mỗi chunk và kiểm tra độ mới của version.

**Đề xuất bước tiếp:** giữ nguyên kết quả này làm baseline; sửa phép đo, thử từng thay đổi trên cùng mẫu với run ID mới, so sánh tổng runtime, số 429, số lần tải lại và QA. Đây là smoke test, **chưa phải final benchmark toàn bộ 20.000 ID**.

Nguồn: `bench_results/work/` và `bench_results/book_csv/`. Bản tóm tắt được soạn với hỗ trợ của OpenAI Codex từ bằng chứng lượt chạy.
