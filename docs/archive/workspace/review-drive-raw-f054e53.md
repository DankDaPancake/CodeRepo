# Review branch raw Drive — f054e53

Đã fetch remote và kiểm tra `origin/fix/drive-raw-folder-checkpoints` tại commit `f054e53`. Không sửa branch hoặc các thay đổi local đang dở.

## Kết luận

Code checkpoint đã chuyển sang mirror raw, nhưng chưa nên dùng notebook này để fullcrawl trước khi xử lý các điểm bên dưới.

1. **P1 — Notebook vẫn chạy code ZIP cũ.** `src/notebooks/arxiv_nhom1_crawl_benchmark.ipynb:42` đặt `CODE_REF=8310f7eb6d244dae5ad244e4d4632604b57efb36`; cell setup fetch và checkout đúng revision này (dòng 93–102). Revision đó dùng `ZipFile` cho checkpoint. Mở notebook từ branch mới vẫn chưa chạy implementation raw. Cần một commit pin revision triển khai raw sau khi sửa và kiểm thử.
2. **P1 — Runtime loss có thể làm checkpoint trước mất khả năng restore.** `src/benchmark/checkpoints.py:177–199` thay từng file mutable tại chỗ, rồi mới cập nhật `INDEX.json`. Nếu ngắt sau khi `work/run.log` đã bị thay nhưng trước khi ghi index, index cũ giữ hash của nội dung cũ. `restore()` ở dòng 231–233 từ chối vì mismatch. Atomic rename từng file không đảm bảo atomic cho cả một generation. Cần cơ chế giữ trạng thái đã commit của journal/metadata, hoặc phục hồi journal từ generation đã commit và tách các log mutable; corpus raw vẫn có thể giữ nguyên cho M2.
3. **P2 — Chưa đúng đường dẫn gốc như ảnh.** `src/benchmark/runner.py:311` đặt remote tại `DRIVE/runs/RUN_ID`; raw nằm ở `arxiv-nhom1/runs/<RUN_ID>/data/corpus` và `work/`. Ảnh và yêu cầu đặt `data/`, `work/` trực tiếp dưới `arxiv-nhom1/`. Cần thống nhất đường dẫn trước khi bàn giao M2.

## Kiểm chứng

- Chạy trên snapshot độc lập của đúng commit, không dùng working tree đang có thay đổi.
- `python -m pytest -q`: **239 passed in 18.69s**.
- `python -m ruff check src`: passed.
- `python -m ruff format --check src`: 65 files already formatted.
- Repro riêng: lưu generation đầu; đổi `work/run.log`; mô phỏng lỗi ngay trước lúc ghi `INDEX.json` trong lần save sau; restore vào thư mục rỗng.
- Kết quả: `previous_index_unchanged=true`, `previous_checkpoint_restorable=false`, `ValueError: Restored file mismatch: work/run.log`.
- Test hiện có chỉ đặt một file temp lẻ để giả lập ngắt upload, chưa bao phủ việc đã replace file mutable trước khi publish index.
- Chưa crawl hoặc thao tác Google Drive thật. Không tạo commit/PR trong lượt review này.
