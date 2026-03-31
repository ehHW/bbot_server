import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bbot_server.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from ws.auth import JwtAuthMiddleware
from ws.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
