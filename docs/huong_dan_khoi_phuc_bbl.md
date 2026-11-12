# Chạy khôi phục .bbl trên Colab

1. Từ thư mục CodeRepo, tạo ZIP bằng `python -m src.benchmark.package_recovery --evidence ../final_evidence --output src/artifacts/bbl-recovery-kit/recovery-runtime.zip`. Năm journal phải có sẵn tại `../final_evidence`; ZIP chứa evidence và không được commit. Tạo `MyDrive/bbl-recovery-kit/`, rồi upload ZIP vào đó.
2. Mở `arxiv_nhom1_bbl_recovery.ipynb` trong Colab và chạy từng cell; mount Drive khi được yêu cầu.
3. Preflight mặc định không crawl: kiểm tra 5 journal, 1.847 paper, 2.297 version. Đây là tập có dấu vết .bbl từng bị loại, không phải tất cả paper thiếu .bib.
4. Chỉnh `RUN_NETWORK = True`, giữ `LIMIT = 10`, chạy lại cell cấu hình và cell crawl. Xem file, journal và summary ở `MyDrive/bbl-recovery-kit/results/run-01/`.
5. Khi đã xem 10 version, đổi `LIMIT = None`, chạy lại cell cấu hình và cell crawl để tiếp tục toàn bộ. Chỉ dùng một runtime cho output này. 2.297 request cần ít nhất khoảng 115 phút cộng thời gian tải và retry; có thể cần nhiều phiên Colab.

Resume bằng cách chạy lại notebook với cùng ZIP và output. File đã khôi phục chỉ được bỏ qua khi hash khớp; kết quả không kết luận được thử lại. `no_bbl` và `unavailable` sẽ không tự thử lại trong cùng output; nếu cần lần thử mới, đổi tên thư mục output. Nếu Colab bị ngắt và `.running` còn tồn tại, chỉ xóa thư mục khóa sau khi kiểm tra không có phiên khác đang chạy. Nếu journal bị hỏng, giữ nguyên để kiểm tra.

`files/<paper>/vN/` chứa .bbl; `versions.jsonl` lưu trạng thái, provenance và hash; `summary.json` thống kê. `unsafe_or_limit` là cần xem xét, không phải bằng chứng không có .bbl. Kết quả lưu riêng, chưa được nhập vào corpus/M2. Version v1 từ S3 trước đây là suy luận; không khẳng định archive v1 tải từ arXiv trùng byte với S3.
