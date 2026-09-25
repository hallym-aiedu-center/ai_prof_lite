"""Validate DNS results and pin requests to a checked address (including TLS SNI)."""
import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit

import httpx

PRIVATE_NETWORKS = tuple(map(ipaddress.ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7')))


def parse_base_url(value: str) -> httpx.URL:
    value = value.strip()
    if not value or any(ord(c) < 33 for c in value) or '\\' in value:
        raise ValueError('Moodle URL 형식이 올바르지 않습니다.')
    try:
        parts = urlsplit(value)
        url = httpx.URL(value)
        if (url.scheme not in {'https', 'http'} or not url.host or
                parts.username is not None or parts.password is not None or
                parts.query or parts.fragment or '%' in url.host):
            raise ValueError()
        # Reject encoded path delimiters/dot-segments and odd default-port spellings.
        if any(p in {'.', '..'} for p in parts.path.split('/')) or '%' in parts.path:
            raise ValueError()
        return url.copy_with(path=url.path.rstrip('/'))
    except (ValueError, httpx.InvalidURL) as exc:
        raise ValueError('Moodle URL은 인증정보·쿼리·fragment 없는 HTTP(S) 주소여야 합니다.') from exc


def origin(url: httpx.URL) -> str:
    host = f'[{url.host}]' if ':' in url.host else url.host
    port = url.port or (443 if url.scheme == 'https' else 80)
    return f'{url.scheme}://{host.lower().rstrip(".")}:{port}'


def origins(setting):
    return {origin(parse_base_url(v)) for v in os.getenv(setting, '').split(',') if v.strip()}


def allowed_address(value: str, allow_private: bool) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            address = address.ipv4_mapped
        elif address.sixtofour or address.teredo:
            return False
    # Never allow loopback, link-local/cloud metadata, multicast or unspecified IPs.
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return False
    if allow_private and any(address.version == n.version and address in n for n in PRIVATE_NETWORKS):
        return True
    return address.is_global


async def resolve_target(value: str):
    url = parse_base_url(value)
    key = origin(url)
    private = key in origins('MOODLE_PRIVATE_ORIGINS')
    allowed = origins('MOODLE_ALLOWED_ORIGINS')
    if allowed and key not in allowed:
        raise ValueError('허용된 Moodle 서버 주소가 아닙니다.')
    if url.scheme != 'https' and not private:
        raise ValueError('Moodle은 HTTPS 주소를 사용하세요. 내부 HTTP 서버는 관리자가 별도로 허용해야 합니다.')
    try:
        addresses = [str(ipaddress.ip_address(url.host))]
    except ValueError:
        try:
            answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                url.host, url.port or (443 if url.scheme == 'https' else 80), type=socket.SOCK_STREAM,
            ), timeout=5)
        except (OSError, TimeoutError) as exc:
            raise ValueError('Moodle 서버의 DNS 주소를 확인할 수 없습니다.') from exc
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or not all(allowed_address(ip, private) for ip in addresses):
        raise ValueError('Moodle URL이 허용되지 않은 내부·특수 네트워크 주소를 가리킵니다.')
    # HTTPX connects to this numeric IP, so it cannot resolve the host again.
    pinned = url.copy_with(host=addresses[0])
    host = url.netloc.decode('ascii')
    return pinned, {'Host': host}, {'sni_hostname': url.host}
