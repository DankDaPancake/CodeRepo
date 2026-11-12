# Kế hoạch: Trực quan hóa kết quả M1 và mô tả Drive shortcut

## Mục tiêu và phạm vi

Bổ sung ba nhóm biểu đồ đã thống nhất vào Jupyter Book M1, dùng evidence của năm run. Giải thích Drive shortcut giúp các tài khoản thành viên truy cập cùng thư mục crawl chính khi chạy nhiều session. Không thay đổi crawler, dữ liệu trên Drive hoặc kết luận QA chưa có chứng cứ.

## 1. Chuẩn bị dữ liệu có thể tái lập

- Cập nhật `arxiv-book/scripts/collect_final_m1.py`: xuất thêm CSV theo run từ năm `work/versions.jsonl` và năm `request_timeline.csv`; bổ sung SHA-256 nguồn vào `data/m1/final/provenance.json`.
- Tính trạng thái version từ bản ghi cuối của từng `(paper ID, version)`, đối chiếu với manifest và snapshot, không cộng trùng retry. Xuất `version_status_by_run.csv` với `run,status,versions`; tổng theo run và toàn nhóm phải khớp journal/snapshot.
- Tạo `reference_status_by_run.csv` từ năm `papers_stats.csv`, thể hiện số paper theo `ref_status`; tính tỷ lệ reference có S2 ID và đủ trường theo số reference thực sự được ghi nhận, tách mẫu số khỏi số paper. Không quy `not_found` thành 0 reference thực tế.
- Gộp năm `request_timeline.csv` thành `request_timeline_by_run.csv`, giữ `run`, phút UTC, 429, 5xx và backoff theo đúng schema export. Không ghép run trùng hoặc suy diễn thời gian chính xác tới từng request từ dữ liệu một phút. Kiểm tra dữ liệu nguồn của từng run, đánh dấu bất kỳ cột/file thiếu thay vì mặc định là 0.
- Không đưa raw corpus, access token hoặc URL bí mật vào Book. Các CSV/biểu đồ được sinh hoặc hiển thị từ input đã kiểm tra; giữ provenance cho mỗi nguồn.

## 2. Data Statistics: source và reference

- Trong `m1/02-data-stats.ipynb`, thêm biểu đồ cột chồng theo run cho `ok`, `no_tex`, `unavailable` và các trạng thái chưa được ghi nhận nếu thực sự có; hiển thị số version và ghi rõ version là đơn vị đếm. Tổng hiện dự kiến: 25.041, 1.364 và 86; xác nhận lại bằng script khi chạy.
- Thêm biểu đồ reference theo run gồm hai góc nhìn được đặt riêng: trạng thái danh sách theo paper và tỷ lệ metadata theo reference đã ghi nhận. Đặt mẫu số và trạng thái `not_found` rõ ràng; `ok` không có nghĩa tất cả metadata reference đầy đủ.
- Tránh để quy mô only-v1 che khuất bốn run multiversion: cung cấp tỷ lệ cạnh số tuyệt đối hoặc biểu đồ tỷ lệ phù hợp, ghi rõ mẫu số. Không dùng tỷ lệ để che số lượng thiếu.

## 3. Performance: 429 và backoff

- Trong `m1/03-performance.ipynb`, thêm biểu đồ theo thời gian UTC và run cho số HTTP 429 của arXiv theo phút, cùng backoff được trích log theo phút; dùng hai trục hoặc hai panel để không lẫn đơn vị. Có thể hiển thị phiên chồng lấp cùng timeline. Exporter lọc nguồn cho mã HTTP nhưng nhận diện backoff theo mẫu log; kiểm tra ngữ cảnh trước khi quy mọi dòng backoff cho một dịch vụ.
- Ghi rõ các con số phụ thuộc log và logic exporter, không nhất thiết gồm mọi retry Semantic Scholar hoặc request ngoài phạm vi; backoff đã nằm trong thời gian chạy và không được cộng thêm vào sampler wall.
- Kiểm tra timeline so với `run.log` gốc tại một số mốc và đối chiếu tổng với các CSV summary nếu cùng phạm vi; giải thích nếu không khớp, không ép khớp bằng cách bỏ dữ liệu.

## 4. Drive shortcut và chạy đồng thời

- Trong `m1/01-methodology.md`, mở rộng đoạn đã có: tài khoản crawl chính chia sẻ thư mục, thành viên tạo shortcut trong My Drive của mình, mount tài khoản tương ứng trên Colab và chọn đường dẫn tới cùng thư mục đích; mỗi run có thư mục/run ID riêng để tránh ghi đè.
- Giải thích shortcut giúp nhiều runtime có quyền truy cập cùng kho chung; shortcut không tự nhân bản corpus, không tự cấp quyền, không tạo limiter arXiv dùng chung và không bảo đảm tốc độ đồng bộ. Phân biệt sơ đồ tổ chức này với bằng chứng độc lập về từng tài khoản/IP; các chi tiết chưa xác minh được ghi là chưa có evidence.
- Dẫn từ Discussion hoặc Performance tới Methodology khi giải thích việc tổng hợp timeline; không tạo lại lịch theo dõi runtime.

## 5. Kiểm tra và bàn giao

1. Chạy collector với evidence local, kiểm tra không thiếu/trùng ID, version và nguồn timeline, kiểm tra hash provenance. Kiểm tra tổng trạng thái và reference theo run cộng lại khớp bảng toàn nhóm.
2. Kiểm tra một vài dòng 429/backoff gốc, xác nhận `minute_utc` và đơn vị, thử dữ liệu rỗng/mẫu số 0 và phân biệt giá trị thiếu.
3. Chạy notebook Data Statistics và Performance trên bản sao; build Jupyter Book với execution, xác nhận biểu đồ/bảng được tạo khi build, không phải screenshot.
4. Kiểm tra thay đổi cục bộ, giữ nguyên chỉnh sửa sẵn có; báo những giới hạn, link file và kết quả kiểm tra. Không commit/push nếu chưa được yêu cầu.
