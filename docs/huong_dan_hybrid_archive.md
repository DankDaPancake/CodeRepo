# Thử nghiệm hybrid với gói 100 paper

Notebook: `src/notebooks/arxiv_nhom1_hybrid_archive_benchmark.ipynb`.

Mặc định chạy lại Đăng offset 0/count 2500 (`2604.20535`–`2604.23034`), giữ thứ tự hybrid S3 → references + arXiv fallback → multi-version. Mỗi gói chứa 100 ID gốc được chọn và mọi version của các ID đó, không phải 100 version hoặc 100 paper trong riêng một pha. Nếu đầy đủ sẽ có 25 batch hoàn tất theo INDEX. Với count không chia hết cho 100, batch cuối được phép ngắn hơn.

## Cấu hình và chạy

- `RUN_ID = "dang-0000-2499-tgz100"`; dùng ID mới nếu tên này đã tồn tại.
- `MODE = "partition"`, `MEMBER = "dang"`, `OFFSET = 0`, `COUNT = 2500`.
- `ARCHIVE_BATCH_SIZE = 100`; `.tar.gz` mức nén 1 cố định cho thí nghiệm này.
- `CHECKPOINT_S = 600`; checkpoint theo ranh giới version hoàn tất, không phải deadline cứng.
- Output: `/content/drive/MyDrive/arxiv-nhom1/archive-tests`. Tạo folder này trước; khởi tạo `TEAM.json` một lần bằng `INITIALIZE_TEAM_FOLDER=True`, sau đó dùng `False`.
- Snapshot và bulk S3 dùng lại các đường dẫn từ notebook hybrid. `S3_DOWNLOAD=False` mặc định không tải bulk lại.
- `CODE_REF="experiment/hybrid-archive-batches"` resolve SHA từ fork `DankDaPancake/CodeRepo` khi bắt đầu run mới; branch này phải được push trước khi chạy Colab. Có thể pin SHA đã publish. Resume dùng SHA trong manifest của run.
- Sau khi xem phạm vi và kế hoạch S3, bật `RUN_CRAWL=True` ở cell chuẩn bị. Không dùng run ID của lượt raw cũ.

## Dữ liệu trên Drive

```text
archive-tests/runs/<RUN_ID>/
  MANIFEST.json
  INDEX.json                       # schema batch-archive-v1
  indices/<generation>.json
  archives/batch-0000-<sha>.tar.gz # snapshot hiện tại hoặc cũ của một nhóm ID
  archives/work-<sha>.tar.gz       # log, journal, báo cáo/CSV khi đã tạo
  checkpoint-events/
  archive-events/
  measurements/
  sessions/
```

Không tạo raw mirror `data/corpus/` trên Drive. Bên trong gói có `BATCH.json` chứa ID, version/status, provenance, hash từng file và thư mục version rỗng; cấu trúc source vẫn là `data/corpus/<paper>/vN/`. Metadata và references có trong snapshot khi đã được tạo. Chỉ batch qua QA source và references cho mọi ID mới có `complete=true` trong INDEX.

Checkpoint giữa chừng dùng snapshot batch chưa hoàn tất (`complete=false`) để bảo toàn version đã xong trong lúc S3/references/multi-version còn chạy. Đây không phải gói corpus đã hoàn tất. Archive và work được ghi, kiểm tra hash rồi mới publish INDEX. Các object cũ được giữ để phục hồi, không tự động xóa. Vì vậy số file archive thực tế có thể lớn hơn 25 và dung lượng Drive lớn hơn tổng 25 gói cuối; luôn duyệt danh sách trong INDEX, không glob mọi archive để gộp corpus.

## Measurement

Đóng gói, đóng băng file mutable, kiểm tra archive/member hash và upload trong checkpoint nằm trong wall session. `work/archive_events.jsonl` và `archive-events/` ghi riêng:

- `packing_verify_s`: freeze + đóng gói + xác minh local;
- `upload_verify_s`: publish archive và xác minh readback;
- `bytes`: dung lượng archive mới được xử lý trong checkpoint.

Các chi phí scan/QA/hash trước đóng gói và ghi index vẫn nằm trong thời gian checkpoint tổng. CSV có `archive_packing_verify_time`, `archive_upload_verify_time`; chúng là thành phần checkpoint, không cộng thêm vào wall. `archive_payload_size` là tổng kích thước các batch mới nhất theo index (có thể còn partial nếu run lỗi), không gồm work/telemetry/object cũ. `output_size` tiếp tục có nghĩa kích thước corpus raw local sau lọc để so sánh với các run cũ.

Việc publish evidence sau sampler được ghi riêng, nằm ngoài wall session. CSV được đóng băng trước publication nên thời gian của chính lần publication cuối được tra trong event remote sau cùng. RAM/disk vẫn lấy mẫu, có thể bỏ lỡ spike ngắn. Vùng tạm nằm trong `work/tmp` để thuộc phạm vi disk sampler, được dọn theo từng archive; corpus raw local vẫn được giữ lại cho QA nên bản này không giảm tuyến tính peak disk theo archive ratio. Không khẳng định tốc độ cải thiện trước khi có smoke Colab.

## Smoke và resume trước lượt 2500

1. Chạy CPU-only Colab với RUN_ID riêng, COUNT=100; hoàn tất mọi cell và tải evidence. Kiểm tra một batch complete, source/reference QA, measurement/timing audit và schema index.
2. Thử count nhỏ có paper multi-version và no_tex/unavailable; khôi phục trên runtime mới, kiểm tra file/hash và thư mục version rỗng.
3. Thử ngắt riêng một run nhỏ ở giữa batch, rồi `RESUME=True` trên runtime mới, giữ nguyên settings và snapshot/revision. Version đã checkpoint được restore; chunk đủ QA được bỏ qua. Restore hiện giải nén toàn bộ checkpoint, chưa có lazy restore.
4. Khi cả smoke và resume đạt, dùng RUN_ID mới với COUNT=2500. Giữ evidence cũ để đối chiếu wall, sync, packing, archive ratio, RAM và disk.

Hard kill có thể để lại timing tail chưa biết; resume thành công về dữ liệu không tự biến timing thành đầy đủ. Readback cùng runtime không chứng minh chắc chắn dữ liệu đã lên cloud; cần kiểm chứng trên runtime mới. Nếu lỗi, chạy cell rescue trước khi reset để giữ raw local/evidence.

## M2

Chỉ dùng batch complete theo INDEX đã chốt. Xác minh checksum archive và hash từng member bằng `verify_batch`; giải nén có kiểm soát về local corpus, giữ version rỗng và trạng thái trong BATCH.json. Bộ lưu trữ đã có `ArchiveCheckpoints.restore()` để phục hồi raw local và log từ run; chưa có công cụ upload các archive này lên Hugging Face. Không dùng cách restore raw cũ hoặc trộn format checkpoint trong cùng RUN_ID.
