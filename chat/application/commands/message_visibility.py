from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from chat.domain.access import get_conversation_access
from chat.domain.serialization import serialize_conversation
from chat.models import ChatMessage, ChatMessageVisibility


def execute_delete_message_for_user_command(current_user, message_id: int) -> dict:
    message = ChatMessage.objects.select_related("conversation").filter(id=message_id).first()
    if message is None:
        raise ChatMessage.DoesNotExist()

    access = get_conversation_access(current_user, message.conversation)
    if access.member is None:
        raise PermissionDenied("巡检视角不支持删除消息")

    ChatMessageVisibility.objects.get_or_create(message=message, user=current_user)
    return {
        "detail": "消息已删除",
        "message_id": message.id,
        "conversation": serialize_conversation(message.conversation, current_user),
    }


def execute_batch_delete_messages_for_user_command(current_user, message_ids: list[int]) -> dict:
    if not message_ids:
        return {"detail": "未指定消息", "deleted_ids": [], "conversation": None}

    messages = list(
        ChatMessage.objects.select_related("conversation")
        .filter(id__in=message_ids)
    )
    if not messages:
        return {"detail": "消息不存在", "deleted_ids": [], "conversation": None}

    # 校验所有消息属于同一个会话，且用户有权限
    conversation = messages[0].conversation
    for msg in messages:
        if msg.conversation_id != conversation.id:
            raise PermissionDenied("批量删除的消息必须属于同一个会话")

    access = get_conversation_access(current_user, conversation)
    if access.member is None:
        raise PermissionDenied("巡检视角不支持删除消息")

    deleted_ids = []
    for msg in messages:
        ChatMessageVisibility.objects.get_or_create(message=msg, user=current_user)
        deleted_ids.append(msg.id)

    return {
        "detail": f"已删除 {len(deleted_ids)} 条消息",
        "deleted_ids": deleted_ids,
        "conversation": serialize_conversation(conversation, current_user),
    }