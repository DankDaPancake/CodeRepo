# Kết luận retry các phiên bản unavailable — 12/11/2026

Lần retry trên Colab xử lý 86 cặp paper/phiên bản duy nhất, thuộc 80 paper. Cả 86 record đều có trạng thái `unavailable`, mã HTTP 404 và lý do `HTTP 404`; không có version nào được khôi phục. Thời điểm ghi kết quả từ 08:33:36 đến 08:37:51 UTC, tương ứng 15:33–15:37 giờ Việt Nam.

Đối chiếu journal kết quả với trạng thái cuối của năm journal đầu vào cho thấy đủ 86 cặp, không thừa; hash SHA-256 của cả năm journal trong manifest khớp evidence local. Mỗi record ghi một lần thử; không có file khôi phục được ghi hash.

**Kết luận:** giữ trạng thái unavailable cho 86 version trong kết quả hiện tại. HTTP 404 cho thấy endpoint `export.arxiv.org/src/<id>v<version>` không trả source trong lần thử này; không đủ để kết luận paper không tồn tại hay mọi nguồn thay thế đều không có. Không đưa thư mục version rỗng vào corpus như một nguồn đã khôi phục.

Nguồn kiểm chứng: bản sao `debug/unavailable-retry-drive-2026-11-12/versions.jsonl`, `summary.json` và `manifest.json` trong workspace; bản kết quả gốc nằm trong Drive của nhóm. Chạy lại notebook cùng output sẽ bỏ qua record unavailable đã hoàn tất; thử lại độc lập cần output mới và giữ nguyên kết quả cũ.
