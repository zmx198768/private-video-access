import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Video

logger = logging.getLogger(__name__)


def _safe_source_files():
    root = settings.VIDEO_SOURCE_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in settings.VIDEO_EXTENSIONS:
            yield path.resolve()


@shared_task
def scan_video_directory():
    now = timezone.now()
    seen = set()
    queued = []
    for path in _safe_source_files():
        stat = path.stat()
        source_path = str(path)
        source_key = hashlib.sha256(source_path.encode()).hexdigest()
        seen.add(source_path)
        with transaction.atomic():
            video, created = Video.objects.select_for_update().get_or_create(
                source_key=source_key,
                defaults={
                    "title": path.stem,
                    "source_path": source_path,
                    "source_size": stat.st_size,
                    "source_mtime_ns": stat.st_mtime_ns,
                    "stable_scan_count": 1,
                    "last_seen_at": now,
                },
            )
            if created:
                continue
            unchanged = video.source_size == stat.st_size and video.source_mtime_ns == stat.st_mtime_ns
            video.last_seen_at = now
            if not unchanged:
                video.source_size = stat.st_size
                video.source_mtime_ns = stat.st_mtime_ns
                video.stable_scan_count = 1
                video.processing_status = Video.ProcessingStatus.DISCOVERED
                video.processing_error = ""
                video.hls_relative_path = ""
            elif video.processing_status in {
                Video.ProcessingStatus.DISCOVERED,
                Video.ProcessingStatus.MISSING,
                Video.ProcessingStatus.FAILED,
            }:
                video.stable_scan_count += 1
                if video.stable_scan_count >= settings.VIDEO_STABLE_SCANS:
                    video.processing_status = Video.ProcessingStatus.QUEUED
                    queued.append(str(video.id))
            video.save()

    Video.objects.exclude(source_path__in=seen).exclude(
        processing_status=Video.ProcessingStatus.MISSING
    ).update(processing_status=Video.ProcessingStatus.MISSING, last_seen_at=now)

    for video_id in queued:
        transcode_video.delay(video_id)
    return {"seen": len(seen), "queued": len(queued)}


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def transcode_video(self, video_id):
    try:
        video = Video.objects.get(pk=video_id)
        source = Path(video.source_path).resolve()
        source_root = settings.VIDEO_SOURCE_DIR.resolve()
        if source_root not in source.parents or not source.is_file():
            video.processing_status = Video.ProcessingStatus.MISSING
            video.processing_error = "源文件不存在"
            video.save(update_fields=["processing_status", "processing_error", "updated_at"])
            return

        video.processing_status = Video.ProcessingStatus.PROCESSING
        video.processing_error = ""
        video.save(update_fields=["processing_status", "processing_error", "updated_at"])

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(source),
            ],
            capture_output=True, text=True, check=True, timeout=120,
        )
        metadata = json.loads(probe.stdout)
        video_stream = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video_stream:
            raise ValueError("文件中没有视频轨道")

        output_dir = (settings.VIDEO_HLS_DIR / str(video.id)).resolve()
        hls_root = settings.VIDEO_HLS_DIR.resolve()
        if hls_root not in output_dir.parents:
            raise ValueError("无效的输出目录")
        temp_dir = output_dir.with_name(f"{output_dir.name}.working")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-force_key_frames", "expr:gte(t,n_forced*6)",
            "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(temp_dir / "seg_%05d.m4s"),
            str(temp_dir / "index.m3u8"),
        ]
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=6 * 60 * 60)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        temp_dir.rename(output_dir)

        video.duration_seconds = metadata.get("format", {}).get("duration") or None
        video.width = video_stream.get("width")
        video.height = video_stream.get("height")
        video.codec = video_stream.get("codec_name", "")
        video.hls_relative_path = f"{video.id}/index.m3u8"
        video.processing_status = Video.ProcessingStatus.READY
        video.processed_at = timezone.now()
        video.processing_error = ""
        video.save()
    except Exception as exc:
        logger.exception("Video transcoding failed for %s", video_id)
        Video.objects.filter(pk=video_id).update(
            processing_status=Video.ProcessingStatus.FAILED,
            processing_error=str(exc)[-4000:],
        )
        raise self.retry(exc=exc)
