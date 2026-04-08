from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Max, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from chat.models import (
    ChatConversation,
    ChatConversationMember,
    ChatFriendRequest,
    ChatFriendship,
    ChatGroupConfig,
    ChatGroupJoinRequest,
    ChatMessage,
    build_pair_key,
)
from user.models import UserPreference


User = get_user_model()


@dataclass
class ConversationAccess:
    conversation: ChatConversation
    member: ChatConversationMember | None
    access_mode: str
    can_send_message: bool


def get_or_create_user_preference(user) -> UserPreference:
    preference, _ = UserPreference.objects.get_or_create(user=user)
    return preference


def user_can_stealth_inspect(user) -> bool:
    if not user.is_authenticated or not user.is_superuser:
        return False
    preference = get_or_create_user_preference(user)
    return bool(preference.chat_stealth_inspect_enabled)


def user_can_review_all_messages(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_permission_code("chat.review_all_messages")))


def user_brief(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar": user.avatar,
    }


def to_serializable_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def friendship_counterparty(friendship: ChatFriendship, current_user_id: int):
    return friendship.user_high if friendship.user_low_id == current_user_id else friendship.user_low


def friendship_remark(friendship: ChatFriendship | None, current_user_id: int) -> str:
    if friendship is None:
        return ""
    return friendship.remark_low if friendship.user_low_id == current_user_id else friendship.remark_high


def update_friendship_remark(friendship: ChatFriendship, current_user_id: int, remark: str) -> ChatFriendship:
    if friendship.user_low_id == current_user_id:
        friendship.remark_low = remark
        friendship.save(update_fields=["remark_low", "updated_at"])
        return friendship
    friendship.remark_high = remark
    friendship.save(update_fields=["remark_high", "updated_at"])
    return friendship


def get_member_preferences(member: ChatConversationMember | None) -> dict:
    settings = member.extra_settings if member else {}
    return {
        "mute_notifications": bool((settings or {}).get("mute_notifications", False)),
        "group_nickname": str((settings or {}).get("group_nickname", "") or ""),
    }


def update_member_preferences(member: ChatConversationMember, *, mute_notifications: bool | None = None, group_nickname: str | None = None) -> ChatConversationMember:
    settings = dict(member.extra_settings or {})
    if mute_notifications is not None:
        settings["mute_notifications"] = bool(mute_notifications)
    if group_nickname is not None:
        settings["group_nickname"] = str(group_nickname)
    member.extra_settings = settings
    member.save(update_fields=["extra_settings", "updated_at"])
    return member


def get_active_friendship_between(user_a_id: int, user_b_id: int) -> ChatFriendship | None:
    pair_key = build_pair_key(user_a_id, user_b_id)
    return ChatFriendship.objects.filter(pair_key=pair_key, status=ChatFriendship.Status.ACTIVE).first()


def get_member(conversation: ChatConversation, user_id: int, active_only: bool = False) -> ChatConversationMember | None:
    queryset = ChatConversationMember.objects.filter(conversation=conversation, user_id=user_id)
    if active_only:
        queryset = queryset.filter(status=ChatConversationMember.Status.ACTIVE)
    return queryset.first()


def ensure_direct_conversation(user_a, user_b) -> ChatConversation:
    pair_key = build_pair_key(user_a.id, user_b.id)
    with transaction.atomic():
        conversation = ChatConversation.all_objects.select_for_update().filter(direct_pair_key=pair_key).first()
        if conversation is None:
            conversation = ChatConversation.objects.create(
                type=ChatConversation.Type.DIRECT,
                direct_pair_key=pair_key,
                status=ChatConversation.Status.ACTIVE,
                name="",
            )
        else:
            if conversation.deleted_at is not None:
                conversation.restore()
            if conversation.status != ChatConversation.Status.ACTIVE:
                conversation.status = ChatConversation.Status.ACTIVE
                conversation.save(update_fields=["status", "updated_at"])

        for current_user in [user_a, user_b]:
            membership = ChatConversationMember.objects.filter(conversation=conversation, user=current_user).first()
            if membership is None:
                ChatConversationMember.objects.create(
                    conversation=conversation,
                    user=current_user,
                    role=ChatConversationMember.Role.MEMBER,
                    status=ChatConversationMember.Status.ACTIVE,
                    joined_at=timezone.now(),
                    show_in_list=True,
                )
            else:
                membership.status = ChatConversationMember.Status.ACTIVE
                membership.left_at = None
                membership.removed_at = None
                membership.removed_by = None
                membership.show_in_list = True
                membership.save(update_fields=["status", "left_at", "removed_at", "removed_by", "show_in_list", "updated_at"])

        recalculate_member_count(conversation)
    return conversation


def recalculate_member_count(conversation: ChatConversation) -> int:
    count = ChatConversationMember.objects.filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE).count()
    if conversation.member_count_cache != count:
        conversation.member_count_cache = count
        conversation.save(update_fields=["member_count_cache", "updated_at"])
    return count


def get_conversation_access(user, conversation: ChatConversation) -> ConversationAccess:
    member = get_member(conversation, user.id, active_only=True)
    if member:
        mute_active = bool(member.mute_until and member.mute_until > timezone.now())
        can_send = conversation.status == ChatConversation.Status.ACTIVE and not mute_active
        if conversation.type == ChatConversation.Type.GROUP and hasattr(conversation, "group_config") and conversation.group_config.mute_all and member.role not in {ChatConversationMember.Role.OWNER, ChatConversationMember.Role.ADMIN}:
            can_send = False
        return ConversationAccess(conversation=conversation, member=member, access_mode="member", can_send_message=can_send)

    if user_can_stealth_inspect(user):
        return ConversationAccess(conversation=conversation, member=None, access_mode="stealth_readonly", can_send_message=False)

    raise PermissionDenied("当前无权访问该会话")


def serialize_message(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "sequence": message.sequence,
        "client_message_id": message.client_message_id,
        "message_type": message.message_type,
        "content": message.content,
        "payload": message.payload or {},
        "is_system": message.is_system,
        "sender": None if message.sender is None else user_brief(message.sender),
        "created_at": to_serializable_datetime(message.created_at),
    }


def serialize_group_config(group_config: ChatGroupConfig | None) -> dict | None:
    if group_config is None:
        return None
    return {
        "join_approval_required": group_config.join_approval_required,
        "allow_member_invite": group_config.allow_member_invite,
        "max_members": group_config.max_members,
        "mute_all": group_config.mute_all,
    }


def serialize_conversation(conversation: ChatConversation, user) -> dict:
    access = get_conversation_access(user, conversation)
    member = access.member
    display_name = conversation.name
    avatar = conversation.avatar
    direct_target = None
    friend_remark = None
    if conversation.type == ChatConversation.Type.DIRECT and member:
        other_member = ChatConversationMember.objects.select_related("user").filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE).exclude(user_id=user.id).first()
        if other_member:
            display_name = other_member.user.display_name or other_member.user.username
            avatar = other_member.user.avatar
            direct_target = user_brief(other_member.user)
            friendship = get_active_friendship_between(user.id, other_member.user_id) or ChatFriendship.objects.filter(pair_key=build_pair_key(user.id, other_member.user_id)).first()
            friend_remark = friendship_remark(friendship, user.id) or None
    return {
        "id": conversation.id,
        "type": conversation.type,
        "name": display_name,
        "avatar": avatar,
        "direct_target": direct_target,
        "friend_remark": friend_remark,
        "is_pinned": False if member is None else member.is_pinned,
        "access_mode": access.access_mode,
        "member_role": None if member is None else member.role,
        "show_in_list": True if member is None else member.show_in_list,
        "unread_count": 0 if member is None else member.unread_count,
        "last_message_preview": conversation.last_message_preview,
        "last_message_at": to_serializable_datetime(conversation.last_message_at),
        "member_count": conversation.member_count_cache,
        "can_send_message": access.can_send_message,
        "status": conversation.status,
        "last_read_sequence": 0 if member is None else member.last_read_sequence,
        "member_settings": get_member_preferences(member),
        "group_config": serialize_group_config(getattr(conversation, "group_config", None)) if conversation.type == ChatConversation.Type.GROUP else None,
        "owner": None if conversation.owner is None else user_brief(conversation.owner),
    }


def serialize_friend_request(friend_request: ChatFriendRequest) -> dict:
    return {
        "id": friend_request.id,
        "status": friend_request.status,
        "from_user": user_brief(friend_request.from_user),
        "to_user": user_brief(friend_request.to_user),
        "request_message": friend_request.request_message,
        "auto_accepted": friend_request.auto_accepted,
        "handled_by": None if friend_request.handled_by is None else user_brief(friend_request.handled_by),
        "handled_at": to_serializable_datetime(friend_request.handled_at),
        "created_at": to_serializable_datetime(friend_request.created_at),
    }


def serialize_friendship(friendship: ChatFriendship, current_user) -> dict:
    friend_user = friendship_counterparty(friendship, current_user.id)
    direct_conversation = ChatConversation.objects.filter(direct_pair_key=friendship.pair_key).first()
    direct_member = None if direct_conversation is None else ChatConversationMember.objects.filter(conversation=direct_conversation, user=current_user).first()
    return {
        "friendship_id": friendship.id,
        "friend_user": user_brief(friend_user),
        "accepted_at": to_serializable_datetime(friendship.accepted_at),
        "remark": friendship_remark(friendship, current_user.id),
        "direct_conversation": None if direct_conversation is None else {"id": direct_conversation.id, "show_in_list": True if direct_member is None else direct_member.show_in_list},
    }


def create_or_restore_friendship(from_user, to_user, source_request: ChatFriendRequest | None = None) -> ChatFriendship:
    pair_key = build_pair_key(from_user.id, to_user.id)
    low_user, high_user = (from_user, to_user) if from_user.id < to_user.id else (to_user, from_user)
    friendship = ChatFriendship.objects.filter(pair_key=pair_key).first()
    now = timezone.now()
    if friendship is None:
        friendship = ChatFriendship.objects.create(
            pair_key=pair_key,
            user_low=low_user,
            user_high=high_user,
            status=ChatFriendship.Status.ACTIVE,
            source_request=source_request,
            accepted_at=now,
            deleted_at=None,
        )
    else:
        friendship.status = ChatFriendship.Status.ACTIVE
        friendship.source_request = source_request or friendship.source_request
        friendship.accepted_at = now
        friendship.deleted_at = None
        friendship.save(update_fields=["status", "source_request", "accepted_at", "deleted_at", "updated_at"])
    return friendship


def create_message(conversation: ChatConversation, sender, content: str, client_message_id: str | None = None, message_type: str = ChatMessage.MessageType.TEXT, payload: dict | None = None, is_system: bool = False) -> ChatMessage:
    payload = payload or {}
    with transaction.atomic():
        locked_conversation = ChatConversation.objects.select_for_update().get(pk=conversation.pk)
        current_max_sequence = ChatMessage.objects.filter(conversation=locked_conversation).aggregate(value=Max("sequence")).get("value") or 0
        next_sequence = current_max_sequence + 1
        message = ChatMessage.objects.create(
            conversation=locked_conversation,
            sequence=next_sequence,
            sender=sender,
            message_type=message_type,
            content=content,
            payload=payload,
            client_message_id=client_message_id,
            is_system=is_system,
        )
        preview = content.strip().replace("\n", " ")[:255]
        locked_conversation.last_message = message
        locked_conversation.last_message_preview = preview
        locked_conversation.last_message_at = message.created_at
        locked_conversation.save(update_fields=["last_message", "last_message_preview", "last_message_at", "updated_at"])
        queryset = ChatConversationMember.objects.filter(conversation=locked_conversation, status=ChatConversationMember.Status.ACTIVE)
        if sender is not None:
            queryset = queryset.exclude(user_id=sender.id)
        queryset.update(unread_count=F("unread_count") + 1)
    return message


def mark_conversation_read(member: ChatConversationMember, last_read_sequence: int) -> ChatConversationMember:
    target_message = ChatMessage.objects.filter(conversation=member.conversation, sequence=last_read_sequence).first()
    member.last_read_sequence = last_read_sequence
    member.last_read_message = target_message
    member.unread_count = 0
    member.save(update_fields=["last_read_sequence", "last_read_message", "unread_count", "updated_at"])
    return member


def get_visible_conversations_queryset(user):
    member_ids = ChatConversationMember.objects.filter(user=user, status=ChatConversationMember.Status.ACTIVE, show_in_list=True).values_list("conversation_id", flat=True)
    queryset = ChatConversation.objects.filter(status=ChatConversation.Status.ACTIVE, id__in=member_ids).select_related("owner", "group_config")
    if user_can_stealth_inspect(user):
        queryset = ChatConversation.objects.filter(status=ChatConversation.Status.ACTIVE).select_related("owner", "group_config")
    return queryset.distinct().order_by("-last_message_at", "-id")


def require_group_member_manager(member: ChatConversationMember):
    if member.role not in {ChatConversationMember.Role.OWNER, ChatConversationMember.Role.ADMIN}:
        raise PermissionDenied("当前无权执行该操作")


def ensure_user_can_invite(member: ChatConversationMember, group_config: ChatGroupConfig):
    if group_config.allow_member_invite:
        return
    require_group_member_manager(member)


def handle_friend_request_action(friend_request: ChatFriendRequest, action: str, actor) -> tuple[ChatFriendRequest, ChatFriendship | None, ChatConversation | None]:
    if friend_request.status != ChatFriendRequest.Status.PENDING:
        raise ValidationError({"detail": "当前申请不可再处理"})
    now = timezone.now()
    friendship = None
    conversation = None
    if action == "accept":
        if friend_request.to_user_id != actor.id:
            raise PermissionDenied("仅接收方可通过好友申请")
        friend_request.status = ChatFriendRequest.Status.ACCEPTED
        friend_request.handled_by = actor
        friend_request.handled_at = now
        friend_request.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
        friendship = create_or_restore_friendship(friend_request.from_user, friend_request.to_user, friend_request)
        conversation = ensure_direct_conversation(friend_request.from_user, friend_request.to_user)
        return friend_request, friendship, conversation
    if action == "reject":
        if friend_request.to_user_id != actor.id:
            raise PermissionDenied("仅接收方可拒绝好友申请")
        friend_request.status = ChatFriendRequest.Status.REJECTED
        friend_request.handled_by = actor
        friend_request.handled_at = now
        friend_request.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
        return friend_request, None, None
    if action == "cancel":
        if friend_request.from_user_id != actor.id:
            raise PermissionDenied("仅发起方可取消好友申请")
        friend_request.status = ChatFriendRequest.Status.CANCELED
        friend_request.handled_by = actor
        friend_request.handled_at = now
        friend_request.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
        return friend_request, None, None
    raise ValidationError({"action": "不支持的操作"})


def create_friend_request(from_user, to_user, request_message: str) -> tuple[str, ChatFriendRequest | None, ChatFriendship | None, ChatConversation | None]:
    if from_user.id == to_user.id:
        raise ValidationError({"detail": "不能给自己发送好友申请"})
    if get_active_friendship_between(from_user.id, to_user.id):
        raise ValidationError({"detail": "你们已经是好友"})

    pair_key = build_pair_key(from_user.id, to_user.id)
    reverse_pending = ChatFriendRequest.objects.filter(from_user=to_user, to_user=from_user, status=ChatFriendRequest.Status.PENDING).first()
    if reverse_pending:
        reverse_pending.status = ChatFriendRequest.Status.ACCEPTED
        reverse_pending.auto_accepted = True
        reverse_pending.handled_by = from_user
        reverse_pending.handled_at = timezone.now()
        reverse_pending.save(update_fields=["status", "auto_accepted", "handled_by", "handled_at", "updated_at"])
        request = ChatFriendRequest.objects.create(
            from_user=from_user,
            to_user=to_user,
            pair_key=pair_key,
            status=ChatFriendRequest.Status.ACCEPTED,
            request_message=request_message,
            auto_accepted=True,
            handled_by=to_user,
            handled_at=timezone.now(),
        )
        friendship = create_or_restore_friendship(from_user, to_user, request)
        conversation = ensure_direct_conversation(from_user, to_user)
        return "auto_accepted", request, friendship, conversation

    if ChatFriendRequest.objects.filter(from_user=from_user, to_user=to_user, status=ChatFriendRequest.Status.PENDING).exists():
        raise ValidationError({"detail": "好友申请已发送，请勿重复提交"})

    request = ChatFriendRequest.objects.create(
        from_user=from_user,
        to_user=to_user,
        pair_key=pair_key,
        status=ChatFriendRequest.Status.PENDING,
        request_message=request_message,
    )
    return "pending", request, None, None


def create_group_conversation(owner, *, name: str, member_users: list[User], join_approval_required: bool, allow_member_invite: bool) -> ChatConversation:
    with transaction.atomic():
        conversation = ChatConversation.objects.create(
            type=ChatConversation.Type.GROUP,
            name=name,
            owner=owner,
            status=ChatConversation.Status.ACTIVE,
        )
        ChatGroupConfig.objects.create(
            conversation=conversation,
            join_approval_required=join_approval_required,
            allow_member_invite=allow_member_invite,
        )
        ChatConversationMember.objects.create(
            conversation=conversation,
            user=owner,
            role=ChatConversationMember.Role.OWNER,
            status=ChatConversationMember.Status.ACTIVE,
            joined_at=timezone.now(),
            show_in_list=True,
        )
        for member_user in member_users:
            if member_user.id == owner.id:
                continue
            ChatConversationMember.objects.get_or_create(
                conversation=conversation,
                user=member_user,
                defaults={
                    "role": ChatConversationMember.Role.MEMBER,
                    "status": ChatConversationMember.Status.ACTIVE,
                    "joined_at": timezone.now(),
                    "show_in_list": True,
                },
            )
        recalculate_member_count(conversation)
    return conversation


def create_or_restore_group_member(conversation: ChatConversation, target_user, *, role: str = ChatConversationMember.Role.MEMBER) -> ChatConversationMember:
    membership = ChatConversationMember.objects.filter(conversation=conversation, user=target_user).first()
    if membership is None:
        membership = ChatConversationMember.objects.create(
            conversation=conversation,
            user=target_user,
            role=role,
            status=ChatConversationMember.Status.ACTIVE,
            joined_at=timezone.now(),
            show_in_list=True,
        )
    else:
        membership.role = role if membership.role != ChatConversationMember.Role.OWNER else membership.role
        membership.status = ChatConversationMember.Status.ACTIVE
        membership.left_at = None
        membership.removed_at = None
        membership.removed_by = None
        membership.show_in_list = True
        membership.save(update_fields=["role", "status", "left_at", "removed_at", "removed_by", "show_in_list", "updated_at"])
    recalculate_member_count(conversation)
    return membership


def get_searchable_conversation_ids(user, include_hidden: bool = False) -> list[int]:
    if user_can_stealth_inspect(user):
        return list(ChatConversation.objects.filter(status=ChatConversation.Status.ACTIVE).values_list("id", flat=True))
    queryset = ChatConversationMember.objects.filter(user=user, status=ChatConversationMember.Status.ACTIVE)
    if not include_hidden:
        queryset = queryset.filter(show_in_list=True)
    return list(queryset.values_list("conversation_id", flat=True))


def get_total_unread_count(user) -> int:
    return int(
        ChatConversationMember.objects.filter(user=user, status=ChatConversationMember.Status.ACTIVE).aggregate(value=Sum("unread_count")).get("value")
        or 0
    )


def prepare_send_text_message(user, conversation_id: int, *, content: str, client_message_id: str | None = None) -> dict:
    conversation = ChatConversation.objects.select_related("owner", "group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
    if conversation is None:
        raise ValidationError({"detail": "会话不存在"})
    access = get_conversation_access(user, conversation)
    if access.access_mode != "member" or not access.can_send_message:
        raise PermissionDenied("当前无权发送消息")
    text = str(content or "").strip()
    if not text:
        raise ValidationError({"detail": "消息不能为空"})
    if access.member is not None and not access.member.show_in_list:
        access.member.show_in_list = True
        access.member.save(update_fields=["show_in_list", "updated_at"])
    message = create_message(conversation, user, text, client_message_id=client_message_id)
    conversation = ChatConversation.objects.select_related("owner", "group_config").get(pk=conversation.pk)
    message_payload = serialize_message(message)
    sender_conversation = serialize_conversation(conversation, user)
    recipient_members = list(
        ChatConversationMember.objects.select_related("user").filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE).exclude(user_id=user.id)
    )
    hidden_recipient_ids = [item.pk for item in recipient_members if not item.show_in_list]
    if hidden_recipient_ids:
        ChatConversationMember.objects.filter(pk__in=hidden_recipient_ids).update(show_in_list=True)
    recipient_payloads = []
    for recipient_member in recipient_members:
        refreshed_member = ChatConversationMember.objects.get(pk=recipient_member.pk)
        recipient_payloads.append(
            {
                "user_id": recipient_member.user_id,
                "conversation": serialize_conversation(conversation, recipient_member.user),
                "unread_count": refreshed_member.unread_count,
                "total_unread_count": get_total_unread_count(recipient_member.user),
            }
        )
    return {
        "conversation_id": conversation.id,
        "message": message_payload,
        "sender_conversation": sender_conversation,
        "recipients": recipient_payloads,
    }


def prepare_mark_read(user, conversation_id: int, *, last_read_sequence: int) -> dict:
    conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
    if conversation is None:
        raise ValidationError({"detail": "会话不存在"})
    member = get_member(conversation, user.id, active_only=True)
    if member is None:
        raise PermissionDenied("当前无权操作该会话")
    member = mark_conversation_read(member, last_read_sequence)
    return {
        "conversation_id": conversation.id,
        "unread_count": member.unread_count,
        "total_unread_count": get_total_unread_count(user),
        "last_read_sequence": member.last_read_sequence,
    }


def prepare_typing_payload(user, conversation_id: int, *, is_typing: bool) -> dict:
    conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
    if conversation is None:
        raise ValidationError({"detail": "会话不存在"})
    member = get_member(conversation, user.id, active_only=True)
    if member is None:
        raise PermissionDenied("当前无权操作该会话")
    target_user_ids = list(
        ChatConversationMember.objects.filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE).exclude(user_id=user.id).values_list("user_id", flat=True)
    )
    return {
        "conversation_id": conversation.id,
        "user": user_brief(user),
        "is_typing": bool(is_typing),
        "target_user_ids": target_user_ids,
    }


def mute_member_until(minutes: int):
    return timezone.now() + timedelta(minutes=minutes)