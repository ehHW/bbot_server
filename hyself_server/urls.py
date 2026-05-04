"""
URL configuration for hyself_server project.
"""
import mimetypes
from pathlib import Path

import aiofiles
from django.conf import settings
from django.contrib import admin
from django.http import Http404, StreamingHttpResponse
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hyself/", include(("hyself.urls", "hyself"), namespace="hyself_web")),
    path("api1/chat/", include(("chat.urls", "chat"), namespace="chat_api")),
    path("api1/game/", include(("game.urls", "game"), namespace="game_api")),
    path("api1/", include("user.urls")),
    path("api1/", include(("hyself.urls", "hyself"), namespace="hyself_api")),
]

if settings.DEBUG:
    media_root = Path(settings.MEDIA_ROOT)
    media_prefix = settings.MEDIA_URL.lstrip("/")  # e.g. "api1/uploads/"

    async def serve_media(request, path):
        file_path = media_root / path
        try:
            file_path.resolve().relative_to(media_root.resolve())
        except ValueError:
            raise Http404
        if not file_path.exists() or not file_path.is_file():
            raise Http404
        content_type, encoding = mimetypes.guess_type(str(file_path))

        async def file_iterator(chunk_size=65536):
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        response = StreamingHttpResponse(
            file_iterator(),
            content_type=content_type or "application/octet-stream",
        )
        response["Content-Length"] = file_path.stat().st_size
        if encoding:
            response["Content-Encoding"] = encoding
        return response

    urlpatterns += [
        re_path(rf"^{media_prefix}(?P<path>.+)$", serve_media),
    ]
