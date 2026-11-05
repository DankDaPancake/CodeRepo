# Hướng dẫn chạy crawler hybrid S3 + arXiv trên Colab

Notebook: [`src/notebooks/arxiv_nhom1_s3_arxiv_benchmark.ipynb`](../src/notebooks/arxiv_nhom1_s3_arxiv_benchmark.ipynb). Mở [notebook trên main bằng Colab](https://colab.research.google.com/github/hcmus-arxiv-nhom1/CodeRepo/blob/main/src/notebooks/arxiv_nhom1_s3_arxiv_benchmark.ipynb). Notebook pin `CODE_REF` theo revision triển khai: không đổi revision khi resume.

## 1. Chuẩn bị

- Chọn runtime **CPU**, dùng tài khoản Google có quyền vào thư mục Drive của nhóm. Điều phối để chỉ có một crawler arXiv hoạt động tại một thời điểm: limiter hiện chạy trong từng runtime, chưa giới hạn chung nhiều máy.
- Snapshot đã lọc cho 20.000 ID ở `MyDrive/arxiv-inputs/arxiv-assigned-20000.jsonl`; notebook kiểm tra SHA-256 trước khi dùng. Đường dẫn có thể chỉnh ở `SNAPSHOT_DRIVE_PATH`.
- Bulk có sẵn ở `MyDrive/arxiv-s3/packages/`; manifest của lần tải ở `MyDrive/arxiv-s3/runs/20261102-135934/manifest.xml`. Nếu folder được chia sẻ nằm nơi khác, thêm shortcut vào My Drive hoặc sửa `S3_BUNDLE_DIR` và `S3_EXISTING_MANIFEST` cho đúng đường dẫn mount. Không xóa hay sửa bulk trong lúc chạy.
- Tạo sẵn thư mục kết quả `MyDrive/arxiv-nhom1/`. Nếu đây là thư mục mới chưa có `TEAM.json`, đặt `INITIALIZE_TEAM_FOLDER = True` ở cell đầu, chạy lại cell cấu hình và cell tạo `BenchmarkConfig`; sau khi khởi tạo có thể trả về `False`. Không thay `TEAM_ID` khi resume.
- Nếu chỉ dùng manifest và bulk đã có, giữ `S3_DOWNLOAD = False`: không cần AWS key hoặc request S3. Nếu cần tải bundle còn thiếu, thiết lập `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` và, chỉ với credentials tạm, `AWS_SESSION_TOKEN` trong Colab Secrets 🔑; bật Notebook access. S3 Requester Pays có thể phát sinh phí. Không đưa key vào notebook, repo, log hoặc chat.
- Semantic Scholar dùng `S2_API_KEY` trong Colab Secrets nếu nhóm có key; thiếu key có thể dẫn tới chậm/429. `ARXIV_CONTACT_EMAIL` là cấu hình liên hệ tùy chọn.

## 2. Chạy smoke 1.000 ID của Đăng

Mở notebook từ GitHub, khởi động runtime mới và chạy từng cell từ đầu. Kiểm tra các thông số ở cell đầu:

```python
MODE = "sample"
RUN_ID = "m1-hybrid-dang-0000-0999-<ten-run-moi>"
MEMBER = "dang"  # chọn dang, thien, tien hoặc hieu
RANGES = (MEMBER,)
OFFSET = 0
COUNT = 1000
CHUNK_SIZE = 100
WITH_REFERENCES = True
CHECKPOINT_S = 600
RESUME = False
```

Mỗi thành viên chọn `MEMBER` là `dang`, `thien`, `tien` hoặc `hieu`; đặt `RUN_ID` mới tương ứng với tên và khoảng offset, chưa tồn tại trên Drive. `RANGES` được tạo tự động từ `MEMBER`. Đây là sample, không phải final benchmark. `COUNT` và `OFFSET` áp dụng cho từng range được chọn. Snapshot mẫu cho phạm vi này có 700 paper chỉ-v1 và 300 paper nhiều version; phân loại sẽ được tính lại từ file snapshot thực tế.

Trong cell cấu hình S3, ban đầu giữ:

```python
PREPARE_S3 = True
S3_DOWNLOAD = False
RUN_CRAWL = False
```

Chạy lần lượt đến cell chuẩn bị S3: kiểm tra số paper từng nhóm, các bundle ứng viên, ID không nằm trong khoảng manifest và đường dẫn Drive. Notebook in kích thước manifest và kích thước thực; hai số có thể khác. Trước khi index, code tính MD5 của **từng bundle** và từ chối checksum không khớp. Nếu bundle thiếu, chuẩn bị lại hoặc bật tải sau khi đã xem khối lượng và chi phí; không tự đổi tên `.part` thành `.tar`.

Sau khi kiểm tra, đổi `RUN_CRAWL = True`, chạy lại cell cấu hình S3, rồi chạy cell **Crawl, checkpoint and benchmark**. Không cần chạy lại bước tải. Theo dõi các pha `s3` → `fallback` → `multi_version` và thông báo checkpoint. Không dùng **Run all** nếu chưa muốn bắt đầu crawl.

## 3. Pipeline và ý nghĩa hoàn tất

Pipeline phân nhóm theo snapshot, thử S3 cho toàn bộ paper chỉ có v1, lấy bù qua arXiv khi thiếu/không phù hợp, sau đó lấy từng version của nhóm nhiều-version qua arXiv. References Semantic Scholar được xử lý trong các lượt tương ứng. Nếu một chunk còn thiếu sau retry, nó được ghi nhận và pipeline tiếp tục; kiểm tra báo cáo cuối.

S3 không gắn nhãn version cho source. Nhóm đã chọn **suy luận v1** khi snapshot chỉ ghi v1 và timestamp bundle muộn hơn ngày v1 ít nhất một ngày. Journal ghi `version_evidence=inferred_snapshot_bundle_timestamp`; đây không phải đối chiếu byte với `/src/idv1`, và phụ thuộc tính đầy đủ của snapshot, đúng ID và thời điểm bundle. Ngày snapshot và bundle phải được nêu khi báo cáo.

Thanh tiến độ đếm paper có source đạt trạng thái đầu cuối trong từng pha/chunk; mẫu số sau discovery là số paper tìm thấy; `no_tex` và `unavailable` có thể được tính, còn references và checkpoint theo dõi riêng. Log chi tiết vẫn nằm trong `work/profile/.../console.log`. `complete=true` theo QA hiện tại không đồng nghĩa mọi version có TeX hoặc mọi reference có metadata. Kiểm tra `work/versions.jsonl`, `work/qa_source.csv`, `work/qa_report.csv`, `book_csv/corpus_summary.csv` và `coverage.json`; phân biệt 404/unavailable, no_tex, failed và references not_found. `final_complete=false` là bình thường đối với sample.

Kết quả raw cho M2 nằm ở `MyDrive/arxiv-nhom1/runs/<RUN_ID>/data/corpus/`, theo cây `<paper-id>/metadata.json`, `references.json`, `vN/`. Checkpoint có index; sau khi bị ngắt nên restore generation đã xác minh trước khi coi mirror là trạng thái đã commit.

## 4. Kiểm tra, export và rescue

Sau khi cell crawl chạy xong, chạy các cell **Inspect completion and measurements** và **Export and download benchmark evidence**. Gửi `bench_results.zip` cùng phạm vi, run ID, revision và cấu hình cho người phân tích. File ZIP chứa report/log, không bao gồm toàn bộ corpus raw.

`wall_time_e2e` là thời gian session được đo và có thể gồm sync/index, nhưng không gồm chuẩn bị/tải bulk S3, setup, tải evidence và thời gian nghỉ giữa các phiên. Report thời gian chuẩn bị bulk riêng và không cộng các khoảng chồng lấp. Xem `timing_audit.json` / `measurement_audit.json` để biết dữ liệu đo có hoàn chỉnh không; mẫu không thay thế benchmark 20.000 ID. Xem thêm [measurement contract](measurements.md).

Khi gặp lỗi, **không reset runtime ngay**: chạy cell **Rescue local data after an error**, lưu file rescue và traceback trước. Nếu Drive sync lỗi, giữ dữ liệu local và kiểm tra generation đã publish; không tùy tiện xóa hoặc ghi đè `INDEX.json`.

## 5. Resume sau timeout

Chỉ resume khi runtime trước đã dừng. Mở notebook trong runtime mới, giữ nguyên `RUN_ID`, `MODE`, ranges, offset/count, chunk/checkpoint, storage, snapshot và revision. Đặt `RESUME = True`; dùng chính manifest của run trong `S3_EXISTING_MANIFEST`, các bundle đã dùng vẫn phải tồn tại. Chạy setup và prepare S3, rồi bật `RUN_CRAWL = True` và chạy crawl. Không chạy đồng thời hai runtime cùng run ID.

Không thay code/config/manifest để vượt kiểm tra resume. Run được tạo trước đó tiếp tục dùng revision đã lưu; fix mới cần một run ID mới. Hard timeout có thể làm mất phần công việc sau checkpoint thành công cuối và phần đo cuối chưa kịp ghi, nên timing audit có thể chỉ là cận dưới.

## 6. Chuẩn bị full benchmark

Sau khi xác nhận cách dùng S3 được chấp nhận cho M1 và smoke/resume đạt yêu cầu, tạo run ID mới, dùng `MODE = "final"`, đủ cả `RANGES = ("thien", "tien", "hieu", "dang")`, `OFFSET = 0`, `COUNT = None`, `WITH_REFERENCES = True`. Kiểm tra đủ dung lượng Drive, 20.000 ID và toàn bộ bundle ứng viên. Benchmark cuối phải bao phủ trọn tập được giao; kiểm tra cả coverage và tính đầy đủ measurement trước khi báo cáo.
