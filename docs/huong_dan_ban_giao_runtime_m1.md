# Bàn giao runtime Colab — M1 Crawl & Benchmark

Tài liệu vận hành cho các thành viên: chuẩn bị tài khoản, smoke test, full crawl 20.000 ID, chuyển ca/resume và lưu kết quả để đưa vào Book.

## 1. Thông tin bàn giao

Điền thông tin đăng nhập trong bản chia sẻ nội bộ; không đưa bản đã điền mật khẩu lên repository công khai.

| Nội dung | Thông tin |
| --- | --- |
| Tài khoản Google crawl chung | ________________________________________ |
| Mật khẩu | ________________________________________ |
| Người giữ/xác nhận đăng nhập 2 bước | ________________________________________ |
| Người phụ trách điều phối ca | ________________________________________ |
| Email liên hệ arXiv | ________________________________________ |
| Link thư mục Drive `arxiv-nhom1` | ________________________________________ |
| Run ID full crawl được nhóm chốt | ________________________________________ |
| Người đang giữ ca / giờ bắt đầu | ________________________________________ |

**Một tài khoản crawl chung, một crawler hoạt động tại một thời điểm.** Các thành viên thay nhau vận hành; không chạy song song từ Colab khác hoặc máy local.

- Notebook bàn giao: [mở trên Colab](https://colab.research.google.com/github/hcmus-arxiv-nhom1/CodeRepo/blob/9ad1a70011f08a41052c876fcef869c906387b15/src/notebooks/arxiv_nhom1_crawl_benchmark.ipynb).
- Code: <https://github.com/hcmus-arxiv-nhom1/CodeRepo>.
- Book: <https://hcmus-arxiv-nhom1.github.io/arxiv-book/>.
- Bản notebook trên pin implementation `bd7941c9fda2cd6fb99befee014326867ea30abb`.

Nhóm có thể chốt một notebook mới hơn trước khi bắt đầu. Khi một run đã tạo, giữ nguyên cấu hình và dùng revision đã lưu để resume run đó.

## 2. Chuẩn bị Drive sạch và runtime

Thư mục full crawl giữ đúng cây `MyDrive/arxiv-nhom1/data/corpus/` và `MyDrive/arxiv-nhom1/work/` như cách team tổ chức ban đầu. Tài liệu giả định người phụ trách đã dọn nội dung trong `MyDrive/arxiv-nhom1` và giữ lại chính thư mục này. Việc dọn chỉ thực hiện trước đợt chạy mới, sau khi các runtime cũ đã dừng. Khi đã bắt đầu full crawl, giữ nguyên thư mục run/checkpoint đến lúc bàn giao xong cho M2.

1. Đăng nhập Colab và Google Drive bằng tài khoản crawl chung ở mục 1.
2. Kiểm tra `MyDrive/arxiv-nhom1` dành cho full crawl. Tạo riêng các thư mục rỗng `MyDrive/arxiv-nhom1-smoke-10-01` và `MyDrive/arxiv-nhom1-smoke-200-01` cho smoke; mỗi Drive root chỉ thuộc một Run ID. Không ghi thí nghiệm mới vào corpus/work của run cũ.
3. Mở notebook theo link bàn giao. Có thể lưu bản sao vào Drive để giữ cấu hình đã điền.
4. Chọn **Runtime → Change runtime type → Hardware accelerator: None/CPU**.
5. Dùng runtime mới. Nếu notebook đã import code ở lần chạy trước, chọn **Runtime → Restart session/runtime** trước khi chạy setup lại.
6. Trong mục **Secrets** bên trái Colab, thêm `ARXIV_CONTACT_EMAIL`. Nếu nhóm có key, thêm `S2_API_KEY`. Bật quyền truy cập của notebook cho các Secret này.
7. Chỉnh cell cấu hình đầu tiên trước khi chạy các cell còn lại.

**Mỗi Drive root mới/dọn trống:** người đầu tiên đặt `INITIALIZE_TEAM_FOLDER = True` để tạo `TEAM.json`. Sau lần khởi tạo thành công, đặt lại `False`. Resume dùng cùng Drive root và không khởi tạo lại. Các thư mục smoke riêng không cho phép chạy nhiều crawler song song.

## 3. Smoke test

Chạy sample nhỏ đạt yêu cầu trước, sau đó mới chạy smoke 200 ID. Mỗi sample có một Run ID riêng và dùng runtime mới để số đo không bị ảnh hưởng bởi dữ liệu còn giữ trong kernel cũ.

### 3.1. Smoke nhỏ — 10 ID

Dùng cấu hình sau trong cell đầu. Thay `SHIFT_OWNER` bằng người vận hành: `dang`, `thien`, `tien` hoặc `hieu`.

```python
MODE = "sample"
RUN_ID = "m1-smoke-dang-10-01"
RANGES = ("dang",)
OFFSET = 0
COUNT = 10
CHUNK_SIZE = 10
WITH_REFERENCES = True
CHECKPOINT_S = 300
SESSION_BUDGET_S = 4 * 60 * 60

RESUME = False
SHIFT_OWNER = "dang"
TAKEOVER = False
DRIVE_DIR = "/content/drive/MyDrive/arxiv-nhom1-smoke-10-01"
TEAM_ID = "arxiv-nhom1"
INITIALIZE_TEAM_FOLDER = True  # chỉ lần đầu trong Drive root này

CODE_REF = "bd7941c9fda2cd6fb99befee014326867ea30abb"
REPO = "https://github.com/hcmus-arxiv-nhom1/CodeRepo.git"
```

Nếu `TEAM.json` đã được tạo ở một lần trước, dùng `INITIALIZE_TEAM_FOLDER = False` ngay từ đầu.

Chạy các cell theo thứ tự:

1. **Cấu hình** → **kiểm tra kernel mới**.
2. **Authorize/setup**: mount đúng Drive, cấp Secrets, lấy đúng implementation và cài dependencies.
3. **Preflight/tạo `cfg`**: đọc cấu hình được in; phải thấy **10 selected IDs, 1 chunk**.
4. **Crawl/benchmark**: chạy cell gọi `run_benchmark(...)`.
5. **Inspect evidence and download**: xem coverage, audit, bảng thống kê và tải ZIP.

**Điều kiện smoke đạt:**

- `coverage.json`: `complete = true`, không có lỗi source/reference QA.
- `timing_complete = true`, `measurement_complete = true`, `paper_timing_complete = true`.
- Không có lỗi cleanup cần xử lý; checkpoint đã được xác nhận.
- Có `bench_results.zip` và các CSV thống kê.
- `final_complete = false` là bình thường vì đây là sample.

Nếu có lỗi hoặc chưa có tiến độ thực tế, giữ log/evidence và báo người phụ trách; không tự chuyển sang full crawl. Để dừng, dùng nút Stop của cell rồi chờ runner kết thúc và lưu evidence nếu có thể. Tải dữ liệu local cần giữ trước khi reset runtime.

### 3.2. Smoke 200 ID

Sau khi sample nhỏ đạt, mở runtime mới. Giữ các giá trị còn lại ở trên và thay:

```python
MODE = "sample"
RUN_ID = "m1-smoke-dang-200-01"
COUNT = 200
CHUNK_SIZE = 100
DRIVE_DIR = "/content/drive/MyDrive/arxiv-nhom1-smoke-200-01"
RESUME = False
TAKEOVER = False
INITIALIZE_TEAM_FOLDER = True  # root smoke 200 mới, chưa có TEAM.json
```

Preflight phải thấy **200 selected IDs, 2 chunks**. Kiểm tra các điều kiện đạt giống mục 3.1. Lần smoke khác dùng tên mới, ví dụ hậu tố `-02`; không dùng cùng ID cho một thí nghiệm mới.

Nên kiểm tra thêm một lượt chuyển ca/resume có chủ đích trước khi full crawl: cho runner dừng theo session budget ở ranh giới chunk, tải evidence rồi tiếp tục cùng Run ID trong runtime mới. Giữ nguyên cấu hình lựa chọn dữ liệu.

## 4. Full crawl và benchmark — 20.000 ID

Người phụ trách chốt **một Run ID full duy nhất** và điền vào sổ ca. Dùng runtime mới, không dùng Run ID của smoke.

Trong cell cấu hình, giữ các thông số môi trường/checkpoint của mẫu trên và thay:

```python
MODE = "final"
RUN_ID = "m1-final-20000-01"  # thay bằng ID full nhóm đã chốt
RANGES = ("thien", "tien", "hieu", "dang")
OFFSET = 0
COUNT = None
CHUNK_SIZE = 100
WITH_REFERENCES = True
DRIVE_DIR = "/content/drive/MyDrive/arxiv-nhom1"
RESUME = False
TAKEOVER = False
INITIALIZE_TEAM_FOLDER = True  # lần đầu của root full đã dọn trống
```

- Preflight phải thấy **20.000 selected IDs, 200 chunks**.
- Final mode phải có đủ bốn range và references. Không chia thành bốn run độc lập để thay cho full run này.
- Giữ nguyên `CODE_REF` đã chốt. Khi resume, notebook tự lấy revision từ manifest của run.
- `SESSION_BUDGET_S` mặc định là 4 giờ, được kiểm tra giữa các chunk; không đảm bảo runtime luôn sống được đến mốc đó hoặc dừng đúng thời điểm tuyệt đối.
- Khi hết budget, runner lưu trạng thái rồi kết thúc phiên. Chuyển ca chủ động thay vì chờ runtime bị ngắt đột ngột.

**Chỉ chốt kết quả final khi** `coverage.json` có `required_ids = 20000`, `final_corpus_complete = true`, `timing_complete = true` và `final_complete = true`, đồng thời QA/audit không còn lỗi. Corpus đủ nhưng timing thiếu thì phải báo rõ phần thiếu, không ghi thành một benchmark đầy đủ.

## 5. Chuyển ca và resume

### Người kết thúc ca

1. Đợi cell crawl kết thúc và checkpoint được xác nhận; nếu buộc dừng sớm, dùng Stop và chờ cleanup.
2. Chạy cell cuối để tải evidence; lưu thêm bản ZIP vào Drive theo mục 6.
3. Điền sổ ca: Run ID, người vận hành, giờ kết thúc, chunk/offset cuối đã được xác nhận, trạng thái QA/timing và nơi lưu báo cáo.
4. Dừng runtime cũ. Xác nhận trong nhóm rằng không còn crawler hoạt động trước khi người tiếp theo nhận ca.

### Người nhận ca

1. Đăng nhập cùng tài khoản Google crawl, dùng runtime mới và cùng notebook đã chốt.
2. Dùng đúng `DRIVE_DIR`, nhập đúng Run ID và **giữ nguyên** `MODE`, `RANGES`, `OFFSET`, `COUNT`, `CHUNK_SIZE`, `WITH_REFERENCES`, `CHECKPOINT_S` của run.
3. Đặt `RESUME = True`, `INITIALIZE_TEAM_FOLDER = False`; đổi `SHIFT_OWNER` thành tên người nhận ca.
4. Thông thường dùng `TAKEOVER = False`. Chỉ đặt `True` sau khi đã xác nhận runtime trước dừng nhưng marker ca chưa được giải phóng.
5. Chạy từ đầu notebook để restore trong thư mục local mới. Đợi xác nhận checkpoint hợp lệ rồi mới để crawler tiếp tục.

**Không tự tăng `OFFSET` để bỏ qua phần đã chạy.** Runner kiểm tra phần đã hoàn tất và tự bỏ qua. Giữ cùng Run ID xuyên suốt mọi ca full crawl; không tạo ID mới khi chỉ cần resume.

Nếu phải đổi code hoặc cấu hình đã khóa, trao đổi với người phụ trách để xác định thí nghiệm/run mới; không sửa manifest thủ công.

## 6. Lưu kết quả và đưa vào Book

Drive dùng cấu trúc:

```text
MyDrive/arxiv-nhom1/
  TEAM.json
  SHIFT.json
  data/corpus/
    2604-20650/
      metadata.json
      references.json
      v1/main.tex, refs.bib
      v2/ ...
  work/
    manifest.json
    versions.jsonl
    discovery.jsonl
    run.log
    profile/<CHUNK>/
  book_csv/                      # CSV và audit cho Book
  runs/<RUN_ID>/
    MANIFEST.json
    checkpoints/*.json           # trạng thái commit; không ZIP corpus
    measurements/<SESSION_ID>/   # mẫu đo và paper events
    sessions/
    checkpoint-events/
    reports/<THOI_DIEM>/          # ZIP báo cáo tùy chọn
```

Checkpoint corpus nhắm mỗi 300 giây ở ranh giới version hoàn tất; telemetry nhắm upload mỗi 30 giây. Đây là mốc mục tiêu, có thể trễ khi file lớn hoặc Drive lỗi. Chỉ dữ liệu đã lưu bền vững mới được khôi phục sau khi runtime mất.

Corpus và work được đồng bộ thành file/thư mục thường trên Drive; M2 không cần giải nén checkpoint. Các file CSV cuối cũng được lưu ở `book_csv/`. Cell cuối có thể tạo ZIP measurement/log để tải về máy; ZIP này không chứa corpus. **Để lưu thêm vào Drive**, sau khi cell đó hoàn tất, chạy cell mới:

```python
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

source = Path(archive)  # ZIP vừa được cell cuối tạo
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
folder = DRIVE / "runs" / cfg.run_id / "reports" / stamp
folder.mkdir(parents=True, exist_ok=False)
saved = folder / source.name
shutil.copyfile(source, saved)


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


digest = sha256(source)
if sha256(saved) != digest:
    raise IOError("Bản ZIP trên Drive không khớp bản local")
(folder / "SHA256SUMS.txt").write_text(f"{digest}  {saved.name}\n", encoding="utf-8")
print("Đã lưu và kiểm tra:", saved)
```

Mỗi phiên có snapshot báo cáo riêng. Dùng bản export cuối của cùng run để báo cáo, không cộng thủ công các ZIP vì chúng có thể chứa lại cùng dữ liệu. `rescue_results.zip` là bản cứu hộ raw, không phải bằng chứng benchmark đã hoàn tất.

Khi full run đạt yêu cầu, người phụ trách tải và giải nén `bench_results.zip`, chuyển các file trong `book_csv/` vào `arxiv-book/data/m1/`. Book build với `--execute` sẽ sinh bảng và biểu đồ từ CSV. Ghi run ID, code revision và link evidence kèm kết quả. M2 đọc trực tiếp `arxiv-nhom1/data/corpus/` sau khi QA hoàn tất; giữ nguyên source M1 và ghi kết quả parsing vào nơi riêng. Các run ZIP cũ vẫn dùng notebook/revision cũ, không tự chuyển đổi khi chạy bản mới.

## 7. Quy tắc thao tác nhanh

| Tình huống | Cách xử lý |
| --- | --- |
| Bắt đầu một thí nghiệm mới | Run ID mới, `RESUME=False`, runtime mới. |
| Tiếp tục run sau khi đổi ca/runtime | Giữ ID và cấu hình, `RESUME=True`. |
| Đã đổi cell cấu hình | Phải chạy lại cell tạo `cfg` trước cell crawl; biến `RUN_ID` thay đổi không tự cập nhật `cfg.run_id`. |
| Cần chạy setup lại sau khi đã import code | Restart runtime trước; không cố bỏ qua guard kernel. |
| `Run already exists` | Chọn resume nếu tiếp tục đúng run; thí nghiệm mới dùng ID mới rồi tạo lại `cfg`. |
| Drive root đã thuộc run khác | Dùng root trống khác cho thí nghiệm mới; không xóa/ghi đè corpus hoặc chuyển chỗ dữ liệu tự động. |
| Cấu hình/revision khác manifest | Kiểm tra sổ ca và cấu hình gốc; không ghi đè/xóa run để ép chạy. |
| Marker báo ca khác còn hoạt động | Xác nhận runtime trước đã dừng rồi mới takeover. |
| Cell crawl lỗi | Giữ runtime/local data, tải evidence hoặc ZIP cứu hộ trước khi reset; gửi người phụ trách. |

## 8. Sổ ca — điền cho từng phiên

| Ca | Người vận hành | Run ID | Bắt đầu / kết thúc | Chunk/offset cuối đã xác nhận | QA/timing | Link evidence | Đã dừng runtime |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | __________ | __________ | __________ | __________ | __________ | __________ | __________ |
| 2 | __________ | __________ | __________ | __________ | __________ | __________ | __________ |
| 3 | __________ | __________ | __________ | __________ | __________ | __________ | __________ |
| 4 | __________ | __________ | __________ | __________ | __________ | __________ | __________ |

## 9. Feature nên bổ sung: Kaggle metadata snapshot cho discovery

**Trạng thái: yêu cầu tính năng, chưa có chế độ discovery bằng snapshot hoàn chỉnh trong notebook này.** Không cần thêm biến cấu hình giả hoặc tự sửa notebook để bật.

Mục tiêu: dùng arXiv metadata snapshot từ Kaggle làm nguồn discovery để giảm phụ thuộc vào API/OAI trong lúc crawl. Cần:

- Đối chiếu đủ 20.000 ID, danh sách mọi version và ngày phiên bản; ghi rõ các ID/thông tin còn thiếu.
- Đọc/index snapshot một lần rồi tra cứu theo ID; tránh quét lại toàn bộ snapshot ở mỗi chunk/runtime.
- Ghi nguồn, phiên bản/ngày snapshot và checksum để tái lập kết quả; nêu rõ độ mới của metadata.
- Có chính sách bổ sung những thông tin thiếu; không coi thiếu trong snapshot là paper không tồn tại hoặc đã hoàn tất.
- Ghi rõ thời gian chuẩn bị snapshot/index trong benchmark và phân biệt chạy từ đầu với dùng cache đã chuẩn bị.

`--snapshot` hiện có trong CLI chỉ hỗ trợ bổ sung thông tin ngày version; chưa thay thế toàn bộ discovery API/OAI và chưa được nối vào entrypoint benchmark. Feature này không thay thế bước tải source của mọi version.
