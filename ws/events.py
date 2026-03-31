"""
WebSocket 事件广播模块
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def notify_user_force_logout(user_id: int, operator_username: str) -> None:
    """
    向用户发送强制下线通知
    
    Args:
        user_id: 目标用户ID
        operator_username: 操作员用户名
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    async_to_sync(channel_layer.group_send)(
        f"ws_user_{user_id}",
        {
            "type": "system.event",
            "payload": {
                "type": "force_logout",
                "message": f"您已被管理员 {operator_username} 踢下线",
            },
        },
    )
