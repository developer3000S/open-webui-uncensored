from __future__ import annotations

import sys

from starlette.datastructures import MutableHeaders

from starlette_compress._identity import IdentityResponder
from starlette_compress._utils import (
    add_compress_type,
    parse_accept_encoding,
    remove_compress_type,
)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

__version__ = '1.7.1'


class CompressMiddleware:
    __slots__ = (
        '_brotli',
        '_gzip',
        '_identity',
        '_remove_accept_encoding',
        '_zstd',
        'app',
    )

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 500,
        zstd: bool = True,
        zstd_level: int = 4,
        brotli: bool = True,
        brotli_quality: int = 4,
        gzip: bool = True,
        gzip_level: int = 4,
        remove_accept_encoding: bool = False,
    ) -> None:
        """Compression middleware supporting multiple algorithms.

        The middleware automatically selects the best available compression method
        based on the client's Accept-Encoding header. Compression methods are tried
        in order: Zstandard, Brotli, Gzip, and finally no compression (identity).

        :param app: ASGI application to wrap.
        :param minimum_size: Minimum response size in bytes to apply compression.
        :param zstd: Enable Zstandard compression.
        :param zstd_level: Zstandard compression level. Valid values are all negative integers (faster) to 22 (best).
        :param brotli: Enable Brotli compression.
        :param brotli_quality: Brotli quality level, 0 (fastest) to 11 (best).
        :param gzip: Enable Gzip compression.
        :param gzip_level: Gzip compression level, 0 (fastest) to 9 (best).
        :param remove_accept_encoding: Remove request Accept-Encoding after reading it.
        """
        self.app = app
        self._identity = IdentityResponder(app, minimum_size)
        self._remove_accept_encoding = remove_accept_encoding

        if zstd:
            if sys.version_info < (3, 14):
                from starlette_compress._zstd_legacy import ZstdResponder
            else:
                from starlette_compress._zstd import ZstdResponder

            self._zstd = ZstdResponder(app, minimum_size, zstd_level)
        else:
            self._zstd = None

        if brotli:
            from starlette_compress._brotli import BrotliResponder

            self._brotli = BrotliResponder(app, minimum_size, brotli_quality)
        else:
            self._brotli = None

        if gzip:
            from starlette_compress._gzip import GZipResponder

            self._gzip = GZipResponder(app, minimum_size, gzip_level)
        else:
            self._gzip = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        headers = MutableHeaders(scope=scope)
        accept_encoding = headers.getlist('Accept-Encoding')
        if accept_encoding:
            if self._remove_accept_encoding:
                del headers['Accept-Encoding']

            accept_encodings = parse_accept_encoding(
                ','.join(accept_encoding)
                if len(accept_encoding) > 1
                else accept_encoding[0]
            )
            if (self._zstd is not None) and 'zstd' in accept_encodings:
                return await self._zstd(scope, receive, send)
            if (self._brotli is not None) and 'br' in accept_encodings:
                return await self._brotli(scope, receive, send)
            if (self._gzip is not None) and 'gzip' in accept_encodings:
                return await self._gzip(scope, receive, send)

        return await self._identity(scope, receive, send)


__all__ = (
    'CompressMiddleware',
    'add_compress_type',
    'remove_compress_type',
)
