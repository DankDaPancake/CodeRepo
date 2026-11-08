# Kế hoạch tách notebook tải S3 bulk

**Mục tiêu:** Tạo notebook Colab độc lập xác định các bundle ứng viên cho toàn bộ 20.000 ID nhóm được giao, tải và benchmark arXiv bulk về Drive; các notebook crawl dùng bundle đã chuẩn bị và không tự tải S3.

**Phạm vi dự kiến:** tách logic tải khỏi `src/notebooks/arxiv_nhom1_only_v1_benchmark.ipynb` và `src/notebooks/arxiv_nhom1_s3_arxiv_benchmark.ipynb`, vì cả hai đang có cell `Optional: prepare S3 source bundles on Drive`. Notebook arXiv và multiversion không tải bulk. Không thay đổi run đang chạy, dữ liệu, cấu trúc Drive hoặc crawler phía sau.

**Kế thừa:** [Kế hoạch benchmark tải S3](2026-11-05-benchmark-tai-s3.md); mặc định đề xuất là tải về local Colab, kiểm tra MD5, sau đó copy Drive. Các lựa chọn chưa thống nhất trong kế hoạch cũ vẫn là đề xuất, không coi là quyết định của nhóm.

## Giao diện và ranh giới

- Notebook mới `src/notebooks/arxiv_nhom1_s3_download_benchmark.ipynb`: cấu hình directory riêng, mặc định chọn toàn bộ 20.000 ID được giao theo snapshot và bốn dải thành viên; hỗ trợ giới hạn phạm vi hoặc danh sách bundle cho smoke. Mount Drive, cài dependencies, nạp AWS Secrets, preview, tải có xác nhận bằng cờ cấu hình, tiến độ, kiểm tra và báo cáo benchmark. Mặc định chỉ preview, không phát sinh tải có phí.
- Đọc snapshot và manifest bằng `parse_manifest`/`select_bundles` trong `src/crawler/s3_prepare.py`; lựa chọn theo khoảng manifest là **bundle ứng viên**, không phải index chính xác paper → bundle, không chứng minh sự hiện diện hay version. Hỗ trợ danh sách bundle rõ ràng cho smoke. Có thể index nội dung sau khi tải nếu cần, nhưng không khẳng định trước khi đọc archive.
- Với phạm vi chính thức, xác minh tập đầu vào có đúng 20.000 ID duy nhất, khớp bốn dải được giao và snapshot; báo ID thiếu, trùng hoặc ngoài dải và dừng trước tải nếu không khớp. Ghi hash snapshot, manifest, danh sách ID và tham số chọn. Phạm vi smoke được ghi nhãn riêng và không được báo là 20.000 ID đầy đủ.
- Lập bảng ID → mọi bundle ứng viên theo các khoảng `first_item`/`last_item`, gồm các khoảng chồng lấn; liệt kê bundle đầu/cuối của từng tháng, tổng số bundle, ước lượng kích thước, bundle có sẵn/thiếu và ID không được phủ. Mặc định không tải nếu ID nào không được phủ hoặc manifest/boundary không hợp lệ; có thể mở rộng hay sửa manifest rồi chạy lại, không âm thầm bỏ qua ID.
- Kiểm tra riêng giới hạn của `select_bundles`: code hiện tại chỉ xét bundle có tháng trong tên trùng tháng ID. Phải xác minh điều kiện này phù hợp với manifest và mục đích thu thập, đặc biệt paper cũ được cập nhật trong tháng khác; nếu không chứng minh được, thiết kế bộ chọn bảo thủ bao phủ mọi bundle có khoảng chứa ID và báo rõ các trường hợp không xác minh được. Không suy luận rằng hai bundle đầu/cuối tạo thành một dải liên tục không có lỗ.
- Sau khi tải, đọc index các member của bundle để báo paper xuất hiện, không tìm thấy hoặc mơ hồ; đây là kiểm tra sự hiện diện, không chứng minh version chính xác. Dù 20.000 ID được dùng để lập phạm vi tải, notebook only-v1 chỉ dùng S3 cho nhóm v1 của snapshot; multiversion vẫn dùng các request version-specific theo pipeline hiện tại.
- Dùng AWS Requester Pays và secrets; không in credentials. Hiển thị số bundle, tổng kích thước theo manifest (chỉ ước lượng), dung lượng local và chi phí có thể phát sinh trước tải; cho phép đặt giới hạn số file/bytes. Không tải, xóa hoặc ghi đè bundle sẵn có ngầm.
- Đầu ra là bundle và manifest tương thích đường dẫn hiện có (`S3_BUNDLE_DIR`, `S3_EXISTING_MANIFEST`); log và benchmark nằm trong thư mục run tải riêng, không đụng `data/corpus` hay `work` của crawler. Tên thư mục cụ thể và cấu hình Drive hiện tại được giữ, có thể điều chỉnh bằng cell directory.
- Trong only-v1 và hybrid, loại bỏ AWS secrets, boto3 fetch manifest, `S3_DOWNLOAD`, `download_bundle` và cell tạo log tải. Giữ đọc manifest local, chọn candidate, kiểm tra bundle và lập S3 index phục vụ crawl. Thiếu bundle phải hiển thị danh sách và giữ fallback arXiv theo hành vi tương ứng hiện có; không làm thay đổi phạm vi ID hay resume. Không tự tải từ S3.
- Manifest MD5 đối chiếu bytes bundle; kích thước thực tế có thể khác manifest. Đóng file hoặc đọc lại trên cùng Drive FUSE không chứng minh cloud đã đồng bộ bền vững. Chỉ gọi bundle `reused_verified` sau khi xác minh thích hợp; `downloaded`, `reused`, `failed`, `incomplete` được báo riêng.

## Các bước triển khai sau khi plan được duyệt

### 1. Khảo sát và hợp đồng

- [ ] Đọc `s3_prepare.py`, các caller, notebook only-v1/hybrid, config và test hiện có; xác định chính xác logic đọc manifest/indexing cần giữ. Ghi lại output paths hiện được crawler tiêu thụ và các đường dẫn shared Drive; không đổi mặc định tùy tiện.
- [ ] Chốt input snapshot, danh sách bundle tùy chọn, run ID, giới hạn, output manifest/bundles và log; dùng cùng định nghĩa candidate/fallback hiện có. Không tạo dependency mới giữa các run crawl.
- [ ] Tái sử dụng danh sách bốn dải và cách lọc của pipeline, kiểm tra chính xác 20.000 ID duy nhất và xuất ID → candidate, danh sách không được phủ, overlap, bundle đầu/cuối và tổng dung lượng. So sánh bộ chọn hiện tại với manifest có bundle khác tháng ID; không giữ điều kiện lọc tháng nếu nó bỏ sót candidate phù hợp với phạm vi yêu cầu.

### 2. Notebook tải và benchmark

- [ ] Tái sử dụng `parse_manifest`, `select_bundles`, `download_bundle` khi phù hợp; nếu cần thay helper, giữ tương thích caller và ghi test cho checksum sai, size khác nhưng MD5 đúng, file đích đã tồn tại, lỗi download, gián đoạn và khôi phục.
- [ ] Tạo cell riêng cho config directory và config còn lại; mount Drive, nạp Secrets chỉ khi thực sự gọi S3. Preview danh sách và chi phí tiềm năng; mặc định không tải.
- [ ] Hiển thị progress tổng bundle và byte của bundle đang tải; phát hiện disk thiếu; tải vào file tạm local, kiểm MD5, copy qua file tạm trong thư mục đích và công bố tên sau khi hoàn tất; không tuyên bố atomic/cloud durable từ FUSE.
- [ ] Ghi JSONL từng bundle, summary CSV/JSON và input hashes, revision, UTC, trạng thái. Đo `selection_s`, `download_s`, `verify_local_s`, `copy_to_drive_s`, `session_wall_s`, bytes thực tế/manifest, tốc độ và resource peaks nếu sampler sẵn có; nêu ranh giới và không cộng các khoảng thời gian lồng nhau. Bundle dùng lại không đưa vào throughput tải mới.

### 3. Đơn giản hóa notebook crawl

- [ ] Bỏ phần tải và AWS authorization trong cả only-v1 lẫn hybrid; giữ nguyên S3 selection/index và fallback. Cung cấp cell preflight đọc bundle/manifest có sẵn và thông báo cách chạy notebook tải khi thiếu.
- [ ] Kiểm tra cấu hình cũ và resume: cùng manifest/run ID/revision không bị thay đổi ngầm. Version code đã lưu khi resume vẫn là nguồn chân lý; không sửa run cũ.
- [ ] Cập nhật hướng dẫn teammate và mirror notebook trên book khi các notebook vận hành được chốt; không tự ý cập nhật mirror trước khi xác định revision và quy trình đồng bộ.

### 4. Kiểm chứng

- [ ] Test với S3/Drive giả lập: manifest rỗng hoặc phạm vi không phủ ID, checksum sai, bundle đã có, lỗi giữa chừng, disk thiếu, resume và summary có `reused`/`failed`; kiểm tra không gọi AWS khi preview hoặc khi chạy notebook crawl.
- [ ] Test 20.000 ID với dải liên tục và không liên tục, ID thiếu/trùng, khoảng manifest chồng lấn hoặc có lỗ, ID ở đúng ranh giới, bundle trùng khoảng nhưng khác tháng, và trường hợp file member không xuất hiện dù nằm trong khoảng. Smoke giới hạn không được ghi nhầm là chạy đủ.
- [ ] Kiểm tra notebook JSON và chạy test liên quan; xác nhận snapshot → bundle selection vẫn chỉ là candidate, fallback, progress bar và output manifest tương thích crawler.
- [ ] Smoke Colab sau khi thống nhất phạm vi, dùng folder thử riêng và giới hạn rõ; ghi số bundle, phí nếu có, thời gian thực tế và giới hạn. Chưa smoke hoặc phát sinh AWS chỉ bằng việc lập plan.

## Quyết định cần chốt trước smoke

1. Benchmark bằng bundle còn thiếu hay tải mẫu mới vào folder thử? Nếu mẫu, số bundle và cách chọn.
2. Chỉ đo phương án local → Drive hay cần đo thêm ghi trực tiếp Drive? Phương án mặc định đề xuất là local → Drive.
3. Đường dẫn lưu báo cáo benchmark cuối và giới hạn chi phí/số bundle cho lần smoke.
