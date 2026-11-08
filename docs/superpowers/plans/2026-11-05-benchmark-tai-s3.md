# Kế hoạch notebook benchmark tải S3

**Mục tiêu:** Tạo notebook Colab độc lập để chọn bundle arXiv S3, tải và lưu lên Google Drive, đồng thời thu thập số đo có thể dùng trong báo cáo M1.

**Trạng thái:** Kế hoạch đề xuất, chưa triển khai. Thiết kế mặc định là tải từng bundle về ổ local của Colab, kiểm tra MD5, rồi copy lên Drive. Cần chốt phạm vi benchmark: tải lại mẫu vào thư mục thử riêng hay chỉ tải bundle còn thiếu. Nếu tái sử dụng bundle, ghi nhận riêng, không coi đó là lượt tải mới.

## Giới hạn và đầu vào

- Notebook độc lập, không crawl paper, không giải nén hoặc xử lý figure, không thay đổi run only-v1 đang hoạt động.
- Đọc snapshot lọc, phạm vi ID và manifest arXiv; chọn bundle ứng viên theo `src/crawler/s3_prepare.py::select_bundles`. Khoảng trong manifest chỉ là bằng chứng ứng viên, không chứng minh paper hoặc version có trong bundle.
- AWS Requester Pays: dùng Colab Secrets, không in credentials; người chạy chịu phí request và truyền dữ liệu có thể phát sinh.
- Preview số file, kích thước ước lượng và danh sách thiếu trước khi bật download; giới hạn số bundle và dung lượng bằng config. Không tự ghi đè bundle hiện có.
- Ghi kết quả benchmark vào thư mục run riêng trên Drive; giữ code revision, hash snapshot và manifest để tái lập.

## Định nghĩa measurement

- `setup_s`: chuẩn bị runtime, mount Drive và đầu vào; đo riêng, không cộng trùng vào crawl.
- `selection_s`: đọc snapshot, manifest và lập kế hoạch bundle.
- Mỗi bundle mới: `download_s` (S3 → local), `verify_local_s` (MD5 local), `copy_to_drive_s` (copy và đóng file), `bytes_actual`, `bytes_manifest`, trạng thái và lỗi/retry.
- `session_wall_s`: toàn bộ phiên benchmark theo ranh giới công bố rõ ràng; báo riêng thời gian setup, không tính hai lần các phép đo lồng nhau. Thông lượng tải tính bằng bytes thực tế chia download_s; thông lượng end-to-end dùng tổng bytes tải mới và wall phù hợp.
- Sampling peak RAM của tiến trình và con; peak disk local tính trên phạm vi xác định, ghi chu kỳ lấy mẫu và lưu ý có thể bỏ sót đỉnh. Không gọi dung lượng Drive là disk local.
- File đã có được ghi là `reused`, có thời gian kiểm tra riêng và không tham gia throughput tải mới. Tránh diễn giải thời gian đóng file hoặc readback trong cùng runtime là bảo đảm đã đồng bộ bền vững lên cloud.
- Lưu JSONL từng sự kiện và CSV/JSON tổng kết; ghi các phép đo không thu thập được là thiếu, không suy diễn là 0. Manifest size có thể khác kích thước file; MD5 là phép đối chiếu đã thống nhất.

## Các bước thực hiện

### 1. Chọn phạm vi và kiểm tra đầu vào

- [ ] Chốt lựa chọn benchmark mẫu mới hay chỉ bundle thiếu; xác định thư mục đích và kích thước smoke trước khi chạy có phí.
- [ ] Tạo `src/notebooks/arxiv_nhom1_s3_download_benchmark.ipynb`, tách cell directory, cấu hình run, cài đặt, mount, secrets, chọn bundle và thực thi.
- [ ] Chọn ID theo snapshot và phạm vi thành viên; hỗ trợ danh sách key rõ ràng cho smoke. Kiểm tra path, snapshot, manifest, credentials, dung lượng local và giới hạn tải.
- [ ] In danh sách bundle ứng viên, đã có, dự kiến tải và ID ngoài manifest. Với bundle có sẵn chưa xác minh, ghi `unverified` thay vì mặc định coi là hợp lệ.

### 2. Tải, xác minh và tiếp tục

- [ ] Xây dựng helper riêng hoặc mở rộng `src/crawler/s3_prepare.py` mà vẫn tương thích caller cũ: tải một bundle về file tạm local, đo bytes/thời gian và cập nhật tiến độ; xác minh MD5 theo manifest.
- [ ] Copy file hợp lệ vào file tạm trong thư mục đích Drive, chỉ đổi tên sau khi copy hoàn tất; giữ các file cũ nguyên vẹn và báo xung đột hoặc checksum sai để xử lý thủ công.
- [ ] Ghi kết quả sau từng bundle để runtime ngắt vẫn còn log; lần chạy lại xác minh bundle đã công bố trước khi bỏ qua. Làm rõ rằng việc đóng file và rename qua Drive FUSE không chứng minh đã đồng bộ bền vững.
- [ ] Tách progress tổng số bundle khỏi progress bytes hiện tại; xử lý lỗi mạng, disk đầy và ngắt runtime mà không đánh dấu file chưa kiểm chứng là thành công.

### 3. Tổng hợp benchmark

- [ ] Viết module đo/tổng hợp phù hợp cấu trúc `src/benchmark/`; đo các phạm vi ở trên bằng đồng hồ monotonic và tài nguyên có sampling.
- [ ] Xuất báo cáo CSV/JSON sau mỗi bundle và cuối phiên; lưu nguồn, revision, cấu hình, hash đầu vào, run ID, timestamp UTC và trạng thái đầy đủ hay bị gián đoạn.
- [ ] Kiểm tra tổng thời gian, đơn vị bytes, throughput và phân biệt `downloaded`, `reused`, `failed`, `incomplete`; các mốc chưa biết không được ghi 0 giả.

### 4. Kiểm chứng trước khi dùng thật

- [ ] Viết test với S3 và Drive giả lập cho: thành công, checksum sai, lỗi mạng giữa chừng, file đích tồn tại, resume sau ngắt, thiếu disk và các giá trị tổng hợp; không gọi AWS thật trong pytest.
- [ ] Chạy test liên quan và kiểm tra notebook có thể load; smoke trên Colab bằng tài khoản được phép, thư mục thử riêng và giới hạn bundle đã thống nhất.
- [ ] Đối chiếu output với file trên Drive, đọc lại từ runtime mới nếu cần kiểm tra khôi phục; báo cáo chi phí/thời gian smoke thực tế và giới hạn quan sát.
- [ ] Chỉ sau khi smoke thành công, quyết định áp dụng cho dữ liệu chính thức; commit/PR theo chỉ dẫn tiếp theo của nhóm.

## Điểm cần thống nhất trước khi triển khai

1. Benchmark tải lại một mẫu vào thư mục thử riêng hay chỉ tải bundle còn thiếu? Nếu dùng mẫu, cần xác định số bundle và cách chọn.
2. Có cần so sánh hai phương án ghi trực tiếp Drive và qua local, hay chỉ benchmark phương án qua local?
3. Thư mục báo cáo và thời điểm nộp kết quả M1; kết quả smoke không đại diện cho toàn bộ tập nếu không chạy đủ phạm vi benchmark yêu cầu.
