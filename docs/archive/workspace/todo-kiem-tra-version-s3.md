# TODO — Kiểm tra version suy luận từ S3

## Kiểm tra suy luận version của paper only-v1 lấy từ S3

Trạng thái: **đề xuất, chưa thực hiện**. Lập luận trong Book là suy luận có điều kiện; việc cố định phạm vi version theo snapshot là trade-off đã chấp nhận.

- [ ] Thu thập evidence của run only-v1, gồm journal version và S3 index/manifest. Lập danh sách paper thực sự được lưu với `version_evidence=inferred_snapshot_bundle_timestamp`, cùng ID, bundle, timestamp và trạng thái source.
- [ ] Tìm bằng chứng đáng tin cậy về thời điểm chốt snapshot và so sánh với timestamp từng bundle. Ngày `update_date` mới nhất 23/10/2026 là ngày của bản ghi, không tự xác định thời điểm chốt snapshot.
- [ ] Gắn cờ bundle cùng ngày hoặc sau mốc chốt nếu mốc này xác minh được. Nếu chưa biết, nêu rõ giới hạn và ưu tiên các bundle có timestamp muộn, gần ngày cập nhật mới nhất quan sát trong snapshot. Đây chỉ là dấu hiệu ưu tiên kiểm tra, không chứng minh suy luận sai.
- [ ] Với tập paper được chọn, tải `/src/{id}v1` từ arXiv theo giới hạn request hiện hành; giải nén, giữ `.tex`/`.bib` cùng cách và so sánh với corpus S3. Ghi nhận riêng paper khác nhau, không có TeX, tải lỗi và không thể kết luận; điều tra chênh lệch trước khi kết luận sai version.
- [ ] Báo cáo phương pháp chọn mẫu, kích thước mẫu, số khớp/khác/chưa kết luận, thời điểm kiểm tra, snapshot hash và bundle liên quan. Không suy rộng kết quả mẫu thành bảo đảm cho toàn bộ corpus.

Tham khảo: ba index từ benchmark cũ của Đăng ghi 3.171 ID khác nhau có timestamp bundle vào 05/05, 07/05, 05/06 và 05/07/2026. Chúng không đại diện toàn bộ run only-v1 và không chứng minh các paper đó đều đã được lưu thành công từ S3.
