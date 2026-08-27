# prepare_ai_course.py

Tool thứ hai trong workflow:

```text
BK-LMS Downloader v2
        ↓
raw course archive
        ↓
prepare_ai_course.py
        ↓
AI-ready knowledge base
        ↓
ChatGPT / RAG / AI Tutor
```

## 1. Cài thư viện

PowerShell:

```powershell
pip install beautifulsoup4 markdownify pypdf python-pptx
```

Nếu muốn transcript video:

```powershell
pip install faster-whisper
```

## 2. Chạy với folder raw

```powershell
python prepare_ai_course.py `
  --input "D:\University\BK_LMS_Data\Your Course" `
  --output "D:\University\AI_Knowledge" `
  --force
```

Hoặc input thẳng ZIP:

```powershell
python prepare_ai_course.py `
  --input "D:\test_v2.zip" `
  --output "D:\University\AI_Knowledge" `
  --force
```

## 3. Mặc định tool làm gì?

- `content.txt` được ưu tiên hơn `content.html` trong cùng Moodle Page.
- HTML trùng sẽ bị skip để tránh feed AI hai lần.
- PDF lecture được extract theo **page**.
- PPTX được extract theo **slide**.
- Subtitle `.srt/.vtt` được đưa vào corpus theo timestamp.
- Video/audio chưa transcript sẽ nằm trong `transcription_queue.md`.
- Textbook/reference lớn chỉ nằm trong `references_index.md`, không flood corpus mặc định.
- `.url` chỉ nằm trong `links_index.md`, không xem là kiến thức.
- Documents/chunks có metadata: `source_id`, source path, chapter, priority, page/slide/timestamp.

## 4. Transcript toàn bộ video

CPU:

```powershell
python prepare_ai_course.py `
  --input "D:\test_v2.zip" `
  --output "C:\...\MMT\AI_Knowledge" `
  --transcribe `
  --whisper-model small `
  --whisper-device cpu `
  --whisper-compute-type int8 `
  --force
```

Nếu có NVIDIA CUDA:

```powershell
python prepare_ai_course.py `
  --input "D:\test_v2.zip" `
  --output "C:\...\MMT\AI_Knowledge" `
  --transcribe `
  --whisper-model medium `
  --whisper-device cuda `
  --whisper-compute-type float16 `
  --force
```

`--language` bỏ trống = auto detect. Nếu video hầu hết tiếng Anh có thể thêm `--language en`; tiếng Việt dùng `--language vi`.

## 5. Extract cả textbook/reference

Không khuyên bật ngay cho AI tutor cơ bản vì corpus sẽ rất lớn. Khi cần:

```powershell
python prepare_ai_course.py `
  --input "D:\test_v2.zip" `
  --output "C:\...\MMT\AI_Knowledge_FULL" `
  --include-references `
  --force
```

## 6. Output

```text
AI_Knowledge/
├─ AI_TUTOR_CONTEXT.md
├─ course_index.md
├─ processing_report.md
├─ references_index.md
├─ transcription_queue.md
├─ links_index.md
│
├─ documents/
│  ├─ 00_course/
│  ├─ chapter_01/
│  ├─ chapter_02/
│  ├─ ...
│  └─ other/
│
├─ chunks/
│  ├─ 00_course/
│  ├─ chapter_01/
│  └─ ...
│
└─ meta/
   ├─ corpus.jsonl
   ├─ documents.jsonl
   ├─ documents.csv
   ├─ stats.json
   └─ raw_downloader_metadata/
```

### File quan trọng nhất để feed AI

- **AI_TUTOR_CONTEXT.md** — luật sử dụng knowledge base và source priority.
- **course_index.md** — mục lục human-readable.
- **documents/** — nội dung full đã chuẩn hóa.
- **meta/corpus.jsonl** — chunk-level data dùng cho embeddings/vector DB/RAG.

## 7. Source priority

Knowledge base cố tình gắn priority:

1. LMS page/text của giảng viên
2. Slide + lecture PDF
3. Transcript video/subtitle
4. Textbook/reference

Mục tiêu là AI học theo scope/cách dạy của môn trước, rồi mới dùng sách để bổ sung.

## 8. Gợi ý workflow thực tế

Lần đầu:

```text
Downloader → raw
prepare_ai_course → AI_Knowledge
```

Khi giảng viên up thêm file:

```text
Downloader chạy lại → raw được cập nhật
prepare_ai_course chạy lại --force → rebuild AI_Knowledge
```

Nếu video chưa cần ngay, chạy prepare không `--transcribe` trước cho nhanh. Khi có thời gian, chạy lại với transcript để tăng chất lượng AI tutor.
