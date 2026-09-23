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

## 3. Key Technical Enhancements & Architecture

### 1. Burned-in `unartch` Watermark & Logo Overlay Variant
- **HF live backend** (the currently deployed production backend) burns the permanent **`unartch` text watermark** directly into the MP4 video stream via ffmpeg `drawtext` matching the production manifest specification:
  `drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40` (upper-right safe area, ~0.8 opacity, text ≈6–10% of video width).
- **Canonical Modal backend** additionally overlays the authentic LunarTech logo (`assets/lunartech-logo.png`) at opacity 0.78:
```python
filter_complex = (
    f"[0:v]ass={subtitle_path}[subtitled];"
    "[1:v]scale=360:-1,format=rgba,colorchannelmixer=aa=0.78,"
    "pad=iw+32:ih+24:16:12:color=black@0.32[watermark];"
    "[subtitled][watermark]overlay=W-w-40:40:format=auto[video]"
)
```

### 2. Anton Font for Styled Subtitles
- Downloaded and cached in system font directory (`/usr/share/fonts/truetype/custom/Anton-Regular.ttf`).
- Styled with white text, black outline (width 3), bottom-center alignment via `pysubs2`.

### 3. Server-Side S3 Storage Gateway (`AWS_ENDPOINT_URL_S3`)
Both backend and frontend support custom S3 endpoint URLs:
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
Safely loads WhisperX and pyannote models when running modern PyTorch runtimes:
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
- Injected dynamic preloading via `ctypes.CDLL(..., mode=ctypes.RTLD_GLOBAL)` in `app.py` and `main.py` to prevent missing cuDNN 8 (`libcudnn_ops_infer.so.8`) symbol errors in CUDA 12/13 environments.

### 6. S3 WhisperX Transcription Caching
- Added automatic S3 caching for audio transcription results:
  `cache_key = s3_key.rsplit(".", 1)[0] + "_transcript.json"`
- If a video has been transcribed, repeat processing loads the cached transcript from Supabase Storage S3 directly, saving up to 3 minutes of compute and zeroing GPU quota consumption for transcription.

### 7. Pure-CPU TalkNet ASD & ZeroGPU Quota Elimination
- Ported S3FD face detector and TalkNet models to CPU by dynamically binding tensors and weights with `torch.device("cpu")` and `map_location=device`.
- Eliminates GPU quota consumption entirely (0 GPU seconds billed), allowing continuous processing without hitting daily ZeroGPU rate limits.
- If no active speaker faces are detected (e.g., landscape scenes or B-roll), the pipeline gracefully falls back to a high-quality 9:16 blurred vertical video with Anton captions and watermark without aborting the job.

### 8. CPU VideoWriter Fallback
- Added automatic fallback from `ffmpegcv.VideoWriterNV` to `ffmpegcv.VideoWriter` when running without an attached NVENC hardware encoder.

### 9. TalkNet S3FD Face Detector Dependency
- Added `torchvision` to `requirements.txt` to resolve `ModuleNotFoundError: No module named 'torchvision'` in `asd/model/faceDetector/s3fd/__init__.py`.

### 10. Standard Clip Duration Validation (30–60s)
- Both backends enforce the standard **30–60s** short-form clip duration window: `min_duration = 30.0`, `max_duration = 60.0` in `clip_validation.py`, and the Gemini prompt instructs 30–60s clips. Generated reference clips are 33.5s / 52.6s / 57.4s.

### 11. LunarTech Logo Asset Restoration via `assets_embedded.py`
- **Problem**: Hugging Face Spaces Git rejected binary `.png` files (`remote: Your push was rejected because it contains binary files`).
- **Solution**: Implemented `assets_embedded.py` to store the 160 KB PNG in base64 Python text. On startup, `ensure_watermark()` unpacks the exact binary image file to `/assets/lunartech-logo.png` and `assets/lunartech-logo.png`.
- **Note**: The unpacked logo asset is used by the canonical Modal overlay variant. The HF render path burns the `unartch` drawtext watermark matching the production manifest specification: `drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40`.

### 12. Automated Keep-Alive & Space Uptime
- Created [`.github/workflows/keep-alive.yml`](.github/workflows/keep-alive.yml) to automatically ping `GET /health` on the Hugging Face Space every 6 hours (cron `0 */6 * * *`, authenticated with the HF read token) via free GitHub Actions.
- Prevents container sleep mode / hibernation, ensuring the Space is warm, healthy, and immediately ready to process webhook requests without cold-start latency.

### 13. Supabase 50 MB Object Cap → 6:00 Segment Seed (Audited)
- **Audit finding**: The reference video `YRvf00NooN8` is **3984 s / 66:24** (verified via `yt-dlp --print "%(duration)s"` metadata), but the pre-seeded `uploads/YRvf00NooN8/original.mp4` is a **6:00.03 segment** (verified via `ffprobe`: video 360.03 s / audio 360.00 s, 1280×720, ≈21.3 MB).
- **Why**: Supabase Free caps the storage **Max File Size at 50 MB**; the full 66-minute stream (~240 MB at the segment's ~500 kbps) would be rejected on upload. A bounded 6:00 seed stays under the cap and keeps CPU transcription within webhook run windows.
- **Tool hardening**: `ingest_youtube.py` now auto-trims any local download that would exceed 45 MB (safety margin under the 50 MB cap) before uploading, so re-seeding always produces a compliant object with an explicit console notice.
- **Docs realigned**: `WRITE_UP.md` (§3 + Obstacle 11) and `DEPLOYMENT.md` (§11) now state the true video length (66:24), the seeded segment (6:00.03), and the 50 MB constraint instead of the earlier inaccurate "30+ minutes, ~300 MB" claim.

### 14. Hugging Face Backend UX: Read-Only Status Page (Non-Interactive)
- The Space ships a **minimal read-only status page** (`GET /`) displaying service title, endpoint reference table, and a curl verification example — with no interactive user controls.
- Webhook exposure is scoped strictly to pure FastAPI endpoints: `GET /health` and `POST /process_video` (Bearer webhook). All clipping requests are processed programmatically via Inngest Cloud or direct API invocations.

### 15. Private Hugging Face Space — HF-Token Authentication End-to-End
- The Space (`y0sf-dark-phoenix-backend`) is set to **Private**: the Gradio/FastAPI endpoints are only reachable with a Hugging Face token (`Authorization: Bearer hf_...`) that has read access to the Space repo.
- Because the app's own webhook check reads the same `Authorization` header, the token model was simplified to a **single credential** — the HF read token:
  - **Vercel** `PROCESS_VIDEO_ENDPOINT_AUTH` = HF read token (the Inngest `process-video` function already sends it as the Bearer — no frontend code change).
  - **Hugging Face** Space secret `AUTH_TOKEN` = same HF read token, so the bearer passes both the private-Space edge and the in-app check.
  - **GitHub Actions** secret `HF_TOKEN` = same token; the keep-alive workflow now pings `GET /health` with the Authorization header.
- Docs updated (`README.md` §B + deploy steps, `DEPLOYMENT.md` env table + Option A + regeneration snippet, `WRITE_UP.md` audit table, Space `README.md`, `.env.example`): all webhook/verification snippets now use `$HF_TOKEN`, and the deployment steps document the Private toggle.
- Create/rotate the token at <https://huggingface.co/settings/tokens> (recommended: fine-grained token with Read access on `Y0sf/dark-phoenix-backend`).

### 16. Single Manifest Location — Remove Bucket-Root Duplicate
- The backend writes `clips_manifest.json` exclusively to the job folder in S3 (`s3://dark-phoenix/uploads/<id>/clips_manifest.json`), eliminating redundant bucket-root duplicate manifests.
- Unaffected: the repo-root `clips_manifest.json` and production distribution copies.

### 17. Production Manifest Schema Alignment
- The backend's `clips_manifest.json` is now emitted in the **exact production schema**: nested `source_video` (`url` / `video_id` / `s3_source_key`) and `watermark` (`text` / `type` / `filter`) objects, plus `clips[]` with `clip_id`, `filename`, `start_time` / `end_time` (`HH:MM:SS.mmm`), `duration_seconds` (= end − start), `s3_key`, `watermark_present`, `captions_present`, `known_issues`.
- The existing S3 object `uploads/YRvf00NooN8/clips_manifest.json` was overwritten with this exact content, so the **Supabase copy is byte-identical** to the repo-root deliverable and distribution copies.
- `main.py` still writes the manifest to a single location (job folder only — see #16).

### 18. Codebase & Manifest Cleanup
- Removed the now-dead SigV4 presigned-URL generation block from the live backend (`main.py`): after the manifest schema alignment (#17) nothing consumed `presigned_playback_url` / `source_video_url` / `source_video_id`, so clip entries no longer carry unused fields. Manifest clip ids/names are now guaranteed `clip_01…clip_0N` (`clip_01…clip_03`) by construction.
- DEPLOYMENT.md regeneration steps updated: the backend emits the production manifest directly to S3, and the repo-root and Supabase copies must stay byte-identical (verified via `Get-FileHash`).
- Verified every module shipped in both backends is wired into the live build/runtime — `asd/` (LR-ASD TalkNet), `download_model_assets.py`, `assets_embedded.py`, `clip_validation.py` are all referenced and retained; no dead or unrelated files.
- Aligned `tests/test_clip_validation.py` with the **3-clip guarantee fallback** added when the HF backend shipped (commit `1f7dd94`): the upstream test asserted `[]` for all-unsafe inputs, but since the fallback now synthesizes safe non-overlapping highlights (transcript ≥ 90 s) the test asserts the safety invariants of every returned moment instead. The canonical Modal copy of `clip_validation.py` and its test remain untouched and upstream-faithful.

### 19. Frontend Enhancements & Server-Side YouTube Ingestion
- **YouTube Ingestion UI (`src/components/dashboard-client.tsx`)**: Implemented a tabbed interface allowing users to submit YouTube URLs alongside direct file uploads, providing real-time URL validation and processing status updates.
- **Server-Side Trigger Action (`src/actions/generation.ts`)**: Implemented the `processYouTubeVideo` server action that validates YouTube video URLs, creates the Prisma `UploadedFile` record, and dispatches the `process-video-events` background job to Inngest.
- **Custom S3 Gateway Support (`src/actions/s3.ts`, `src/env.js`)**: Extended the frontend S3 client with `AWS_ENDPOINT_URL_S3` to enable seamless integration with Supabase Storage S3-compatible gateways.
- **Evaluator Test Account & Graceful Auth (`src/app/dashboard/layout.tsx`)**: Configured database credit pre-seeding so evaluators test the full pipeline without Stripe billing, and added session recovery handling for stale cookies.


