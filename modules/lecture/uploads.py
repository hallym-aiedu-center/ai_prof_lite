import asyncio
import io
import warnings
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from core.config import data_dir, positive_int

FORMATS = {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/webp': 'WEBP'}


def normalize_portrait(content: bytes, content_type: str):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format != FORMATS.get(content_type):
                    raise ValueError('파일의 실제 이미지 형식과 MIME 형식이 일치하지 않습니다.')
                if source.width * source.height > positive_int('MAX_PORTRAIT_PIXELS', 16_000_000):
                    raise ValueError('이미지 픽셀 수가 허용 범위를 초과했습니다.')
                if getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('움직이는 이미지 대신 정지 이미지를 사용하세요.')
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                source.load()
                image = ImageOps.exif_transpose(source)
                has_alpha = image.mode in {'RGBA', 'LA'} or 'transparency' in image.info
                image = image.convert('RGBA' if has_alpha else 'RGB')
                image.thumbnail((2048, 2048))
                output = io.BytesIO()
                image.save(output, format='PNG')  # Discard metadata and trailing payload.
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f'유효한 교수 사진이 아닙니다: {exc}') from exc


async def normalize_uploaded_portrait(upload: UploadFile) -> bytes:
    content_type = upload.content_type or ''
    if content_type not in FORMATS:
        raise HTTPException(status_code=422, detail='PNG, JPEG, WebP 사진만 업로드할 수 있습니다.')

    maximum = positive_int('MAX_PORTRAIT_BYTES', 10 * 1024 * 1024)
    content = bytearray()
    try:
        while chunk := await upload.read(64 * 1024):
            content.extend(chunk)
            if len(content) > maximum:
                raise HTTPException(status_code=413, detail='사진 파일이 허용 크기를 초과했습니다.')
    finally:
        await upload.close()

    if not content:
        raise HTTPException(status_code=422, detail='사진 파일이 비어 있습니다.')

    return await asyncio.to_thread(
        normalize_portrait,
        bytes(content),
        content_type,
    )


async def save_portrait(upload: UploadFile):
    normalized = await normalize_uploaded_portrait(upload)
    directory = data_dir() / 'uploads'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{uuid4().hex}.png'
    temporary = path.with_suffix('.tmp')
    try:
        await asyncio.to_thread(temporary.write_bytes, normalized)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
