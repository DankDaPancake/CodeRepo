# Đối chiếu tiêu chí M1 — 31/10/2026

**Kết luận: chưa đủ để nộp final.** Pipeline đã có phần lớn chức năng và phép đo cần thiết; minh chứng hiện tại mới là smoke 200/20.000 ID (1%). Book còn dùng CSV giả. Không thể quy đổi thành điểm hoặc phần trăm hoàn thành vì đề không công bố trọng số/thang điểm.

Đối chiếu `M1_requirements.md`, code local `CodeRepo@9b9cfcd`, Book local `arxiv-book@6527a68` và `bench_results/`. Smoke chạy implementation `6c8c2b3`. Có xét thêm trả lời của thầy: final benchmark phải chạy toàn bộ dữ liệu được giao; Book có hai chương M1/M2.

## Năm tiêu chí chấm điểm

| Tiêu chí | Đã có | Còn thiếu để nộp |
| --- | --- | --- |
| Report / Jupyter Book | Methodology, công cụ/thư viện, tối ưu và giới hạn; notebook sinh bảng/biểu đồ từ CSV lúc build; hai nhóm chương M1/M2; notebook Colab được nhúng và bỏ qua execution khi build. | Thay CSV giả bằng kết quả thật của full run; bổ sung phân tích, raw logs và liên kết evidence; cập nhật mô tả sample cũ. Kiểm tra lại GitHub Pages sau cập nhật. |
| Source code | Repo riêng, `src/requirements.txt`, README hướng dẫn môi trường và cấu hình; pipeline đã chạy được trên Colab với smoke. Không thấy corpus được Git theo dõi. | Sửa lỗi đo thời gian đã xác nhận; kiểm tra lại code revision được notebook pin trước final. Lần đối chiếu này không chạy lại toàn bộ test suite. |
| Discovery & Crawling | Discovery API/OAI, tải tất cả phiên bản được discovery ghi nhận, references, retry/rate limiter, Range recovery, checkpoint. Sample có 200 paper hoàn tất, 279 phiên bản. | Full crawl toàn bộ 20.000 ID/all versions; QA và báo cáo ngoại lệ trên toàn bộ tập. Sample không chứng minh coverage của 19.800 ID còn lại. |
| Resulted Data | Data contract và QA; giữ `.tex`/`.bib`, metadata/references, version rỗng có trạng thái. Smoke không có lỗi QA source/reference. | Corpus đầy đủ trên Drive, kiểm tra restore/handoff M2, QA full corpus. Gói evidence không chứa corpus nên lần đối chiếu này không kiểm tra trực tiếp mọi file nguồn. Phân biệt hoàn tất xử lý với tải được TeX. |
| Scraper’s Performance | Smoke Colab CPU có wall time, discovery time, RAM max/mean, disk peak/output, profile samples và `/usr/bin/time -v`. | Benchmark đủ 20.000 ID; chốt phạm vi end-to-end và toàn hệ thống; sửa số đo thành phần; trình bày bottleneck và bằng chứng tối ưu. Chưa có dữ liệu so sánh với nhóm khác để kết luận hiệu suất tương đối. |

## Phép đo theo yêu cầu

| Yêu cầu | Minh chứng smoke | Nhận xét |
| --- | --- | --- |
| Tổng end-to-end / trung bình mỗi ID | Pipeline 1.805,18 s; 9,026 s/ID; session tới final sync 1.811,907 s. | Pipeline chưa gồm các bước ngoài profiler. Báo rõ cả pipeline và session; không gọi riêng tổng chunk là toàn bộ hệ thống nếu loại sync/restore/điều phối. |
| Thời gian từng paper | `papers_stats.csv/process_sec` cộng `total_s` các phiên bản. | Có số đo, nhưng không bao gồm toàn bộ discovery/references/checkpoint theo paper. Cần ghi rõ định nghĩa; không coi trung bình cột này là wall time/ID của hệ thống. |
| Tổng thời gian discovery | 7,6 s. | Đã có cho sample. |
| RAM max / mean | RSS cây tiến trình crawler: 49,4 / 48,0 MB. | Chưa bao phủ parent runner/notebook và profiler; cần xác định các tiến trình thuộc hệ thống và đo nhất quán để đáp ứng “full system”. `time -v` có phạm vi khác, không thay thế tổng RSS hệ thống. |
| Disk peak / output | 40,9 / 40,5 MB trong các thư mục được theo dõi. | Peak là sampled; chưa đại diện toàn bộ đĩa Colab hoặc Drive. Nêu rõ local data/work, temporary spool và các phần bị loại. |
| Số paper / tỷ lệ thành công | Coverage 200/200; 279 version gồm 266 `ok`, 12 `no_tex`, 1 `unavailable`. | 100% hoàn tất xử lý theo contract không có nghĩa 100% tải được TeX. Cần công bố các nhóm riêng. |
| Kích thước trước/sau loại figures | CSV có `size_before_bytes`, `size_after_bytes`. | Có thể tính trung bình theo paper; dữ liệu là kích thước giải nén trước/sau lọc whitelist, không phải cùng một đại lượng với compressed download bytes. Book hiện hiển thị MB; nên kèm bytes như yêu cầu. |
| References trung bình / metadata success | Có `n_refs_total`, `n_refs_meta_ok`, `ref_status`. | Phân biệt tỷ lệ paper lấy được danh sách references với tỷ lệ citation resolve được S2 ID; có S2 ID chưa đảm bảo đủ title/authors/date. Nêu rõ mẫu số và mức đầy đủ metadata. |

## Các điểm cần xử lý trước khi chốt báo cáo

1. **Lỗi thời gian:** `elapsed_s` đã chứa limiter wait, nhưng `download_s` lại cộng `wait_s`; thời gian cộng dồn download 2.504,055 s vượt tổng version 1.790,864 s. Sửa và kiểm chứng trước final. Wall profiler/time-v và `total_s` vẫn dùng được với đúng phạm vi.
2. **Lỗi tỷ lệ thành công tiềm ẩn trong Book:** `ok = n_versions_ok == n_versions` coi paper discovery thất bại (`0 == 0`) là thành công. Cần điều kiện `n_versions > 0`, kèm QA; tách số paper có TeX, version không TeX và unavailable.
3. **Phạm vi benchmark:** tổng wall chunk, thời gian sync ngoài chunk và tổng session là các chỉ số khác nhau. Với nhiều runtime, ghi đầy đủ attempts, restore, session và khoảng nghỉ; không mô tả là một runtime liên tục. Profile thiếu phải được công bố, không tính thành 0.
4. **Book chưa chứa kết quả thật:** trang Performance còn TODO raw logs; Discussion còn nhận xét sample 100 ID chưa có evidence. Khi cập nhật, dùng smoke 200 như sample có provenance, sau đó thay bằng full results trước nộp.
5. **Tối ưu không có ngưỡng thời gian cứng:** đề nói không giới hạn runtime, nhưng hiệu suất vẫn được so sánh. Sample có 90 HTTP 429, 69 lần đứt body và 10 lần tải lại từ đầu; RAM/disk thấp là lợi thế, mạng/retry còn dư địa cải thiện. Không bắt buộc dùng Kaggle, GPU hay S3 để đạt tiêu chí.

## Thứ tự ưu tiên

Sửa độ đúng của số đo và cách tính success → kiểm tra checkpoint/restore thực tế và pin revision → chạy full 20.000 ID trên Colab CPU → QA corpus và timing audit → đưa CSV thật vào Book, bổ sung logs/phân tích → build Book có execute, kiểm tra Pages và nộp hai link công khai trên Moodle.

Đây là đánh giá mức đáp ứng yêu cầu, không phải dự đoán điểm chấm. Chưa xác minh lại Pages đang deploy hay trạng thái công khai của các repo trong lần đối chiếu này.
