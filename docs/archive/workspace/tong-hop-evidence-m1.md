# Tổng hợp evidence crawl M1

Trạng thái: **đang đối chiếu**. Đã nhận `book_csv` khôi phục của only-v1 và đối chiếu số ID/version với bốn run còn lại; chưa hoàn thành kiểm toán corpus raw và tổng hợp timing nhóm.

## Phạm vi và trạng thái version

Đối chiếu `work/manifest.json` của năm run với snapshot 20.000 ID: 20.000 ID duy nhất, không trùng, không thiếu và không ngoài phạm vi. Đối chiếu journal với số version theo snapshot cho thấy đủ 26.491 cặp paper/version có bản ghi. Đây là đối chiếu journal, chưa phải kiểm toán lại corpus raw.

| Run | Paper | Version theo snapshot | `ok` | `no_tex` | `unavailable` |
| --- | ---: | ---: | ---: | ---: | ---: |
| only-v1-all | 14.913 | 14.913 | 13.955 | 958 | 0 |
| multi-dang | 1.466 | 3.389 | 3.217 | 144 | 28 |
| multi-hieu | 1.343 | 3.060 | 2.937 | 101 | 22 |
| multi-thien | 1.114 | 2.510 | 2.411 | 79 | 20 |
| multi-tien | 1.164 | 2.619 | 2.521 | 82 | 16 |
| Tổng | 20.000 | 26.491 | 25.041 | 1.364 | 86 |

Số trạng thái `ok` không đồng nghĩa số paper hoàn tất reference. Cả năm `failed.csv` chỉ có tiêu đề; QA source có lần lượt 25, 17, 8, 7 và 12 dòng cảnh báo `tex_empty` theo thứ tự trên. Một dòng là cảnh báo file, không nhất thiết là một paper.

## Multi Đăng: CSV khôi phục

`final_evidence/multi-dang-0000-4999-recovered-book-csv` có 1.466 dòng paper khác nhau. Trong đó 1.466 paper terminal-complete theo định nghĩa exporter; 1.410 có ít nhất một version với TeX. Reference status: 1.464 `ok`, 2 `not_found`; có 57.440 reference được ghi nhận, 50.429 có Semantic Scholar ID, 50.008 đủ các trường theo định nghĩa exporter.

`measurement_audit.json` của CSV ghi `measurement_complete: false`, `scope: legacy chunk-only`. Dòng `wall_time_e2e = 18.527,26 s` là tổng profiler của 51 chunk, không phải thời gian end-to-end session; các số RAM cùng bảng cũng thuộc phạm vi profiler chunk.

Telemetry trong `final_evidence/multi-dang-0000-4999-drive-evidence/measurements` đã được kiểm tra bằng `session_report` trên bản sao tạm đúng vị trí `work/measurements`: một session hợp lệ, 19.379 mẫu, thời gian sampler 19.511,39 s. Khoảng thời gian này theo phạm vi sampler, không mặc nhiên bao gồm toàn bộ setup/export bên ngoài.

## Only-v1: CSV khôi phục

`final_evidence/only-v1-all-recovered-book-csv/book_csv` có 14.913 dòng paper duy nhất; ID và số version từng paper khớp manifest và snapshot. Reference status gồm 14.899 `ok` và 14 `not_found`; 13.955 paper có ít nhất một version có TeX. `measurement_audit.json` ghi `legacy chunk-only`, vì vậy `wall_time_e2e = 9.127,13 s` trong CSV là tổng profiler 400 chunk, không phải session wall.

Telemetry tại `final_evidence/only-v1-drive-evidence/measurements` được kiểm tra trên bản sao tạm đúng vị trí `work/measurements`: một session hợp lệ, 28.760 mẫu, thời gian sampler 31.271,25 s. Thời gian này theo phạm vi sampler, không mặc nhiên bao gồm setup và export evidence.

## Tổng hợp CSV năm run — đối chiếu sơ bộ

Năm `papers_stats.csv` chứa tổng cộng 20.000 ID duy nhất, đúng manifest từng run; số version và số terminal-state mỗi paper khớp snapshot và journal. Các số sau phụ thuộc exporter và corpus được đọc lúc khôi phục, chưa thay thế QA độc lập hoặc đọc lại từng source:

- 18.878 paper có ít nhất một version có TeX; không suy ra mọi version của các paper này đều có TeX.
- Tổng kích thước ghi nhận trước/sau lọc: 118.130.383.898 / 5.275.637.959 byte; trung bình trên 20.000 ID: 5.906.519,19 / 263.781,90 byte mỗi ID. Các số trước/sau này không mặc định là dung lượng truyền qua mạng.
- 19.983 paper có reference-list status `ok`, 17 `not_found`; 704.067 reference được ghi nhận, trung bình 35,20335 reference trên mỗi ID được yêu cầu. Paper không lấy được reference không thể được kết luận là không có reference.
- 616.754/704.067 reference có Semantic Scholar ID (87,599%); 611.683/704.067 có đủ S2 ID, title, authors và submission date/year theo exporter (86,879%). Mẫu số là các reference đã ghi nhận, không gồm danh sách chưa lấy được.

## Việc cần đối chiếu khi đủ evidence

- Kiểm tra sâu giá trị thiếu, định nghĩa kích thước trước/sau và nguồn reference; đối chiếu corpus raw nếu cần kết luận về chất lượng dữ liệu.
- Phân tích khác biệt revision: `ad03e0a3dc8d96bf1404472f6752aac5e2c42857` cho only-v1, Đăng và Thiên; `cf57e341d46eff12293dc96541514473d9e30d82` cho Hiếu và Tiến.
- Đối chiếu session/measurement audit, khoảng thời gian chồng lấp và phạm vi đo trước khi trình bày runtime nhóm. Không cộng thời gian chạy song song thành wall time end-to-end.
- Kiểm tra lại corpus raw, reference và provenance; trạng thái journal hoặc checkpoint không thay thế kiểm toán file.
