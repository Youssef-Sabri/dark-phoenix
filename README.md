<p align="center">
  <img src="branding/lunartech-banner.png" alt="LUNARTECH" width="100%">
</p>

<h1 align="center">Dark Phoenix</h1>

<p align="center">
  <strong>Production AI-Powered Podcast & Video Clipper</strong><br>
  A <a href="https://lunartech.ai/">LUNARTECH</a> Labs Project &bull; Created by <a href="https://www.linkedin.com/in/vahe-aslanyan/">Vahe Aslanyan</a>
</p>

---

## 1. Executive Summary & Overview

**Dark Phoenix** is an automated, end-to-end AI clipping engine that ingests long-form video podcasts, transcribes dialogue with word-level precision, detects viral highlight moments using LLMs, tracks active speakers dynamically, crops footage to a 9:16 vertical aspect ratio, and burns styled animated subtitles with a permanent watermark directly into the MP4 video bytes.

### Core Processing Pipeline
```
[YouTube / S3 Source Video]
           │
           ▼
[1. WhisperX] ──► Word-level audio transcription & timestamp alignment
           │
           ▼
[2. Google Gemini 3.1 Flash Lite] ──► Intelligent highlight moment selection (30–60s)
           │
           ▼
[3. TalkNet ASD] ──► Active speaker face detection & continuous tracking
           │
           ▼
[4. 9:16 Vertical Cropper] ──► Dynamic framing centered on active speaker
           │
           ▼
[5. FFmpeg Ass Subtitles] ──► Styled animated subtitles (Anton font)
           │
           ▼
[6. FFmpeg `unartch` Watermark] ──► Burned-in `unartch` watermark overlay (Upper-right safe area)
           │
           ▼
[Rendered Output Clips] ──► Stored in Supabase Storage S3 & delivered to user
```

---

## 2. Complete System Architecture

```
                                [User / Reviewer Browser]
                                           │
                      ┌────────────────────┴────────────────────┐
                      ▼                                         ▼
           [Vercel: Next.js 15 UI]                   [Hugging Face Space]
                      │                                         │
                      │                                ┌────────┴────────┐
                      │ (Signed PUT/GET)               ▼                 ▼
                      ▼                     [Supabase PostgreSQL]  [Supabase S3]
       [Supabase Storage: S3 Gateway] ◄──────────────────────────────────┘
                      ▲
                      │ (Webhook Trigger: POST /process_video)
                      ▼
           [Inngest Cloud Queue]
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
  [Modal GPU Worker (L40S)]  [Hugging Face ZeroGPU]
```

---

## 3. Repository Layout

```
dark-phoenix/
├── .env                                ← Master environment file (gitignored)
├── .env.example                        ← Documented template with upload destinations
├── README.md                           ← Master root documentation (single source of truth)
├── DEPLOYMENT.md                       ← Production deployment & infrastructure guide
├── WRITE_UP.md                         ← Engineering analysis, failure log & trade-offs
├── CHANGES.md                          ← Detailed codebase changelog & audit
│
├── ai-podcast-clipper-frontend/        ← Next.js 15 App (React 19, Prisma, NextAuth, Inngest)
│   ├── src/                            ← Frontend application code
│   ├── prisma/                         ← PostgreSQL schema & migrations
│   ├── README.md                       ← Dedicated frontend guide & local dev runbook
│   └── next.config.js                  ← Loads ../.env via @next/env
│
├── ai-podcast-clipper-backend/         ← [Canonical] Modal serverless GPU backend (L40S)
│   ├── main.py                         ← Modal entrypoint & pipeline
│   ├── asd/                            ← TalkNet active-speaker detection module
│   ├── setup_modal_secret.py           ← Synchronizes ../.env into Modal Secret
│   └── requirements.txt                ← Python dependencies
│
└── ai-podcast-clipper-backend-huggingface/ ← [Free Cloud] Hugging Face Space backend
    ├── app.py                          ← FastAPI webhook + read-only Gradio status page
    ├── main.py                         ← Clipper engine with scoped GPU execution
    ├── requirements.txt                ← Fast-resolving pinned dependency lock
    └── packages.txt                    ← System dependencies (ffmpeg, fontconfig)
```

---

## 4. Backend Deployment Matrix & Options

Dark Phoenix provides two production-grade backend execution environments:

| Feature | Modal Backend (`ai-podcast-clipper-backend/`) | Hugging Face Space (`ai-podcast-clipper-backend-huggingface/`) |
|---|---|---|
| **Platform** | [Modal.com](https://modal.com/) | [Hugging Face Spaces](https://huggingface.co/spaces) |
| **Hardware** | NVIDIA L40S GPU | Pure-CPU & ZeroGPU-Ready |
| **Cost** | Trial credits (requires card) | **100% Free** ($0.00, no card) |
| **Interface** | Serverless REST API | FastAPI (`/process_video`) + read-only Gradio status page |
| **Status** | Canonical main repo code | **Live, Deployed & Tested** |
| **Live Link** | Modal endpoint URL | [huggingface.co/spaces/Y0sf/dark-phoenix-backend](https://huggingface.co/spaces/Y0sf/dark-phoenix-backend) |

---

## 5. Master Environment Variable Guide

All secrets and settings are centralized in [.env](.env) (gitignored) and [.env.example](.env.example). Each key is categorized below by the exact cloud platform where it must be uploaded:

### A. Database & Object Storage (Supabase)
- **`DATABASE_URL`**: Supabase PostgreSQL connection string.  
  *(Upload to **Vercel** as an Environment Variable).*
- **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, **`AWS_REGION`**, **`AWS_ENDPOINT_URL_S3`**, **`S3_BUCKET_NAME`**: Supabase Storage S3-Compatible Gateway credentials.  
  *(Upload to **Vercel**, **Hugging Face Secrets**, and **Modal Secrets**).*

### B. Backend Endpoint & Authentication
- **`PROCESS_VIDEO_ENDPOINT`**: URL of the active clipping backend.  
  *(Upload to **Vercel**)* — e.g. `https://y0sf-dark-phoenix-backend.hf.space/process_video`.
- **`PROCESS_VIDEO_ENDPOINT_AUTH`**: Hugging Face token with **read access** to the Space (starts with `hf_`). Sent as `Authorization: Bearer <token>`; must equal the Space's `AUTH_TOKEN` secret.  
  *(Upload to **Vercel** as `PROCESS_VIDEO_ENDPOINT_AUTH` and to **Hugging Face Secrets** as `AUTH_TOKEN`)*.
- **`HF_TOKEN`** *(GitHub Actions only)*: The same token, stored as a repository secret; the keep-alive workflow pings `GET /health` on the **private** Space with it. Create/rotate at <https://huggingface.co/settings/tokens> (recommended: fine-grained token with Read access on `Y0sf/dark-phoenix-backend`).

### C. Highlight Moment Detection (Google AI Studio)
- **`GEMINI_API_KEY`**: Google AI Studio API key.  
  *(Upload to **Hugging Face Secrets** and **Modal Secrets**).*
- **`GEMINI_MODEL`**: Set to `gemini-3.1-flash-lite`.

### D. Frontend Auth & Web App (NextAuth / Next.js)
- **`AUTH_SECRET`**: Random 32+ character string for NextAuth session JWT signing.  
  *(Upload to **Vercel**).*
- **`BASE_URL`**: Canonical web URL (e.g. `https://dark-phoenix-xyz.vercel.app` or `http://localhost:3001`).  
  *(Upload to **Vercel**).*
- **`SKIP_ENV_VALIDATION`**: Set to `"true"` to streamline CI/CD builds.

### E. Background Queue & Payments (Inngest & Stripe)
- **`INNGEST_EVENT_KEY`**: Inngest Cloud event key — **required in production**. `inngest.send()` throws in cloud mode (`VERCEL_ENV=production`) without it; on local dev the SDK auto-falls back to the Dev Server (`localhost:8288`).  
  *(Upload to **Vercel**).*
- **`INNGEST_SIGNING_KEY`**: Inngest Cloud signing key — **required in production**. Without it, `/api/inngest` signature validation fails and Inngest Cloud callbacks return 401.  
  *(Upload to **Vercel**).*
- **`STRIPE_SECRET_KEY`**, **`STRIPE_WEBHOOK_SECRET`**, **`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`**: Stripe keys.  
  *(Upload to **Vercel**).*
- **`STRIPE_SMALL_CREDIT_PACK`**, **`STRIPE_MEDIUM_CREDIT_PACK`**, **`STRIPE_LARGE_CREDIT_PACK`**: Stripe Price IDs for each credit pack.  
  *(Upload to **Vercel**).*

---

## 6. How to Run Each Component

### 1. Frontend (Next.js 15)
```bash
cd ai-podcast-clipper-frontend
npm install
npx prisma db push       # Sync Prisma schema with Supabase PostgreSQL
npm run dev              # Starts local server at http://localhost:3001 (next dev --turbo -p 3001)
```

### 2. Hugging Face Space (Active 100% Free Cloud Backend)
The backend is live, operational, and verified end-to-end at:
[`https://huggingface.co/spaces/Y0sf/dark-phoenix-backend`](https://huggingface.co/spaces/Y0sf/dark-phoenix-backend)

**Key Capabilities & Optimizations:**
- **100% Free Pure-CPU Execution**: TalkNet ASD face tracking and local WhisperX (int8) run entirely on CPU (**0 GPU seconds consumed**), eliminating ZeroGPU daily quota limits and credit card requirements.
- **Graceful Hardware Fallbacks**: If NVENC GPU encoder is unavailable, the pipeline automatically uses CPU `VideoWriter` with 1080×1920 dynamic speaker tracking, guaranteeing 100% completion reliability.
- **S3 Transcript Caching**: Automatically persists WhisperX transcriptions to `<video_name>_transcript.json` in the Supabase S3 bucket to eliminate redundant transcription compute on repeat runs.
- **Modern cuDNN 9 & CUDA 12 Support**: Pinned `ctranslate2>=4.5.0` with `nvidia-cudnn-cu12` runtime library preloading for Blackwell/Hopper compatibility.
- **Dual Interface**:
  - `POST /process_video`: Authenticated webhook endpoint for Inngest Cloud and Next.js.
  - `GET /`: Read-only status page (no interactive controls); processing is programmatic via `POST /process_video` or the frontend.

To deploy or update:
1. Create a Space with the **Gradio SDK** (a plain CPU Space is sufficient — the pipeline runs 100% on CPU; ZeroGPU is optional and not required).
2. Add the 8 Space secrets (`AUTH_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ENDPOINT_URL_S3`, `S3_BUCKET_NAME`). The same HF read token is stored as GitHub repository secret `HF_TOKEN` for the keep-alive workflow (see §B).
3. Push files from `ai-podcast-clipper-backend-huggingface/`.
4. In the Space's **Settings → Visibility**, set it to **Private**, and set its `AUTH_TOKEN` secret to the same HF read token used in §B, so the bearer passes both the private-Space edge and the in-app check.

### 3. Canonical Modal Backend
```bash
cd ai-podcast-clipper-backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python setup_modal_secret.py                       # Syncs root .env into Modal Secret
modal deploy main.py                               # Deploys L40S GPU worker
```

---

## 7. Watermark & Subtitle Specifications

### Burned-in `unartch` Watermark
The watermark is permanently baked into the video stream via FFmpeg (never a CSS/web-player overlay). The deployed HF live backend uses the exact `drawtext` filter matching the production manifest specification:
```bash
ffmpeg -y -i input_clip.mp4 \
  -filter_complex "[0:v]ass=subtitles.ass,drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40[video]" \
  -map "[video]" -map "0:a?" \
  -c:v h264 -preset fast -crf 23 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  output_watermarked_clip.mp4
```
The canonical Modal backend instead overlays the LunarTech logo (`assets/lunartech-logo.png`) at 78% opacity in the upper-right safe margin.
- **Text**: `unartch` (exact lowercase string per production specification).
- **Position**: Upper-right safe margin (`x=w-tw-40:y=40`), clear of speaker faces and bottom caption areas.
- **Styling**: White text at 80% opacity (`fontcolor=white@0.8`), `fontsize=28` — matching the production manifest filter specification.

### Anton Font Subtitles
Subtitles are generated in ASS format using `pysubs2` with the Anton font, high-contrast white fill, black stroke border (width 3), bottom-center vertical alignment, and chunked to max 5 words for modern social video consumption.

---

## 8. Key Documentation Links

- **[`DEPLOYMENT.md`](DEPLOYMENT.md)**: Master production deployment guide, cloud credentials matrix, reviewer account details, and verification steps.
- **[`WRITE_UP.md`](WRITE_UP.md)**: Engineering analysis, architectural rationale, debugging log (pip backtracking, ZeroGPU quota scoping, PyTorch 2.6 unpickler fix), and future roadmap.
- **[`CHANGES.md`](CHANGES.md)**: Full audit of modifications, directory refactors, and feature additions.
- **[`ai-podcast-clipper-frontend/README.md`](ai-podcast-clipper-frontend/README.md)**: Next.js 15 frontend architecture, YouTube ingestion UI, and local dev runbook.

---

## 9. License

See [LICENSE.MD](LICENSE.MD).
