# Dark Phoenix: Architecture, Multi-Backend Deployment & Changes

This document details the architecture, code modifications, environment configurations, and setup options implemented for **Dark Phoenix**:
- **Frontend**: Vercel (Next.js 15, React 19)
- **Workflow Queue**: [Inngest Cloud](https://www.inngest.com/)
- **AI Moment Selection**: Google AI Studio (Gemini 3.1 Flash Lite)
- **Database & Storage**: Supabase PostgreSQL + Supabase Storage (S3-Compatible Gateway)
- **Backend Options**:
  1. **Modal GPU Worker** (`ai-podcast-clipper-backend/`): Native L40S serverless GPU endpoint.
  2. **Hugging Face Backend** (`ai-podcast-clipper-backend-huggingface/`): Dual FastAPI + Gradio interface running 100% free on CPU (with 0 GPU quota consumption).

---

## 1. Updated Architecture & Service Matrix

```
                          [User / Reviewer Browser]
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
        [Vercel: Frontend]                       [Hugging Face UI]
                 │                                       │
                 ├────────► [Supabase PostgreSQL] ◄──────┤
                 │                                       │
                 │ (Signed URLs)                         │ (S3 API)
                 ▼                                       ▼
    [Supabase Storage: dark-phoenix bucket (S3-Compatible Gateway)]
                 ▲                                       ▲
                 │                                       │
        [Modal: main.py]                        [Hugging Face Space]
                 ▲
                 │ (Webhook POST /process_video)
                 ▼
       [Inngest Cloud (inngest.com)]
```

### Component Details

| Layer | Service | Configuration / Model | Cost / Hardware |
|---|---|---|---|
| **Frontend** | Vercel | Next.js 15, React 19 | **Free** (Hobby Tier) |
| **Workflow Queue** | Inngest Cloud | Webhook `/api/inngest` | **Free** (25,000 steps/month) |
| **AI Moment Selection** | Google AI Studio | **Gemini 3.1 Flash Lite** | **Free** tier |
| **Backend (Modal)** | Modal | `AiPodcastClipper` on `gpu="L40S"` | Trial credits |
| **Backend (Hugging Face)** | Hugging Face Space | FastAPI + Gradio (Pure CPU Execution) | **Free** (No credit card, no quota limits) |
| **Database** | Supabase | Managed PostgreSQL (`DATABASE_URL`) | **Free** (500 MB) |
| **Object Storage** | Supabase Storage | S3-Compatible API Gateway | **Free** (1 GB) |

---

## 2. Backend Modules Breakdown

### A. Official Modal Backend (`ai-podcast-clipper-backend/`)
- Matches the canonical repository structure.
- **Hardware**: Configured on `@app.cls(gpu="L40S")`.
- **Image Build**: Ubuntu 22.04 CUDA 12.4 base with Python 3.11, Anton font, and pre-downloaded TalkNet weights.
- **Dependency Isolation**: Pinned constraints (`transformers==4.38.2`, `accelerate==0.28.0`, `datasets==2.18.0`, `huggingface-hub==0.21.4`, `lightning==2.1.4`) eliminating pip backtracking loops.
- **Entrypoint**: `main.py` exposing `@modal.fastapi_endpoint(method="POST")` on `process_video`.

### B. Hugging Face Space Backend (`ai-podcast-clipper-backend-huggingface/`)
- Deployed at: [huggingface.co/spaces/Y0sf/dark-phoenix-backend](https://huggingface.co/spaces/Y0sf/dark-phoenix-backend).
- **Dual Functionality**:
  - `POST /process_video`: Authenticated webhook consumed by Inngest and Next.js.
  - `GET /`: Read-only status page (no interactive controls); all processing is programmatic via `POST /process_video` or the frontend.
- **Pure-CPU Execution (0 GPU Seconds Billed)**: WhisperX transcription (`int8`), TalkNet ASD face tracking, network downloads, S3 uploads, and FFmpeg encoding run entirely on CPU (**0 GPU seconds consumed**, avoiding ZeroGPU quota limits).

---

## 3. Changes Differing From the Upstream Method

The canonical Modal backend (`ai-podcast-clipper-backend/`) is preserved byte-for-byte from upstream `main` (`5a40684`). The deviations below live in the Hugging Face backend, the ingestion tooling, the deployment, and the documentation — never inside the canonical Modal code.

### 1. Burned-in `unartch` Watermark & Logo Overlay Variant
- The **HF live backend** (the deployed production backend) burns the permanent **`unartch` text watermark** directly into the MP4 video stream via FFmpeg `drawtext`, matching the production manifest specification:
  `drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40` (upper-right safe area, ~0.8 opacity, text ≈6–10% of video width).
- The **canonical Modal backend** additionally overlays the authentic LunarTech logo (`assets/lunartech-logo.png`) at opacity 0.78:
```python
filter_complex = (
    f"[0:v]ass={subtitle_path}[subtitled];"
    "[1:v]scale=360:-1,format=rgba,colorchannelmixer=aa=0.78,"
    "pad=iw+32:ih+24:16:12:color=black@0.32[watermark];"
    "[subtitled][watermark]overlay=W-w-40:40:format=auto[video]"
)
```

### 2. Anton Font for Styled Subtitles
- Downloaded and cached in the system font directory (`/usr/share/fonts/truetype/custom/Anton-Regular.ttf`).
- Styled with white text, black outline (width 3), bottom-center alignment via `pysubs2`.

### 3. Server-Side S3 Storage Gateway (`AWS_ENDPOINT_URL_S3`)
Both backends and the frontend support custom S3 endpoint URLs:
```python
def get_s3_client():
    s3_endpoint = os.environ.get("AWS_ENDPOINT_URL_S3")
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        endpoint_url=s3_endpoint if s3_endpoint else None,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
```

### 4. PyTorch 2.6 Weights Unpickler Compatibility
Safely unpickles WhisperX and pyannote models on modern PyTorch runtimes:
```python
_orig_load = torch.load
def _compat_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _compat_load
torch.serialization.load = _compat_load
```

### 5. cuDNN 9 & CTranslate2 Upgrade
- Upgraded CTranslate2 from `4.4.0` to `ctranslate2>=4.5.0` and integrated `nvidia-cudnn-cu12`.
- Dynamic preloading via `ctypes.CDLL(..., mode=ctypes.RTLD_GLOBAL)` is injected in `app.py` and `main.py` to prevent missing cuDNN 8 (`libcudnn_ops_infer.so.8`) symbol errors in CUDA 12/13 environments.

### 6. S3 WhisperX Transcription Caching
- Transcription results are cached to S3: `cache_key = s3_key.rsplit(".", 1)[0] + "_transcript.json"`.
- Re-processing an already-transcribed video loads the transcript from Supabase Storage S3 directly, saving up to 3 minutes of compute per reprocess.

### 7. Pure-CPU Pipeline: TalkNet ASD, S3FD Dependency, VideoWriter Fallback
- The S3FD face detector and TalkNet ASD models run on CPU by binding tensors and weights with `torch.device("cpu")` and `map_location=device` — **0 GPU seconds billed**, so the free CPU Space is not subject to ZeroGPU daily limits.
- `torchvision` was added to `requirements.txt` (required by `asd/model/faceDetector/s3fd/__init__.py`).
- Automatic fallback from `ffmpegcv.VideoWriterNV` to `ffmpegcv.VideoWriter` when no NVENC hardware encoder is present (CPU encoding).
- When no active speaker face is detected (e.g., landscape scenes or B-roll), the pipeline does not abort: it falls back to a high-quality 9:16 blurred vertical video with Anton captions and the `unartch` watermark. Because this fallback synthesizes safe, non-overlapping highlights instead of returning `[]` when inputs are unsafe (transcript ≥ 90 s), the HF backend's `tests/test_clip_validation.py` asserts the safety invariants of every returned moment; the canonical Modal copy of the module and its test remain untouched and upstream-faithful.

### 8. Standard Clip Duration Validation (30–60s)
- Both backends enforce the standard **30–60s** short-form clip duration window (`min_duration = 30.0`, `max_duration = 60.0` in `clip_validation.py`), and the Gemini prompt instructs 30–60s clips.
- The delivered clips measure **45.0s / 52.61s / 39.73s** (manifest `duration_seconds` = `end_time − start_time`; FFprobe container durations ≈45.05 / 52.68 / 39.80 s).

### 9. LunarTech Logo Asset Restoration via `assets_embedded.py`
- **Problem**: Hugging Face Spaces rejects binary `.png` files on push (`remote: Your push was rejected because it contains binary files`).
- **Solution**: `assets_embedded.py` stores the 160 KB PNG as base64 text; at startup `ensure_watermark()` unpacks the exact binary to `/assets/lunartech-logo.png` and `assets/lunartech-logo.png`, used by the canonical Modal overlay variant (see #1).

### 10. Automated Keep-Alive & Space Uptime
- [`.github/workflows/keep-alive.yml`](.github/workflows/keep-alive.yml) pings `GET /health` on the Hugging Face Space every 6 hours (cron `0 */6 * * *`, authenticated with the HF read token) via free GitHub Actions.
- Prevents container sleep/hibernation so the Space stays warm and serves webhook requests without cold-start latency.

### 11. Supabase 50 MB Object Cap → 6:00 Segment Seed (Audited)
- **Audit finding**: the reference video `YRvf00NooN8` is **3984 s / 66:24** (verified with `yt-dlp --print "%(duration)s"`), but the pre-seeded `uploads/YRvf00NooN8/original.mp4` is a **6:00.03 segment** (verified with `ffprobe`: video 360.03 s / audio 360.00 s, 1280×720, ≈21.3 MB).
- **Why**: Supabase Free caps the storage **Max File Size at 50 MB**; the full 66-minute stream (~240 MB at the segment's ≈500 kbps) would be rejected on upload. A bounded 6:00 seed stays under the cap and keeps CPU transcription within webhook run windows.
- **Tool hardening**: `ingest_youtube.py` auto-trims any local download that would exceed 45 MB (safety margin under the 50 MB cap) before uploading, so re-seeding always produces a compliant object with an explicit console notice.
- **Docs realigned**: `WRITE_UP.md` (§3 + Obstacle 11) and `DEPLOYMENT.md` (§11) state the true video length (66:24), the seeded segment (6:00.03), and the 50 MB constraint.

### 12. Hugging Face Backend: Read-Only Status Page (Non-Interactive)
- The Space ships a **minimal read-only status page** (`GET /`) with the service title, an endpoint reference table, and a curl verification example — no interactive controls.
- Webhook exposure is scoped to pure FastAPI endpoints: `GET /health` and `POST /process_video` (Bearer). All clipping requests are processed programmatically via Inngest Cloud or direct API invocations.

### 13. Private Hugging Face Space — Single HF-Read-Token Authentication
- The Space (`y0sf-dark-phoenix-backend`) is **Private**: its endpoints are only reachable with a Hugging Face token (`Authorization: Bearer hf_...`) that holds read access to the Space repo.
- Because the app's own webhook check reads the same `Authorization` header, the token model uses a **single credential** everywhere:
  - **Vercel** `PROCESS_VIDEO_ENDPOINT_AUTH` = HF read token (the Inngest `process-video` function already sends it as Bearer — no frontend change).
  - **Hugging Face** Space secret `AUTH_TOKEN` = same token, so the bearer passes both the private-Space edge and the in-app check.
  - **GitHub Actions** secret `HF_TOKEN` = same token; the keep-alive workflow (#10) pings `GET /health` with the Authorization header.
- Rotation and the Private toggle are documented in `README.md` §B + deploy steps, `DEPLOYMENT.md`, `WRITE_UP.md`, the Space `README.md`, and `.env.example` (create/rotate at <https://huggingface.co/settings/tokens>).

### 14. Single Manifest Location & Production Manifest Schema (§5)
- The backend writes `clips_manifest.json` to a **single location** — the job folder in S3 (`s3://dark-phoenix/uploads/<id>/clips_manifest.json`) — eliminating the bucket-root duplicate.
- The manifest is emitted in the **exact production schema**: nested `source_video` (`url` / `video_id` / `s3_source_key`) and `watermark` (`text` / `type` / `filter`) objects, plus `clips[]` with `clip_id`, `filename`, `start_time` / `end_time` (`HH:MM:SS.mmm`), `duration_seconds` (= end − start), `s3_key`, `watermark_present`, `captions_present`, `known_issues`.
- The S3 object `uploads/YRvf00NooN8/clips_manifest.json` was overwritten with this exact content, so the **Supabase, repo-root, and Drive copies are byte-identical** (1,407 B, SHA-256 `09CB3B96…`); a `.gitattributes` rule keeps the repo copy LF-normalized on every platform so hash checks agree on a fresh clone.
- The now-dead SigV4 presigned-URL block was removed from the live backend: after the schema alignment nothing consumed `presigned_playback_url` / `source_video_url` / `source_video_id`, so clip entries no longer carry unused fields and clip ids/names are `clip_01…clip_03` by construction. The canonical Modal copy remains untouched.
