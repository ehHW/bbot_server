"""
WebSocket 认证中间件
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken


@database_sync_to_async
def get_user(user_id):
    """从数据库中获取用户对象"""
    User = get_user_model()
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


class JwtAuthMiddleware(BaseMiddleware):
    """JWT 认证中间件，从查询参数中提取和验证 token"""
    
    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token = params.get("token", [""])[0]

        scope["user"] = None
        if token:
            try:
                validated = UntypedToken(token)
                user_id = validated.payload.get("user_id")
                if user_id is not None:
                    scope["user"] = await get_user(user_id)
            except (InvalidToken, TokenError):
                scope["user"] = None

        return await super().__call__(scope, receive, send)
