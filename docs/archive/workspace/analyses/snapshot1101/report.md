# Kiểm chứng smoke snapshot ngày 01/11/2026

## Kết luận

Run mới đã xử lý đủ **100/100 paper, 130/130 version** theo snapshot được ghim; corpus thực tế khớp journal. Phạm vi là 2604.20535–2604.20634, offset 0, count 100, chunk 100. Đây không phải smoke 200 ID và chưa phải benchmark final 20.000 ID.

Nguồn: bench_results_new/work, bench_results_new/book_csv, data_snapshot1101/corpus; đối chiếu độc lập với snapshot gốc trong CodeRepo và 100 ID đầu tương ứng của bench_results_old. Không sửa dữ liệu đầu vào.

## Đủ version và file thật

- Snapshot gốc yêu cầu 130 version; journal có đúng 130 dòng và 130 cặp ID/version duy nhất, không thiếu/thừa.
- 100 folder paper và đủ các folder vN theo snapshot; không có paper ngoài tập yêu cầu.
- 123 version ok có source TeX, 7 version no_tex đều được nhận diện PDF và có thư mục rỗng; không có failed/unavailable trong lượt này.
- 445 source files, tổng 18.099.631 bytes; tên file và bytes_after của từng version khớp journal. Đây là đối chiếu tồn tại/danh sách/kích thước, không phải xác nhận hash source so với máy chủ arXiv.
- Số version và ngày của từng version trong metadata.json khớp snapshot gốc. Cả 130 version có title/authors không rỗng; request lịch sử 30 version đã thành công trong một batch API.
- Chạy lại validate_range với journal và require_references=True trên corpus tải về: kiểm tra 100 paper, không có issue.
- 100/100 references.json có status ok, tổng 3.865 citations. Theo CSV, 88,15% citation đủ S2 ID + title + authors + date/year; không đồng nghĩa mọi citation có metadata đầy đủ.
- Trạng thái, kind, danh sách file, bytes_before và bytes_after của 130 version khớp journal của cùng 100 ID ở lượt cũ.

7 version PDF-only: 2604.20545v1, 2604.20546v1, 2604.20547v1, 2604.20547v2, 2604.20548v1, 2604.20558v1, 2604.20605v1. Chúng thuộc 6 paper không có TeX; 94/100 paper có ít nhất một version TeX.

## Timing và so sánh đúng phạm vi

| Chỉ số | Lượt cũ, 100 ID đầu | Lượt snapshot, cùng 100 ID |
|---|---:|---:|
| Pipeline profiler | 895,38 s | 602,03 s |
| Pipeline / paper | 8,95 s | 6,02 s |
| Discovery trong chunk | 3,7 s | 0,6 s |
| arXiv requests | 213 | 132 |
| HTTP 429 | 43 | 0 |
| Body cuts | 37 | 1 |

Pipeline giảm 293,35 s, tương đương 32,76%. Không so 100 ID mới với tổng 200 ID cũ. Không so mean_download_s cũ với mới vì revision cũ có timer từng thành phần bị cộng trùng.

Snapshot preparation trong Colab tốn 26,975 s. Discovery tổng có tính index là 27,6 s, cao hơn 3,7 s ở lượt cũ này. Do đó không được kết luận mức cải thiện 32,76% hoàn toàn do tăng tốc discovery: lượt mới có điều kiện mạng tốt hơn rõ rệt, ít retry/resume hơn, đồng thời code/checkpoint cũng khác.

Full-session wall mới 635,359 s (~10 phút 35 s), trung bình 6,354 s/paper. Pipeline 602,03 s đã gồm periodic checkpoint 9,868 s; checkpoint ngoài pipeline 4,364 s. Không cộng các số này lại vào E2E lần nữa. Tạo index đã nằm trong session wall. Upload/copy snapshot và xác minh manifest ban đầu là setup ngoài phạm vi này.

## Measurement và giới hạn trước fullcrawl

- Recompute session_report và paper_timing_report: complete=true, 100 lifecycle hoàn tất, không có lỗi segment/timing. timing_audit và cleanup_errors khớp: không lỗi cleanup.
- SHA-256 index checkpoint khớp manifest index; nguồn snapshot được ghi SHA-256 7063f0824386733e331be93f4338bd06058a16210195adb22454c11e11288f71, giống bản local đã kiểm tra.
- Peak RSS full-session 189,95 MB; mean 186,09 MB. Peak chunk RSS 55,5 MB là phạm vi khác, không thay cho full-session RSS.
- **disk_max=20,50 MB chỉ tính thư mục run/work hiện được monitor; chưa tính snapshot 5.649.388.235 bytes ở /content.** Không dùng 20,50 MB làm peak disk toàn pipeline trong Book. Chỉ riêng input snapshot + run peak đã khoảng 5,67 GB, chưa kể repo/cache hoặc bản sao khác. Cần sửa scope disk trước final benchmark.
- complete=true của sample là đúng; final_complete=false cũng đúng do đây chỉ là 100 ID sample. Kết quả không chứng minh đủ 20.000 ID hoặc không có version mới sau ngày snapshot.
- Snapshot discovery đạt smoke này; backend Hugging Face và khả năng resume sau runtime loss chưa được smoke này kiểm chứng.

Chi tiết machine-readable: facts.json. Script tái kiểm chứng: audit.py (chạy từ workspace root bằng Python của CodeRepo).
