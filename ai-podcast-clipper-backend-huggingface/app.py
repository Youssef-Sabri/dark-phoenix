# 1. ZeroGPU MUST be imported FIRST before any other library
try:
    import spaces
    has_spaces = True
except ImportError:
    has_spaces = False
    class spaces:
        @staticmethod
        def GPU(duration=180):
            def decorator(fn):
                return fn
            return decorator

if has_spaces:
    @spaces.GPU(duration=1)
    def _zerogpu_startup_probe():
        return True

import os
import sys
import time
import uuid
import json
import shutil
import pathlib
import subprocess
import urllib.request
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import gradio as gr



# Ensure local backend dir is in sys.path
BASE_DIR = pathlib.Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Ensure nvidia CUDA & cuDNN shared libraries in site-packages are on LD_LIBRARY_PATH and preloaded
import glob
import ctypes
for p in list(sys.path):
    nvidia_path = os.path.join(p, "nvidia")
    if os.path.isdir(nvidia_path):
        for sub in ("cudnn", "cublas", "cuda_runtime", "cufft", "curand", "cusolver", "cusparse"):
            lib_dir = os.path.join(nvidia_path, sub, "lib")
            if os.path.isdir(lib_dir):
                curr_ld = os.environ.get("LD_LIBRARY_PATH", "")
                if lib_dir not in curr_ld:
                    os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{curr_ld}" if curr_ld else lib_dir
                for so in sorted(glob.glob(os.path.join(lib_dir, "*.so*"))):
                    try:
                        ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    except Exception:
                        pass

import types
import torch
import torch.serialization
_orig_torch_load = torch.load
def _compat_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_torch_load(*args, **kwargs)
torch.load = _compat_torch_load
torch.serialization.load = _compat_torch_load

try:
    import omegaconf.listconfig
    import omegaconf.dictconfig
    if hasattr(torch.serialization, "add_safe_globals"):
        torch.serialization.add_safe_globals([
            omegaconf.listconfig.ListConfig,
            omegaconf.dictconfig.DictConfig
        ])
except Exception:
    pass

import torchaudio
if not hasattr(torchaudio, "set_audio_backend"):
    torchaudio.set_audio_backend = lambda *args, **kwargs: None
if not hasattr(torchaudio, "get_audio_backend"):
    torchaudio.get_audio_backend = lambda *args, **kwargs: "soundfile"
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda *args, **kwargs: ["soundfile"]

if "torchaudio.backend" not in sys.modules:
    backend_mod = types.ModuleType("torchaudio.backend")
    backend_common_mod = types.ModuleType("torchaudio.backend.common")
    backend_common_mod.AudioMetaData = getattr(torchaudio, "AudioMetaData", None)
    backend_mod.common = backend_common_mod
    torchaudio.backend = backend_mod
    sys.modules["torchaudio.backend"] = backend_mod
    sys.modules["torchaudio.backend.common"] = backend_common_mod

from main import (
    AiPodcastClipper,
    ProcessVideoRequest,
    auth_scheme
)
from download_model_assets import MODEL_ASSETS, ensure_model_asset, ensure_bgutil_pot

# ---------------------------------------------------------------------------
# Setup & Initialization
# ---------------------------------------------------------------------------

def ensure_environment():
    """Ensure fonts, whisperx, and offline model assets are downloaded and ready."""
    # 0. Ensure whisperx is installed with --no-build-isolation
    try:
        import whisperx
    except ImportError:
        print("Installing whisperx...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--no-cache-dir", "--no-build-isolation", "--no-deps",
            "-q", "--root-user-action=ignore", "git+https://github.com/m-bain/whisperx.git@v3.2.0"
        ], check=True)

    # 0b. Ensure yt-dlp is updated to latest release for YouTube cipher/bot patches
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-q", "-U", "yt-dlp"], check=False)
        print("yt-dlp verified/updated to latest.")
    except Exception as e:
        print(f"Warning: yt-dlp update skipped: {e}")
    font_dir = pathlib.Path("/usr/share/fonts/truetype/custom")
    font_path = font_dir / "Anton-Regular.ttf"
    if not font_path.exists():
        try:
            font_dir.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
                str(font_path)
            )
            subprocess.run(["fc-cache", "-f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print("Anton font cached.")
        except Exception as e:
            print(f"Warning: Anton font setup skipped: {e}")

    # 2. Ensure TalkNet & Face Detector weights exist
    for asset in MODEL_ASSETS:
        try:
            ensure_model_asset(*asset)
        except Exception as e:
            print(f"Warning: Could not pre-download model asset {asset[1]}: {e}")

    # 3. Ensure LunarTech logo watermark asset
    try:
        from assets_embedded import ensure_watermark
        ensure_watermark()
        print("LunarTech watermark asset verified.")
    except Exception as e:
        print(f"Warning: Watermark setup skipped: {e}")

    # 4. Ensure bgutil-pot binary for automated PO-Token generation
    try:
        ensure_bgutil_pot()
        print("bgutil-pot binary verified.")
    except Exception as e:
        print(f"Warning: bgutil-pot setup skipped: {e}")

import threading
threading.Thread(target=ensure_environment, daemon=True).start()

# Initialize Clipper singleton
_clipper_instance: Optional[AiPodcastClipper] = None

def get_clipper() -> AiPodcastClipper:
    global _clipper_instance
    if _clipper_instance is None:
        ensure_environment()
        _clipper_instance = AiPodcastClipper()
        _clipper_instance.load_model()
    return _clipper_instance




# ---------------------------------------------------------------------------
# Minimal, non-interactive status page
# ---------------------------------------------------------------------------
with gr.Blocks(
    title="Dark Phoenix — Backend",
    theme=gr.themes.Soft(primary_hue="purple", secondary_hue="slate", neutral_hue="slate"),
) as demo:
    gr.Markdown(
        """# 🔥 Dark Phoenix — AI Video Clipper Backend

Cloud production service · 9:16 vertical clips · burned-in `unartch` watermark · automatic S3 manifest.

**This page is read-only** — there are no interactive controls. Processing is driven programmatically
by the frontend and by API clients.

**Private Space** — this Space is private; requests must present a Hugging Face token with read
access (`Authorization: Bearer <HF_TOKEN>`).

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | `GET` | Liveness + active Gemini model |
| `/process_video` | `POST` | Full clipping pipeline (Bearer auth) |


## Example

```bash
curl -X POST <host>/process_video \\
  -H "Authorization: Bearer $HF_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"s3_key": "uploads/YRvf00NooN8/original.mp4", "max_clips": 3}'
```"""
    )

    

# ---------------------------------------------------------------------------
# Attach FastAPI Endpoints to Gradio Server (Consumed by Inngest Cloud & Vercel)
# ---------------------------------------------------------------------------
import gradio.routes
_orig_create_app = gradio.routes.App.create_app

def _custom_create_app(*args, **kwargs):
    app = _orig_create_app(*args, **kwargs)

    @app.get("/health")
    def health_check():
        return {
            "status": "online",
            "service": "Dark Phoenix Backend",
            "zerogpu_available": has_spaces,
            "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        }

    @app.post("/process_video")
    def process_video_endpoint(
        request: ProcessVideoRequest,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme)
    ):
        clipper = get_clipper()
        return clipper.process_video(request, token=credentials)

    return app

gradio.routes.App.create_app = _custom_create_app

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
