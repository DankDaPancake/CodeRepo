# Kế hoạch điều chỉnh — bỏ SHIFT, nhiều tài khoản và tổng hợp log

> Thay thế phương án “lưu nguyên archive, không giải nén” trong `2026-11-01-raw-crawl-no-shifts.md`. Giữ giải nén/stream và chỉ giữ `.tex`/`.bib` như pipeline hiện hành. Đây là bản thiết kế; chưa triển khai.

## Những điểm đã chốt

- Tiếp tục discovery bằng snapshot + API/OAI khi cần, source extraction/filter và references hiện tại. M1 vẫn cần số liệu trước/sau bỏ figure.
- Bỏ `SHIFT.json`, takeover, owner/heartbeat chia ca và các UI liên quan; không xóa marker hay dữ liệu cũ của người dùng. Giữ checkpoint và resume để phục hồi sau timeout. Sử dụng run ID mới/schema mới; run cũ tiếp tục dùng revision cũ, không tự migrate.
- **Đã xác nhận:** nhiều tài khoản Colab chạy đồng thời, mỗi tài khoản crawl một phần ID riêng; sau đó tổng hợp log/evidence. Không còn giao diện chia ca. Mặc định xây manifest bốn partition theo bốn range được giao; có thể chia nhỏ thêm nhưng phải kiểm tra đầy đủ và không trùng.
- Quy tắc nhóm hiện tại là một kết nối arXiv trong toàn nhóm, cách request ít nhất 3 giây. [Điều khoản API arXiv](https://info.arxiv.org/help/api/tou.html) nêu rõ giới hạn legacy API áp dụng tổng thể các máy và không dùng nhiều máy để vượt rate limit. Không suy diễn rằng chia tài khoản cho phép tăng request rate. Duy trì một lane chung cho mọi request nhóm đang xử lý; phần nguồn `/src` tiếp tục theo chính sách thận trọng hiện có của nhóm.
- Thầy yêu cầu final benchmark Colab CPU trên toàn bộ tập được giao. Việc ghép log nhiều runtime không tự chứng minh tương đương một benchmark trên một Colab instance; nêu thiết kế/machine/sessions rõ ràng và xác nhận với thầy nếu muốn nộp số tổng hợp từ nhiều runtime như final.

## Hiện trạng cần sửa

- `src/benchmark/runner.py` dùng `Shift` chung trên root, `SHIFT_OWNER`, `TAKEOVER`, `hf_shift_token`, `session_budget_s`; `src/benchmark/huggingface.py` kiểm `owner_token` trước pointer. Bỏ marker mà không thay đổi ngữ nghĩa ownership có thể làm nhiều runtime đè `INDEX`/`LATEST` cùng run.
- `plan_chunks()` hiện coi mọi subset là `sample` và `final` yêu cầu bốn range trọn vẹn; CSV và coverage hiện dựa một `RUN_ID`. Chưa có collector cross-run kiểm đủ/không trùng 20.000 ID.
- `paper_timing_report()` và `session_exports()` đã nhận nhiều work directories, nhưng `session_exports()` nối timeline theo offset tuần tự; không dùng nguyên xi để khẳng định end-to-end hay RAM tổng của các runtime chạy chồng lấp. Cần audit trùng/thiếu và xử lý clock/overlap.
- `RateLimiter` hiện trong từng process, không đồng bộ Colab khác. `src/crawler/coordinator.py` có prototype coordinator cho nhiều worker nhưng chưa chứng minh triển khai cross-runtime có bảo mật, đồng hồ/lease và failure-safe; không đưa thẳng service local ra Internet.
- HF parent-commit kiểm xung đột, nhưng `CommitBudget` nằm trong local staging mỗi runtime; nhiều tài khoản cùng Dataset có thể chung quota/server và tạo 409/429. LATEST/index phải là namespace riêng từng run; hai runtime không được viết cùng run ID.
- Repo Book `docs/drive-plain-folders` có thay đổi chưa commit của user/session; không reset/stash hoặc ghi đè chúng.

## Thiết kế dự kiến

### Chạy đồng thời, chia phạm vi độc lập

1. Dùng một group manifest bất biến tạo trước khi crawl: group ID, danh sách đúng 20.000 assigned IDs, schema, revision, snapshot SHA-256, reference settings, ID/phiên bản quota. Định nghĩa partitions rời nhau (ví dụ theo bốn range hoặc subrange); validate tập hợp **bằng đúng** tập ID được giao, không trùng, không thiếu, không ID lạ. Không suy ra partition từ tên tài khoản.
2. Mỗi runtime/tài khoản có `RUN_ID` + partition ID riêng và output/checkpoint riêng. Nếu dùng chung HF Dataset: `runs/<RUN_ID>/...` riêng, không dùng `LATEST` chung, không cùng sửa một file run; khi cùng dùng Drive cần đường dẫn/team folder có quyền thích hợp. Không tự thay đổi quyền Dataset hay công khai token. Chỉ collector sau khi kiểm chứng mới tạo tổng hợp; output/run cũ giữ nguyên.
3. Để các runtime hoạt động đồng thời mà vẫn giữ một lane arXiv cho cả nhóm, ưu tiên một **gateway/worker duy nhất thực sự thực hiện các request arXiv**, bao phủ toàn bộ thời gian request/stream body và khoảng cách request, kể cả API/OAI/source và các lần Range/retry. Các runtime khác gửi công việc tới gateway và xử lý phần của mình; cần thiết kế đường chuyển response/stream và measurement rõ ràng. Một lock từ xa dựa vào lease đơn thuần không đủ chứng minh an toàn khi bị chia mạng: một client mất kết nối coordinator vẫn có thể còn kết nối tới arXiv. Kiểm thử điều kiện này, không giả định lease expiry chấm dứt HTTP cũ. Các runtime không được tự fallback sang limiter riêng nếu coordinator mất kết nối: fail-closed và giữ dữ liệu đã checkpoint. Gateway cần một endpoint đáng tin cậy, có auth/TLS, khả dụng suốt job; endpoint/triển khai cụ thể chưa được cung cấp, và runtime Colab thường không có inbound endpoint ổn định. Không khẳng định hệ thống đã chạy được cho tới khi giải được kết nối này. Prototype hiện có phải được kiểm thử mất mạng/lease expiry/clock/race và bảo mật trước khi dùng. Nhiều runtime có thể giúp bước không phải arXiv, nhưng không làm tăng tổng rate của lane chung; chưa khẳng định nhanh hơn.
4. HF có nhiều writers vào cùng Git repository: đo và xử lý xung đột commit, quota chung và tương tác telemetry/commit budgets. Bảo đảm no silent overwrite và giới hạn thử lại/cooldown; dùng parent commit/đối chiếu, không dùng nhiều máy để lách quota. Nếu không có coordinator/hạ tầng an toàn, không kích hoạt chế độ request arXiv đồng thời; vẫn có thể gom dữ liệu các runs phân vùng không chồng lấn đã thực hiện lần lượt.

## Collector evidence và Book

- Thu manifests, phạm vi, revision/snapshot SHA, start/end UTC, logs/profile, paper events, discovery/versions/references, QA, telemetry checksummed và checkpoint từ từng run. Không cần copy raw corpus về Book. Giữ nguyên evidence gốc, nguồn và lỗi; không chắp hai run thành một bằng cách overwrite file.
- Tạo inventory và validate: ID cần đúng 20.000; version expected theo snapshot; 404/unavailable phân biệt downloaded; references; thiếu sample/session summary; trùng ID, version hoặc attempt, mismatch code/snapshot/schema. Report rõ các phần failed/unavailable/missing thay vì bỏ qua hoặc cộng gấp đôi. Không tự chấp nhận `final_complete` của từng partition làm final toàn nhóm. Kết quả không đủ evidence phải `incomplete`/lower bound.
- Với các phiên nối tiếp: báo tổng active wall theo phiên và tổng elapsed từ lúc bắt đầu đến kết thúc gồm offline gaps **là hai chỉ số riêng**. Với runtime chồng lấp: báo tổng active work, elapsed theo timeline và per-machine/per-session; không cộng trực tiếp thời gian chồng chéo thành end-to-end.
- RAM/disk: đo mỗi runtime và per-session peak/mean đúng scope. Với đồng thời, peak hệ thống toàn nhóm không được lấy tổng các peak xảy ra khác thời điểm; chỉ ước lượng theo samples đồng bộ đồng hồ có audit độ lệch và sampling, hoặc báo thiếu/chỉ per-runtime. Không gán số đo của nhiều máy thành RAM của một Colab. Mean weighted theo thời gian và scope, không lấy trung bình tùy tiện.
- Thời gian mỗi paper giữ lifecycle/attempt và retries theo nguồn; discovery là tổng thời gian công việc và nếu chạy đồng thời nêu các khoảng chồng lấp. `retry_backoff_wait` không phản ánh toàn bộ Semantic Scholar retries; giữ log mã HTTP riêng.
- Đầu ra collector: manifest hợp nhất, provenance, QA trùng/thiếu, timing audit, `papers_stats.csv`, `references_stats.csv`, `benchmark_summary.csv`, `resource_timeseries.csv` với schema rõ. Book M1 nêu dữ liệu sample/final, testbed, limitations và cách tính. Không thay CSV giả bằng số chưa đạt coverage/timing.

## Bước triển khai

1. **Chốt partition manifest và định nghĩa tính điểm** cho bốn phần riêng; cho chọn Drive/HF, output isolation, hai repo/paths và quyền sẵn có. Không cần gửi secret trong hội thoại. Không can thiệp dữ liệu đang có.
2. **Viết test lỗi trước:** marker cũ không chặn run mới; không viết/đọc SHIFT; hai run riêng không lẫn; checkpoint/resume không tạo dữ liệu giả; old manifests không được âm thầm migrate; session budget và cleanup chính xác. Bổ sung test coordinator fail-closed, không có 2 request in-flight và 3 giây giữa start, multi-process/race/restart, xung đột HF 409/429 và giới hạn quota. Nếu không có coordinator test được, không công bố hỗ trợ chạy song song arXiv.
3. **Sửa runner/backend/notebook:** loại Shift và flags nhưng giữ per-run protections/checkpoint/resume; remove ownership token guard chỉ sau khi thay bằng isolation phù hợp và tests. Thêm partition config nếu cần; điều chỉnh `mode`/`coverage` phân biệt partition thuộc final cohort với `sample`, không cho tự coi một partition là final. Loại 4h auto-pause nếu đó là chủ đích sau xác nhận, vẫn cho người vận hành có thể dừng an toàn.
4. **Xây collector** với fixtures nhiều runs/versions/retries, trùng/thiếu, snapshot sai, đồng hồ lệch và interrupted summary; đảm bảo không cộng đúp, không publish final khi QA/timing thiếu. Không đưa secrets/corpus vào Book.
5. **Cập nhật Book và mirror** theo revision CodeRepo: giữ giải nén, kết quả cũ đúng scope và dữ liệu placeholder rõ; ghi rõ benchmark nhiều máy và metric không so sánh trực tiếp với một runtime. Tôn trọng working tree Book đang sửa.
6. **Verify:** targeted pytest → full pytest, Ruff, build Book + notebook analysis, chạy smoke nhỏ dùng nhiều tài khoản trên các partition đồng thời; xác nhận version, reference, log merge và restore sau gián đoạn; đo source concurrency và quota. Không chạy live khi chưa có thông tin/điều kiện cần; báo rõ phần chưa test, không gọi full 20k complete.

## Đầu ra

Một notebook/operator flow không có shift; dữ liệu M2 vẫn là thư mục TeX/Bib sau lọc; có checkpoint/resume và evidence tổng hợp có audit. Không hứa tăng tốc tỷ lệ thuận số account, không xóa run cũ, không khẳng định benchmark tổng hợp là được thầy chấp nhận khi chưa xác nhận.
