# Kế hoạch chốt M1 và tiếp tục M2

> Phạm vi: kết luận M1 theo bằng chứng hiện có; chuẩn bị, chạy và đánh giá M2. Đây là kế hoạch, chưa phải bằng chứng chạy M2 chính thức.

> **Cập nhật:** Phương án staging/chép `.bbl` vào bản corpus ở phần 2–3 bên dưới đã được thay thế. Dùng [kế hoạch M2 hai nguồn đầu vào](2026-11-13-m2-readiness-to-full-run.md): parser đọc corpus và recovery từ hai đường dẫn riêng trong cùng lần chạy.

**Mục tiêu:** Giữ kết quả benchmark crawl M1 nguyên trạng, sử dụng `.bbl` recovery như dữ liệu bổ sung có provenance cho M2, và tạo kết quả M2 đầy đủ, có thể kiểm tra và tái lập.

**Tài liệu yêu cầu:** `docs/m1_requirements.md`, `docs/specs/0005-m2-runner.md`, [đề M2](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/). Book là repo `../arxiv-book`, không di chuyển các tệp của Book.

## Baseline và giới hạn

- Năm run M1: 20.000 ID, 26.491 version trong snapshot, gồm 25.041 `ok`, 1.364 `no_tex`, 86 `unavailable`; 18.878 paper có ít nhất một version TeX. Đây là kết quả tổng hợp journal/export, chưa phải kiểm tra đọc lại mọi file.
- Retry 86 version `unavailable` vẫn nhận 404. Không khẳng định paper không tồn tại hoặc không có nguồn khác. Version v1 lấy từ S3 là suy luận có điều kiện theo snapshot/bundle; không xác minh metadata lại theo quyết định đã chốt.
- Recovery riêng: 2.296/2.297 version, 1.846 paper, 2.332 tệp; 2606.08140v1 HTTP 404. Kết quả thuộc tập có bằng chứng `.bbl` bị loại, không phải toàn bộ paper thiếu `.bib`. Năm tệp được kiểm tra hash lấy mẫu; chưa kiểm toàn bộ.
- Đóng băng số liệu, thời gian, dung lượng và phạm vi benchmark crawl M1: không cộng tải, lưu trữ hay kết quả `.bbl` recovery vào bất kỳ metric crawl nào. Nêu recovery tại M2, kèm phương pháp, nguồn, giới hạn và chi phí riêng.
- Chưa xác nhận tính nguyên vẹn toàn corpus Drive; thời gian sampler không bao gồm chuẩn bị S3 trước đó và setup/hoạt động ngoài khoảng đo. Hai audit gốc báo không hoàn chỉnh vẫn giữ; controlled rerun giải thích được khác biệt do bố trí evidence nhưng không chứng minh nguyên nhân runtime gốc.
- Book M2 hiện xuất số liệu mẫu 100 paper / 130 version trên Windows, không phải kết quả 20.000 paper trên Colab. Không suy rộng tốc độ hay chất lượng từ mẫu.

## 1. Hoàn thiện bàn giao M1

- [ ] Trong Book M1, giữ kết quả năm run và giới hạn trên; ghi rõ retry 86/86 vẫn 404, link nguồn evidence, không đưa số recovery `.bbl` vào bảng/biểu đồ benchmark. Giữ nguyên cờ timing gốc và mô tả điều kiện controlled rerun.
- [ ] Phân biệt hoàn tất phạm vi snapshot theo journal với xác minh đầy đủ nội dung, usable TeX và metadata; không tuyên bố đã kiểm chứng toàn bộ corpus hoặc mọi version sau snapshot.
- [ ] Xác thực các liên kết Book, provenance của CSV và build Book; đối chiếu đầu ra trang M1 với 20.000 / 26.491 và 25.041 / 1.364 / 86. Ghi nhận các thiếu sót còn lại thay vì thay số hoặc chạy lại benchmark.

**Điều kiện chốt:** có thể chốt thu thập/benchmark M1 theo phạm vi và giới hạn đã công bố; không kết luận mọi tiêu chí chất lượng hoặc integrity đều đạt nếu thiếu evidence. Audit khi restore là cổng đầu vào M2, không thay đổi kết quả M1.

## 2. Cổng đầu vào M2 và tích hợp `.bbl`

**Tệp dự kiến:** `src/notebooks/arxiv_nhom1_m2_parse_benchmark.ipynb`, module mới dưới `src/benchmark/` cho staging `.bbl`, tests tương ứng, `docs/specs/0005-m2-runner.md`, hướng dẫn chạy. Giữ original Drive corpus và journal bất biến.

- [ ] Chốt input gồm năm checkpoint gốc và run recovery `run-01`; ghi ID, revision, hash `INDEX.json`, manifest, `candidates.json`, `versions.jsonl` và summary, thời điểm, số lượng vào manifest M2. Không sửa contract corpus gốc.
- [ ] Restore năm checkpoint vào vùng local; xác thực hash theo INDEX và kiểm tra đủ đúng 20.000 ID, không trùng giữa roots, version theo journal. Kiểm tra dung lượng local, output và Drive trước khi chạy; báo lỗi rõ nếu thiếu/không truy cập được. Không coi journal là kiểm chứng file.
- [ ] Dựng bước staging trên bản corpus đã restore: đọc record cuối theo `(arxiv_id, version)`, chỉ dùng `recovered`; xác minh đường dẫn tương đối an toàn, ID/version thuộc một root đúng, kích thước và SHA-256 từng tệp, không ghi đè tệp tồn tại. Giữ nguyên đường dẫn tương đối trong version, không ghi vào Drive gốc. Các bản ghi khác được báo cáo riêng; mismatch, thiếu file, trùng đích hoặc record không hợp lệ phải dừng trước parse.
- [ ] Ghi báo cáo staging và hash manifest riêng, bao gồm số version/file thành công, version unavailable và số không map được. Kiểm tra đủ 2.332 tệp theo journal, không chỉ 5 mẫu; test đường dẫn lồng, file trùng, hash sai, thiếu file và resume/idempotence. Do v1 S3 chỉ suy luận, ghi đây là `.bbl` lấy lại từ arXiv v1, không khẳng định đồng nhất byte với source S3.
- [ ] Kiểm tra parser hiện tại `extract_references` chỉ dùng `.bbl` khi chưa có entries từ TeX/`.bib`; kiểm thử tập tiêu biểu (nhiều `.bbl`, có `\\bibitem` trong TeX, biblatex không theo `\\bibitem`, file rỗng/không parse được), đo riêng version đã staged, được parser dùng và số reference trích. Recovery không bảo đảm có reference trích xuất hay chất lượng trường. Kiểm tra việc quét mọi `.bbl` trong thư mục có gây trùng hoặc lấy sai danh sách và xử lý theo bằng chứng trước khi chạy full.
- [ ] Trên runtime mới và khi resume, restore và stage cùng input đã pin **trước** khi restore tiếp trạng thái M2; kiểm tra fingerprint/revision và từ chối nếu input thay đổi. Chạy output/run ID mới cho corpus đã bổ sung; không resume shard của corpus cũ.

**Điều kiện qua cổng:** restore và toàn bộ hash staging thành công; đủ ID, không trùng; manifest cố định và test pass; smoke cho thấy `.bbl` được dùng đúng, không làm đổi corpus M1.

## 3. Smoke và chạy chính thức M2

- [ ] Rà soát notebook: đường dẫn năm run/Drive, tài khoản, revision chính xác, preflight và cờ `RUN_M2`; làm rõ restore/staging là setup ngoài parser benchmark, đồng thời báo riêng chi phí và dung lượng. Đảm bảo các cell QA/export không tự chạy khi chưa có output.
- [ ] Chạy smoke Colab CPU trên tập đại diện gồm version `.bbl` khôi phục, nhiều version, `no_tex`, `unavailable` và các trường hợp fallback; kiểm tra ba bảng, status và log. Thử ngắt/resume ở output smoke riêng và đối chiếu kết quả với chạy liên tục.
- [ ] Khi smoke đạt, chạy full 20.000 ID bằng notebook M2, lưu session, thông số, revision và manifest; đo wall time parser, thời gian/paper, RSS toàn process tree, disk và output; nêu rõ chi phí đồng bộ Drive cạnh tranh tài nguyên và thời gian các session khi resume. Không cộng crawl/recovery vào M2 parser benchmark.
- [ ] Kiểm tra `assigned_check.json`, `run_summary.json`, journal và CSV: đủ paper/version theo input, status `parsed`, `empty`, `no_root`, `error`, `missing` phải giải thích được; xử lý/retry lỗi có kiểm soát và lưu evidence trước khi chốt. Không khẳng định hoàn tất chỉ vì process exit 0.

## 4. QA, báo cáo và bàn giao M3

- [ ] Chạy `src.qa.check_tables`, `src.qa.audit_structure` trên toàn output; lưu báo cáo, xem lỗi schema/khóa/cây và chênh lệch cấu trúc, sửa hoặc công bố giới hạn với evidence. Rút mẫu 30 paper seed 2026, để thành viên đọc và điền score sheet, có các ca `.bbl`; không suy rộng mẫu smoke cũ.
- [ ] Tổng hợp parsing success/coverage theo version và paper, element/reference trước và sau dedup, số `.bbl` được sử dụng và chất lượng trích, số lỗi và giới hạn; đối chiếu tổng với journal và Parquet. Công bố provenance và mẫu số, không nhầm recovered với parse thành công.
- [ ] Xuất CSV M2 chính thức, thay số smoke và các câu hardcode smoke tại `../arxiv-book/m2/` và `../arxiv-book/data/m2/`; cập nhật phần methodology cho recovery thực tế và giữ các phần M1 tách biệt. Xác thực figures sinh khi build, build Book, kiểm tra đường dẫn và nội dung trên trang được xuất bản sau khi tích hợp.
- [ ] Bàn giao ba bảng Parquet, manifest, logs, báo cáo QA và hướng dẫn tái lập cho M3; ghi rõ các vấn đề chưa khắc phục. Không công bố kho dữ liệu hoặc tạo nhánh mới ngoài yêu cầu của người dùng.
