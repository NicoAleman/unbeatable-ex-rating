"""Upload Bingo score proof images to Supabase Storage."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable

from rating.formatting import format_difficulty_display_name
from rating.supabase_config import (
    BINGO_PROOF_BUCKET,
    get_supabase_service_role_key,
    get_supabase_url,
    supabase_storage_configured,
)

# path -> (url, monotonic expiry). Avoids re-signing on every Streamlit rerun.
_PROOF_URL_CACHE: dict[str, tuple[str, float]] = {}
_PROOF_URL_CACHE_LOCK = threading.Lock()
_PROOF_URL_CACHE_SKEW_SECONDS = 120.0

MAX_PROOF_BYTES = 50 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class BingoProofUpload:
    proof_path: str
    content_type: str


def _sanitize_path_segment(value: str) -> str:
    """Reduce a label to Supabase/S3-safe path characters."""
    cleaned = str(value).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or "unknown"


def build_bingo_proof_path(
    *,
    display_name: str,
    chart_display_name: str,
    difficulty: str,
    score: int,
    extension: str,
) -> str:
    """Return `{player}/{chart}_{difficulty}/{score}.{ext}` using safe path chars."""
    chart_label = "_".join(
        part
        for part in (
            _sanitize_path_segment(chart_display_name),
            _sanitize_path_segment(format_difficulty_display_name(difficulty)),
        )
        if part
    )
    ext = extension if extension.startswith(".") else f".{extension}"
    filename = f"{int(score)}{ext.lower()}"
    return "/".join(
        (
            _sanitize_path_segment(display_name),
            chart_label or "unknown_chart",
            filename,
        )
    )


def detect_proof_image_content_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_proof_image(*, data: bytes, filename: str | None = None) -> tuple[str, str]:
    """Return (content_type, extension) or raise ValueError."""
    if not data:
        raise ValueError("Proof image is required.")
    if len(data) > MAX_PROOF_BYTES:
        raise ValueError("Proof image must be 50 MB or smaller.")

    content_type = detect_proof_image_content_type(data)
    if content_type is None:
        raise ValueError("Proof must be a PNG, JPEG, or WebP image.")

    extension = _ALLOWED_CONTENT_TYPES[content_type]
    if filename:
        lowered = filename.casefold()
        allowed_suffixes = (".png", ".jpg", ".jpeg", ".webp")
        if not any(lowered.endswith(suffix) for suffix in allowed_suffixes):
            raise ValueError("Proof filename must end with .png, .jpg, .jpeg, or .webp.")

    return content_type, extension


def upload_bingo_score_proof(
    *,
    display_name: str,
    chart_display_name: str,
    difficulty: str,
    score: int,
    data: bytes,
    filename: str | None = None,
) -> BingoProofUpload:
    """Upload a proof image and return its storage path."""
    if not supabase_storage_configured():
        raise RuntimeError(
            "Supabase Storage is not configured. Set supabase.url and "
            "supabase.service_role_key in secrets or environment variables."
        )

    content_type, extension = validate_proof_image(data=data, filename=filename)
    proof_path = build_bingo_proof_path(
        display_name=display_name,
        chart_display_name=chart_display_name,
        difficulty=difficulty,
        score=score,
        extension=extension,
    )

    base_url = get_supabase_url().rstrip("/")
    service_role_key = get_supabase_service_role_key()
    object_url = (
        f"{base_url}/storage/v1/object/{BINGO_PROOF_BUCKET}/"
        f"{urllib.parse.quote(proof_path, safe='/')}"
    )
    request = urllib.request.Request(
        object_url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status >= 400:
                raise RuntimeError(f"Storage upload failed ({response.status}).")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Could not upload proof image: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not upload proof image: {exc.reason}") from exc

    return BingoProofUpload(proof_path=proof_path, content_type=content_type)


def delete_bingo_score_proof(proof_path: str) -> None:
    """Best-effort delete when a DB write fails after upload."""
    if not proof_path or not supabase_storage_configured():
        return

    base_url = get_supabase_url().rstrip("/")
    service_role_key = get_supabase_service_role_key()
    object_url = (
        f"{base_url}/storage/v1/object/{BINGO_PROOF_BUCKET}/"
        f"{urllib.parse.quote(proof_path, safe='/')}"
    )
    request = urllib.request.Request(
        object_url,
        method="DELETE",
        headers={"Authorization": f"Bearer {service_role_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            pass
    except Exception:
        return


def _cache_get_proof_url(proof_path: str) -> str | None:
    now = time.monotonic()
    with _PROOF_URL_CACHE_LOCK:
        cached = _PROOF_URL_CACHE.get(proof_path)
        if cached is None:
            return None
        url, expires_at = cached
        if expires_at <= now:
            _PROOF_URL_CACHE.pop(proof_path, None)
            return None
        return url


def _cache_put_proof_url(proof_path: str, url: str, *, expires_in: int) -> None:
    ttl = max(1.0, float(expires_in) - _PROOF_URL_CACHE_SKEW_SECONDS)
    expires_at = time.monotonic() + ttl
    with _PROOF_URL_CACHE_LOCK:
        _PROOF_URL_CACHE[proof_path] = (url, expires_at)


def clear_bingo_proof_signed_url_cache() -> None:
    with _PROOF_URL_CACHE_LOCK:
        _PROOF_URL_CACHE.clear()


def _create_bingo_proof_signed_url_uncached(
    proof_path: str,
    *,
    expires_in: int = 3600,
) -> str | None:
    """Fetch a signed URL from Supabase Storage (no cache)."""
    if not proof_path or not supabase_storage_configured():
        return None

    base_url = get_supabase_url()
    service_role_key = get_supabase_service_role_key()
    if not base_url or not service_role_key:
        return None

    sign_url = (
        f"{base_url.rstrip('/')}/storage/v1/object/sign/{BINGO_PROOF_BUCKET}/"
        f"{urllib.parse.quote(proof_path, safe='/')}"
    )
    request = urllib.request.Request(
        sign_url,
        data=json.dumps({"expiresIn": max(1, int(expires_in))}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    signed = payload.get("signedURL") or payload.get("signedUrl")
    if not signed:
        return None
    signed = str(signed)
    if signed.startswith("http://") or signed.startswith("https://"):
        return signed
    if signed.startswith("/object/"):
        return f"{base_url.rstrip('/')}/storage/v1{signed}"
    if signed.startswith("/storage/v1/"):
        return f"{base_url.rstrip('/')}{signed}"
    return f"{base_url.rstrip('/')}{signed}"


def create_bingo_proof_signed_url(
    proof_path: str,
    *,
    expires_in: int = 3600,
) -> str | None:
    """Return a time-limited URL for viewing a private proof object."""
    if not proof_path:
        return None
    cached = _cache_get_proof_url(proof_path)
    if cached is not None:
        return cached
    signed = _create_bingo_proof_signed_url_uncached(
        proof_path, expires_in=expires_in
    )
    if signed:
        _cache_put_proof_url(proof_path, signed, expires_in=expires_in)
    return signed


def prefetch_bingo_proof_signed_urls(
    proof_paths: Iterable[str],
    *,
    expires_in: int = 3600,
    max_workers: int = 16,
) -> dict[str, str]:
    """Sign many proof paths concurrently; reuse the process cache when possible."""
    unique: list[str] = []
    seen: set[str] = set()
    for raw in proof_paths:
        path = str(raw or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    if not unique:
        return {}

    result: dict[str, str] = {}
    missing: list[str] = []
    for path in unique:
        cached = _cache_get_proof_url(path)
        if cached is not None:
            result[path] = cached
        else:
            missing.append(path)

    if not missing:
        return result

    workers = max(1, min(int(max_workers), len(missing)))

    def _sign_one(path: str) -> tuple[str, str | None]:
        return path, _create_bingo_proof_signed_url_uncached(
            path, expires_in=expires_in
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for path, signed in pool.map(_sign_one, missing):
            if not signed:
                continue
            _cache_put_proof_url(path, signed, expires_in=expires_in)
            result[path] = signed
    return result
