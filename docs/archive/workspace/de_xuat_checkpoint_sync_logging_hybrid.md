# Đề xuất cải thiện checkpoint, đồng bộ Drive và logging cho pipeline hybrid

Ngày phân tích: 02/11/2026. Cơ sở là [kết quả smoke 1.000 ID đầu của Đăng](../debug/bench_results_hybrid_dang1000/) và code revision `8480271e8dde2a2a6bb3e99f85cc7cc749e1cfb4`. Đây là đề xuất; chưa sửa pipeline hay khẳng định đã tăng tốc.

## Kết quả liên quan đến ưu tiên

- Run sample `2604.20535`–`2604.21534`, `CHUNK_SIZE=100`, `CHECKPOINT_S=300`, Drive. Session sampler ghi **4.453,87 giây** (1 giờ 14 phút 13,87 giây), không bao gồm tải bulk đã chuẩn bị trước, setup môi trường hay xuất/tải evidence cuối. 30 profiler child cộng **4.092,08 giây**; không cộng số này vào session wall vì đã nằm trong session.
- QA hiện tại ghi 1.000/1.000 paper hoàn tất theo định nghĩa trạng thái đầu cuối; 1.395/1.395 version được ghi nhận gồm 1.290 `ok`, 100 `no_tex`, 5 `unavailable` sau HTTP 404. Đây không có nghĩa cả 1.395 version đều có source TeX. Danh sách 404: `2604.20668v2`, `2604.21023v2`, `2604.21038v2`, `2604.21231v2`, `2604.21294v6`.
- Có 700 version lấy từ S3, đều gắn `inferred_snapshot_bundle_timestamp`; đây là suy luận theo snapshot và timestamp bundle, không phải bằng chứng khẳng định tuyệt đối version. 695 version còn lại được ghi nhận qua arXiv. References: 998 `ok`, 2 `not_found` (`2604.21318`, `2604.21531`); `not_found` được QA hiện tại chấp nhận là trạng thái đầu cuối, không phải reference metadata đầy đủ.
- Có 70 checkpoint event: 1 initial, 30 prelaunch, 30 post-chunk, 7 periodic, 1 final-reports và 1 final. Tổng thời gian được ghi: **28,75 giây periodic** và **211,09 giây external**; cộng khoảng **239,84 giây** theo event, xấp xỉ 5,4% session wall. Periodic đã nằm trong profiler child; không cộng lần nữa vào 4.092,08 giây. Đây là thời gian event được ghi, không phải kết luận rằng tối ưu sẽ tiết kiệm được toàn bộ 239,84 giây.
- 10 profile pha S3 cộng **72,64 giây**; 10 profile pha fallback cộng **73,16 giây**; 10 profile pha multi-version cộng **3.946,28 giây**. Pha fallback của run này không download source vì tất cả 700 source S3 đã terminal, nhưng vẫn xử lý references: không được xóa pha mà không thay bằng cơ chế hoàn thành references và đo tương đương.
- Theo báo cáo `references_stats.csv`, có 95 phản hồi 429 từ arXiv, 10 từ Semantic Scholar. `benchmark_summary.csv` ghi **470,1 giây backoff** trên 87 lần chờ từ các lỗi trong run; không cộng phần này vào wall vì đã bao gồm trong thời gian chạy. Pha multi-version chiếm phần lớn profile wall, vì vậy cần nghiên cứu 429 song song với sync, trong giới hạn chính sách arXiv.
- Quét và kiểm tra bundle S3/index ghi **103,89 giây**, thuộc session; không tính lại như thời gian bổ sung. Toàn bộ bulk S3 tải trước không nằm trong phép đo này. Thông số Drive bundle và nguồn được ghi riêng khi báo cáo.

Nguồn: [coverage](../debug/bench_results_hybrid_dang1000/work/coverage.json), [timing audit](../debug/bench_results_hybrid_dang1000/work/timing_audit.json), [báo cáo benchmark](../debug/bench_results_hybrid_dang1000/book_csv/benchmark_summary.csv), [corpus](../debug/bench_results_hybrid_dang1000/book_csv/corpus_summary.csv), [requests](../debug/bench_results_hybrid_dang1000/book_csv/references_stats.csv), [checkpoint events](../debug/bench_results_hybrid_dang1000/work/checkpoint_events.jsonl), [version journal](../debug/bench_results_hybrid_dang1000/work/versions.jsonl).

## 1. Ưu tiên: checkpoint nhất quán khi file đang được ghi

**Vấn đề:** [Checkpoints._save](../CodeRepo/src/benchmark/checkpoints.py) quét các file trong `work/`, tính hash và sao chép. `profile_samples.csv`, `console.log`, `run.log` hoặc journal có thể tiếp tục được ghi trong lúc đó. Lần chạy Drive cũ từng báo lỗi xác minh `profile_samples.csv`; việc source đổi trong lúc hash/copy là giả thuyết hợp lý, chưa được chứng minh là nguyên nhân duy nhất. Run hybrid này không ghi lỗi cleanup.

**Đề xuất:** tạo bản chụp nhất quán của file mutable trước khi tính hash/copy, hoặc tách các đoạn log immutable theo checkpoint; các bản đo còn đang ghi phải được xử lý có quy tắc và vẫn được lưu đủ để audit. Không loại bỏ dữ liệu đo để làm checkpoint trông thành công. Giữ cơ chế commit `INDEX.json` cuối và kiểm tra bản restore.

**Đánh đổi:** thêm thao tác chụp file hoặc metadata và có thể tăng disk local. Cần đảm bảo snapshot có ranh giới dòng hoàn chỉnh, không làm lộ version đang trích xuất và không báo checkpoint đầy đủ khi thiếu phần bắt buộc.

**Kiểm chứng:** test ghi `profile_samples.csv` liên tục trong lúc checkpoint; giả lập ngắt giữa hash, copy, verify và publish index; restore vào thư mục trống và so sánh source, metadata, references, empty `vN/`, journal và telemetry. Smoke Colab với checkpoint định kỳ và chủ động dừng runtime khi phù hợp.

## 2. Giảm công việc sync lặp lại

**Vấn đề:** code đã tránh sao chép lại source bất biến có trong index, nhưng mỗi checkpoint vẫn đọc state, quét `work/`, hash các file ứng viên và đối chiếu nhiều đường dẫn. Chưa có đo phân rã quét/hash/copy/verify nên chưa xác định phần nào chiếm thời gian.

**Đề xuất:** trước hết thêm measurement cho scan, hash, copy, verify, số file và byte. Sau đó thử theo dõi tập file thay đổi và dùng lại metadata của source bất biến; vẫn kiểm tra tính toàn vẹn những file mới và file cần sửa. Chỉ bỏ checkpoint trùng khi chứng minh được không có state/measurement mới cần publish.

**Kiểm chứng:** so sánh số file, byte và thời gian theo giai đoạn trên cùng phạm vi/config; kiểm thử restore sau lỗi giữa hai checkpoint và so sánh QA. Không dựa vào `mtime` đơn lẻ để khẳng định file toàn vẹn.

## 3. Điều chỉnh nhịp checkpoint theo pha

**Vấn đề:** `CHECKPOINT_S=300` được xét tại ranh giới sau khi một version xử lý xong; không phải giới hạn tuyệt đối 300 giây từ dữ liệu gần nhất đến khi dữ liệu được bảo vệ. File lớn, request, backoff và thời gian sync có thể kéo dài khoảng này. Ngoài periodic còn có prelaunch/post-chunk và final.

**Đề xuất:** thử ngưỡng kết hợp theo thời gian và số version terminal, có cấu hình theo S3 và arXiv; giữ checkpoint sau chunk. Bước đầu so sánh các cấu hình trên sample giống nhau, báo rõ thời gian sync và lượng version/time kể từ checkpoint thành công gần nhất. Không suy ra số paper mất tối đa từ ngưỡng thời gian.

**Kiểm chứng:** chủ động dừng trong lúc trích một version, sau journal, trong sync và trước publish; khôi phục và đo phần phải làm lại. Kiểm tra quota/Drive readback và toàn vẹn trong mỗi ca.

## 4. Logging rõ theo pha và trạng thái

**Đề xuất:** in tiến độ kiểm tra MD5/index theo bundle (tên, thứ tự, thời gian, số ID tìm thấy); mỗi 10 paper ghi pha và số S3 inferred, S3 cần fallback, arXiv terminal, lỗi; ghi checkpoint bắt đầu/kết thúc, duration, byte/file, generation và thời điểm thành công gần nhất. Tách source `ok`, `no_tex`, `unavailable`, `failed` khỏi references `ok`, `not_found`, `failed`. Giữ log chi tiết trong file, không in secret.

**Lưu ý:** số `PAPER_PROGRESS` hiện đếm paper có source terminal của từng chunk, không chứng minh có TeX hay references hoàn tất. `S3 inferred` phải được công bố là suy luận. Log được in không thay cho checkpoint thành công hoặc QA.

**Kiểm chứng:** chạy fixture có S3 thành công, fallback, 404, retry, S2 not_found và checkpoint fail; đối chiếu log với journals/coverage và đảm bảo không ghi trùng khi resume.

## 5. Giảm overhead điều phối sau khi đo

**Quan sát:** run hiện khởi chạy 30 child cho 10 chunk ở mỗi pha S3, fallback và multi-version; có 60 checkpoint prelaunch/post-chunk. Pha fallback vẫn làm references, dù `versions_processed_this_run=0`.

**Đề xuất:** đánh giá tăng kích thước chunk ở pha S3 hoặc tổ chức references theo nhóm độc lập, sao cho không lặp discovery/source và vẫn tôn trọng thứ tự toàn bộ nhóm chỉ-v1 trước multi-version. Có thể nghiên cứu gộp sync quanh các ranh giới phù hợp, nhưng không được bỏ cơ chế lưu intent/khôi phục. Giữ limiter arXiv; không tăng số kết nối hoặc vượt chính sách.

**Kiểm chứng:** benchmark cùng 1.000 ID và snapshot, so sánh session wall, phase wall, S3/arXiv request, checkpoint, QA, RAM/disk và số lần phải làm lại sau ngắt. Biến động 429/mạng có thể lấn át cải thiện; cần nhiều run hoặc giải thích điều kiện, không kết luận nhân quả từ một lượt.

## Giới hạn và thứ tự thực hiện

1. Hoàn thiện/kiểm thử checkpoint nhất quán và restore trước khi thay đổi chu kỳ sync.
2. Bổ sung breakdown và log; chạy smoke tương đương để chọn tối ưu theo bằng chứng.
3. Tối ưu quét/copy và điều phối; so sánh với baseline cũ trên cùng ID và điều kiện gần nhất có thể.
4. Xem xét xử lý 429 theo chính sách dịch vụ; không dùng proxy hoặc tăng đồng thời để vượt giới hạn.

Run sample này không thay thế benchmark full 20.000 ID. Tính đầy đủ cuối cùng phải nêu rõ 404, no_tex, references not_found, version suy luận từ S3, snapshot và phạm vi measurement. Run hiện tại pin revision; không sửa cấu hình/revision để ép resume hoặc trộn số liệu khác phiên bản.
