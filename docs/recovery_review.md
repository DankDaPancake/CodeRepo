# Chạy Colab

Tạo runtime từ checkout chứa mã recovery và năm journal:

```bash
python -m src.benchmark.package_recovery --evidence ../final_evidence --output src/artifacts/recovery-colab-kit/recovery-runtime.zip
```

Upload ZIP lên `MyDrive/recovery-colab-kit/`; mở các notebook trong `src/notebooks/` bằng Colab. Chạy cell từ đầu, kiểm tra preflight rồi đổi RUN_NETWORK thành True. Kết quả nằm trong `MyDrive/recovery-colab-kit/results/`. Chỉ chạy notebook retry; không dùng đồng thời hai runtime cho cùng output. Khi arXiv chặn, retry ghi `inconclusive` rồi dừng; đợi hết thời gian chặn trước khi resume.

# Kiểm chứng S3 v1 và retry unavailable

Notebook `src/notebooks/arxiv_nhom1_recovery_metadata.ipynb` đã ngừng sử dụng: nhóm chấp nhận không kiểm chứng lại metadata S3 v1. Các cell bị chặn để tránh chạy nhầm; giả định version từ timestamp vẫn chưa được xác minh. Dùng `arxiv_nhom1_recovery_retry.ipynb` cho unavailable, với năm JOURNALS và OUTPUT riêng. Mặc định RUN_NETWORK=False. Không chạy nhiều runtime cùng ghi một output.

Kết quả kiểm chứng metadata cũ, nếu có, chỉ là bằng chứng lịch sử: `compatible` chỉ nói chronology phù hợp, không chứng minh nội dung S3 là v1. Không gán múi giờ phỏng đoán cho evidence.

Retry giữ đúng cặp ID/version cùng danh sách original_runs. HTTP 404/410 theo downloader thành unavailable; lỗi mạng thành inconclusive; archive hỏng sau các lần tải thành corrupt. Journal append + fsync, manifest kiểm tra hash đầu vào, hash từng file dùng cho resume. Nếu mất điện làm hỏng dòng cuối, dừng để kiểm tra thay vì âm thầm bỏ record.

## Thử tích hợp trên bản sao

Chỉ dùng một tập nhỏ kết quả đã được nhóm xem xét. Chuẩn bị thư mục staging với layout giống run gốc, ví dụ corpus/ và work/versions.jsonl. Không đưa manifest hoặc summary của retry vào staging. Giữ trường hashes và đúng thư mục corpus/<paper>/vN cho từng record. Hàm từ chối thư mục thiếu hoặc hash không khớp cả trước tích hợp và sau restore. Chỉ chọn record ok/no_tex đã kiểm tra; chưa kết luận không được coi là khôi phục thành công.

```python
from pathlib import Path
from src.benchmark.recovery_review import measure_integration
report = measure_integration(
    Path('/content/drive/MyDrive/original-run'),
    Path('/content/drive/MyDrive/recovery-staging'),
    Path('/content/drive/MyDrive/integration-experiment-new'),
)
print(report)
```

Output phải chưa tồn tại, ba đường dẫn phải rời nhau. Hàm copy run, overlay staging và gộp trạng thái journal theo key; tạo checkpoint ZIP, restore, so hash và đọc lại journal. Báo restore_s, update_s, checkpoint_s, restore_verify_s, qa_s. Đây là kiểm tra filesystem/journal, chưa phải QA nội dung parser. Chạy QA chuẩn của pipeline trên restored trước khi đề xuất cập nhật run thật. Không sửa run thật. Chưa có phép đo Drive thực tế thì không suy ra thời gian tích hợp trên Drive.
