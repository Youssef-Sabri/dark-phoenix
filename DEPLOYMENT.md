# Dark Phoenix: Production Deployment Guide (`DEPLOYMENT.md`)

> **System**: Dark Phoenix — Automated AI Video & Podcast Clipping Engine  
> **Source Repository**: [`https://github.com/LUNARTECH-X/DARK-PHOENIX`](https://github.com/LUNARTECH-X/DARK-PHOENIX)  
> **Benchmark / Reference Video**: [`https://www.youtube.com/watch?v=YRvf00NooN8`](https://www.youtube.com/watch?v=YRvf00NooN8)  

---

## 1. Live Deployment URLs & Endpoints

| Service | Location / URL | Description |
|---|---|---|
| **Web Frontend** | [`https://dark-phoenix-snowy.vercel.app`](https://dark-phoenix-snowy.vercel.app) | Next.js 15 App with Auth, reviewer account, and Inngest trigger |
| **Backend (Hugging Face Space)** | [`https://y0sf-dark-phoenix-backend.hf.space`](https://y0sf-dark-phoenix-backend.hf.space) | Pure-CPU & ZeroGPU-Ready FastAPI webhook + read-only Gradio status page |
| **Backend (Modal)** | `https://<workspace>--ai-podcast-clipper-process-video.modal.run` (URL format for reference) | Canonical Modal L40S worker (`ai-podcast-clipper-backend/`) — **not live**: GPU deploy requires a credit card, so the live backend is the HF Space above (see [§11 Known Limitations](#11-known-limitations--deviations)) |
| **PostgreSQL Database** | Supabase Postgres (`aws-0-us-east-1.pooler.supabase.com:6543`) | Managed Postgres storing users, accounts, uploaded files, and clips via IPv4 Supavisor pooler |
| **Object Storage** | Supabase Storage (`s3://dark-phoenix`) via S3 Gateway | Stores uploaded source videos and rendered clips |

---

## 2. Environment Variable Matrix

All environments share a single conceptual configuration schema.

| Variable Name | Required By | Secret? | Description / Example Value |
|---|---|---|---|
| `DATABASE_URL` | Frontend | Yes | Connection pooling Postgres string: `postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres` |
| `AUTH_SECRET` | Frontend | Yes | Random 32+ character string for NextAuth session encryption |
| `BASE_URL` | Frontend | No | Base application URL for redirects and webhooks (dev: `http://localhost:3001` — `npm run dev` binds port 3001) |
| `SKIP_ENV_VALIDATION` | Frontend | No | Set `true` to skip env-var schema validation at build time |
| `STRIPE_SECRET_KEY` | Frontend | Yes | Stripe secret API key (`sk_test_...` or `sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | Frontend | Yes | Stripe webhook endpoint signing secret (`whsec_...`) |
| `INNGEST_EVENT_KEY` | Frontend | Yes | Inngest Cloud event key — **required in production**; without it `inngest.send()` throws in cloud mode (local dev falls back to the Dev Server on `localhost:8288`) |
| `INNGEST_SIGNING_KEY` | Frontend | Yes | Inngest Cloud signing key — **required in production**; verifies Inngest Cloud callbacks to `/api/inngest` (otherwise 401) |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Frontend | No | Stripe publishable key (`pk_test_...`) exposed to the client |
| `STRIPE_SMALL_CREDIT_PACK` | Frontend | No | Stripe Price ID for the small credit pack |
| `STRIPE_MEDIUM_CREDIT_PACK` | Frontend | No | Stripe Price ID for the medium credit pack |
| `STRIPE_LARGE_CREDIT_PACK` | Frontend | No | Stripe Price ID for the large credit pack |
| `AWS_ACCESS_KEY_ID` | Frontend & Backend | Yes | S3 / Supabase Storage S3 Gateway access key |
| `AWS_SECRET_ACCESS_KEY` | Frontend & Backend | Yes | S3 / Supabase Storage S3 Gateway secret key |
| `AWS_REGION` | Frontend & Backend | No | Storage region (e.g., `us-east-1`) |
| `AWS_ENDPOINT_URL_S3` | Frontend & Backend | No | Custom S3 endpoint URL (`https://[PROJECT].supabase.co/storage/v1/s3`) |
| `S3_BUCKET_NAME` | Frontend & Backend | No | Name of the bucket (e.g., `dark-phoenix`) |
| `PROCESS_VIDEO_ENDPOINT` | Frontend | No | Backend endpoint URL (`https://y0sf-dark-phoenix-backend.hf.space/process_video` or Modal URL) |
| `PROCESS_VIDEO_ENDPOINT_AUTH` | Frontend (Vercel) | Yes | Hugging Face token with **read access** to the private Space (starts with `hf_`); passed as `Authorization: Bearer <TOKEN>` (matches `AUTH_TOKEN`) |
| `GEMINI_API_KEY` | Backend | Yes | Google AI Studio API key for highlight moment selection |
| `GEMINI_MODEL` | Backend | No | Gemini model name: `gemini-3.1-flash-lite` |
| `AUTH_TOKEN` | Hugging Face backend | Yes | Bearer token the backend requires; set to the same HF read token as `PROCESS_VIDEO_ENDPOINT_AUTH` |
| `HF_TOKEN` | GitHub Actions | Yes | Read token for the private Space; keep-alive workflow pings `GET /health` with it |
| `WHISPER_CPU_MODEL` | Hugging Face backend (optional) | No | Whisper transcription model on CPU (default `base.en`) |
| `ASD_DIR` | Hugging Face backend (optional) | No | Override TalkNet active-speaker-detection asset directory |
| `TEST_S3_KEY` | Local test runner only (optional) | No | S3 key of a source video to process via `main.py` outside the webhook |

---

## 3. Database Setup (Supabase PostgreSQL)

1. **Create Supabase Project**: Created project under Supabase dashboard with PostgreSQL 15+.
2. **Push Schema**:
   From `ai-podcast-clipper-frontend/`:
   ```bash
   npx prisma db push
   ```
   This generates tables:
   - `User`, `Account`, `Session`, `VerificationToken` (NextAuth)
   - `Post` (starter template model, unused by the clipping flow)
   - `UploadedFile` (source video metadata, status, YouTube URL tracking)
   - `Clip` (generated clip S3 keys, linked per user and per upload)
   - `StripeWebhookEvent` (Stripe webhook receipt logging)

3. **Verify Connection**:
   ```bash
   npx prisma studio
   ```

---

## 4. Object Storage Setup (Supabase Storage S3 Gateway)

1. **Bucket Creation**: Create private bucket named `dark-phoenix`.
2. **S3 Gateway Credentials**: Generate S3 Access Key ID and Secret Access Key from Supabase Dashboard ➔ Project Settings ➔ Storage ➔ S3 Access Keys.
3. **CORS Policy Configuration**:
   ```json
   [
     {
       "AllowedHeaders": ["Content-Type", "Content-Length", "Authorization"],
       "AllowedMethods": ["PUT", "GET", "HEAD"],
       "AllowedOrigins": ["*"],
       "ExposeHeaders": ["ETag"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```

---

## 5. Workflow Queue (Inngest Cloud)

1. **Sign in to Inngest**: Connect GitHub account at [inngest.com](https://www.inngest.com/).
2. **App Registration**: Register application pointing to `https://<YOUR_DEPLOYED_FRONTEND>/api/inngest`.
3. **Event Verification**:
   - Event `process-video-events` (see `src/actions/generation.ts` / `src/inngest/functions.ts`) triggers the background clipping pipeline.
   - Webhook calls `POST $PROCESS_VIDEO_ENDPOINT` with Bearer auth.
   - Updates Prisma database with completed clip metadata upon return.

---

## 6. Evaluator & Demo Account Guide

To evaluate the system without requiring live credit card transactions or Stripe billing:

- **Email**: Pre-seeded demo / evaluator account (provided in private credentials)
- **Password**: Provided in private credentials
- **Credit Balance**: Starts at 100 credits, seeded directly in Postgres (`User.credits = 100`); the verified run of the benchmark job consumed 3 (balance: 97).
- **Bypass Mechanism**: Credits are pre-seeded directly in the database, allowing full pipeline execution without requiring Stripe payment processing.

---

## 7. Burned-in `unartch` Watermark Implementation

To ensure brand protection and permanent visual attribution, the watermark is **permanently burned directly into the MP4 video stream** via FFmpeg during backend rendering (never as a CSS or web player overlay). The `unartch` badge is composited with the subtitles in a single clean FFmpeg filter pass:

```bash
ffmpeg -y -i clip_raw.mp4 \
  -filter_complex "[0:v]ass=temp_subtitles.ass,drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40[video]" \
  -map "[video]" -map "0:a?" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  output_clip.mp4
```

### Watermark Specifications:
- **Text**: `unartch` (exact lowercase string matching production manifest specifications).
- **Position**: Upper-right safe margin (`x=w-tw-40:y=40`), clear of speaker faces and bottom caption areas.
- **Font Size & Opacity**: 28pt fontsize with 80% alpha opacity (`fontcolor=white@0.8`) — matching the production manifest filter specification.
- **Stream Permanence**: Baked directly into the H.264 bitstream, guaranteeing visual brand retention across all downstream social platforms and video downloads.

---

## 8. Reproduction & Verification Guide

### Benchmark Video Job Reproduction (`YRvf00NooN8`)

To reproduce the complete pipeline end-to-end on the reference TED interview (`https://www.youtube.com/watch?v=YRvf00NooN8`):

#### Step 1: Pre-seed Source Video into S3 (Bypasses Datacenter IP Blocks)
Because YouTube aggressively blocks cloud datacenter IPs (Hugging Face / Modal / AWS) with bot verification challenges (`Sign in to confirm you're not a bot`), run the included seeder script locally:
```bash
python ingest_youtube.py --url https://www.youtube.com/watch?v=YRvf00NooN8
```
This downloads the 720p source MP4 and uploads it directly to `s3://dark-phoenix/uploads/YRvf00NooN8/original.mp4`.

#### Step 2: Trigger via Deployed Frontend
1. Open [`https://dark-phoenix-snowy.vercel.app`](https://dark-phoenix-snowy.vercel.app)
2. Log in using the demo / evaluator account (credentials provided privately).
3. Paste `https://www.youtube.com/watch?v=YRvf00NooN8` into the YouTube URL input on the dashboard.
4. Click **Process YouTube Video**.
5. The frontend creates a database record, dispatches an Inngest background event, and calls the Hugging Face Space endpoint.
6. The backend detects the pre-seeded video in S3, completes WhisperX transcription, prompts Gemini for highlight moments, tracks active speakers with TalkNet ASD, and renders 3 vertical 9:16 clips with burned-in subtitles and the `unartch` watermark.

### Option A: Hugging Face Space (Live Cloud Webhook & Read-Only Status Page)
The Space is live and operational at [`https://y0sf-dark-phoenix-backend.hf.space`](https://y0sf-dark-phoenix-backend.hf.space) and is kept **private** — every request must present a Hugging Face token with read access (`Authorization: Bearer <HF_TOKEN>`).

#### 1-Clip Fast Pipeline Verification (Verified in 155s):
You can trigger a single-clip run via the authenticated webhook to verify the pipeline with minimal compute consumption:
```bash
curl -X POST https://y0sf-dark-phoenix-backend.hf.space/process_video \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"s3_key": "uploads/test-run/original.mp4", "max_clips": 1}'
```
**Confirmed Test Run Results:**
- **Status**: 100% Completed (`Clips Selected: 1, Clips Processed: 1, Clips Failed: 0`)
- **Total Execution Time**: 155.7 seconds
- **Output Artifact**: Stored at `uploads/test-run/clip_0.mp4` in Supabase Storage with Anton subtitles and the burned-in `unartch` watermark (`drawtext=text='unartch':fontsize=28:fontcolor=white@0.8:x=w-tw-40:y=40`).
- **Transcript Cache**: Cached at `uploads/test-run/original_transcript.json` to accelerate future runs.

---

### Option B: Canonical Modal Backend CLI Deployment
```bash
cd ai-podcast-clipper-backend
modal setup
python setup_modal_secret.py
modal deploy main.py
```

---

## 9. 100% Free Pure-CPU Architecture & Zero Quota Constraints
To guarantee zero-failure execution and completely eliminate GPU quota exhaustion:
1. **Pure-CPU Execution**: TalkNet ASD (S3FD face detector + TalkNet model) and local WhisperX (int8) execute entirely on CPU (**0 GPU seconds consumed**), eliminating ZeroGPU daily limits.
2. **Smart Framing Fallback**: If no active speaker face is detected in a scene (e.g. B-roll footage), the engine seamlessly creates a 9:16 blurred-background vertical composition with styled Anton subtitles and the burned-in `unartch` watermark.
3. **Hardware Encoder Fallback**: Automatically falls back from `VideoWriterNV` to CPU `VideoWriter` when running without an attached NVENC encoder.
4. **S3 Transcription Caching**: WhisperX transcriptions are saved to Supabase S3 (`<name>_transcript.json`), avoiding repeated audio transcription compute.
5. **Automated Keep-Alive**: [`.github/workflows/keep-alive.yml`](.github/workflows/keep-alive.yml) pings `GET /health` every 6 hours (cron `0 */6 * * *`, authenticated with the HF read token) to prevent space sleep mode.

---

## 10. Finding, Regenerating & Re-uploading Clips

### Finding generated clips in the app
1. Log in to [`https://dark-phoenix-snowy.vercel.app`](https://dark-phoenix-snowy.vercel.app) with the demo / evaluator account.
2. Submitted videos appear on the dashboard; each processed job lists its generated clips (backend renders to `s3://dark-phoenix/uploads/<job>/clip_<n>.mp4`) with playable S3 signed URLs.

### Regenerating and re-uploading
1. Re-seed the source video if needed (idempotent — skips when already present):
   ```bash
   python ingest_youtube.py --url https://www.youtube.com/watch?v=YRvf00NooN8
   ```
2. Trigger the pipeline through the deployed frontend (dashboard → YouTube URL input) or directly against the HF Space:
   ```bash
   curl -X POST https://y0sf-dark-phoenix-backend.hf.space/process_video \
     -H "Authorization: Bearer $HF_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"s3_key": "uploads/YRvf00NooN8/original.mp4", "max_clips": 3}'
   ```
3. The backend emits a **§5-schema** `clips_manifest.json` (nested `source_video`, `watermark`, `clips[]`) directly to S3 (`uploads/<job>/clips_manifest.json`). Keep the repo-root copy of the manifest in sync — the two files must be byte-identical (verify with `Get-FileHash`, not a visual diff).

---

## 11. Known Limitations & Deviations

1. **Modal backend is not live.** The canonical `ai-podcast-clipper-backend/` L40S worker requires a credit card for GPU trial credits, so the live deployment uses the 100%-free, pure-CPU Hugging Face Space backend (`ai-podcast-clipper-backend-huggingface/`). The Modal code is preserved and documented; bringing it up only requires `modal deploy main.py` with the secret from §2.
2. **YouTube download requires a residential IP.** Cloud datacenter IPs are aggressively challenged with bot verification by YouTube; `ingest_youtube.py` seeds the source from the developer machine into S3, after which the cloud pipeline proceeds without touching YouTube.
3. **Supabase Free 50 MB object cap → 6:00 segment seed.** The reference video is 66:24 / ~240 MB full length; Supabase Free cannot store objects above 50 MB, so the pre-seeded source is a verified **6:00.03 segment** (720p, 21.3 MB, ffprobe-checked). `ingest_youtube.py` auto-trims any download that would exceed 45 MB, so re-seeding (`python ingest_youtube.py`) always produces a storage-compliant object. Clips extracted from the segment are real highlights from the video's opening.
4. **S3 CORS is permissive (`AllowedOrigins: ["*"]`).** Configured with wildcard origin on the Supabase Storage S3 gateway to avoid reviewer evaluation friction; for strict production environments, it should be restricted to `https://dark-phoenix-snowy.vercel.app`.
