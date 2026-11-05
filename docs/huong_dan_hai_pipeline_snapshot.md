# Hai pipeline theo số version trong snapshot

Notebook `arxiv_nhom1_only_v1_benchmark.ipynb` chọn ID chỉ có một version theo snapshot, tải nguồn từ S3 và fallback về arXiv khi cần. Notebook `arxiv_nhom1_multi_version_benchmark.ipynb` chọn paper có hơn một version và tải từng version từ arXiv. Notebook only-v1 mặc định chọn cả bốn range trong một run. Notebook multi-version chọn một thành viên bằng `MEMBER` và tạo run ID riêng cho mỗi thành viên hoặc mỗi dải; `OFFSET = 0`, `COUNT = None` chọn toàn bộ dải thành viên. Offset/count áp dụng trước khi phân nhóm.

Hai notebook dùng hai file snapshot tách từ cùng snapshot 20.000 ID. Only-v1 dùng `arxiv-assigned-only-v1.jsonl` (SHA-256 `2cb0fa363ce57bfb63f668603c8a4e6e3d790fde47e7af1b482df5235d7ea175`); multi-version dùng `arxiv-assigned-multi-version.jsonl` (SHA-256 `4d457f0e78bea5bae7addad0e56f55e056949b61037925fd0412ef20b0e5a081`). Chỉ sử dụng bản snapshot đã chuẩn bị cho tập được giao. Khi có ID bị thiếu, metadata sai hoặc version không liên tục, bước lọc dừng và báo số lượng; không chuyển im lặng ID sang một nhóm khác. `snapshot_group` là một phần run identity; không đổi group hoặc snapshot khi resume. Sử dụng RUN_ID khác nhau, `MODE = "partition"`, và chưa coi một nhóm là benchmark final toàn bộ 20.000 ID.

Trước khi chạy trên Colab, cần merge/publish phiên bản này. `CODE_REF = "main"` chọn commit main mới nhất của `REPO` khi bắt đầu run mới; notebook in và lưu SHA thực tế trong manifest. Có thể thay bằng SHA đã publish để cố định code cho nhiều run. Resume tự dùng SHA trong manifest, không phụ thuộc main mới. Mount Drive, kiểm tra snapshot, đường dẫn và tài khoản, sau đó bật `RUN_CRAWL = True`; notebook S3 cần manifest và các bundle hợp lệ. Giả định v1 từ snapshot/bundle cần được ghi rõ; fallback khi không xác minh được source. Tọa độ RUN_ID và tốc độ request arXiv giữa các runtime: rate limiter hiện chỉ trong một runtime, không điều phối dùng chung.

Cần đối chiếu union hai tập ID và coverage/version, references, QA, timing và revision trước khi tổng hợp kết quả cho Book; hiện chưa có bộ tổng hợp final tự động. Chạy smoke riêng và kiểm tra resume từng pipeline trước khi full crawl. Không thay config của run cũ.

## Hai vùng lưu trữ trên Drive

```text
MyDrive/arxiv-nhom1/
├── only-v1/
│   ├── TEAM.json
│   └── runs/only-v1-all/
└── multi-version/
    ├── TEAM.json
    └── runs/
        ├── multi-dang-0000-4999/
        ├── multi-hieu-0000-4999/
        ├── multi-thien-0000-4999/
        └── multi-tien-0000-4999/
```

Tạo sẵn hai thư mục output trong Drive. Với mỗi thư mục mới, khởi tạo marker một lần bằng `INITIALIZE_TEAM_FOLDER = True` sau khi xác nhận đúng folder; về sau dùng `False`. Không chạy đồng thời hai runtime cùng khởi tạo một folder hoặc cùng RUN_ID. Mỗi thành viên cấu hình `MEMBER` và RUN_ID khớp dải; run con giữ checkpoint riêng. M2 đọc corpus dưới mỗi run và cần bước tổng hợp có kiểm chứng.

Đặt hai file JSONL vào `MyDrive/arxiv-inputs/`. Notebook xác minh SHA-256 riêng trước khi sử dụng; code chỉ chấp nhận chính xác hash của nhóm và ghi hash vào manifest. Hai hash có cùng nguồn snapshot 20.000 ID SHA-256 `033d7bded327d3aa1595f5502ebfc44bcfe353a89a2011b297742d287ba4de15`. Phân nhóm phụ thuộc phiên bản snapshot; các ID không hợp lệ sẽ chặn chạy, cần xử lý riêng trước khi nhóm được coi là đầy đủ.

## Phạm vi và tiến độ

Với snapshot local 20.000 ID đã kiểm tra, số lượng theo member là: Đăng 1.466 paper / 3.389 version; Hiếu 1.343 / 3.060; Tiến 1.164 / 2.619; Thiên 1.114 / 2.510. Tổng multi-version là 5.087 paper / 11.578 version, only-v1 là 14.913 paper. Notebook tính lại số liệu từ snapshot thực tế trước khi chạy; OFFSET và COUNT áp dụng trước khi lọc.

Only-v1 hiển thị thanh paper cho từng chunk, có nhãn `s3` hoặc `fallback`. Multi-version hiển thị hai thanh paper và version cho chunk hiện tại. Các thanh chỉ đếm source ở trạng thái cuối, bao gồm `no_tex` và `unavailable`; chúng không chứng minh references hoặc QA hoàn tất. Resume tính cả kết quả đã có trong chunk. Các pha có thể bị bỏ qua nếu đã đủ dữ liệu; progress không phải số lượng paper duy nhất toàn run.

## Tạo lại file dữ liệu

Từ CodeRepo: `python -m src.crawler.split_assigned_snapshot arxiv-metadata-oai-snapshot.json ../snapshot-split-new`. Script từ chối ghi đè file có sẵn và đối chiếu các ID/version. Bộ hash mặc định trong notebook chỉ áp dụng đúng snapshot của nhóm; với snapshot khác cần cập nhật hợp đồng hash và kiểm thử. Không commit dữ liệu JSONL vào repository code.

Notebook arXiv thuần và hybrid dùng snapshot đủ 20.000 ID. Hybrid mặc định offset 0, count 1000 cho mỗi thành viên (4.000 ID), `RUN_CRAWL=False`; đây là thử nghiệm, chưa phải final benchmark 20.000 ID.
