<!-- Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules. -->
# M3 — Gán nhãn, phân tích, đọc chéo, dataset Hugging Face

Phụ trách: Tiến (Member 2). Code trong `src/m3/`, test trong `src/tests/test_m3.py`.

## Định dạng nhãn (cố định từ 16/11)

Mỗi bài một file CSV `labels/<method>/<folder>.csv`, với `method` là `manual` hoặc `auto` và `folder` là ID có dấu `-` (`2606-25801`). File là ma trận ứng viên m × n:

```text
citation_key,2602.17657,2401.00001,...   <- mỗi cột là một ứng viên (ref_arxiv_id)
smith2020,no,yes,...                      <- mỗi hàng là một mục BibTeX, ô yes/no
```

- Ứng viên của một bài là các reference của bài đó có `arxiv_id` khác null (đúng bảng `references`, data contract mục 6), bỏ trùng, giữ thứ tự gốc.
- Mỗi hàng có **đúng một** `yes`, hoặc toàn `no` khi không reference nào đúng (sách, bài không có trên arXiv, …).
- `src/m3/labels.py: read_matrix` từ chối file sai định dạng (ô khác yes/no, hơn một yes, trùng key, sai số cột).
- Nhãn không đưa lên repo. Chúng nằm trong dataset Hugging Face, thư mục `labels/`.

## Chuẩn bị trên Colab

**Cách nhanh nhất:** mở notebook [arxiv_nhom1_m3_labeling.ipynb](https://colab.research.google.com/github/hcmus-arxiv-nhom1/CodeRepo/blob/main/src/notebooks/arxiv_nhom1_m3_labeling.ipynb). Notebook lấy BibTeX từ `m2/derived/m2-full-no-empty-roots-01` và đối chiếu `identity.json` với `M2_MANIFEST.json` trong `m2/m2-full-01` để xác định các checkpoint M1. Notebook làm đủ các bước dưới đây, mỗi bước một ô. Nó chỉ copy `bibtex.parquet` của M2 và `references.json` của M1 từ Drive (có kiểm tra SHA-256), không restore cả corpus. Các lệnh bên dưới dành cho ai muốn tự chạy.

```python
!git clone -b main https://github.com/hcmus-arxiv-nhom1/CodeRepo /content/CodeRepo
%cd /content/CodeRepo
!pip install -q -r src/requirements.txt
M2 = "/content/m2-local/out"        # thư mục có shard-*/bibtex.parquet (restore từ Drive như notebook QA)
CORPUS = "/content/m1-local/corpus" # corpus M1: <folder>/references.json
LABELS = "/content/drive/MyDrive/arxiv-nhom1/m3/labels"  # để trên Drive cho khỏi mất khi runtime reset
```

## 1. Chọn 20 bài gán nhãn thủ công

```python
!python -m src.m3.select_papers --m2-dir $M2 --corpus-dir $CORPUS --out $LABELS/../selection.csv
```

Mỗi dải chọn 5 bài, mỗi bài có 20–80 mục BibTeX, ít nhất 20 ứng viên và ít nhất 5 mục có tiêu đề trùng hẳn tiêu đề một ứng viên. Đây chỉ là dấu hiệu cho thấy bài có ứng viên đúng, không phải nhãn. Các bài được chia theo tỉ lệ mục có DOI/URL (thấp/vừa/cao) và rút xen kẽ từ ba nhóm để đa dạng kiểu trích dẫn, hạt giống cố định `20261116`. Nếu dải nào không đủ 5 bài, script in cảnh báo; khi đó hạ `--min-hits` hoặc tăng `--max-entries`.

## 2. Gán nhãn thủ công (mỗi người 5 bài của dải mình)

```python
!python -m src.m3.label_tool --m2-dir $M2 --corpus-dir $CORPUS --labels-dir $LABELS --arxiv-id 2606.25801
```

Công cụ hiện mục BibTeX và các ứng viên, sắp theo độ giống tiêu đề để dễ tìm. **Công cụ không điền sẵn câu trả lời; người gán nhãn đọc và gõ lựa chọn.**

| Phím | Ý nghĩa |
| --- | --- |
| `3` | ứng viên số 3 là reference đúng |
| `0` | không ứng viên nào đúng (cả hàng `no`) |
| `a` | hiện mọi ứng viên |
| `/từ` | lọc ứng viên có tiêu đề chứa "từ" |
| `b` | quay lại mục trước để sửa |
| `q` | lưu và thoát |

Mỗi câu trả lời được ghi ngay vào file. Chạy lại cùng lệnh sẽ tiếp tục từ mục chưa gán; thêm `--redo` để làm lại từ đầu.

## 3. Phân tích dữ liệu (số liệu cho feature và poster)

```python
!python -m src.m3.analysis --m2-dir $M2 --corpus-dir $CORPUS --labels-dir $LABELS \
    --partitions $LABELS/../partitions.csv --out-dir $LABELS/../analysis
```

`--partitions` là file `arxiv_id,partition` của Hiếu. Khi có file này, chỉ bài **Train** được dùng, nên Valid và Test không ảnh hưởng tới việc chọn feature. Kết quả gồm:

- `summary.txt`: số bài và số mục đã gán, tỉ lệ mục không có reference đúng, số ứng viên mỗi bài, MRR@5 baseline khi chỉ xếp theo độ giống tiêu đề, và trung bình từng tín hiệu ở cặp đúng so với cặp sai.
- `signal_summary.csv`: count, mean, các tứ phân vị của `title_sim`, `author_overlap`, `year_diff`, `id_in_entry`, tách theo yes/no. Dùng để vẽ boxplot cho poster.
- `pairs.csv`: mỗi ô của ma trận một dòng (dùng cho Đăng khi huấn luyện), `paper_summary.csv`: mỗi bài một dòng.

## 4. Đọc chéo nhãn (10 mục mỗi người)

```python
!python -m src.m3.crosscheck sample --m2-dir $M2 --corpus-dir $CORPUS --labels-dir $LABELS \
    --sheet $LABELS/../crosscheck_sheet.csv --key $LABELS/../crosscheck_key.csv
```

Mở `crosscheck_sheet.csv` bằng Excel hoặc Google Sheets. Với mỗi mục, đọc danh sách `candidates` rồi điền `reviewer_choice` (số thứ tự ứng viên, `0` nếu không có) và tên mình vào `reviewer`. **Không mở `crosscheck_key.csv` trước khi điền xong.** Sau đó chấm:

```python
!python -m src.m3.crosscheck score --sheet $LABELS/../crosscheck_sheet.csv --key $LABELS/../crosscheck_key.csv
```

Script in tỉ lệ đồng thuận theo từng người, tỉ lệ chung và danh sách các mục lệch. Hai người cùng xem lại từng mục lệch và sửa file nhãn nếu nhãn đầu sai.

## 5. Dataset Hugging Face của dải

Gói 6 bảng do Hiếu ghi, mỗi bảng một thư mục `papers/ references/ elements/ hierarchy/ bibtex/ predictions/` chứa `*.parquet`.

1. Thêm Colab Secret `HF_TOKEN` (token **write** của tài khoản cá nhân). Không dán token vào code, chat hay output.
2. Chạy thử, chưa upload:

   ```python
   !python -m src.m3.hf_dataset --package-dir /content/pkg/tien --repo-id <hf-user>/arxiv-nhom1-tien \
       --range tien --labels-dir $LABELS --dry-run
   ```

3. Upload, rồi tải lại từng bảng bằng streaming:

   ```python
   import os
   from google.colab import userdata
   os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN")
   !python -m src.m3.hf_dataset --package-dir /content/pkg/tien --repo-id <hf-user>/arxiv-nhom1-tien \
       --range tien --labels-dir $LABELS
   ```

Script kiểm tra đủ 6 bảng và cột phẳng. Nếu chưa có `README.md`, script viết dataset card với YAML `configs` (không dùng loading script). Sau đó nó tạo repo **public**, upload kèm `labels/` của dải, rồi tải lại cả 6 bảng. Cuối cùng, mở link ở cửa sổ ẩn danh để chắc dataset public.
