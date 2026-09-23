# Dark Phoenix Frontend (Next.js 15)

The web dashboard and client application for **Dark Phoenix**, an automated AI-powered video clipping platform.

---

## 1. Overview & Architecture

The frontend serves as the primary user interface for Dark Phoenix, allowing users and reviewers to submit YouTube URLs or upload video files, monitor background clipping pipelines, and preview/download generated vertical clips.

### Tech Stack
- **Framework**: Next.js 15 (App Router with TurboPack)
- **UI & Components**: React 19, Tailwind CSS v4, Radix UI primitives, Lucide Icons, Sonner notifications
- **Authentication**: Auth.js (`next-auth` v5 beta) with credentials login and Prisma adapter
- **Database**: Prisma Client v6 connected to PostgreSQL (Supabase)
- **Object Storage**: AWS S3 SDK v3 (`@aws-sdk/client-s3`) supporting custom S3 API gateways (`AWS_ENDPOINT_URL_S3`)
- **Queue Client**: Inngest SDK v3 (`src/inngest/`) dispatching background events to the clipping pipeline

---

## 2. Key Features

- **Server-Side YouTube Ingestion**: Dashboard input for YouTube URLs (`https://www.youtube.com/watch?v=YRvf00NooN8`). A Next.js server action validates the URL, creates an `UploadedFile` record, and triggers Inngest. Video downloading and processing occur entirely server-side.
- **Direct File Upload**: Client-side signed S3 PUT URL generation for direct video file uploads.
- **Reviewer Test Account**: Pre-seeded database credentials and credits (`User.credits`), bypassing credit-card entry and Stripe checkout for review evaluation.
- **Vertical Clip Player**: Responsive 9:16 vertical video player rendering clips from signed S3 GET URLs with one-click download.

---

## 3. Directory Layout

```
ai-podcast-clipper-frontend/
├── prisma/
│   └── schema.prisma             # PostgreSQL schema (User, UploadedFile, Clip, Account)
├── src/
│   ├── actions/
│   │   ├── generation.ts         # Job creation, YouTube URL submission, and Inngest trigger
│   │   ├── s3.ts                 # S3 signed PUT and GET URL generation
│   │   └── stripe.ts             # Credit purchasing and Stripe session management
│   ├── app/
│   │   ├── api/inngest/route.ts  # Inngest webhook route
│   │   ├── dashboard/            # User dashboard (clip display & submission tabs)
│   │   └── login/                # Authentication page with reviewer login helper
│   ├── components/
│   │   ├── clip-display.tsx      # 9:16 vertical clip video player
│   │   └── dashboard-client.tsx  # Dashboard interface with YouTube URL and file upload tabs
│   ├── env.js                    # Type-safe environment variable schema
│   └── inngest/
│       ├── client.ts             # Inngest client configuration
│       └── functions.ts          # Video processing workflow function
├── next.config.js                # Next.js configuration
└── package.json                  # Scripts and dependencies
```

---

## 4. Local Development Runbook

```bash
# Install dependencies
npm install

# Push Prisma schema to PostgreSQL
npm run db:push

# Start development server on port 3001
npm run dev

# Start local Inngest Dev Server (optional, for local queue testing)
npm run inngest-dev
```
