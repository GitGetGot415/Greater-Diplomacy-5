"""Download and verify the browser runtime at build time for offline Android play."""

import hashlib
from pathlib import Path
import re
import shutil
import urllib.request

from compilation_scripts import build_manifest as manifest


def validate_web_runtime(index):
    """Refuse a different interpreter instead of producing an incomplete offline APK."""
    loader = re.search(r'<script\b[^>]*\bsrc=["\']([^"\']+/pythons\.js)["\'][^>]*>', index)
    python = re.search(r'\bdata-python=["\']([^"\']+)["\']', loader[0]) if loader else None
    if not loader or loader[1] != manifest.ANDROID_RUNTIME_CDN + manifest.ANDROID_RUNTIME_LOADER or not python or python[1] != manifest.ANDROID_RUNTIME_PYTHON:
        raise ValueError("Unsupported Pygbag runtime in the web build. Update the Android runtime inventory in build_manifest.py before building this interpreter.")


def _matches(path, expected):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected


def download_runtime(destination):
    """Reuse only verified files. A failed download must never become a cached runtime."""
    destination = Path(destination)
    for relative, expected in manifest.ANDROID_RUNTIME_FILES.items():
        target = destination / relative
        if _matches(target, expected):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".download")
        print(f"Downloading Android runtime: {relative}", flush=True)
        try:
            request = urllib.request.Request(manifest.ANDROID_RUNTIME_CDN + relative, headers={"User-Agent": "Greater-Diplomacy-5-Build"})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if not _matches(temporary, expected):
                raise ValueError(f"Android runtime checksum mismatch: {relative}. The CDN changed; review and update the runtime inventory in build_manifest.py.")
            temporary.replace(target)
        except OSError as error:
            raise OSError(f"Cannot bundle Android runtime {relative}: {error}. Build with internet access once to fill the runtime cache.") from error
        finally:
            temporary.unlink(missing_ok=True)
