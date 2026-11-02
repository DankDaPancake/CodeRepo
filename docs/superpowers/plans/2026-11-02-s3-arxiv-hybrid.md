# Kế hoạch triển khai pipeline S3 + arXiv

**Mục tiêu:** Trên Colab CPU, xử lý trước toàn bộ paper chỉ có v1 theo snapshot bằng source S3 đã chuẩn bị trên Drive, rồi xử lý toàn bộ version của nhóm nhiều version qua arXiv; lưu corpus raw cho M2 và bằng chứng benchmark.

**Kiến trúc:** Một notebook hybrid riêng điều khiển code Python dùng chung với pipeline benchmark hiện tại. Bước tải S3 là bước chuẩn bị độc lập; crawl dùng bundle trên Drive, không cần AWS credentials. Source S3 chỉ được ghi nhận khi có bằng chứng xác định đúng version; các trường hợp khác đưa vào hàng đợi arXiv và giữ lý do.

**Công nghệ:** Python, Colab CPU, boto3 cho chuẩn bị, tarfile và extractor hiện có, Google Drive, pytest.

**Cơ sở:** `docs/pipeline_s3_m1.md` trong workspace và yêu cầu hội thoại. Kế hoạch này thay thế phần trình tự cho chế độ hybrid trong tài liệu đó.

## Ràng buộc chung

- Phạm vi version được chốt bằng snapshot và SHA-256; không khẳng định snapshot phản ánh các thay đổi sau thời điểm chụp.
- Chế độ hybrid là trọng tâm. Giữ thiết kế ba chế độ `arxiv`, `arxiv_s3`, `s3` độc lập với phạm vi benchmark và nơi lưu; không chặn hoàn thiện hybrid để giả lập chế độ chưa được kiểm thử.
- `s3`: không dùng arXiv cho source hoặc discovery; thiếu hay không xác minh thì ghi `source_missing`/`version_unverified`, tiếp tục và QA chưa hoàn tất. Semantic Scholar vẫn được dùng nếu bật references.
- `arxiv_s3`: xử lý nhóm chỉ v1 trước; không bắt đầu source của nhóm nhiều version cho đến khi pha S3 và hàng đợi fallback nhóm v1 kết thúc hoặc đã ghi nhận thất bại sau retry. References có thể chạy song song và phải được ghi thời gian riêng.
- Dữ liệu M2 ở `data/corpus/<id>/metadata.json`, `references.json`, `vN/`; chỉ giữ `.tex`/`.bib`, bỏ figure; empty version theo quy ước hiện tại.
- Không tạo nhiều kết nối arXiv song song trái chính sách nhóm; dùng limiter chung giữa các runtime nếu chạy đồng thời.
- Cấu hình, mã, snapshot, manifest và inventory cố định khi resume. Không trộn kết quả của các run khác nguồn hoặc revision thành benchmark đồng nhất.

## Vị trí dự kiến

- Tạo `src/notebooks/arxiv_nhom1_s3_arxiv_benchmark.ipynb`: cấu hình, chuẩn bị, preflight, thực thi theo pha, báo cáo và rescue.
- Mở rộng `src/crawler/s3_prepare.py`: lập kế hoạch theo danh sách chỉ-v1; bảo toàn manifest và trạng thái tải.
- Tạo `src/crawler/s3_sources.py`: đọc từng bundle đã kiểm tra, xác định member và bằng chứng version, trích xuất an toàn theo hợp đồng `extract.py`.
- Mở rộng `src/crawler/discovery.py` và `src/run_pipeline.py`: phân nhóm có thể khôi phục, phương thức nguồn, fallback và ghi journal; tái sử dụng extractor, references, limiter và QA.
- Mở rộng `src/benchmark/runner.py`, `src/benchmark/checkpoints.py`, `src/benchmark/measurements.py` và `src/analysis/measurement_exports.py` để chạy pha, đo, khôi phục và xuất bằng chứng; thay đổi cụ thể theo nhu cầu để không phá arXiv-only.
- Thêm test `src/tests/test_s3_sources.py`, mở rộng `test_s3_prepare.py`, `test_run_pipeline.py`, `test_benchmark_runner.py`, `test_benchmark_notebook.py`.

## Các bước có kiểm chứng

### 1. Phân nhóm và chốt phạm vi

- [ ] Từ snapshot, tạo danh sách ID, version và owner cho nhóm `only_v1`, `multi_version` và các ID thiếu/sai metadata; không tự xếp ID thiếu sang v1. Ghi snapshot SHA, số lượng, ID đầu/cuối từng nhóm và theo owner.
- [ ] Dữ liệu tham chiếu: 20.000 ID, 14.913 chỉ-v1, 5.087 nhiều version và 26.491 version, theo snapshot local đã quét. Snapshot thực tế khác phải tính lại, không hardcode các số này.
- [ ] Test ID trùng, snapshot thiếu/malformed, version thiếu liên tục, ID ngoài range và resume với snapshot khác.

### 2. Xác định bundle và chuẩn bị Drive

- [ ] Fetch manifest S3 với Requester Pays từ Colab Secrets; chế độ xem kế hoạch in bundle ứng viên chứa các ID đầu/cuối từng range, mọi bundle ứng viên cho toàn bộ `only_v1`, các ID nằm ngoài ranh giới, kích thước và ước tính chi phí với giả định công khai.
- [ ] Phân biệt `first_item`/`last_item` là ranh giới ứng viên, không bảo đảm chứa paper hay version. Kiểm tra trường hợp manifest thay đổi, nhiều bundle trùng khoảng, ID thiếu; không dừng ở hai bundle đầu/cuối. Ba tháng ID của tập hiện tại là `2604`, `2606`, `2607`, không suy ra từ ngày cập nhật version.
- [ ] Tải bundle được chọn về `MyDrive/arxiv-nhom1/s3-bulk/bundles/`, lưu manifest theo hash và nhật ký inventory; giới hạn tổng byte trước tải, log từng bundle. Kiểm tra MD5 và kích thước trước khi công bố; file lỗi không được coi đã tải xong. Resume bỏ qua bundle đã xác minh, tải lại file `.part`; không ghi đè file hoàn chỉnh không khớp mà không kiểm tra.
- [ ] Test manifest thực tế được lưu sau khi người dùng chạy, manifest sai/không thể diễn giải, tải dở, checksum sai và đổi manifest. Một lần thử tải thật là smoke có tính phí và cần đo dung lượng Drive thực tế.

### 3. Xử lý nhóm chỉ-v1 từ bundle

- [ ] Xây dựng index member theo bundle một lần, không quét toàn bộ bundle lại cho từng paper/chunk. Giữ provenance gồm snapshot SHA, manifest SHA, key, MD5, member, thời gian và phương pháp xác minh version.
- [ ] Quy tắc fail closed: checksum, tên ID không version và timestamp bundle không tự chứng minh version. Chỉ chấp nhận bằng chứng version đáng tin cậy được xác định trong giai đoạn thử; nếu không có thì ghi `version_unverified` và chuyển `/src/<id>v1`. Không coi so khớp một mẫu nhỏ là bằng chứng cho mọi paper. Đối chiếu `/src/` nếu dùng để xác minh phải được tính riêng chi phí/request và thời gian; không công bố đó là tiết kiệm request cho những paper đã đối chiếu.
- [ ] Stream trích `.tex`/`.bib` qua extractor hiện có, xử lý PDF/no_tex, file lỗi và path traversal; chỉ journal `ok`/`no_tex` sau khi nguồn và kết quả được kiểm tra. Không đánh đồng S3 missing với HTTP 404.
- [ ] Thử bằng fixture archive giả chứa paper v1, version không rõ, member trùng, source hỏng và file không an toàn. So sánh dữ liệu thực ở một bundle với `/src/idv1`, bao gồm paper chỉ-v1, nhiều-version và bài cập nhật; ghi kết quả cùng giới hạn của phép so sánh.

### 4. Thứ tự pha và fallback arXiv

- [ ] Pha 1: duyệt toàn bộ nhóm chỉ-v1 qua S3 và lưu fallback; sau đó xử lý fallback `/src/idv1` với retry/limiter. Pha 2 chỉ bắt đầu sau khi pha 1 hoàn tất hoặc thất bại đã được ghi nhận; crawl mọi version của nhóm nhiều-version.
- [ ] Các paper chưa có metadata hoặc version chưa xác minh không được tính hoàn tất. References được crawl cho toàn bộ paper và theo dõi `ok`, `not_found`, `failed` riêng.
- [ ] Test thứ tự bằng nguồn giả: một bài S3 thành công, một bài fallback, một bài multi; kiểm tra không có multi source trước khi pha 1 kết thúc, 429/retry, missing và resume sau ranh giới pha. `s3`-only không có request arXiv kể cả metadata fallback.

### 5. Checkpoint, notebook và measurement

- [ ] Lưu journal sau version hoàn tất và checkpoint định kỳ, có thể khôi phục giữa bundle hoặc giữa các pha sang runtime mới. Không lặp S3 source đã hoàn tất, không mất `no_tex`, references, log hay thư mục rỗng. Kiểm tra riêng rủi ro checkpoint copy profiler file đang được ghi.
- [ ] Notebook có cell tách cấu hình ID/mode, mount Drive, secret AWS chỉ cho tải, plan, tải, kiểm tra inventory, crawl từng pha và báo cáo. Tải mặc định tắt; run ID mới cho experiment mới; `CODE_REF` pin commit.
- [ ] Ghi tách thời gian chuẩn bị S3→Drive, đọc Drive/index, xử lý S3, fallback, multi-version, references, sync và wall thực tế. Báo cáo chuẩn bị và crawl riêng cùng tổng thời gian, không cộng các khoảng chồng lấp; peak/mean RAM, disk bao gồm file tạm và chỉ rõ phạm vi dữ liệu trên Drive, bytes S3, output, số request, retry/429, chi phí ước tính và thực tế nếu có.
- [ ] Kiểm tra kill giữa download, giữa bundle và lúc sync; resume trên runtime mới; QA đối chiếu đầy đủ ID/version/source/references. Test lỗi sync và đảm bảo không báo final_complete khi còn thiếu hoặc measurement thiếu.

### 6. Smoke và bàn giao

- [ ] Chạy unit/integration bằng fixture, toàn bộ pytest; smoke một bundle trên Colab và so sánh với API trong giới hạn request/chi phí. Không cần AWS secret trong máy phát triển.
- [ ] Smoke 100–500 ID với nhóm v1 và multi, đối chiếu tốc độ/coverage với run arXiv cũ, xác nhận pha và checkpoint; chưa dùng sample làm final benchmark.
- [ ] Chỉ tiến tới full 20.000 ID khi bằng chứng version, khôi phục và measurement đạt yêu cầu, có đủ quota Drive và đã xác nhận cách dùng S3 đáp ứng yêu cầu M1. Báo cáo riêng dữ liệu thiếu và giả định.

## Quyết định kỹ thuật cần xác minh trước crawl chính thức

Không có trong manifest hiện tại một trường được xác nhận là version của từng member. Nếu không tìm được bằng chứng đủ tin cậy cho từng v1, pipeline hybrid vẫn chạy nhưng phải fallback arXiv; vì vậy mức tiết kiệm request có thể thấp hoặc bằng không. Không tự giảm chuẩn xác minh để đạt 75%.
