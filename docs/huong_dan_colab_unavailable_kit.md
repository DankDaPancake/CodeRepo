# Chạy retry unavailable trên Colab

Gói này dùng mã đã merge PR #44. Ngày chuẩn bị: 12/11/2026.

1. Trên Google Drive tạo `MyDrive/recovery-colab-kit` và upload `src/artifacts/recovery-colab-kit/recovery-runtime.zip` từ CodeRepo vào đó. Nếu trước đây có file trùng tên, thay bằng gói mới này.
2. Mở https://colab.research.google.com/, chọn File > Upload notebook rồi chọn `arxiv_nhom1_recovery_retry.ipynb`.
3. Chạy từng cell từ trên xuống; cho phép notebook mount Drive. Notebook cài dependencies và xác minh SHA-256 của gói.
4. Cell cấu hình mặc định `RUN_NETWORK = False`. Chạy preflight và kiểm tra kết quả: 5 run, 86 cặp unavailable, 1.000 ID S3 trong mẫu.
5. Đổi `RUN_NETWORK = True` trong cell cấu hình, chạy lại cell đó rồi chạy cell kế tiếp để bắt đầu retry 86 cặp.
6. Để notebook chạy. Kết quả nằm tại `MyDrive/recovery-colab-kit/results/retry/`: `manifest.json`, `versions.jsonl`, `summary.json` và `corpus/`.

Không cần chạy notebook metadata trước. Chạy một runtime cho output này. Khi runtime ngắt, mở lại notebook, chạy các cell theo thứ tự và bật RUN_NETWORK=True. Các trạng thái hoàn tất có hash khớp được bỏ qua; inconclusive và corrupt được thử lại. Khi bị chặn liên tiếp, chương trình ghi inconclusive rồi dừng; chờ hết thời gian chặn trước khi thử lại. Giữ nguyên ZIP và đường dẫn để resume.

Nếu notebook báo journal hỏng do bị ngắt giữa dòng, giữ nguyên output và kiểm tra journal trước khi chạy lại. Không copy kết quả đè lên corpus gốc: cần rà soát và tích hợp riêng.

Đã kiểm tra offline: SHA-256 của các file runtime, preflight năm journal/86 cặp và 58 test. Chưa thực hiện crawl hoặc xác minh mount Colab/Drive thực tế.
