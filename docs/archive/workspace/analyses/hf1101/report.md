# Smoke Hugging Face — 100 ID Đăng, 01/11/2026

Kết luận: lượt crawl mới hoàn tất theo evidence xuất từ Colab. Chưa kiểm chứng restore ở runtime mới và chưa đọc trực tiếp Dataset private để kiểm tra raw files.

## Phạm vi và dữ liệu

- Run: `m1-hf-smoke-dang-100-01`, code `8636ba0915ddd7938739d31d90234a54857fab2a`.
- Đúng 100 ID `2604.20535`–`2604.20634`; snapshot index đủ 100, checksum index đúng.
- Snapshot dự kiến 130 version; journal có đúng 130 bản ghi duy nhất, không thiếu/thừa: 123 `ok`, 7 `no_tex` (PDF). 94 bài có TeX. PDF-only không phải crawl thất bại.
- Journal kê 445 file source, 18.099.631 byte; status/kind/file list/bytes_before/bytes_after khớp hoàn toàn lượt snapshot trước. Đây là kiểm tra journal, không phải đọc lại file raw trên HF.
- QA source/report và failed.csv đều 0 dòng lỗi. References 100/100 `ok`, 3.865 citations; metadata đầy đủ 88,15% citations, không phải 100%.
- Không có primary/cleanup error. `final_complete=false` đúng vì đây là sample.

## Thời gian và tài nguyên

| Chỉ số | Lượt snapshot + Drive trước | Lượt snapshot + HF |
|---|---:|---:|
| Pipeline profiler | 602,03 s | 437,65 s |
| Toàn phiên sampler | 635,36 s | 502,10 s |
| Bình quân sampler / ID | 6,354 s | 5,021 s |
| Discovery gồm chuẩn bị index | 27,6 s | 54,0 s |
| Peak RSS toàn phiên | 189,95 MB | 260,91 MB |

Lượt HF giảm 21,0% wall sampler, 27,3% pipeline. Chưa thể quy toàn bộ cải thiện cho HF: khác code revision, snapshot và mạng. Trước đây source có gián đoạn tải; lượt HF arXiv 131 request đều 200, không retry/backoff, min gap 3 s. Tốc độ hiện tại phần lớn bị giới hạn bởi khoảng nghỉ request: 130 version cần khoảng 390 s với nhịp 3 s/request.

Discovery HF: 25,634 s chuẩn bị snapshot + 28,4 s discovery chunk; gần 27,94 s ở một API batch bổ sung metadata của 30 version cũ. Dùng snapshot vẫn có request bổ sung title/authors lịch sử.

Peak disk mới 5.708,68 MB (~5,71 GB), đã gồm input snapshot và HF staging/cache. Số 20,5 MB lượt trước không tính snapshot nên không so trực tiếp. Output corpus khoảng 19,82 MB; source TeX/Bib riêng 18,10 MB.

Sampler có 467 mẫu trong 17 segment, kiểm tra lại thứ tự/checksum hợp lệ. Measurement và 100 paper lifecycle đều complete. Peak là quan sát lấy mẫu, không phải cực đại liên tục.

## Đồng bộ và giới hạn chứng cứ

7 checkpoint events, tổng duration 51,63 s. Periodic 15,04 s và post-chunk 12,77 s. Tổng này gồm 10,03 s evidence-publication sau sampler; không cộng tất cả vào wall. Corpus sync đã nằm trong sampler. Session totals ghi 527,04 s do clock bắt đầu trước manifest hashing; sampler 502,10 s bắt đầu sau bước đó. Cả hai chưa tính tải Kaggle/cài môi trường; sampler dừng trước final telemetry publication và evidence re-export/upload.

Semantic Scholar có 3 HTTP 429, lần 4 thành công, references tổng 21,7 s và chạy song song source. `retry_backoff_wait=0` trong benchmark_summary không chứng minh toàn pipeline không retry: trường này không phản ánh các retry S2 trong lượt này. references_stats.csv giữ đúng 3 lần 429.

SHA snapshot mới `97a7fee00eac38ee5ea92d5cddae351cf3cbb444775a397ac60efb773f217b10`, khác bản trước `7063f0824386733e331be93f4338bd06058a16210195adb22454c11e11288f71`. Riêng tập 100 ID, danh sách version và ngày version vẫn giống hoàn toàn. Khi resume phải giữ đúng bytes mới này hoặc tải đúng Kaggle version; tải latest sau này có thể bị từ chối vì SHA đổi.

## Trước full crawl

Nên thực hiện một smoke resume ở runtime mới với cùng RUN_ID/config/snapshot và RESUME=True. Lượt sạch đã release shift; chỉ dùng TAKEOVER khi marker còn active và đã xác nhận runtime cũ dừng. Restore phải đọc checkpoint đã publish, xác minh SHA raw files, bỏ qua chunk đã QA đạt, vẫn ra 100 bài/130 version. Đây mới kiểm chứng bàn giao/reset thực tế, điều mà một lượt fresh crawl chưa chứng minh.

Không sửa source code hoặc dữ liệu smoke trong lần phân tích này. Facts chi tiết ở `facts.json` cùng thư mục.
