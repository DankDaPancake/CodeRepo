# Rà soát test trên main — 9e6470b

Phạm vi: `CodeRepo/src/tests`, 27 file test, 216 hàm test; pytest thu thập 244 case sau parametrization. Không sửa source/test, không commit hoặc tạo PR trong lượt rà soát.

Kiểm chứng: `python -m pytest -q --durations=15` → **244 passed in 18.15s**. So sánh AST không thấy hai hàm test có body giống hệt; các đề xuất dưới đây dựa trên kịch bản và assertion, không chỉ độ giống văn bản.

## 1. Test có thể bỏ

`test_run_pipeline_queue.py:158` — `test_trial_data_paths_are_distinct` chỉ assert hai đường dẫn bên trong `tmp_path` mới chưa tồn tại. Không gọi hàm sản phẩm và cũng không kiểm tra hai đường dẫn khác nhau. Test vẫn pass khi logic tạo đường dẫn của ứng dụng sai. Nên bỏ, hoặc thay bằng kiểm tra đầu ra của hàm thật nếu đường dẫn trial còn là một yêu cầu.

## 2. Bốn cặp có thể gộp, giữ toàn bộ assertion

| Vị trí | Hai test | Lý do và cách gộp |
|---|---|---|
| `test_discovery.py:179`, `:203` | `test_discover_survives_malformed_api_response` + `test_discover_counts_a_failed_api_batch` | Cùng mô phỏng batch đầu XML hỏng rồi API tốt. Một lần gọi `discover()` có thể assert cả `found`, `api_failed_batches == 1`, `oai_fallbacks == 0`. |
| `test_run_pipeline.py:143`, `:170` | `test_lock_is_released_when_a_run_stops_on_an_error` + `test_run_stopped_by_blocked_error_is_marked_interrupted` | Cùng BlockedError sau một download. Assert `interrupted` ngay sau lỗi, rồi chạy lại để xác nhận lock được nhả. |
| `test_run_pipeline.py:178`, `:213` | `test_failed_version_is_reported_and_retried` + `test_versions_log_keeps_one_record_per_version` | Cùng một version trả 503 rồi retry thành công. Đưa assertion số dòng journal vào test retry đang có, tránh chạy lại hai lượt crawl giống nhau. |
| `test_benchmark_runner.py:101`, `:172` | `test_checkpoint_survives_kill_and_ignores_stray_upload` + `test_checkpoint_copies_land_directly_under_remote_mirror` | Cùng seed một version rồi save. Có thể gom các assertion raw source/metadata/không ZIP vào test round-trip có file temp. Đổi tên để mô tả round-trip và bỏ qua temp; test này chưa giả lập ngắt giữa các thao tác replace và cập nhật index. |

Nếu chỉ làm bốn phép gộp và bỏ test đường dẫn, số case dự kiến giảm từ 244 xuống 239. Đây là ước tính về số case; cần chạy lại sau thay đổi để xác nhận. Giữ assertion hiện có không đồng nghĩa đã chứng minh đầy đủ coverage bằng mutation testing.

## 3. Có thể parametrization; giữ nguyên các tình huống

- `test_scheduler.py:6`, `:20`, `:26`: seed mặc định, backlog cao và worker không tiến triển có setup/assert cùng dạng. Parametrize `queue_depth`, `worker_progress`, `expected`, đặt ID rõ ràng cho từng case. Giữ riêng test tăng batch nhiều bước và giới hạn prefetch vì có chuỗi trạng thái.
- `test_extract.py:73`, `:80`: gzip có/không tên trong header có thể dùng một test tham số hóa. Vẫn kiểm tra đúng tên file, nội dung và `has_tex` ở cả hai case.
- `test_http_client.py:175`, `:189`: server bỏ qua Range và Content-Range sai có thể chung test restart với response khác nhau. Giữ assertion reset Range và không nối trùng bytes cho cả hai case.

Parametrization giảm code lặp, không chủ đích giảm số case hay số nhánh cần kiểm tra. Không nên nhét các kịch bản exception và happy path khác assertion vào một test lớn nhiều `if`.

## 4. Những test cần mạnh hơn, không nên coi là đã bảo vệ đủ hành vi

### Retry-After của Semantic Scholar đang pass giả

`test_references.py:71` dùng `sleep=(sleeps or []).append`. Khi caller truyền `sleeps=[]`, helper chọn một list mới; test ở dòng 105 không nhận được các lần sleep. Assertion `all(s >= 2 for s in sleeps)` trên list rỗng trả về True.

Đã chạy lại chính FakeS2/crawl của test và quan sát:

```text
requests=3, ok=1, captured_sleeps=[], all_ge_2_assertion=True
```

Nên phân biệt `None` với list rỗng trong helper và assert cả số lần lẫn giá trị sleep. Test này cần giữ vì S2Client là implementation khác với HttpClient của arXiv.

### Một số tên test khẳng định nhiều hơn assertion

- `test_run_pipeline_queue.py:85`, `test_adaptive_scheduler_is_used_in_queue_mode`: chỉ có một ID và assert số job bằng 1, chưa quan sát scheduler được gọi hoặc quyết định kích thước batch. Test mixed Tex/no-Tex ở dòng 101 đã bao phủ phần xuất một job. Nên thay test yếu bằng spy/recording scheduler để kiểm tra việc tích hợp, thay vì chỉ xóa rồi coi coverage scheduler đã đủ.
- `test_parser_worker.py:69`, `test_worker_cli_generates_a_unique_default_consumer`: chỉ tạo một consumer và assert không rỗng, chưa chứng minh unique giữa hai worker.
- `test_benchmark_runner.py:181`, `test_all_checkpoint_phases_have_durable_duration_events`: chỉ gọi `phase='final'`. Nên đổi tên đúng phạm vi hoặc parametrization các phase được hỗ trợ.
- `test_benchmark_runner.py:166`, `test_restore_rejects_unsafe_archive_path`: chỉ gọi `safe_name()`, không gọi `restore()`, và raw checkpoint hiện không phải archive. Giữ test predicate với tên đúng; nếu muốn bảo vệ restore phải có case index chứa đường dẫn không an toàn.

## 5. Những chỗ nhìn giống nhưng nên giữ

- `test_worklock.py` kiểm tra primitive khóa; `test_run_pipeline.py` và `test_producer.py` kiểm tra từng entrypoint thực sự sử dụng/nhả khóa. Các test tầng dưới không phát hiện được entrypoint quên lấy khóa.
- `test_http_client.py:133` và `:146`: một case EOF ngắn hơn Content-Length, case kia ném ChunkedEncodingError. Cùng kết quả resume nhưng là hai cơ chế lỗi khác nhau.
- Extractor no-Tex, pipeline no-Tex và crawler worker no-Tex: lần lượt kiểm tra phân loại/lọc file, trạng thái journal và quyết định publish/ack. Giữ các tầng này.
- `test_measurements.py` kiểm tra thu thập/durability/session report; `test_stats.py` kiểm tra CSV xuất ra và không báo thời gian chính xác khi thiếu telemetry. Gộp qua hai tầng sẽ làm chẩn đoán lỗi khó hơn.
- `test_profiler.py` theo dõi cây process của chunk; `test_measurements.py` bao gồm runner/kernel và session. Không phải cùng phạm vi resource.
- Parser worker và crawler worker tuy có nhiều fake queue giống nhau nhưng chạy code sản phẩm khác; không bỏ test ack/retry của một bên.

## 6. Dọn cấu trúc có ích hơn gom file test

`test_benchmark_runner.py` đang chứa cả checkpoint, Shift, config và orchestration. Nếu dọn, tách checkpoint sang `test_checkpoints.py` và các helper dùng chung sang `helpers.py`/fixture rõ ràng. Hiện nhiều file import `FakeArxiv`, `client_for`, `seed_version` hoặc `monitor` trực tiếp từ file test khác; tách helper sẽ giảm phụ thuộc khi đổi tên/xóa test.

Không cần gom 27 file thành vài file lớn. Thời gian suite hiện chỉ khoảng 18 giây; phần chậm chủ yếu là coordinator concurrency/lease thật, profiler subprocess và shutdown server (~0.5 giây cho nhiều fixture). Gộp test logic nhanh sẽ cải thiện bảo trì nhiều hơn cải thiện tốc độ. Những test Redis/queue/parser phục vụ nhánh khác hoặc M2 vẫn có giá trị; việc không nằm trong đường crawl Colab hiện tại không phải lý do để xóa.

Ưu tiên: sửa assertion Retry-After; bỏ test đường dẫn vô nghĩa; gộp bốn cặp có cùng kịch bản; sau đó mới parametrization và tổ chức helper. Các lỗi checkpoint/pin notebook đã phát hiện ở lượt trước cần regression test phù hợp; dọn test trùng không tự xử lý những lỗ hổng đó.
