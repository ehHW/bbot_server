"""
URL configuration for hyself_server project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hyself/", include(("hyself.urls", "hyself"), namespace="hyself_web")),
    path("api1/chat/", include(("chat.urls", "chat"), namespace="chat_api")),
    path("api1/game/", include(("game.urls", "game"), namespace="game_api")),
    path("api1/", include("user.urls")),
    path("api1/", include(("hyself.urls", "hyself"), namespace="hyself_api")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)