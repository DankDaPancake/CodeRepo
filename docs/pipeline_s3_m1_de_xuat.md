> **Ghi chú lịch sử:** tài liệu này ghi lại đề xuất ban đầu. Chế độ hybrid đã được triển khai sau đó; cấu hình và giới hạn hiện hành nằm trong [hướng dẫn Colab hybrid](huong_dan_colab_hybrid.md). Các câu “chưa triển khai” bên dưới mô tả thời điểm viết đề xuất, không phải trạng thái hiện nay.

# Đề xuất pipeline S3 + arXiv cho Milestone 1

## Mục tiêu và trạng thái

Giảm số request source tới `export.arxiv.org`, đồng thời giữ đầy đủ các version được giao, corpus `.tex`/`.bib` dùng cho M2 và phép đo end-to-end trên Colab CPU. Đây là **đề xuất**, chưa tích hợp vào notebook hiện tại và chưa được xác nhận bằng benchmark đầy đủ trên Colab.

Nguồn tham khảo: [PR #23 — S3 lane](https://github.com/hcmus-arxiv-nhom1/CodeRepo/pull/23), [tài liệu S3 của arXiv](https://info.arxiv.org/help/bulk_data_s3.html) và [đề M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/).

## Phân chia dữ liệu theo snapshot

Snapshot local SHA-256 `7063f0824386733e331be93f4338bd06058a16210195adb22454c11e11288f71` có đủ 20.000 ID đã giao, tổng 26.491 version:

| Range | Tổng paper | Chỉ v1 | Nhiều version | Tổng version |
|---|---:|---:|---:|---:|
| Thiên | 5.000 | 3.886 | 1.114 | 6.396 |
| Tiến | 5.000 | 3.836 | 1.164 | 6.455 |
| Hiếu | 5.000 | 3.657 | 1.343 | 6.717 |
| Đăng | 5.000 | 3.534 | 1.466 | 6.923 |
| **Tổng** | **20.000** | **14.913** | **5.087** | **26.491** |

Các danh sách kết quả quét và snapshot dùng để tạo chúng được lưu ngoài repository trong workspace của người thực hiện. Snapshot là ảnh chụp tại một thời điểm: cần xác nhận hoặc công bố thời điểm chốt version; không mặc định giấy chỉ có v1 vẫn chưa được cập nhật.

## Đề xuất ba chế độ nguồn

Dùng `SOURCE_MODE` riêng với `MODE` của benchmark (`sample`, `partition`, `final`) và tùy chọn lưu trữ (`drive`, `huggingface`). Các giá trị dưới đây là **thiết kế đề xuất, chưa được triển khai**:

| `SOURCE_MODE` | Xử lý source | Thiếu hoặc không xác minh được version | arXiv metadata / references |
|---|---|---|---|
| `arxiv` | Toàn bộ version source qua `export.arxiv.org/src/<id>vN` | Retry theo chính sách và ghi thất bại nếu vẫn thiếu | Discovery snapshot có thể fallback arXiv; references qua Semantic Scholar |
| `arxiv_s3` | Nhóm chỉ-v1 theo snapshot ưu tiên S3 đã xác minh; paper nhiều version dùng `/src/` | Fallback `/src/` khi bundle không có, không đủ mới, không xác định được version, hỏng hoặc lỗi | Discovery snapshot và fallback arXiv; references qua Semantic Scholar |
| `s3` | Chỉ source được chứng minh đúng version từ S3 | Ghi thiếu/chưa xác minh và tiếp tục; **không** giả định dữ liệu mới nhất là các version cũ | Discovery chỉ dùng snapshot đã chốt, không fallback arXiv; references Semantic Scholar có thể vẫn dùng mạng |

`SOURCE_MODE` quản lý **nguồn source**. Với `s3`, chính sách trên còn chủ động tắt arXiv cho discovery để phép thử S3-only không vô tình gọi API arXiv. Cần tách rõ thiết lập `REFERENCES`: `True` vẫn gọi Semantic Scholar, `False` chỉ phù hợp sample và không đạt yêu cầu references đầy đủ. Chỉ thử `/src/` để đối chiếu trong một bước validation riêng, không trộn vào số đo hay nhận dạng `s3`-only.

Quy ước đã thống nhất cho `s3`-only: ghi rõ `source_missing` hoặc `version_unverified`, không dùng `unavailable`/HTTP 404 khi không có bằng chứng từ arXiv. Không silently đổi sang arXiv. Nếu thiếu một version hoặc metadata bắt buộc, QA và `final_complete` phải phản ánh chưa hoàn tất. `arxiv_s3` dùng version fallback sau khi ghi lý do; không khẳng định thành công nếu cả hai nguồn đều thất bại.

Mỗi run ghi mode, cấu hình chính xác, snapshot SHA-256 và mốc chốt version, code revision, manifest S3, bundle và checksum, nguồn/fallback của từng version vào bằng chứng. Đổi mode hoặc revision cần một run ID mới; không thay manifest để ép resume run cũ. Tất cả các chế độ giữ nguyên checkpoint và dữ liệu theo lựa chọn Drive/HF, thống kê và QA cùng định nghĩa. Các run có nguồn hoặc dữ liệu đầu vào khác nhau phải được báo cáo riêng; không gộp thành một benchmark đồng nhất.

Notebook dự kiến cho phép chọn:

```python
SOURCE_MODE = "arxiv"  # "arxiv", "arxiv_s3", hoặc "s3"
MODE = "sample"  # phạm vi benchmark; tách khỏi nguồn
```

Chỉ yêu cầu AWS credentials với hai chế độ có S3, thông qua Colab Secrets, và không ghi secret vào manifest/log. `arxiv` không đọc AWS secret. Các mode có S3 phải hiển thị ước tính dung lượng/chi phí trước bước tải và cần thử với tài khoản được cấp quyền; ước tính và AWS budget alert không phải giới hạn chi phí tức thời.

## Hai phần đề xuất

1. **Nhóm chỉ v1:** đọc manifest S3, chọn bundle chứa ID cần, stream từng `.tar`, kiểm tra checksum, tìm paper, xác minh nội dung có thể gán đúng `v1`, rồi trích chỉ `.tex`/`.bib`. Bài vắng mặt, stale, không xác định được version hay lỗi checksum được đưa vào hàng đợi `/src/<id>v1`.
2. **Nhóm nhiều version:** dùng discovery để xác định số version và lấy từng `v1` đến `vN` qua `/src/<id>vN`; theo dõi retry, 429 và các lỗi khác. Dùng một limiter arXiv chung theo chính sách của nhóm.
3. **Hai phần cùng hợp nhất:** chạy references Semantic Scholar, lưu metadata, versions journal và QA theo cùng data contract. Đầu ra Drive là thư mục `data/corpus/<id>/vN/` cùng metadata/references, có thể dùng cho M2. Ghi nguồn (`s3` hoặc `export`), bản snapshot, manifest, key bundle, checksum và lý do fallback để truy vết.

Nếu mọi bài chỉ-v1 đều có dữ liệu S3 đúng phiên bản, còn tối thiểu 11.578 version source thuộc nhóm nhiều version để tải qua `/src/`. Đây là giới hạn lý tưởng: snapshot stale, paper vắng hoặc lỗi sẽ làm tăng số request. Không cộng thời gian các luồng chạy song song thành wall time end-to-end.

## PR #23 đã làm được gì?

PR đề xuất rộng hơn: lấy **version mới nhất của cả paper nhiều version** từ S3 khi vượt qua kiểm tra stale; lấy các version còn lại qua `/src/`. S3 được stream và kiểm tra MD5 của bundle trước khi ghi nhận kết quả. Theo báo cáo của PR, một bundle có 15/15 paper chưa stale khớp source arXiv từng byte; 5/5 paper được sửa sau snapshot bundle khác bản mới nhất. Thử nghiệm còn giới hạn ở một bundle và local; không suy rộng thành đảm bảo cho tất cả bundle.

PR ước tính từ manifest lúc thử: 144 bundle, khoảng 76,7 GB và 6,9 USD theo giá giả định. **Chưa xác nhận hóa đơn, độ phủ hiện tại, băng thông Colab hoặc tổng chi phí thực tế.** S3 Requester Pays cần tài khoản AWS có thanh toán và quyền đọc; không đưa access key vào notebook hay repo. Thiết lập budget alert và giới hạn thử trước khi tải thật.

Các điểm chưa tương thích với pipeline hiện tại:

- Notebook PR lưu Drive thành `parts/*.tar`, không phải cây thư mục raw đã chốt cho M2. Các lời gọi đóng gói được đọc trong notebook không bao gồm `references.json`; cần sửa và kiểm tra restore thực tế.
- Notebook clone `main` mà không pin revision; các run resume có thể dùng code khác. Chưa tích hợp trực tiếp checkpoint, đo tài nguyên và retry/throttling mới.
- Một số bước chuẩn bị/manifest và đối chiếu S3–arXiv nằm ngoài phạm vi recorder của notebook PR; phải thiết kế lại phạm vi đo và lưu dấu vết.
- Cơ chế checkpoint mới phải xử lý file profiler đang được ghi; lỗi xác minh `profile_samples.csv` từng xảy ra ở run Drive cũ chưa được xác nhận đã sửa.

## Lộ trình kiểm chứng trước full crawl

1. **Xác nhận yêu cầu:** đề M1 giới thiệu S3 nhưng cũng nói từng version lấy qua endpoint versioned `/src/`. Hỏi giảng viên xem pipeline kết hợp S3 cho source v1 có được tính là phương pháp hợp lệ không.
2. **Thử một bundle:** đọc manifest với giới hạn chi phí; chọn paper có v1, paper nhiều version, bài cập nhật sau bundle và PDF-only. So sánh cây file đã lọc và metadata với `/src/idvN`; ghi rõ byte/hash hoặc sai khác và nguyên nhân. Không khẳng định vN nếu không có bằng chứng.
3. **Tích hợp có kiểm thử:** bổ sung lane S3 vào pipeline hiện tại; chọn theo danh sách ID, giữ source provenance, fallback không mất ID, chống đường dẫn độc hại, phát hiện lỗi/tải dở và chỉ checkpoint kết quả đã xác minh.
4. **Checkpoint và khôi phục:** Drive giữ corpus raw, metadata, references, journals và measurement; thử tắt runtime giữa bundle, restore sang runtime mới và QA độc lập; không xóa run cũ.
5. **Benchmark sample rồi full:** CPU-only Colab, đo từ đầu discovery/manifest đến xử lý, lọc, references và checkpoint theo phạm vi công bố; ghi wall time theo paper và end-to-end, peak/mean RAM, peak disk kể cả file tạm, dung lượng đầu ra, lỗi, retry và chi phí. Sample không thay thế kết quả trên toàn bộ tập được giao.
6. **Reconcile:** xác nhận không trùng/thiếu ID và version; phân biệt `ok`, `no_tex`, `unavailable`, `failed`, stale và fallback. Bảo toàn bằng chứng nếu nguồn không cung cấp version.

Chưa được phép kết luận tỷ lệ paper S3 phủ thực tế, tốc độ ước tính, chi phí cuối hay tuân thủ đầy đủ yêu cầu M1 chỉ từ số lượng version trong snapshot.
