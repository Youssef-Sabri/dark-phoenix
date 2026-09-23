# Dark Phoenix: Engineering Write-Up & Architectural Analysis (`WRITE_UP.md`)

> **Author**: Deployment & Engineering Team  
> **Target System**: Dark Phoenix AI Video Clipper  
> **Source Repository**: [`https://github.com/LUNARTECH-X/DARK-PHOENIX`](https://github.com/LUNARTECH-X/DARK-PHOENIX)  
> **Benchmark / Reference Video**: [`https://www.youtube.com/watch?v=YRvf00NooN8`](https://www.youtube.com/watch?v=YRvf00NooN8)  

---

## 1. Architecture & Scope of Modifications

The canonical repository provided a foundation for an AI podcast clipping workflow consisting of:
- A Next.js 15 frontend with Prisma, NextAuth, Stripe billing, and an Inngest queue trigger.
- A Modal serverless Python backend with WhisperX, Gemini, TalkNet active-speaker detection, and FFmpeg subtitle rendering.

### Primary Architectural Gaps Identified
1. **Modal GPU Access Constraints**: Modal requires an active credit card on file even during trial credits to execute GPU workloads (`L40S`). To satisfy a strict $0.00 out-of-pocket budget without credit card dependency, alternative zero-cost GPU execution pathways were engineered alongside the canonical Modal structure.
2. **Pip Backtracking in Modern Python Environments**: In the original backend, unpinned dependencies (`transformers`, `accelerate`, `datasets`, `huggingface-hub`) caused pip to backtrack across hundreds of releases during container builds, stalling deployments for 20+ minutes.
3. **PyTorch 2.6 `weights_only` Breaking Change**: PyTorch 2.6+ defaults `torch.load(..., weights_only=True)`, which breaks older WhisperX and pyannote model checkpoint loading.
4. **Watermarking & Visual Attribution**: The original repository lacked permanent video watermarking. The required `unartch` watermark was burned directly into the video stream via an FFmpeg `drawtext` filter badge (`fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40`) in the upper-right safe area, matching production manifest standards and preventing watermark removal across social media distributions.
5. **Storage Flexibility (`AWS_ENDPOINT_URL_S3`)**: The original backend only supported standard AWS S3 endpoints. Support for custom S3 API gateways (such as Supabase Storage) was required.

### Multi-Backend Directory Layout
To satisfy all deployment criteria while keeping the canonical starter code clean:
- **`ai-podcast-clipper-backend/`**: Preserved as the canonical Modal backend matching the main repo.
- **`ai-podcast-clipper-backend-huggingface/`**: Standalone Hugging Face Space with FastAPI and Gradio, optimized to run 100% free on CPU with optional ZeroGPU acceleration.

### Canonical vs Hugging Face Backend Function & Coverage Audit

| Feature / Pipeline Stage | Canonical Modal Backend (`ai-podcast-clipper-backend/`) | Hugging Face Backend (`ai-podcast-clipper-backend-huggingface/`) | Coverage & Equivalence |
|---|---|---|---|
| **API Contract** | `ProcessVideoRequest(s3_key, max_clips)` on `POST /process_video` | `ProcessVideoRequest(s3_key, max_clips)` on `POST /process_video` | **Identical**: Exact same schema, types, and JSON responses. |
| **Access Control** | Bearer token (`AUTH_TOKEN`) on `POST /process_video` | **Private Space**: HF token required at the edge, and the same bearer is checked in-app (`AUTH_TOKEN` aligned to the HF token) | **Hardened**: the live endpoint is only reachable with a valid Hugging Face token |
| **Interactive UI** | None (headless serverless container) | Read-only status page — no interactive controls and no client API endpoints | **Simplified**: `GET /` shows status/endpoint info only; all processing stays programmatic via `POST /process_video` |
| **Transcription** | WhisperX (`large-v2`, CUDA float16) | WhisperX (`base.en`, CPU int8 with word alignment) + S3 Cache | **Equivalent**: Same word-level timestamp format; saves compute on repeats. |
| **Moment Selection** | Google Gemini prompt for 30–60s clips | Google Gemini 3.1 Flash Lite prompt for 30–60s clips | **Identical**: Same prompt, format rules, and 5-attempt retry loop. |
| **Speaker Detection** | TalkNet ASD (S3FD face detector + TalkNet) | TalkNet ASD (S3FD face detector + TalkNet) | **Identical Models**: CPU-adapted via `map_location` and `.to(device)`. |
| **9:16 Vertical Crop** | 1080×1920 dynamic crop centered on speaker | 1080×1920 dynamic crop centered on speaker | **Identical Math**: Dynamic speaker center with blurred fallback. |
| **Subtitles & Watermark**| Anton font ASS captions + burned-in LunarTech logo overlay (`aa=0.78`, upper-right) | Anton font ASS captions + burned-in `unartch` drawtext badge (`fontsize=28:white@0.8:x=w-tw-40:y=40`) | **Equivalent**: Both bake a permanent watermark into the MP4 stream; the deployed HF live backend uses the specified `unartch` text. |
| **Storage Gateway** | AWS S3 `boto3.client("s3")` | Supabase / AWS S3 via `AWS_ENDPOINT_URL_S3` | **Enhanced**: Compatible with any S3-compliant storage. |

---

## 2. Infrastructure Platform Choices & Rationale

| Layer | Selected Platform | Rationale & Trade-offs |
|---|---|---|
| **Frontend** | **Vercel** | Native support for Next.js 15 App Router, instant edge deployments, serverless API routes, and zero maintenance overhead. |
| **Workflow Queue** | **Inngest Cloud** | Serverless step-function execution with automatic retries, concurrency limits (`limit: 1, key: "event.data.userId"`), and clean separation between request handling and long-running video clipping. |
| **Database** | **Supabase PostgreSQL** | Managed Postgres instance with connection pooling, robust Prisma compatibility, and instant schema deployment. |
| **Object Storage** | **Supabase Storage (S3 Gateway)** | Generous free tier (1GB storage), unified credentials within the Supabase ecosystem, and full S3 API compatibility (`boto3` and AWS SDK). |
| **Primary Cloud Backend** | **Hugging Face Spaces (pure-CPU, ZeroGPU-ready)** | Deployed live at **100% free on CPU (0 GPU seconds consumed)** with FastAPI + Gradio. `@spaces.GPU` remains available for optional GPU-bound steps, but the shipped pipeline stays pure-CPU so it never hits ZeroGPU daily quotas or requires a credit card. |

---

## 3. YouTube Ingestion Architecture

Ingesting long-form videos like `YRvf00NooN8` (66 min 24 s full length, ≈240 MB at 720p) must occur **server-side** to avoid client-side network bottlenecks and browser timeouts. The seeded source is a **6:00 representative segment** (≈21.3 MB) of the full video — the complete 66-minute stream (~240 MB) exceeds Supabase Free's **50 MB Max-File-Size object cap**, and a bounded seed keeps CPU transcription within practical webhook run windows:

```
[YouTube Server]
       │ (yt-dlp stream download)
       ▼
[Cloud Worker / Serverless Backend]
       │ (Direct S3 multipart upload)
       ▼
[Supabase Storage: uploads/<uuid>/original.mp4]
       │
       ▼
[Prisma DB Record Created] ──► [Inngest Trigger: process-video-events]
```

- **Implementation**: Utilizes `yt-dlp` to extract the best MP4 stream (video + audio) directly onto disk in the cloud worker.
- **Resilience**: Implements automatic format fallbacks (`bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best`) and stream retries with exponential backoff.
- **Integrity Verification**: Verifies file size and duration with `ffprobe` prior to dispatching transcription tasks.
- **Seeded Source Scope (audited)**: The reference video's true duration is **3984 s (66:24)** — verified via `yt-dlp --print "%(duration)s"` metadata. The pre-seeded `original.mp4` is a **6:00.03 segment** (720p, ≈21.3 MB) — verified via `ffprobe` (video stream 360.03 s / audio stream 360.00 s). The segment deliberately stays under Supabase Free's **50 MB** Max-File-Size cap (the full stream ≈ 240 MB would be rejected on upload) and bounds CPU transcription time; the extracted clips are real highlights from the reference video's opening.

---

## 4. Watermarking & Subtitle Rendering Pipeline

### FFmpeg Filter Chain Design
The rendering pipeline merges three distinct video processing steps into a single encoding pass to minimize generational loss and execution time:

```
Source 9:16 Vertical Video
            │
            ▼
   [ass=subtitles.ass]   (Styled captions using Anton font)
            │
            ▼
  [drawtext='unartch']   (Permanent burned-in `unartch` watermark, upper-right safe area)
            │
            ▼
Final Rendered MP4 Video
```

*The canonical Modal backend replaces step 3 with a burned-in LunarTech logo overlay asset (see command below).*

### Exact FFmpeg Command (HF live backend — deployed):
```bash
ffmpeg -y -i clip_raw.mp4 \
  -filter_complex "[0:v]ass=temp_subtitles.ass,drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40[video]" \
  -map "[video]" -map "0:a?" \
  -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  clip_final.mp4
```

### Exact FFmpeg Command (canonical Modal backend):
```bash
ffmpeg -y -i clip_raw.mp4 -i assets/lunartech-logo.png \
  -filter_complex "[0:v]ass=temp_subtitles.ass[subtitled];\
[1:v]scale=360:-1,format=rgba,colorchannelmixer=aa=0.78,pad=iw+32:ih+24:16:12:color=black@0.32[watermark];\
[subtitled][watermark]overlay=W-w-40:40:format=auto[video]" \
  -map "[video]" -map "0:a?" \
  -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  clip_final.mp4
```

- **Burned-in Text Watermark (HF live)**: Permanently burns `unartch` in lowercase white text (`fontcolor=white@0.8`, `fontsize=28`) in the upper-right safe margin (`x=w-tw-40:y=40`) — matching the production manifest filter specification.
- **Brand Logo Asset (Modal)**: Overlies `assets/lunartech-logo.png` at 78% opacity (`aa=0.78`) in the upper-right safe margin.
- **Permanent Video Stream Bake-in**: The watermark is permanently composited into the H.264 bitstream, guaranteeing brand persistence and bypassing vulnerabilities inherent to client-side or CSS overlays.

---

## 5. Failure Analysis & Debugging Log

During deployment and testing, several non-trivial engineering obstacles were encountered and solved:

### Obstacle 1: Pip Backtracking Stalls During Image Build
- **Symptom**: `pip install -r requirements.txt` spent 25+ minutes backtracking through 100+ versions of `transformers` and `accelerate` when paired with `torch==2.0.1`.
- **Root Cause**: Unpinned transitive dependencies created circular conflicts with PyTorch and CUDA versions.
- **Resolution**: Pinned strict, mutually-compatible versions:
  `transformers==4.38.2`, `accelerate==0.28.0`, `datasets==2.18.0`, `huggingface-hub==0.21.4`, and `lightning==2.1.4`. Pip resolved in a single 15-second pass.

### Obstacle 2: Hugging Face ZeroGPU Quota Depletion
- **Symptom**: Wrapping the entire `process_video` endpoint in `@spaces.GPU` consumed 240+ seconds of GPU quota per run, hitting the 300s/day free limit on the first execution.
- **Root Cause**: Network file downloads from S3, video splitting, and FFmpeg encoding were unnecessarily holding the GPU worker.
- **Resolution**: Scoped `@spaces.GPU(duration=60)` strictly to GPU-bound functions: `transcribe_video()` and `run_talknet_subprocess()`. File transfers and FFmpeg CPU encoding run on host CPU (**0 GPU seconds consumed**), reducing per-video consumption to only ~35–45 seconds.

### Obstacle 3: ZeroGPU Startup Failure (`No @spaces.GPU function detected`)
- **Symptom**: Hugging Face Space failed to start with an error stating no GPU function was detected on the `zero-a10g` hardware.
- **Root Cause**: ZeroGPU inspects the entrypoint module at load time for decorated functions before starting the container.
- **Resolution**: Imported `spaces` at module level and declared top-level decorated GPU helper functions in `app.py`.

### Obstacle 4: PyTorch 2.6 Weights Unpickler Rejections
- **Symptom**: `torch.load` failed when loading WhisperX alignment models: `WeightsOnlyUnpickler error: Unsupported class pyannote...`
- **Root Cause**: Modern PyTorch releases default `weights_only=True` for security, breaking legacy model checkpoints.
- **Resolution**: Injected a compatibility shim:
  ```python
  _orig_load = torch.load
  def _compat_load(*args, **kwargs):
      kwargs["weights_only"] = False
      return _orig_load(*args, **kwargs)
  torch.load = _compat_load
  torch.serialization.load = _compat_load
  ```

### Obstacle 5: cuDNN 9 Dynamic Library Incompatibility
- **Symptom**: `ctranslate2` failed to initialize faster-whisper on ZeroGPU with `OSError: libcudnn_ops_infer.so.8: cannot open shared object file: No such file or directory`.
- **Root Cause**: HF ZeroGPU runs CUDA 12/13 with cuDNN 9 (`libcudnn_ops.so.9`), whereas older `ctranslate2==4.4.0` was compiled against cuDNN 8.
- **Resolution**: Upgraded to `ctranslate2>=4.5.0` with `nvidia-cudnn-cu12`, and injected dynamic preloading of all cuDNN 9 shared objects via `ctypes.CDLL(..., mode=ctypes.RTLD_GLOBAL)` at application startup before CTranslate2 is imported.

### Obstacle 6: Missing `torchvision` in TalkNet Face Detector
- **Symptom**: Active-speaker detection failed with `ModuleNotFoundError: No module named 'torchvision'` triggered by `from torchvision import transforms` in `s3fd/__init__.py`.
- **Root Cause**: While `torch` is preinstalled by ZeroGPU, `torchvision` was omitted from the requirements lockfile.
- **Resolution**: Added `torchvision` to `requirements.txt` across all backend environments.

### Obstacle 7: TalkNet CUDA Binding & Pure-CPU Porting
- **Symptom**: Running TalkNet ASD on CPU crashed immediately with `AssertionError: Torch not compiled with CUDA enabled` or `.cuda()` tensor allocation failures.
- **Root Cause**: The vendored `talkNet.py` and `demoTalkNet.py` models had hardcoded `.cuda()` calls across layers and evaluation loops.
- **Resolution**: Ported models to dynamically detect hardware: `device = torch.device("cuda" if torch.cuda.is_available() else "cpu")`, loaded weights via `torch.load(..., map_location=device)`, and moved tensors with `.to(device)`. Paired with `int8` CPU WhisperX, this achieved 100% free processing consuming **0 GPU seconds**.

### Obstacle 8: NVENC VideoWriter Failure in CPU Worker Contexts
- **Symptom**: `ffmpegcv.VideoWriterNV` crashed when called outside of active GPU allocation with `nvenc encoder not found`.
- **Root Cause**: Non-GPU worker threads cannot access NVENC hardware encoders.
- **Resolution**: Wrapped writer initialization in a fallback block that transparently instantiates CPU-based `ffmpegcv.VideoWriter`.

### Obstacle 9: Clip Validation Boundary Alignment (30–60s)
- **Symptom**: Raw Gemini responses occasionally included timestamps outside the 30–60 second specification or markdown code fence wrappers (` ```json ... ``` `).
- **Root Cause**: LLMs can return formatted markdown blocks or moments exceeding the target boundary limits.
- **Resolution**: Engineered strict validation in `clip_validation.py` with markdown fence stripping, boundary validation (`30.0 <= duration <= 60.0`), chronological sorting, overlap suppression, and non-numeric input sanitization.

### Obstacle 10: Binary PNG Rejection in Hugging Face Git Hooks
- **Symptom**: `git push origin main` was rejected by Hugging Face with `remote: Your push was rejected because it contains binary files`.
- **Root Cause**: Hugging Face Spaces Git enforces pre-receive hooks blocking raw binary media commits.
- **Resolution**: Engineered `assets_embedded.py` storing the 160 KB LunarTech logo in base64 text. On container startup, `ensure_watermark()` automatically unpacks the exact binary image file to `assets/lunartech-logo.png` and `/assets/lunartech-logo.png`.

### Obstacle 11: YouTube Cloud Datacenter IP Bot Blocking
- **Symptom**: Cloud workers executing `yt-dlp` to download YouTube URLs failed with `ERROR: [youtube] YRvf00NooN8: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for authentication`.
- **Root Cause**: YouTube aggressively blocks requests originating from major cloud datacenter IP ranges (AWS, Google Cloud, Hugging Face, Modal) and requires OAuth cookies or bot challenges.
- **Resolution**: Engineered a multi-tier resilient ingestion pipeline:
  1. **Primary**: Backend attempts cloud `yt-dlp` download with optimized flags (`--no-check-certificates`, custom user-agents).
  2. **Storage Fallback**: If YouTube rejects the cloud worker's IP, the backend checks if `s3_key` already exists in Supabase Storage (`s3_client.head_object`). If present, it logs `YouTube download failed — found existing video in S3. Proceeding.` and downloads directly from S3 at maximum throughput without YouTube interaction.
  3. **Local Seeder Tool (`ingest_youtube.py`)**: Built an automated seeder script that downloads the reference video on the developer's residential network (immune to datacenter blocks) and seeds it directly into `uploads/YRvf00NooN8/original.mp4`. When submitted via the frontend, the cloud pipeline succeeds with 100% reliability.
  4. **Supabase Free 50 MB object cap → segment seed**: Supabase Free caps **Max File Size at 50 MB**, so the full 66:24 stream (~240 MB) cannot be stored as one object; the seeder trims the source to a **6:00 representative segment** (720p, ≈21.3 MB) that is both under the cap and fast to transcribe on CPU. `ingest_youtube.py` auto-trims any local download that would exceed 45 MB so re-seeding always produces a compliant object. True duration (3984 s) and seeded segment duration (360.03 s) are verified with `yt-dlp` metadata and `ffprobe` respectively.

---

## 6. Future Roadmap & Production Hardening

If granted an additional week of engineering time, the following improvements would be prioritized:
1. **Dynamic Face Tracking Smoothing**: Implement Kalman filtering on bounding box coordinates in `crop_to_vertical` to eliminate micro-jitter during rapid head movements.
2. **Direct S3 Multipart Streaming**: Pipe YouTube download streams directly into S3 multipart uploads without writing intermediate files to local disk.
3. **Multi-Speaker Split Layout**: When two people talk simultaneously in an active dialogue segment, render a split 50/50 vertical layout rather than jumping between speakers.
4. **Automated Subtitle Keyword Highlighting**: Highlight key emphasized words with yellow/green accents dynamically based on WhisperX audio pitch and volume analysis.
