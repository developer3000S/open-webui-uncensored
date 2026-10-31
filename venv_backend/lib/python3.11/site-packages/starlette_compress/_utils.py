from __future__ import annotations

from functools import lru_cache

TYPE_CHECKING = False
if TYPE_CHECKING:
    from starlette.types import Message

_SUPPORTED_ENCODINGS = frozenset({'br', 'gzip', 'zstd'})


def _accepts_encoding_quality(params: list[str]) -> bool:
    for param in params:
        key, _, value = param.strip().partition('=')
        if key.strip().lower() != 'q':
            continue
        try:
            return float(value) > 0
        except ValueError:
            return False
    return True


@lru_cache(maxsize=128)
def parse_accept_encoding(accept_encoding: str) -> frozenset[str]:
    """Parse the accept encoding header and return a set of supported encodings.

    >>> _parse_accept_encoding('br;q=1.0, gzip;q=0.8, *;q=0.1')
    {'br', 'gzip', 'zstd'}
    """
    accepted: set[str] = set()
    rejected: set[str] = set()
    wildcard = False

    for item in accept_encoding.split(','):
        coding, *params = item.split(';')
        coding = coding.strip().lower()
        if not coding:
            continue

        if _accepts_encoding_quality(params):
            if coding == '*':
                wildcard = True
            elif coding in _SUPPORTED_ENCODINGS:
                accepted.add(coding)
        else:
            rejected.add(coding)
            accepted.discard(coding)

    if wildcard:
        accepted.update(_SUPPORTED_ENCODINGS - rejected)

    return frozenset(accepted)


# Based on
# - https://github.com/h5bp/server-configs-nginx/blob/main/h5bp/web_performance/compression.conf#L38
# - https://developers.cloudflare.com/speed/optimization/content/compression/
_compress_content_types: set[str] = {
    'application/atom+xml',
    'application/connect+json',
    'application/connect+proto',
    'application/eot',
    'application/font-sfnt',
    'application/font-woff',
    'application/font',
    'application/geo+json',
    'application/gpx+xml',
    'application/graphql+json',
    'application/javascript-binast',
    'application/javascript',
    'application/json',
    'application/ld+json',
    'application/manifest+json',
    'application/opentype',
    'application/otf',
    'application/proto',
    'application/protobuf',
    'application/rdf+xml',
    'application/rss+xml',
    'application/truetype',
    'application/ttf',
    'application/vnd.api+json',
    'application/vnd.google.protobuf',
    'application/vnd.mapbox-vector-tile',
    'application/vnd.ms-fontobject',
    'application/wasm',
    'application/x-google-protobuf',
    'application/x-httpd-cgi',
    'application/x-javascript',
    'application/x-opentype',
    'application/x-otf',
    'application/x-perl',
    'application/x-protobuf',
    'application/x-ttf',
    'application/x-web-app-manifest+json',
    'application/xhtml+xml',
    'application/xml',
    'font/eot',
    'font/otf',
    'font/ttf',
    'font/x-woff',
    'image/bmp',
    'image/svg+xml',
    'image/vnd.microsoft.icon',
    'image/x-icon',
    'multipart/bag',
    'multipart/mixed',
    'text/cache-manifest',
    'text/calendar',
    'text/css',
    'text/html',
    'text/javascript',
    'text/js',
    'text/markdown',
    'text/plain',
    'text/richtext',
    'text/vcard',
    'text/vnd.rim.location.xloc',
    'text/vtt',
    'text/x-component',
    'text/x-cross-domain-policy',
    'text/x-java-source',
    'text/x-markdown',
    'text/x-script',
    'text/xml',
}


def add_compress_type(content_type: str) -> None:
    """Add a new content-type to be compressed."""
    _compress_content_types.add(content_type)


def remove_compress_type(content_type: str) -> None:
    """Remove a content-type from being compressed."""
    _compress_content_types.discard(content_type)


def is_start_message_satisfied(message: Message) -> bool:
    """Check if response should be compressed based on the start message."""
    content_type: bytes | None = None

    for name, value in message['headers']:
        name = name.lower()
        if name == b'content-encoding':
            for encoding in value.split(b','):
                encoding = encoding.strip()
                if encoding and encoding.lower() != b'identity':
                    return False
        elif name == b'content-type':
            content_type = value

    if content_type is None:
        return False

    basic_content_type = content_type.split(b';', maxsplit=1)[0].strip()
    try:
        return basic_content_type.decode('ascii') in _compress_content_types
    except UnicodeDecodeError:
        return False
