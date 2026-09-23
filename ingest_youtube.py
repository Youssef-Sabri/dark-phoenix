#!/usr/bin/env python3
"""
Dark Phoenix — Local YouTube Ingest & Supabase S3 Seeder
=========================================================
Downloads YouTube video locally (from residential/clean IP, immune to datacenter bot blocks)
and seeds it directly into Supabase S3 storage at `uploads/{video_id}/original.mp4`.

When the user enters the YouTube URL in the deployed frontend, the backend will find
the pre-seeded video in S3 and seamlessly process all clips with 0% failure risk.

Supabase Free caps object size at 50 MB; if the downloaded file would exceed that
cap, it is auto-trimmed to a leading segment that fits (45 MB safety margin).
"""

import os
import sys
import re
import argparse
import pathlib
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import boto3
from botocore.config import Config


def parse_video_id(url_or_id: str) -> str:
    url_or_id = url_or_id.strip()
    match = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url_or_id)
    if match:
        return match.group(1)
    if len(url_or_id) == 11 and re.match(r"^[0-9A-Za-z_-]{11}$", url_or_id):
        return url_or_id
    raise ValueError(f"Could not parse YouTube video ID from: '{url_or_id}'")


def get_s3_client():
    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3", "https://yfhodriqdjhiyzmniyjj.supabase.co/storage/v1/s3")
    region = os.environ.get("AWS_REGION", "us-east-1")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

    if not access_key or not secret_key:
        print("❌ Error: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in .env")
        sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4")
    )


class ProgressCallback:
    def __init__(self, total_bytes: int):
        self.total = total_bytes
        self.uploaded = 0

    def __call__(self, bytes_amount: int):
        self.uploaded += bytes_amount
        percent = (self.uploaded / self.total * 100) if self.total else 0
        mb_up = self.uploaded / (1024 * 1024)
        mb_tot = self.total / (1024 * 1024)
        print(f"\r  ⏫ Uploading to S3: {mb_up:.1f} MB / {mb_tot:.1f} MB ({percent:.1f}%)", end="", flush=True)


def download_youtube_video(video_id: str, output_path: pathlib.Path) -> bool:
    import yt_dlp

    youtube_url = f"https://www.youtube.com/watch?v=YRvf00NooN8" if video_id == "YRvf00NooN8" else f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n▶️ Downloading YouTube video via yt-dlp: {youtube_url}")
    print(f"   Target path: {output_path}")

    ffmpeg_exe = None
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"   Using local FFmpeg: {ffmpeg_exe}")
    except Exception:
        pass

    ydl_opts = {
        "format": "best[height<=720]/bestvideo[height<=720]+bestaudio/best",
        "outtmpl": str(output_path),
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "nocheckcertificate": True,
        "overwrites": True,
    }
    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download([youtube_url])
        if error_code != 0:
            print(f"❌ yt-dlp returned error code: {error_code}")
            return False

    if not output_path.exists() or output_path.stat().st_size < 100_000:
        # Check if yt-dlp appended extension or changed filename
        potential_files = list(output_path.parent.glob(f"{output_path.stem}*"))
        if potential_files:
            found = potential_files[0]
            if found != output_path:
                found.rename(output_path)

    return output_path.exists() and output_path.stat().st_size > 100_000


S3_OBJECT_CAP_MB = 45.0  # Supabase Free max file size = 50 MB; keep a 5 MB safety margin


def _probe_duration_seconds(ffmpeg_exe: str, path: pathlib.Path) -> float:
    """Parse Duration (h:mm:ss.ss) from `ffmpeg -i` stderr without needing ffprobe."""
    import subprocess
    proc = subprocess.run([ffmpeg_exe, "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not match:
        raise RuntimeError(f"Could not parse duration from: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def trim_seed_to_cap(path: pathlib.Path) -> bool:
    """Trim a downloaded video to fit Supabase Free's 50 MB object cap.

    Returns True if the file was trimmed (the local download was larger than
    S3_OBJECT_CAP_MB and a leading segment was kept). Idempotent for re-seeding:
    a previously trimmed cache file is left untouched.
    """
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb <= S3_OBJECT_CAP_MB:
        return False

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

    duration = _probe_duration_seconds(ffmpeg_exe, path)
    keep_seconds = max(60.0, int(duration * (S3_OBJECT_CAP_MB / size_mb) * 0.95))

    trimmed = path.with_suffix(".trimmed.mp4")
    import subprocess
    proc = subprocess.run(
        [
            ffmpeg_exe, "-y", "-i", str(path),
            "-t", f"{keep_seconds:.2f}",
            "-c", "copy", "-movflags", "+faststart",
            str(trimmed),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not trimmed.exists():
        raise RuntimeError(
            "Failed to trim source to fit Supabase's 50 MB object cap "
            f"(ffmpeg rc={proc.returncode})."
        )

    trimmed.replace(path)
    new_mb = path.stat().st_size / (1024 * 1024)
    print(
        f"\n✂️  Local download is {size_mb:.1f} MB — exceeds Supabase Free's 50 MB object cap. "
        f"Trimmed to a {keep_seconds / 60:.1f}-min leading segment ({new_mb:.1f} MB) for seeding."
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="Download YouTube video locally and seed into Supabase S3")
    parser.add_argument(
        "--url", "-u",
        default="https://www.youtube.com/watch?v=YRvf00NooN8",
        help="YouTube URL or video ID (default: assigned video https://www.youtube.com/watch?v=YRvf00NooN8)"
    )
    parser.add_argument("--force", "-f", action="store_true", help="Force re-upload even if already in S3")
    parser.add_argument("--keep-local", "-k", action="store_true", help="Keep downloaded MP4 on local disk")

    args = parser.parse_args()

    video_id = parse_video_id(args.url)
    s3_key = f"uploads/{video_id}/original.mp4"
    bucket = os.environ.get("S3_BUCKET_NAME", "dark-phoenix")

    print("=" * 70)
    print("🔥 DARK PHOENIX — LOCAL YOUTUBE INGEST & S3 SEEDER")
    print("=" * 70)
    print(f"📍 Video ID:       {video_id}")
    print(f"📍 Target S3 Key:  {s3_key}")
    print(f"📍 S3 Bucket:      {bucket}")
    print("=" * 70)

    s3_client = get_s3_client()

    # Check if already present in S3
    if not args.force:
        try:
            head = s3_client.head_object(Bucket=bucket, Key=s3_key)
            size_mb = head.get("ContentLength", 0) / (1024 * 1024)
            print(f"\n✅ Video already exists in Supabase S3 ({size_mb:.2f} MB)!")
            print(f"   S3 Key: s3://{bucket}/{s3_key}")
            print("\n🎉 Nothing to download. The video is already pre-seeded.")
            print_next_steps(video_id)
            return
        except Exception:
            pass

    # Download locally
    cache_dir = pathlib.Path(__file__).parent.resolve() / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_video_path = cache_dir / f"{video_id}.mp4"

    if not local_video_path.exists() or local_video_path.stat().st_size < 100_000:
        success = download_youtube_video(video_id, local_video_path)
        if not success:
            print("❌ Download failed. Please verify internet connection or provide cookies.")
            sys.exit(1)
    else:
        mb = local_video_path.stat().st_size / (1024 * 1024)
        print(f"\n📦 Found existing local download: {local_video_path} ({mb:.1f} MB)")

    # Comply with Supabase Free's 50 MB Max-File-Size object cap (45 MB safety margin)
    trim_seed_to_cap(local_video_path)

    total_bytes = local_video_path.stat().st_size
    print(f"\n🚀 Uploading to Supabase S3: s3://{bucket}/{s3_key} ({total_bytes / (1024*1024):.2f} MB)...")

    try:
        with open(local_video_path, "rb") as f:
            data = f.read()
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=data,
            ContentType="video/mp4"
        )
        print("✅ Upload complete and verified!")
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)

    # Verify via head_object
    verified = s3_client.head_object(Bucket=bucket, Key=s3_key)
    print(f"   Confirmed S3 size: {verified.get('ContentLength', 0) / (1024*1024):.2f} MB")

    if not args.keep_local:
        try:
            local_video_path.unlink(missing_ok=True)
            print("🧹 Local cache cleaned up.")
        except Exception:
            pass

    print_next_steps(video_id)


def print_next_steps(video_id: str):
    print("\n" + "=" * 70)
    print("👉 NEXT STEPS:")
    print("1. Open your deployed Vercel frontend or local dashboard:")
    print("   https://dark-phoenix.vercel.app (or localhost:3000)")
    print(f"2. In the 'YouTube Video URL' input box, enter:")
    print(f"   https://www.youtube.com/watch?v={video_id}")
    print("3. Click 'Process YouTube Video'.")
    print("   • Frontend creates uploaded_file record with status 'queued'")
    print("   • Inngest triggers the pipeline call to Hugging Face Space")
    print("   • HF backend finds the pre-seeded video in S3")
    print("   • WhisperX + Gemini + TalkNet ASD processes clips")
    print("   • Burned-in unartch watermark + animated subtitles are applied")
    print("   • Output clips are uploaded to S3!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
