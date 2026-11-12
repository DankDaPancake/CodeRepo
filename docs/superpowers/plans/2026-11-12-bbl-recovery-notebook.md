# Notebook khôi phục .bbl — Kế hoạch triển khai

> Khi triển khai: dùng executing-plans; chạy kiểm thử theo từng công việc.

**Mục tiêu:** Một notebook Colab tải lại đúng version cần rà soát và lưu .bbl khôi phục cùng bằng chứng vào thư mục Drive riêng; có thể tiếp tục sau khi runtime ngắt.

**Kiến trúc:** Module Python riêng quản lý chọn đầu vào, tải source, trích xuất .bbl an toàn và checkpoint; notebook chỉ cấu hình, preflight, chạy và hiển thị tổng hợp. Tái sử dụng HttpClient/RateLimiter và bộ đọc journal hiện có; không dùng thẳng `process_version` vì fallback của nó có thể bỏ .bbl nếu thấy .bib hoặc bibitem.

**Công nghệ:** Python, Google Colab/Drive, downloader arXiv trong repo, JSONL/CSV, pytest.

## Phạm vi và ràng buộc

- Năm journal đã dùng trong `debug/bbl-crawl-2026-11-12/missing-bbl-counts.json`; trạng thái cuối theo (ID, version) của từng run. Lọc status ok, không giữ .bib/.bbl, dropped .bbl > 0; gộp theo cặp ID/version, giữ mọi run nguồn. Baseline hiện tại 1.847 paper / 2.297 version; kiểm tra lại khi thực thi, không hardcode làm điều kiện thành công.
- Đây là tập có bằng chứng .bbl từng bị loại, không đại diện mọi paper thiếu .bib. Chưa biết có bibitem trong TeX hay không. Với record S3 v1, version là suy luận theo snapshot: nguồn lấy lại là arXiv v1, không khẳng định trùng byte với S3.
- Chỉ một client/connection; tối thiểu 3 giây giữa request, dùng chính sách retry và circuit breaker của repo. Mặc định RUN_NETWORK=False; giới hạn thử 10 version có thể cấu hình trước khi chạy toàn bộ.
- Đầu ra tại `MyDrive/bbl-recovery/<run-id>/`, không ghi corpus hoặc journal gốc. Không tự merge kết quả vào corpus/M2. Không chạy đồng thời hai runtime cho cùng output; có khóa ngăn chạy đồng thời và hướng dẫn khôi phục khóa sau ngắt.
- Lưu mọi regular file .bbl an toàn từ archive, kể cả nếu source hiện tại cũng có .bib hoặc bibitem; lưu trạng thái riêng để nhóm quyết định dùng. Bảo toàn đường dẫn tương đối; chặn traversal, absolute path, link, trùng tên, giới hạn kích thước; log file bỏ qua và lý do. Không dùng extractall cho dữ liệu từ mạng.
- Cùng version có thể có nhiều .bbl. Journal ghi URL, thời gian UTC, HTTP/status, hash source nếu đọc đủ, từng đường dẫn/hash/size .bbl, các .bib hiện có, provenance gốc, lỗi và số lần thử. Không coi download lỗi, archive hỏng hay .bbl vượt giới hạn là không có .bbl.
- Ghi dữ liệu vào staging trên Drive rồi publish file; chỉ ghi kết quả hoàn tất sau khi file đã được lưu và hash kiểm tra lại. Resume theo record cuối; bỏ qua thành công chỉ khi mọi file còn tồn tại và hash khớp; lỗi tạm thời/corrupt có thể chạy lại. Journal lỗi phải dừng và báo rõ, không im lặng bỏ dòng.
- Phân biệt `recovered`, `no_bbl`, `unavailable`, `inconclusive`, `unsafe_or_limit`; `no_bbl` chỉ sau khi đọc đầy đủ archive hợp lệ. Tổng hợp theo version và paper, không đếm một paper nhiều lần trong số paper duy nhất.

## Công việc

### 1. Danh sách đầu vào và provenance

Files: `src/benchmark/bbl_recovery.py`, `src/tests/test_bbl_recovery.py`.

- [ ] Viết test cho journal record cuối, record hỏng/thiếu, lọc .bib/.bbl, gộp version trùng qua các run, version khác nhau cùng paper, và hash đầu vào; chạy test thấy lỗi mong đợi.
- [ ] Triển khai `select_candidates(journals)` trả về record ổn định theo ID/version và danh sách run; lưu danh sách và manifest SHA-256. Phát hiện thay đổi đầu vào khi resume, không âm thầm trộn hai tập.
- [ ] Chạy test và so kết quả với 1.847/2.297 trên evidence hiện có; báo chênh lệch nếu journal đã thay đổi.

### 2. Download và trích xuất chính xác .bbl

Files: `src/benchmark/bbl_recovery.py`, `src/tests/test_bbl_recovery.py`.

- [ ] Test archive có nhiều .bbl, .bib cùng .bbl, bibitem, không .bbl, tar/zip hỏng, đường dẫn nguy hiểm, tên trùng, file quá lớn, 404/410 và lỗi mạng. Kiểm thử bằng fixture và client giả, không phụ thuộc arXiv.
- [ ] Dùng HttpClient/RateLimiter của repo để tải đúng `id` và `version`; đọc hết archive hợp lệ và giữ .bbl theo ràng buộc. Ghi hash archive khi đã tải đầy đủ; đặt giới hạn rõ ràng và báo lỗi nếu vượt giới hạn.
- [ ] Chạy test, xác nhận không có cách nào phân loại lỗi tải thành `no_bbl` và mọi file .bbl hợp lệ đều được giữ.

### 3. Lưu trên Drive, resume và báo cáo

Files: `src/benchmark/bbl_recovery.py`, `src/tests/test_bbl_recovery.py`.

- [ ] Test gián đoạn trước/sau publish, journal hỏng, hash sai/file thiếu, rerun idempotent, thay đổi manifest, hai phiên cùng output, và thống kê paper/version. Bảo đảm không phát sinh record thành công trước khi các file đã lưu.
- [ ] Triển khai staging/publish và JSONL theo từng version, verify hash, resume, khóa output, báo cáo CSV/JSON. Khóa cần hướng dẫn xử lý sau khi runtime mất; không tự xóa khóa đang hoạt động.
- [ ] Xác minh dữ liệu trong thư mục Drive riêng có thể khôi phục chỉ từ output và manifest; nguồn gốc 5 journal không bị sửa.

### 4. Notebook và hướng dẫn

Files: `src/notebooks/arxiv_nhom1_bbl_recovery.ipynb`, `docs/huong_dan_khoi_phuc_bbl.md`, `src/tests/test_bbl_recovery_notebook.py`.

- [ ] Tạo notebook: mount Drive, cài phụ thuộc, nhận repo/gói runtime và năm journal; cấu hình output, run-id, giới hạn, RUN_NETWORK; preflight kiểm hash/đếm/đường dẫn/khóa/dung lượng.
- [ ] Thêm cell chạy thử 10 version rồi cell chạy toàn bộ do người dùng bật; một luồng request và hiển thị tiến độ, số đã khôi phục, lỗi và nơi lưu. Hướng dẫn resume sau ngắt, thời gian tối thiểu theo số request thực tế và giới hạn Colab.
- [ ] Hướng dẫn cấu trúc output, trạng thái, kết quả S3 v1 suy luận và kiểm tra M2; không hứa tự cập nhật corpus. Chuẩn bị cách đóng gói code và journal lên Drive có thể lặp lại, ghi SHA-256.
- [ ] Kiểm tra schema notebook, compile code cells, chạy preflight offline với năm journal thực và smoke test với client giả; không mặc định gọi mạng.

### 5. Nghiệm thu

- [ ] Chạy test module, downloader, notebook và bộ test repo phù hợp; đọc kết quả và rà diff.
- [ ] Chạy thử live có kiểm soát trên 10 version ở output mới riêng; đối chiếu .bbl, hash, phiên bản và khả năng M2 đọc references; báo trường hợp thất bại, không suy rộng 10 mẫu.
- [ ] Xác nhận resume không tải lại file đã xác minh và không sửa corpus/journal gốc. Báo rõ live Colab/Drive chưa được kiểm chứng nếu không có phiên Drive thực.
