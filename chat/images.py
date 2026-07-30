import os
import uuid
import warnings
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


class ChatImageError(ValueError):
    pass


def resolve_chat_image_path(relative_path):
    root = settings.CHAT_IMAGE_DIR.resolve()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents:
        raise ChatImageError("图片路径无效")
    return candidate


def delete_chat_image(relative_path):
    if not relative_path:
        return
    try:
        path = resolve_chat_image_path(relative_path)
    except ChatImageError:
        return
    path.unlink(missing_ok=True)
    root = settings.CHAT_IMAGE_DIR.resolve()
    parent = path.parent
    if parent != root:
        try:
            parent.rmdir()
        except OSError:
            pass


def store_chat_image(uploaded, room_id):
    if not uploaded:
        raise ChatImageError("请选择需要上传的图片")
    if uploaded.size <= 0:
        raise ChatImageError("图片文件不能为空")
    if uploaded.size > settings.CHAT_IMAGE_MAX_BYTES:
        limit_mb = settings.CHAT_IMAGE_MAX_BYTES / (1024 * 1024)
        raise ChatImageError(f"图片不能超过 {limit_mb:g} MB")

    root = settings.CHAT_IMAGE_DIR.resolve()
    room_directory = (root / str(room_id)).resolve()
    if root not in room_directory.parents:
        raise ChatImageError("图片保存目录无效")
    room_directory.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    temporary_path = room_directory / f".{file_id}.uploading"
    final_path = room_directory / f"{file_id}.webp"

    def cleanup_failed_upload():
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        try:
            room_directory.rmdir()
        except OSError:
            pass

    try:
        uploaded.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(uploaded) as source:
                width, height = source.size
                if width <= 0 or height <= 0:
                    raise ChatImageError("图片尺寸无效")
                if width * height > settings.CHAT_IMAGE_MAX_PIXELS:
                    raise ChatImageError("图片像素尺寸过大")
                source.seek(0)
                source.load()
                normalized = ImageOps.exif_transpose(source)
                has_alpha = normalized.mode in {"RGBA", "LA"} or (
                    normalized.mode == "P" and "transparency" in normalized.info
                )
                normalized = normalized.convert("RGBA" if has_alpha else "RGB")
                normalized.thumbnail(
                    (
                        settings.CHAT_IMAGE_MAX_DIMENSION,
                        settings.CHAT_IMAGE_MAX_DIMENSION,
                    ),
                    Image.Resampling.LANCZOS,
                )
                output_width, output_height = normalized.size
                with temporary_path.open("xb") as destination:
                    normalized.save(
                        destination,
                        format="WEBP",
                        quality=85,
                        method=6,
                        exif=b"",
                        icc_profile=None,
                    )
                    destination.flush()
                    os.fsync(destination.fileno())
        os.replace(temporary_path, final_path)
        stat = final_path.stat()
        return {
            "relative_path": final_path.relative_to(root).as_posix(),
            "content_type": "image/webp",
            "size": stat.st_size,
            "width": output_width,
            "height": output_height,
        }
    except ChatImageError:
        cleanup_failed_upload()
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        cleanup_failed_upload()
        raise ChatImageError("请上传有效图片（JPG、PNG、GIF或WebP）") from exc
