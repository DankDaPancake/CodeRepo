> **Đã thay thế ngày 01/11/2026:** nhóm quyết định tiếp tục giải nén và lọc figure. Dùng `2026-11-01-multi-account-no-shift.md`; không triển khai phương án lưu source nguyên bản dưới đây.

# Kế hoạch M1 — lưu source nguyên bản và bỏ chia ca

> Đây là kế hoạch, chưa triển khai. Yêu cầu: bỏ giải nén trong crawler, lưu dữ liệu crawl as-is và bỏ tính năng chia shift.

## Mục tiêu và quyết định phạm vi

- Với từng version đã discovery, lưu nguyên **HTTP response body thành công** từ `/src/<id>vN`, không giải nén, không lọc `.tex`/`.bib`, không cắt sớm PDF, không tự đóng gói lại hay chuyển đổi định dạng. HTTP header `Accept-Encoding: identity`; tính SHA-256 của body đã lưu. Các byte đó là HTTP entity body sau transport, không phải raw packet/TLS.
- Vẫn thu thập metadata và references như hiện tại dưới dạng JSON đã chuẩn hóa. Giả định yêu cầu “as-is” nói về source của từng version; nếu nhóm cần lưu nguyên cả response JSON/XML gốc của API/OAI/Semantic Scholar, bổ sung đó là phạm vi riêng và đo disk/network tương ứng.
- Giữ nguyên 20.000 ID, các version có trong snapshot, fallback, reference crawl, CPU-only, hai backend Drive/HF và output raw cho M2. Không dùng S3. Snapshot chỉ phản ánh dữ liệu tại thời điểm của nó; nó không chứng minh không có version mới sau snapshot.
- Bỏ thực sự `SHIFT.json`, owner/heartbeat/takeover/ca trực, token ownership trong checkpoint và các giao diện tương ứng. Không còn tự dừng theo ngân sách bốn giờ để bàn giao ca. Chỉ còn một lần chạy bình thường, người dùng chủ động dừng hoặc Colab tự ngắt.
- **Giữ checkpoint và resume** khi ngắt: cùng RUN_ID, backend, cấu hình, source snapshot và implementation revision. Bỏ chia shift không làm checkpoint tự biến mất; session được ghi lại để đo khi runtime khởi động lại. Việc resume phải do người dùng chủ động thực hiện. Không giữ lại cơ chế đổi ca dưới tên khác.
- Vẫn tuân thủ một luồng kết nối arXiv, rate limiter và lock cục bộ khi dùng chung work directory. Không có SHIFT nghĩa là không còn khóa phân tán giữa các runtime/tài khoản: cả nhóm phải vận hành không đồng thời chạy nhiều crawler. Local lock không ngăn được hai runtime riêng; không hứa có phát hiện tự động.
- Không xóa, ghi đè hay tự chuyển đổi các run, corpus raw-TeX hoặc dataset trước đây. Schema mới dùng run ID và định danh schema mới; cấm resume run cũ bằng phiên bản này nếu chưa có migration được thiết kế và kiểm tra riêng. Các PR hiện chưa được yêu cầu.

## Tác động yêu cầu M1 và tài nguyên

1. `M1_requirements.md` yêu cầu cỡ bài trước **và sau khi bỏ hình**, tỷ lệ source và reference metadata, thời gian, RAM, disk, output. Tải nguyên archive không thể tính trung thực cỡ sau khi bỏ hình hoặc `has_tex` nếu không kiểm tra bên trong. Không đặt 0, không dùng dung lượng compressed làm cỡ uncompressed, không coi download 200 đồng nghĩa có TeX. Đánh dấu metric là unavailable và Book chưa đủ evidence ở phần này; nếu cần chấm đủ, nhóm cần bước phân tích riêng sau crawl đọc/giải nén archive để tính metric (ngoài pipeline crawl), với scope đo rõ ràng. Kế hoạch không lén giữ giải nén trong crawler.
2. Trước khi full crawl, kiểm tra sức chứa Colab, lưu trữ output, số lượng file và băng thông. Smoke 500 trước đó có 346 records có `archive_bytes`, tổng khoảng 1,5055 GB và trung bình 4,35 MB/record; sample này không đại diện các range còn lại, một số PDF có thể dùng Content-Length từ lần chỉ đọc đầu, và đây không phải tổng thực đo của dataset. Nhân thô với 26.491 version theo snapshot cho khoảng 115 GB decimal body, chưa gồm metadata, temporary/staging, checkpoint, retries và các version sau snapshot. Chỉ để lập kế hoạch, không phải dự báo hay cam kết. HF công bố [100 GB private storage ở free tier](https://huggingface.co/docs/hub/storage-limits); chưa biết quota thực tế của tài khoản này. Cần kiểm tra quota thực tế trước full run; giữ Drive/HF option, không tự bật dịch vụ trả phí.
3. Raw có thể cải thiện CPU và tránh giải nén trong khi tải, nhưng full PDF/figures tăng network và disk. Sample cũ cho thấy nhiều 429, body cut/Range resume; không hứa đạt 1.000 paper/giờ hoặc nhanh hơn cho đến khi benchmark cùng phạm vi và điều kiện có thể so sánh.

## Cấu trúc dữ liệu đề xuất

```text
runs/<RUN_ID>/data/corpus/<paper-id>/
  metadata.json
  references.json
  v1/
    source.bin            # body gốc, không đổi bytes; không giả định tar.gz
    source_info.json      # status, headers cần thiết, size, SHA-256, version
  v2/
    source.bin
    source_info.json
  v3/
    source_info.json      # unavailable; chỉ ghi nhận 404/410 thực sự, không có body source
```

`source.bin` là tên lưu nội bộ ổn định, không thay đổi body. `source_info.json` lưu an toàn tên gốc từ `Content-Disposition` nếu có, Content-Type, Content-Encoding, HTTP status, URL, received size, SHA-256, thời điểm, attempts/resumes và schema. Tên gốc chỉ là metadata không tin cậy, không dùng nguyên văn làm đường dẫn. Có thể mô tả format theo header/magic bytes mà không giải nén, nhưng không biến suy đoán thành kiểm chứng integrity của archive. Thành công `downloaded` yêu cầu đủ body và tính hash; 404/410 `unavailable` là kết quả riêng, không có archive. HTML error, 429, 5xx, timeout, body ngắn hoặc bị cắt không được ghi như source hoàn tất. Không lưu token, cookie, authorization hay thông tin nhạy cảm vào header/log.

Drive giữ `runs/<RUN_ID>/data/corpus/...` trực tiếp; HF vẫn dùng shard month/prefix hiện tại và khôi phục về cây flat tại local. Không lưu plaintext mirror nén thành một ZIP toàn corpus; mỗi body giữ đúng dạng server trả (`tar.gz`, `tar`, `zip`, `gz`, TeX, PDF, v.v.). M2 nhận **archive**, phải có bước đọc/giải nén an toàn riêng sau này; parser M2 hiện đọc `.tex` trong thư mục nên không thể được tuyên bố tương thích ngay. Tránh giải nén archive không tin cậy trực tiếp vào đường dẫn tùy ý.

## Các task và file thực hiện

### 1. Raw downloader và tính toàn vẹn

**Files:** `src/crawler/downloader.py`, `src/crawler/http_client.py`, `src/run_pipeline.py`, `src/crawler/worker.py`, `src/config.py`; tests tương ứng trong `src/tests/`.

- [ ] Viết test giả lập server cho tar.gz, tar, zip, single gz/TeX, PDF và body nhị phân; so sánh byte source lưu ra với response fixture và SHA-256; kiểm chứng không gọi extractor/không tạo các file đã giải nén.
- [ ] Viết test response 404/410, 429, HTML error, hết retries, content-length sai, bị cắt giữa body, server trả `206` hợp lệ, Range bị bỏ qua/trả sai, kill giữa ghi và khởi động lại. `.part` và body lỗi không được publish thành source hoàn tất. Chỉ coi 404/410 `unavailable` khi response đúng theo chính sách; không coi 429 hay HTML lỗi là `downloaded`.
- [ ] Thay luồng `extract_stream()` bằng stream body vào `.part` trên local, không tải cả file vào RAM, hash theo byte; hoàn thiện atomically và chỉ append journal sau khi body đủ, length/range hợp lệ, flush và kiểm tra size/hash. Xử lý retry tránh ghép lặp bytes hoặc lưu rác. Giữ 1 arXiv connection, limiter, 429/backoff, circuit breaker và contact email.
- [ ] Đổi version journal sang schema raw: `downloaded`, `unavailable`, `failed`; size là số byte body gốc, SHA-256 rõ nguồn, headers đã lọc và version. Không tự xác nhận archive giải nén được. Chỉ skip khi journal + file + size/hash hợp lệ; phân biệt empty body hợp lệ và response lỗi theo HTTP.
- [ ] Không phát parser queue sang M2 cũ khi raw archive chưa hỗ trợ; xử lý tương thích fail-fast hoặc đổi contract rõ ràng. Cập nhật CLI/help, loại cấu hình `keep_extensions` khỏi đường chạy raw; giữ hay xóa module extractor cũ theo phụ thuộc thực tế, không xóa công việc M2 ngoài phạm vi.

### 2. Checkpoint raw và bỏ shift

**Files:** `src/benchmark/runner.py`, `src/benchmark/checkpoints.py`, `src/benchmark/huggingface.py`, `src/benchmark/measurements.py`, notebook và tests.

- [ ] Test Drive/HF checkpoint body raw, hash, file 0 byte, 404 không có body, dữ liệu dở không được commit; crash trong tải/upload/pointer và restore từ điểm đã verified; test thay đổi mutable file trên Drive vẫn phục hồi bằng hash backup. HF dùng `LATEST` + pinned revision và kiểm chứng, không làm mất pointer cũ khi upload gián đoạn.
- [ ] Điều chỉnh selector/checkpoint/restore để `source.bin` và `source_info.json` là đơn vị atomic của một version; không dựa vào `.tex`, `.bib` hay empty directory làm bằng chứng duy nhất. Bảo đảm size, SHA-256 ở journal, manifest và nội dung nhận được nhất quán; HF dùng LFS/Xet theo SDK và không đọc toàn bộ source lớn vào RAM. Đo và giới hạn dung lượng spool/staging; cảnh báo sớm theo disk/quota thực đo, giữ đủ vùng trống để hoàn thành checkpoint. Với file lớn hơn giới hạn batch, gửi riêng; cap hiện hành là target không phải giới hạn cứng.
- [ ] Bỏ `Shift`, `owner`, `SHIFT_OWNER`, `TAKEOVER`, `shift.check/close`, `owner_token`, `check_owner`, `hf_shift_token`, ghi/đọc `SHIFT.json` và commit bàn giao; xóa cell/hướng dẫn liên quan. Trước khi bỏ ownership guard phải bảo đảm các đường gọi mới vẫn không để concurrent local writers phá checkpoint; no distributed lock được nêu rõ. Không xóa `SHIFT.json` cũ ở Drive/HF và không thay đổi shared resources đã tồn tại.
- [ ] Bỏ mặc định session budget/handoff sau 4 giờ; hỗ trợ dừng bình thường và signal/exception cleanup có giới hạn. Giữ checkpoint 300 giây là mục tiêu, checkpoint thời điểm cuối và resume thủ công; không hứa recovery của partial download qua runtime loss, không thêm thời gian ngoại tuyến vào wall. Không bỏ HF commit budget/cooldown để lách rate limit.
- [ ] Test không yêu cầu marker/takeover, không có request hoặc commit `SHIFT.json`; local work lock vẫn ngăn hai process; resume ở runtime mới không phụ thuộc vào SHIFT cũ. Test nhiều runtime không được coi là an toàn: fail rõ hoặc tài liệu yêu cầu người dùng điều phối một crawler, không suy ra lock phân tán tồn tại.

### 3. QA, statistics và measurement không bịa

**Files:** `src/qa/validate.py`, `src/analysis/stats.py`, `src/analysis/measurement_exports.py`, `docs/data_contract.md`, `docs/measurements.md`, tests.

- [ ] Tách rõ: ID found; versions discovered; body tải hoàn tất; versions unavailable; source failure; papers với toàn bộ expected version đã xử lý; reference retrieval/metadata completeness. Nêu định nghĩa success và mẫu số; không gọi 404 thành “source tải thành công”. Kiểm tra expected số version đúng snapshot và phát hiện extra/partial, hash sai, file thiếu, schema cũ lẫn schema mới.
- [ ] Sửa QA không đánh dấu `.tar.gz`/`.bin` là binary bất hợp lệ; QA phiên bản raw xác minh manifest + size/hash và 404, không claim archive có TeX hay an toàn giải nén. M2 QA extraction riêng.
- [ ] Bổ sung metric `raw_body_bytes`, số file, throughput và output bytes; các cột cũ `size_before_bytes`, `size_after_bytes`, `has_source/has_tex` chỉ điền khi thực sự tính được đúng nghĩa; otherwise để missing + audit lý do. Không đổi semantics các CSV mà không nâng phiên bản schema/đồng bộ Book. Trong full 20k final vẫn cần giải quyết metric after-figures theo yêu cầu thầy ở bước phân tích riêng.
- [ ] Sampler RAM toàn system, peak/mean, disk (bao gồm snapshot, archive, partials, HF staging/cache) và output size; đo phiên end-to-end, checkpoint, setup và sync theo scope công bố. Tính kích thước output từ raw archive thực, không cộng trùng overlap/lost tails. Bổ sung lower-bound cho phiên bị ngắt, `/usr/bin/time -v` chỉ đối chiếu process, paper lifecycle phản ánh phiên retry. Kiểm tra measurement input snapshot và file staging không bị bỏ sót.

### 4. Notebook, Book và vận hành

**Files:** `src/notebooks/arxiv_nhom1_crawl_benchmark.ipynb`, `README.md`, `docs/huggingface_colab.md`; `arxiv-book/m1/01-methodology.md`, `m1/04-discussion.md`, `m1/index.md`, analysis notebooks nếu schema đổi và notebook mirror.

- [ ] Notebook toggle `USE_HUGGINGFACE` vẫn hoạt động; cấu hình sample 100 ID mới; full mode 20.000 ID/các range/references; snapshot Drive input, output Drive/HF. Không còn cell/flag/hướng dẫn shift hay takeover. Nêu phải chạy duy nhất một runtime. User dừng thủ công; sau disconnect mới resume thủ công bằng cùng config và code revision.
- [ ] Viết hướng dẫn M2 rằng dữ liệu là nguyên body, định dạng khác nhau; không tự chạy parser trên archive. Nêu dung lượng, checksum, run cũ schema khác và nơi chứa dữ liệu. Rescue ZIP phải bảo toàn file & metadata/trạng thái unavailable, kể cả empty directories nếu contract yêu cầu; phần `.part` luôn được đánh dấu chưa hoàn tất. Không xóa dữ liệu rescue của user.
- [ ] Cập nhật Book M1 để phân biệt benchmark raw mới và các smoke cũ (stream/filter), effort, trade-off, số chưa đo và phần tiêu chí còn thiếu. Các bảng/hình sinh từ CSV trong Book compile. Không gán số đã lọc cũ cho raw, không đưa giả định 115 GB hoặc sample thành kết quả final. Giữ hai chương M1/M2; cập nhật mirror từ commit CodeRepo chính xác và không chạy crawler khi build.
- [ ] Giữ các sửa chưa commit trong `arxiv-book`: kiểm tra diff trước thay đổi, không reset/stash/overwrite; Book và CodeRepo thay đổi riêng. Notebook source hiện ở fork, đồng bộ Book đúng repo+SHA; chỉ mở PR/merge khi có chỉ đạo.

### 5. Xác minh và tiêu chí hoàn thành

- [ ] Test-driven: chứng minh test mới fail trước fix; chạy các test downloader/Range, local lock, checkpoint hai backend, QA/schema, notebook, measurement, retry + giới hạn bộ nhớ, sau đó toàn bộ pytest, Ruff và `git diff --check`. So sánh SHA nguồn fixture với file đã tải, kể cả các mẫu lớn và interruption.
- [ ] Build Book với notebook phân tích execute, notebook crawler được skip; test mirror provenance. Các tiêu chí M1 thiếu evidence phải được liệt kê thật, không tuyên bố đã đủ.
- [ ] Smoke Colab CPU bằng run ID mới: 10 ID trước, kiểm tra raw bytes/hash, upload Drive/HF và reference, RAM/disk, commit count/429; dừng giữa version và resume một runtime mới từ checkpoint, xác nhận không có `SHIFT.json` request. Sau đó tăng lên 100 ID hoặc size mẫu phù hợp để đo archive lớn. Không chạy hai runtime arXiv đồng thời và không xóa run cũ.
- [ ] So sánh source được tải với HTTP body gốc của các fixture/phiên sample phù hợp, kiểm tra SHA trên storage được chọn sau restore. Xác nhận PDF body tải trọn, 404 tách riêng, M2 có contract xử lý. Đo lượng storage thực và ước lượng quota dựa trên sample đại diện hơn trước full crawl 20.000; không kỳ vọng sample 10 ID chứng minh full throughput.
- [ ] Nếu không thể truy cập Colab/secret hoặc runtime bị ngắt: ghi rõ chỉ offline test/partial evidence, chưa xác thực tốc độ, chưa xác nhận full data. Bàn giao chính xác code revision, schema, tình trạng Book, số liệu đã đo và phần còn thiếu; không nói full-crawl hoàn tất.
