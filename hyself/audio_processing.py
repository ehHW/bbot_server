from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from django.db import transaction

from hyself.models import Asset
from hyself.utils.upload import build_stored_name, get_upload_root, media_url, normalize_relative_path, relative_to_uploads


AUDIO_PROCESSING_KEY = "audio_processing"
AUDIO_ARTIFACTS_ROOT = "audio_artifacts"


def _resolve_command_path(command_name: str) -> str:
    resolved = shutil.which(command_name)
    if resolved:
        return resolved
    raise FileNotFoundError(f"未找到 {command_name}，请先安装并加入 PATH")


def _run_json_command(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout or "{}")


def _get_asset_file_path(asset: Asset) -> Path:
    return get_upload_root() / Path(normalize_relative_path(asset.storage_key))


def _get_audio_artifact_folder_name(asset: Asset) -> str:
    return f"audio_{asset.id}"


def _get_audio_output_root(asset: Asset) -> Path:
    target = get_upload_root() / Path(AUDIO_ARTIFACTS_ROOT) / _get_audio_artifact_folder_name(asset)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_audio_asset(asset: Asset) -> dict:
    ffprobe_path = _resolve_command_path("ffprobe")
    source_path = _get_asset_file_path(asset)
    if not source_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {source_path}")

    probe_result = _run_json_command([
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(source_path),
    ])

    streams = probe_result.get("streams") or []
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    format_info = probe_result.get("format") or {}
    duration_seconds = _to_float((audio_stream or {}).get("duration") or format_info.get("duration"))
    codec_name = str((audio_stream or {}).get("codec_name") or "").strip()

    return {
        "codec": codec_name,
        "duration_seconds": duration_seconds,
        "probe_raw": {
            "format_name": format_info.get("format_name"),
            "bit_rate": format_info.get("bit_rate"),
            "audio_codec": codec_name,
        },
    }


@transaction.atomic
def update_audio_probe_metadata(asset: Asset, probe_payload: dict) -> Asset:
    metadata = dict(asset.extra_metadata or {})
    audio_processing = dict(metadata.get(AUDIO_PROCESSING_KEY) or {})
    audio_processing.update({
        "codec": probe_payload.get("codec") or "",
        "status": audio_processing.get("status") or "queued",
        "duration_seconds": probe_payload.get("duration_seconds"),
        "probe_raw": probe_payload.get("probe_raw") or {},
    })
    metadata[AUDIO_PROCESSING_KEY] = audio_processing

    asset.duration_seconds = probe_payload.get("duration_seconds") or asset.duration_seconds
    asset.extra_metadata = metadata
    asset.save(update_fields=["duration_seconds", "extra_metadata", "updated_at"])
    return asset


@transaction.atomic
def mark_audio_processing_status(asset: Asset, *, status: str, error: str = "", extra: dict | None = None) -> Asset:
    metadata = dict(asset.extra_metadata or {})
    audio_processing = dict(metadata.get(AUDIO_PROCESSING_KEY) or {})
    audio_processing["status"] = status
    if error:
        audio_processing["error"] = error
    elif "error" in audio_processing:
        audio_processing.pop("error", None)
    if extra:
        audio_processing.update(extra)
    metadata[AUDIO_PROCESSING_KEY] = audio_processing
    asset.extra_metadata = metadata
    asset.save(update_fields=["extra_metadata", "updated_at"])
    return asset


def queue_audio_processing(asset: Asset) -> None:
    from hyself.tasks import process_audio_asset_task

    metadata = dict(asset.extra_metadata or {})
    audio_processing = dict(metadata.get(AUDIO_PROCESSING_KEY) or {})
    if audio_processing.get("status") in {"processing", "ready"}:
        return
    mark_audio_processing_status(asset, status="queued")
    process_audio_asset_task.delay(asset.id)


def ensure_audio_asset_pipeline(asset: Asset | None) -> Asset | None:
    if asset is None or asset.media_type != Asset.MediaType.AUDIO or asset.storage_backend != Asset.StorageBackend.LOCAL:
        return asset
    try:
        probe_payload = probe_audio_asset(asset)
        asset = update_audio_probe_metadata(asset, probe_payload)
        queue_audio_processing(asset)
    except Exception as exc:
        mark_audio_processing_status(asset, status="failed", error=str(exc))
    return asset


@transaction.atomic
def attach_audio_lyrics_file(asset: Asset, lyrics_file, *, original_name: str = "") -> Asset:
    output_root = _get_audio_output_root(asset)
    lyrics_name = build_stored_name(original_name or getattr(lyrics_file, "name", "lyrics.lrc"))
    if not lyrics_name.lower().endswith(".lrc"):
        lyrics_name = f"{Path(lyrics_name).stem}.lrc"
    lyrics_path = output_root / lyrics_name
    with lyrics_path.open("wb") as target:
        for chunk in lyrics_file.chunks():
            target.write(chunk)

    lyrics_relative_path = relative_to_uploads(lyrics_path)
    return mark_audio_processing_status(
        asset,
        status=dict((asset.extra_metadata or {}).get(AUDIO_PROCESSING_KEY) or {}).get("status") or "queued",
        extra={
            "lyrics_relative_path": lyrics_relative_path,
            "lyrics_url": media_url(lyrics_relative_path),
            "lyrics_name": Path(original_name or getattr(lyrics_file, "name", "lyrics.lrc")).name,
        },
    )


def transcode_audio_to_m4a(asset: Asset) -> dict:
    ffmpeg_path = _resolve_command_path("ffmpeg")
    source_path = _get_asset_file_path(asset)
    if not source_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {source_path}")

    output_root = _get_audio_output_root(asset)
    m4a_path = output_root / "stream.m4a"
    cover_path = output_root / "cover.jpg"

    subprocess.run([
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(m4a_path),
    ], capture_output=True, text=True, check=True)

    cover_extracted = False
    try:
        subprocess.run([
            ffmpeg_path,
            "-y",
            "-i",
            str(source_path),
            "-an",
            "-vcodec",
            "mjpeg",
            str(cover_path),
        ], capture_output=True, text=True, check=True)
        cover_extracted = cover_path.exists() and cover_path.stat().st_size > 0
    except Exception:
        cover_path.unlink(missing_ok=True)

    m4a_relative_path = relative_to_uploads(m4a_path)
    payload = {
        "stream_relative_path": m4a_relative_path,
        "stream_url": f"{media_url(m4a_relative_path)}?v={m4a_path.stat().st_mtime_ns}",
        "transcoded_format": "m4a",
    }
    if cover_extracted:
        cover_relative_path = relative_to_uploads(cover_path)
        payload.update({
            "cover_relative_path": cover_relative_path,
            "cover_url": f"{media_url(cover_relative_path)}?v={cover_path.stat().st_mtime_ns}",
        })
    return payload