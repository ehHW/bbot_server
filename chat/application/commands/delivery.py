from __future__ import annotations

from django.contrib.auth import get_user_model

from chat.domain.messaging import get_total_unread_count
from chat.domain.serialization import serialize_conversation, serialize_message
from chat.infrastructure.event_bus import notify_chat_conversation_updated, notify_chat_new_message, notify_chat_unread_updated
from chat.infrastructure.repositories import list_recipient_members, refresh_member, refresh_conversation, reveal_hidden_members
from user.models import UserPreference


User = get_user_model()


def _list_stealth_inspectors(*, excluded_user_ids: set[int]) -> list:
    inspector_ids = list(
        UserPreference.objects.filter(
            chat_stealth_inspect_enabled=True,
            user__is_superuser=True,
            user__is_active=True,
            user__deleted_at__isnull=True,
        )
        .exclude(user_id__in=excluded_user_ids)
        .values_list('user_id', flat=True)
    )
    if not inspector_ids:
        return []
    return list(User.objects.filter(id__in=inspector_ids).order_by('id'))


def build_message_delivery_payloads(*, conversation, sender_user, message):
    conversation = refresh_conversation(conversation.pk)
    message_payload = serialize_message(message)
    sender_conversation = serialize_conversation(conversation, sender_user)
    recipient_members = list_recipient_members(conversation, exclude_user_id=sender_user.id)
    reveal_hidden_members(recipient_members)
    delivered_user_ids = {sender_user.id}

    recipient_payloads = []
    for recipient_member in recipient_members:
        refreshed_member = refresh_member(recipient_member.pk)
        delivered_user_ids.add(recipient_member.user_id)
        recipient_payloads.append(
            {
                "user_id": recipient_member.user_id,
                "conversation": serialize_conversation(conversation, recipient_member.user),
                "unread_count": refreshed_member.unread_count,
                "total_unread_count": get_total_unread_count(recipient_member.user),
            }
        )
    for inspector in _list_stealth_inspectors(excluded_user_ids=delivered_user_ids):
        recipient_payloads.append(
            {
                "user_id": inspector.id,
                "conversation": serialize_conversation(conversation, inspector),
                "unread_count": 0,
                "total_unread_count": get_total_unread_count(inspector),
            }
        )
    return conversation, message_payload, sender_conversation, recipient_payloads


def emit_message_delivery_events(*, conversation, sender_user, message_payload: dict, sender_conversation: dict, recipient_payloads: list[dict]) -> None:
    notify_chat_new_message(sender_user.id, {"conversation_id": conversation.id, "message": message_payload})
    notify_chat_conversation_updated(sender_user.id, sender_conversation)
    for recipient in recipient_payloads:
        notify_chat_new_message(recipient["user_id"], {"conversation_id": conversation.id, "message": message_payload})
        notify_chat_conversation_updated(recipient["user_id"], recipient["conversation"])
        notify_chat_unread_updated(recipient["user_id"], conversation.id, recipient["unread_count"], recipient["total_unread_count"])