# Chẩn đoán smoke Đăng 100 ID — 31/10/2026

**Kết luận: 25 phút 31 giây được dùng để chờ discovery thất bại; chưa có request tải source nào.** Không thể dùng lần này để kết luận throughput download/extract giảm so với smoke 200 trước.

Run: `m1-smoke-dang-100-02`, implementation `8310f7e`, 100 ID `2604.20535`–`2604.20634`, references bật, chunk 100. Phân tích offline từ ZIP cứu hộ; không sửa dữ liệu gốc và không gọi arXiv.

## Timeline từ run.log (UTC)

| Khoảng | Sự kiện |
| --- | --- |
| 03:59:13–04:00:12 | Hai request arXiv API discovery đều trả HTTP 429; khoảng 59 giây. |
| 04:00:12–04:10:46 | OAI fallback ID `2604.20535`: 5 lần read timeout 120 giây; hơn 10 phút. |
| 04:10:46–04:20:20 | ID `2604.20536`: 4 timeout và lần cuối HTTP 503; hơn 9 phút. |
| 04:20:20–04:24:23 | ID `2604.20537`: thêm 2 timeout; vẫn đang discovery khi run dừng khoảng 04:24:41. |

Tổng log có 11 ReadTimeout, 2 response 429, 1 response 503 và 75,3 giây backoff được yêu cầu. Backoff đã nằm trong wall time; không cộng lại. Phần lớn thời gian là chờ phản hồi mạng. Chưa có bằng chứng để khẳng định lý do server từ chối hoặc nguồn gốc mất marker Drive.

## Vì sao 0 paper complete?

- `discovery.jsonl`: 0 byte; `versions.jsonl`: 0 byte.
- `paper_events.jsonl`: chỉ 100 event `start`, không có event discovered/version/complete.
- `data/corpus/` rỗng, output 0 byte; không có metadata, TeX/Bib hay references để tiếp tục từ run này.
- `run.log` không có request `/src/`. Vì discovery chưa xong, pipeline chưa khởi động bước tải source và references.
- Cả batch discovery chỉ ghi metadata/journal sau vòng fallback. Crawler mới xử lý lỗi của vài ID đầu và chưa hoàn tất vòng này.

## Nút thắt trong code đã xác định

`oai_get_record()` gọi `client.get(url)` với mặc định chung: read timeout 120 giây, tối đa 5 attempts. Khi API từ chối một batch 100 ID, discovery chuyển sang OAI tuần tự theo ID. Một ID OAI không phản hồi có thể tiêu tốn hơn 10 phút; chưa có budget tổng hoặc cơ chế dừng sớm khi endpoint lỗi liên tiếp. Đây là đường chờ quá dài trong tình trạng endpoint không phục vụ được, không phải phép đo CPU/extraction.

## SHIFT và tình trạng evidence

Session summary và bản staging có đủ 1.529 resource samples, wall 1.531,106 giây, peak RSS khoảng 183,1 MB (gồm notebook/runner baseline). Ba checkpoint events initial/prelaunch/final chỉ tổng cộng khoảng 0,162 giây; không có checkpoint định kỳ theo version vì chưa hoàn tất version nào.

Điểm cần sửa nhận định trước: **evidence của lần cụ thể này có final session summary và `shift_released=true`**, tức finalization đã chạy. Vì vậy không thể quy lỗi lần này hoàn toàn cho `shift.close()` che exception. Traceback thiếu marker phù hợp với lỗi khi kiểm tra SHIFT trong lúc đợi child, sau đó marker đọc được lại khi cleanup; đây là suy luận từ control flow, không chứng minh ai/cái gì làm file biến mất. Không có log heartbeat/marker đầy đủ để kết luận FUSE, mất mount hay tác nhân khác.

Chunk không có `profile_summary.json`, `time_v.log` rỗng và `timing_complete=false`. Session measurement đầy đủ không biến chunk thất bại thành benchmark thành công. `avg_paper_time=15,31 s` chỉ là wall / 100 ID được yêu cầu của một attempt thất bại; không được trình bày như tốc độ hoàn tất paper.

## Hành động tiếp theo

### Đối chiếu với smoke PR25

Đã so sánh implementation `6c8c2b3` của smoke 200 với `8310f7e` của run lỗi: `discovery.py`, `config.py`, `ratelimit.py` có Git blob giống hệt nhau. HTTP client chỉ đổi công thức đo elapsed, không đổi request/retry/timeout. URL discovery đầu tiên cho cùng 100 ID giống hệt nhau; hai run đều không có metadata cache. Python 3.13.18, requests 2.32.4, urllib3 2.5.0, certifi 2026.10.23 và lxml 6.1.3 cũng giống nhau.

Smoke trước có bốn response API HTTP200, discovery hai chunk lần lượt 3,7 và 3,9 giây; không vào OAI. Run hiện tại nhận HTTP429 ngay request discovery đầu tiên rồi gặp OAI timeout/503. Sự khác biệt phản hồi đã kích hoạt nhánh fallback chờ rất lâu vốn đã tồn tại trong PR25. Không có log IP/response headers đầy đủ để khẳng định nguyên nhân HTTP429 là IP Colab, mức tải/rate-limit phía dịch vụ hay yếu tố khác. Rollback riêng discovery về PR25 không loại bỏ nhánh chờ này.

### Ưu tiên

1. Giữ run này như incident evidence. Không có corpus hoàn tất để resume và tiết kiệm tải source; resume hiện tại sẽ quay lại discovery.
2. Trước khi chạy mẫu lớn, kiểm tra discovery của 1 ID trên chính runtime Colab. Nếu API vẫn 429 và OAI vẫn timeout/503, dừng thử lớn; không tăng workers hoặc giảm request gap để vượt tình trạng này.
3. Sửa discovery để có timeout/retry riêng cho metadata, budget tổng và dừng sớm sau lỗi endpoint liên tiếp. Giữ các ID lỗi ở trạng thái retryable; không coi chúng là paper không tồn tại hoặc đã crawl xong.
4. Sau khi metadata/source truy cập được, smoke rất nhỏ rồi mới tăng lên 100/200. Fix phục hồi SHIFT ở PR27 vẫn hữu ích nhưng không chữa endpoint discovery không phản hồi.
5. Kaggle snapshot hoặc cache metadata từ run trước đáng đánh giá như nguồn discovery thay thế. Hiện `--snapshot` chỉ bổ sung thông tin version date và vẫn gọi API/OAI; chưa phải chế độ discovery offline. Cần kiểm tra đủ ID, version, ngày và provenance. Dùng cache phải công bố warm start, không gộp vào cold benchmark như thể discovery miễn phí.
