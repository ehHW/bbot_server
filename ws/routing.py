"""
WebSocket URL 路由配置
"""
from django.urls import path

from ws.consumers import GlobalWebSocketConsumer

websocket_urlpatterns = [
    path("api1/ws/global/", GlobalWebSocketConsumer.as_asgi()),
]
