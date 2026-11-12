# Thử crawl khôi phục .bbl — 12/11/2026

Đã gọi trực tiếp export.arxiv.org/src/<id>v<N> cho 10 ID duy nhất; mỗi request cách nhau ít nhất 3 giây. Không sửa corpus/evidence gốc.

Mẫu có chủ đích: record cuối status ok, không giữ .bib/.bbl, journal ghi đã loại .bbl; chọn 10 archive nhỏ nhất từ bốn run multi, mỗi paper một version. Đây là kiểm tra khả năng khôi phục, không phải mẫu ngẫu nhiên để ước lượng tỷ lệ cả corpus.

| Paper/version | .bbl trong archive | Bytes | M2 references từ .bbl |
|---|---|---:|---:|
| 2606.28756v1 | main.bbl | 4571 | 17 |
| 2604.23484v2 | vn1.bbl | 4194 | 21 |
| 2607.00775v1 | PointsOnCircle.bbl | 993 | 5 |
| 2606.27034v1 | Main.bbl | 1974 | 10 |
| 2604.20785v2 | UpdatedCobordisms.bbl | 3096 | 13 |
| 2606.05881v2 | main.bbl | 3102 | 15 |
| 2606.07820v1 | main.bbl | 1563 | 6 |
| 2606.27340v1 | paper7.bbl | 1635 | 8 |
| 2606.09022v1 | hmfa-openai.bbl | 1288 | 7 |
| 2606.30672v1 | v1.0_Comment_PhysRevAccelBeams.bbl | 9203 | 10 |

Kết quả: HTTP 200 cho cả 10; có .bbl trong cả 10 archive; không có member .bib. M2 đọc được 112 references từ .bbl. Crawler hiện tại tự giữ .bbl qua fallback. Journal cũ ghi .bbl trong dropped, cho thấy dữ liệu cũ đã loại file có thể tải lại được; chưa xác định phiên bản mã crawler đã tạo từng run.

Bằng chứng nằm tại `../../../../debug/bbl-crawl-2026-11-12/`: selection.json chứa nguồn journal và hash; results.jsonl chứa URL/version, HTTP, danh sách file, hash archive và .bbl; crawl.log lưu request. raw/ giữ archive gốc, extracted/ là output crawler, recovered-bbl/ chứa bản .bbl độc lập; m2-references/ chứa references đã parse.

M2 có thể vẫn báo missing_bib do lệnh bibliography trỏ tới .bib không được nộp; điều này không ngăn fallback .bbl lấy references. Chưa đánh giá thủ công độ chính xác từng trường title/author.
