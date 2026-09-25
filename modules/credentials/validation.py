from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlparse


def _allow_private_moodle_urls() -> bool:
    return os.getenv(
        "ALLOW_PRIVATE_MOODLE_URLS",
        "0",
    ).strip().lower() in {"1", "true", "yes", "on"}


def _unsafe_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _resolve_host(hostname: str, port: int) -> set[str]:
    results = socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    return {
        item[4][0]
        for item in results
    }


async def validate_moodle_base_url(
    value: str,
) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Moodle URL은 http:// 또는 https:// 주소여야 합니다."
        )
    if not parsed.hostname:
        raise ValueError(
            "Moodle URL의 호스트명을 확인할 수 없습니다."
        )
    if parsed.username or parsed.password:
        raise ValueError(
            "Moodle URL에 사용자명/비밀번호를 포함할 수 없습니다."
        )

    if _allow_private_moodle_urls():
        return value

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(
            "localhost Moodle URL은 허용되지 않습니다."
        )

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if _unsafe_address(str(literal)):
            raise ValueError(
                "사설/로컬 네트워크 Moodle URL은 허용되지 않습니다. "
                "내부 Moodle이 필요하면 ALLOW_PRIVATE_MOODLE_URLS=1을 설정하세요."
            )
        return value

    port = parsed.port or (
        443 if parsed.scheme == "https" else 80
    )

    try:
        addresses = await asyncio.to_thread(
            _resolve_host,
            hostname,
            port,
        )
    except OSError as exc:
        raise ValueError(
            "Moodle URL의 호스트를 확인할 수 없습니다."
        ) from exc

    if not addresses:
        raise ValueError(
            "Moodle URL의 호스트를 확인할 수 없습니다."
        )

    if any(_unsafe_address(address) for address in addresses):
        raise ValueError(
            "Moodle URL이 사설/로컬 주소로 해석됩니다. "
            "내부 Moodle이 필요하면 ALLOW_PRIVATE_MOODLE_URLS=1을 설정하세요."
        )

    return value
