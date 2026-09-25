import base64
from pathlib import Path

import httpx

from core.openai.client import get_client


async def generate_image(
    *,
    api_key: str,
    prompt: str,
    output_path: str | Path,
    model: str,
    size: str = "1536x1024",
    quality: str = "medium",
) -> Path:
    """
    Generate one lecture visual and save it as PNG/JPEG returned by the API.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = get_client(api_key=api_key)

    async with client:
        result = await client.images.generate(
            model=model, prompt=prompt, size=size, quality=quality,
        )

    item = result.data[0]

    if getattr(item, "b64_json", None):
        _atomic_write(output_path, base64.b64decode(item.b64_json))
        return output_path

    url = getattr(item, "url", None)

    if not url:
        raise RuntimeError(
            "Image API returned neither b64_json nor url."
        )

    async with httpx.AsyncClient(timeout=120.0) as http:
        response = await http.get(url)
        response.raise_for_status()
        _atomic_write(output_path, response.content)

    return output_path


def _atomic_write(path: Path, content: bytes):
    if not content:
        raise ValueError("Image API returned an empty image.")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
