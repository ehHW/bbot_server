from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import ChatConversation, ChatConversationMember, ChatFriendRequest, ChatFriendship, ChatGroupJoinRequest, ChatMessage, build_pair_key
from chat.serializers import (
    ConversationPreferenceSerializer,
    ConversationReadSerializer,
    CreateGroupConversationSerializer,
    FriendSettingUpdateSerializer,
    FriendRequestCreateSerializer,
    FriendRequestHandleSerializer,
    GroupConfigUpdateSerializer,
    GroupJoinRequestHandleSerializer,
    InviteConversationMemberSerializer,
    MuteConversationMemberSerializer,
    ConversationPinSerializer,
    OpenDirectConversationSerializer,
    UpdateConversationMemberRoleSerializer,
    UserPreferenceSerializer,
)
from chat.services import (
    create_friend_request,
    create_group_conversation,
    create_message,
    create_or_restore_group_member,
    ensure_direct_conversation,
    ensure_user_can_invite,
    get_active_friendship_between,
    get_conversation_access,
    get_member,
    get_member_preferences,
    get_or_create_user_preference,
    get_searchable_conversation_ids,
    handle_friend_request_action,
    friendship_remark,
    mute_member_until,
    recalculate_member_count,
    require_group_member_manager,
    serialize_conversation,
    serialize_friend_request,
    serialize_friendship,
    serialize_group_config,
    serialize_message,
    to_serializable_datetime,
    update_friendship_remark,
    update_member_preferences,
    user_brief,
    user_can_review_all_messages,
)
from ws.events import (
    notify_chat_conversation_updated,
    notify_chat_friend_request_updated,
    notify_chat_friendship_updated,
    notify_chat_group_join_request_updated,
    notify_chat_system_notice,
    notify_chat_unread_updated,
)


User = get_user_model()


class FriendRequestListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        direction = str(request.query_params.get("direction", "received")).strip().lower()
        status_filter = str(request.query_params.get("status", "")).strip()
        queryset = ChatFriendRequest.objects.select_related("from_user", "to_user", "handled_by")
        if direction == "sent":
            queryset = queryset.filter(from_user=request.user)
        elif direction == "all":
            queryset = queryset.filter(Q(from_user=request.user) | Q(to_user=request.user))
        else:
            queryset = queryset.filter(to_user=request.user)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        items = [serialize_friend_request(item) for item in queryset[:100]]
        return Response({"count": len(items), "next": None, "previous": None, "results": items})

    def post(self, request):
        serializer = FriendRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user = User.objects.filter(id=serializer.validated_data["to_user_id"], deleted_at__isnull=True, is_active=True).first()
        if target_user is None:
            return Response({"detail": "目标用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        mode, friend_request, friendship, conversation = create_friend_request(request.user, target_user, serializer.validated_data.get("request_message", ""))
        if friend_request:
            notify_chat_friend_request_updated(target_user.id, serialize_friend_request(friend_request))
        if mode == "auto_accepted" and friendship and conversation:
            for current_user in [request.user, target_user]:
                notify_chat_friendship_updated(current_user.id, {"action": "accepted", "friend_user": user_brief(target_user if current_user.id == request.user.id else request.user), "conversation": {"id": conversation.id, "type": conversation.type, "show_in_list": True}})
                notify_chat_conversation_updated(current_user.id, serialize_conversation(conversation, current_user))
            return Response({"mode": mode, "detail": "双方已自动成为好友", "friendship": serialize_friendship(friendship, request.user), "conversation": {"id": conversation.id, "type": conversation.type, "show_in_list": True}})
        return Response({"mode": mode, "detail": "好友申请已发送", "request": serialize_friend_request(friend_request)})


class FriendRequestHandleAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        friend_request = ChatFriendRequest.objects.select_related("from_user", "to_user", "handled_by").filter(id=request_id).first()
        if friend_request is None:
            return Response({"detail": "好友申请不存在"}, status=status.HTTP_404_NOT_FOUND)
        serializer = FriendRequestHandleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        friend_request, friendship, conversation = handle_friend_request_action(friend_request, serializer.validated_data["action"], request.user)
        for current_user_id in {friend_request.from_user_id, friend_request.to_user_id}:
            notify_chat_friend_request_updated(current_user_id, serialize_friend_request(friend_request))
        response = {"detail": "好友申请已处理", "request": {"id": friend_request.id, "status": friend_request.status}}
        if friendship and conversation:
            response["friendship"] = {"id": friendship.id, "status": friendship.status}
            response["conversation"] = {"id": conversation.id, "type": conversation.type}
            notify_chat_friendship_updated(friend_request.from_user_id, {"action": "accepted", "friend_user": user_brief(friend_request.to_user), "conversation": {"id": conversation.id, "type": conversation.type, "show_in_list": True}})
            notify_chat_friendship_updated(friend_request.to_user_id, {"action": "accepted", "friend_user": user_brief(friend_request.from_user), "conversation": {"id": conversation.id, "type": conversation.type, "show_in_list": True}})
            notify_chat_conversation_updated(friend_request.from_user_id, serialize_conversation(conversation, friend_request.from_user))
            notify_chat_conversation_updated(friend_request.to_user_id, serialize_conversation(conversation, friend_request.to_user))
        return Response(response)


class FriendListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        keyword = str(request.query_params.get("keyword", "")).strip()
        friendships = ChatFriendship.objects.filter(status=ChatFriendship.Status.ACTIVE).select_related("user_low", "user_high")
        friendships = [item for item in friendships if request.user.id in {item.user_low_id, item.user_high_id}]
        if keyword:
            lowered = keyword.lower()
            friendships = [
                item
                for item in friendships
                if lowered in (item.user_low.display_name or item.user_low.username).lower() or lowered in (item.user_high.display_name or item.user_high.username).lower()
            ]
        results = [serialize_friendship(item, request.user) for item in friendships]
        return Response({"count": len(results), "next": None, "previous": None, "results": results})


class FriendDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, friend_user_id: int):
        friendship = get_active_friendship_between(request.user.id, friend_user_id)
        if friendship is None:
            return Response({"detail": "好友关系不存在"}, status=status.HTTP_404_NOT_FOUND)
        friendship.status = ChatFriendship.Status.DELETED
        friendship.deleted_at = timezone.now()
        friendship.save(update_fields=["status", "deleted_at", "updated_at"])
        notify_chat_friendship_updated(request.user.id, {"action": "deleted", "friend_user": {"id": friend_user_id}})
        notify_chat_friendship_updated(friend_user_id, {"action": "deleted", "friend_user": {"id": request.user.id}})
        return Response({"detail": "已删除好友", "friend_user_id": friend_user_id})


class FriendSettingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, friend_user_id: int):
        friendship = ChatFriendship.objects.filter(pair_key=build_pair_key(request.user.id, friend_user_id)).first()
        if friendship is None:
            return Response({"detail": "好友关系不存在"}, status=status.HTTP_404_NOT_FOUND)
        serializer = FriendSettingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "remark" in serializer.validated_data:
            update_friendship_remark(friendship, request.user.id, serializer.validated_data["remark"])
        return Response({"detail": "好友设置已更新", "remark": friendship_remark(friendship, request.user.id)})


class ConversationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        category = str(request.query_params.get("category", "all")).strip().lower()
        keyword = str(request.query_params.get("keyword", "")).strip()
        include_hidden = str(request.query_params.get("include_hidden", "false")).strip().lower() in {"1", "true", "yes", "on"}
        queryset = ChatConversation.objects.filter(status=ChatConversation.Status.ACTIVE).select_related("owner", "group_config")
        visible_ids = get_searchable_conversation_ids(request.user, include_hidden=include_hidden)
        queryset = queryset.filter(id__in=visible_ids)
        if category in {"direct", "group"}:
            queryset = queryset.filter(type=category)
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        results = [serialize_conversation(item, request.user) for item in queryset.order_by("-last_message_at", "-id")[:200]]
        return Response({"count": len(results), "next": None, "previous": None, "results": results})


class ConversationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: int):
        conversation = ChatConversation.objects.select_related("owner", "group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_conversation(conversation, request.user))


class DirectConversationOpenAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OpenDirectConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user = User.objects.filter(id=serializer.validated_data["target_user_id"], deleted_at__isnull=True, is_active=True).first()
        if target_user is None:
            return Response({"detail": "目标用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target_user.id == request.user.id:
            return Response({"detail": "不能和自己发起单聊"}, status=status.HTTP_400_BAD_REQUEST)
        conversation = ensure_direct_conversation(request.user, target_user)
        notify_chat_conversation_updated(request.user.id, serialize_conversation(conversation, request.user))
        notify_chat_conversation_updated(target_user.id, serialize_conversation(conversation, target_user))
        return Response({"detail": "会话已打开", "created": False, "conversation": {"id": conversation.id, "type": conversation.type, "show_in_list": True}})


class GroupConversationCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateGroupConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member_ids = sorted(set(serializer.validated_data.get("member_user_ids", [])))
        member_users = list(User.objects.filter(id__in=member_ids, deleted_at__isnull=True, is_active=True))
        conversation = create_group_conversation(
            request.user,
            name=serializer.validated_data["name"],
            member_users=member_users,
            join_approval_required=serializer.validated_data["join_approval_required"],
            allow_member_invite=serializer.validated_data["allow_member_invite"],
        )
        for user in {request.user, *member_users}:
            notify_chat_conversation_updated(user.id, serialize_conversation(conversation, user))
        return Response({"detail": "群聊创建成功", "conversation": {"id": conversation.id, "type": conversation.type, "name": conversation.name}}, status=status.HTTP_201_CREATED)


class ConversationHideAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前无权操作该会话"}, status=status.HTTP_403_FORBIDDEN)
        member.show_in_list = False
        member.save(update_fields=["show_in_list", "updated_at"])
        notify_chat_conversation_updated(request.user.id, serialize_conversation(conversation, request.user))
        return Response({"detail": "会话已从列表移除", "conversation_id": conversation.id, "show_in_list": False})


class ConversationReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        serializer = ConversationReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前无权操作该会话"}, status=status.HTTP_403_FORBIDDEN)
        from chat.services import mark_conversation_read

        member = mark_conversation_read(member, serializer.validated_data["last_read_sequence"])
        notify_chat_unread_updated(request.user.id, conversation.id, member.unread_count)
        return Response({"detail": "已标记为已读", "conversation_id": conversation.id, "unread_count": member.unread_count, "last_read_sequence": member.last_read_sequence})


class ConversationMessagesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: int):
        conversation = ChatConversation.objects.select_related("owner", "group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        access = get_conversation_access(request.user, conversation)
        if access.member is not None and not access.member.show_in_list:
            access.member.show_in_list = True
            access.member.save(update_fields=["show_in_list", "updated_at"])
        before_sequence = request.query_params.get("before_sequence")
        after_sequence = request.query_params.get("after_sequence")
        around_sequence = request.query_params.get("around_sequence")
        limit = max(1, min(100, int(request.query_params.get("limit", 30))))
        queryset = ChatMessage.objects.select_related("sender").filter(conversation=conversation)
        if around_sequence:
            anchor_sequence = int(around_sequence)
            around_queryset = queryset.filter(sequence__lte=anchor_sequence).order_by("-sequence")
            messages = list(reversed(list(around_queryset[:limit])))
            has_more_before = around_queryset.count() > limit
            has_more_after = queryset.filter(sequence__gt=anchor_sequence).exists()
        elif before_sequence:
            queryset = queryset.filter(sequence__lt=int(before_sequence)).order_by("-sequence")
            messages = list(reversed(list(queryset[:limit])))
            has_more_before = queryset.count() > limit
            has_more_after = False
        elif after_sequence:
            queryset = queryset.filter(sequence__gt=int(after_sequence)).order_by("sequence")
            messages = list(queryset[:limit])
            has_more_before = False
            has_more_after = queryset.count() > limit
        else:
            messages = list(reversed(list(queryset.order_by("-sequence")[:limit])))
            has_more_before = queryset.count() > limit
            has_more_after = False
        first_sequence = messages[0].sequence if messages else None
        last_sequence = messages[-1].sequence if messages else None
        return Response({
            "conversation": {"id": conversation.id, "type": conversation.type, "access_mode": access.access_mode, "can_send_message": access.can_send_message},
            "cursor": {"before_sequence": first_sequence, "after_sequence": last_sequence, "has_more_before": has_more_before, "has_more_after": has_more_after},
            "items": [serialize_message(item) for item in messages],
        })


class ConversationPreferenceAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, conversation_id: int):
        conversation = ChatConversation.objects.select_related("owner", "group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前无权操作该会话"}, status=status.HTTP_403_FORBIDDEN)
        serializer = ConversationPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_member_preferences(
            member,
            mute_notifications=serializer.validated_data.get("mute_notifications"),
            group_nickname=serializer.validated_data.get("group_nickname"),
        )
        payload = serialize_conversation(conversation, request.user)
        notify_chat_conversation_updated(request.user.id, payload)
        return Response({"detail": "会话设置已更新", "conversation": payload, "member_settings": get_member_preferences(member)})


class ConversationMembersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: int):
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        get_conversation_access(request.user, conversation)
        items = list(ChatConversationMember.objects.select_related("user").filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE))

        def member_sort_key(item: ChatConversationMember):
            role_order = 0 if item.role == ChatConversationMember.Role.OWNER else 1 if item.role == ChatConversationMember.Role.ADMIN else 2
            nickname = str((item.extra_settings or {}).get("group_nickname", "") or "")
            display = nickname or item.user.display_name or item.user.username
            return (role_order, display.lower())

        result_items = []
        for item in sorted(items, key=member_sort_key):
            friendship = get_active_friendship_between(request.user.id, item.user_id) or ChatFriendship.objects.filter(pair_key=build_pair_key(request.user.id, item.user_id)).first()
            result_items.append({
                "user": user_brief(item.user),
                "role": item.role,
                "status": item.status,
                "mute_until": to_serializable_datetime(item.mute_until),
                "joined_at": to_serializable_datetime(item.joined_at),
                "group_nickname": str((item.extra_settings or {}).get("group_nickname", "") or ""),
                "friend_remark": friendship_remark(friendship, request.user.id) or None,
            })
        return Response({"conversation_id": conversation.id, "items": result_items})


class ConversationInviteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        serializer = InviteConversationMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = ChatConversation.objects.select_related("group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前无权邀请成员"}, status=status.HTTP_403_FORBIDDEN)
        target_user = User.objects.filter(id=serializer.validated_data["target_user_id"], deleted_at__isnull=True, is_active=True).first()
        if target_user is None:
            return Response({"detail": "目标用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if get_member(conversation, target_user.id, active_only=True):
            return Response({"detail": "目标用户已在群中"}, status=status.HTTP_400_BAD_REQUEST)
        ensure_user_can_invite(member, conversation.group_config)
        if conversation.group_config.join_approval_required:
            if ChatGroupJoinRequest.objects.filter(conversation=conversation, target_user=target_user, status=ChatGroupJoinRequest.Status.PENDING).exists():
                return Response({"detail": "该用户已有待审批记录"}, status=status.HTTP_400_BAD_REQUEST)
            join_request = ChatGroupJoinRequest.objects.create(conversation=conversation, inviter=request.user, target_user=target_user, status=ChatGroupJoinRequest.Status.PENDING)
            active_admins = ChatConversationMember.objects.select_related("user").filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE, role__in=[ChatConversationMember.Role.OWNER, ChatConversationMember.Role.ADMIN])
            for admin_member in active_admins:
                notify_chat_group_join_request_updated(admin_member.user_id, {"id": join_request.id, "conversation_id": conversation.id, "status": join_request.status, "target_user": user_brief(target_user), "created_at": join_request.created_at})
            return Response({"mode": "pending_approval", "detail": "已提交群审批", "join_request": {"id": join_request.id, "status": join_request.status}})
        created_member = create_or_restore_group_member(conversation, target_user)
        for affected_user in [target_user, request.user]:
            notify_chat_conversation_updated(affected_user.id, serialize_conversation(conversation, affected_user))
        notify_chat_system_notice(target_user.id, "你已加入群聊", {"conversation_id": conversation.id})
        return Response({"mode": "joined", "detail": "成员已加入群聊", "member": {"user_id": created_member.user_id, "status": created_member.status}})


class ConversationLeaveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前不在该群聊中"}, status=status.HTTP_400_BAD_REQUEST)
        member.status = ChatConversationMember.Status.LEFT
        member.left_at = timezone.now()
        member.show_in_list = False
        member.save(update_fields=["status", "left_at", "show_in_list", "updated_at"])
        recalculate_member_count(conversation)
        notify_chat_system_notice(request.user.id, "已退出群聊", {"conversation_id": conversation.id})
        return Response({"detail": "已退出群聊", "conversation_id": conversation.id})


class ConversationRemoveMemberAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int, user_id: int):
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        actor_member = get_member(conversation, request.user.id, active_only=True)
        if actor_member is None:
            return Response({"detail": "当前无权操作该群聊"}, status=status.HTTP_403_FORBIDDEN)
        require_group_member_manager(actor_member)
        target_member = get_member(conversation, user_id, active_only=True)
        if target_member is None:
            return Response({"detail": "目标成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target_member.role == ChatConversationMember.Role.OWNER:
            return Response({"detail": "不能移除群主"}, status=status.HTTP_400_BAD_REQUEST)
        target_member.status = ChatConversationMember.Status.REMOVED
        target_member.removed_at = timezone.now()
        target_member.removed_by = request.user
        target_member.show_in_list = False
        target_member.save(update_fields=["status", "removed_at", "removed_by", "show_in_list", "updated_at"])
        recalculate_member_count(conversation)
        notify_chat_system_notice(target_member.user_id, "你已被移出群聊", {"conversation_id": conversation.id})
        return Response({"detail": "已移出群成员", "conversation_id": conversation.id, "user_id": user_id})


class ConversationUpdateMemberRoleAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int, user_id: int):
        serializer = UpdateConversationMemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        actor_member = get_member(conversation, request.user.id, active_only=True)
        if actor_member is None or actor_member.role != ChatConversationMember.Role.OWNER:
            return Response({"detail": "仅群主可设置成员角色"}, status=status.HTTP_403_FORBIDDEN)
        target_member = get_member(conversation, user_id, active_only=True)
        if target_member is None:
            return Response({"detail": "目标成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target_member.role == ChatConversationMember.Role.OWNER:
            return Response({"detail": "不能修改群主角色"}, status=status.HTTP_400_BAD_REQUEST)
        target_member.role = serializer.validated_data["role"]
        target_member.save(update_fields=["role", "updated_at"])
        return Response({"detail": "成员角色已更新", "conversation_id": conversation.id, "user_id": user_id, "role": target_member.role})


class ConversationMuteMemberAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int, user_id: int):
        serializer = MuteConversationMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = ChatConversation.objects.filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None:
            return Response({"detail": "群聊不存在"}, status=status.HTTP_404_NOT_FOUND)
        actor_member = get_member(conversation, request.user.id, active_only=True)
        if actor_member is None:
            return Response({"detail": "当前无权操作该群聊"}, status=status.HTTP_403_FORBIDDEN)
        require_group_member_manager(actor_member)
        target_member = get_member(conversation, user_id, active_only=True)
        if target_member is None:
            return Response({"detail": "目标成员不存在"}, status=status.HTTP_404_NOT_FOUND)
        if target_member.role == ChatConversationMember.Role.OWNER:
            return Response({"detail": "不能禁言群主"}, status=status.HTTP_400_BAD_REQUEST)
        target_member.mute_until = mute_member_until(serializer.validated_data["mute_minutes"])
        target_member.mute_reason = serializer.validated_data.get("reason", "")
        target_member.save(update_fields=["mute_until", "mute_reason", "updated_at"])
        return Response({"detail": "成员已被禁言", "conversation_id": conversation.id, "user_id": user_id, "mute_until": target_member.mute_until})


class GroupConfigAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, conversation_id: int):
        conversation = ChatConversation.objects.select_related("group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE, type=ChatConversation.Type.GROUP).first()
        if conversation is None or not hasattr(conversation, "group_config"):
            return Response({"detail": "群配置不存在"}, status=status.HTTP_404_NOT_FOUND)
        actor_member = get_member(conversation, request.user.id, active_only=True)
        if actor_member is None:
            return Response({"detail": "当前无权操作该群聊"}, status=status.HTTP_403_FORBIDDEN)
        require_group_member_manager(actor_member)
        serializer = GroupConfigUpdateSerializer(conversation.group_config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        conversation_fields = []
        if "name" in serializer.validated_data:
            conversation.name = serializer.validated_data["name"]
            conversation_fields.append("name")
        if "avatar" in serializer.validated_data:
            conversation.avatar = serializer.validated_data["avatar"]
            conversation_fields.append("avatar")
        if conversation_fields:
            conversation.save(update_fields=[*conversation_fields, "updated_at"])
        serializer.save()
        active_members = ChatConversationMember.objects.select_related("user").filter(conversation=conversation, status=ChatConversationMember.Status.ACTIVE)
        for member in active_members:
            notify_chat_conversation_updated(member.user_id, serialize_conversation(conversation, member.user))
        return Response({"detail": "群配置已更新", "conversation": serialize_conversation(conversation, request.user), "group_config": serialize_group_config(conversation.group_config)})


class ConversationPinAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        conversation = ChatConversation.objects.select_related("owner", "group_config").filter(id=conversation_id, status=ChatConversation.Status.ACTIVE).first()
        if conversation is None:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        member = get_member(conversation, request.user.id, active_only=True)
        if member is None:
            return Response({"detail": "当前无权操作该会话"}, status=status.HTTP_403_FORBIDDEN)
        serializer = ConversationPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member.is_pinned = serializer.validated_data["is_pinned"]
        member.save(update_fields=["is_pinned", "updated_at"])
        payload = serialize_conversation(conversation, request.user)
        notify_chat_conversation_updated(request.user.id, payload)
        return Response({"detail": "会话置顶状态已更新", "conversation": payload})


class GroupJoinRequestListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conversation_id = request.query_params.get("conversation_id")
        status_filter = str(request.query_params.get("status", "")).strip()
        queryset = ChatGroupJoinRequest.objects.select_related("conversation", "target_user", "inviter", "reviewer")
        if conversation_id:
            queryset = queryset.filter(conversation_id=int(conversation_id))
        queryset = queryset.filter(conversation__members__user=request.user, conversation__members__status=ChatConversationMember.Status.ACTIVE).distinct()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        items = [{"id": item.id, "conversation_id": item.conversation_id, "status": item.status, "target_user": user_brief(item.target_user), "created_at": item.created_at} for item in queryset[:100]]
        return Response({"count": len(items), "next": None, "previous": None, "results": items})


class GroupJoinRequestHandleAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        serializer = GroupJoinRequestHandleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        join_request = ChatGroupJoinRequest.objects.select_related("conversation", "target_user", "inviter", "reviewer", "conversation__group_config").filter(id=request_id).first()
        if join_request is None:
            return Response({"detail": "群审批记录不存在"}, status=status.HTTP_404_NOT_FOUND)
        if join_request.status != ChatGroupJoinRequest.Status.PENDING:
            return Response({"detail": "当前审批记录不可再处理"}, status=status.HTTP_400_BAD_REQUEST)
        action = serializer.validated_data["action"]
        actor_member = get_member(join_request.conversation, request.user.id, active_only=True)
        now = timezone.now()
        if action in {"approve", "reject"}:
            if actor_member is None:
                return Response({"detail": "当前无权处理审批"}, status=status.HTTP_403_FORBIDDEN)
            require_group_member_manager(actor_member)
            join_request.status = ChatGroupJoinRequest.Status.APPROVED if action == "approve" else ChatGroupJoinRequest.Status.REJECTED
            join_request.reviewer = request.user
            join_request.review_note = serializer.validated_data.get("review_note", "")
            join_request.reviewed_at = now
            join_request.save(update_fields=["status", "reviewer", "review_note", "reviewed_at", "updated_at"])
            if action == "approve":
                create_or_restore_group_member(join_request.conversation, join_request.target_user)
                notify_chat_conversation_updated(join_request.target_user_id, serialize_conversation(join_request.conversation, join_request.target_user))
        else:
            if join_request.inviter_id != request.user.id:
                return Response({"detail": "仅邀请人可取消审批"}, status=status.HTTP_403_FORBIDDEN)
            join_request.status = ChatGroupJoinRequest.Status.CANCELED
            join_request.reviewer = request.user
            join_request.review_note = serializer.validated_data.get("review_note", "")
            join_request.reviewed_at = now
            join_request.save(update_fields=["status", "reviewer", "review_note", "reviewed_at", "updated_at"])
        for target_user_id in {join_request.target_user_id, join_request.inviter_id}:
            notify_chat_group_join_request_updated(target_user_id, {"id": join_request.id, "conversation_id": join_request.conversation_id, "status": join_request.status, "target_user": user_brief(join_request.target_user), "created_at": join_request.created_at})
        return Response({"detail": "群审批已处理", "join_request": {"id": join_request.id, "status": join_request.status}})


class ChatSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        keyword = str(request.query_params.get("keyword", "")).strip()
        if not keyword:
            return Response({"detail": "搜索关键字不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(20, int(request.query_params.get("limit", 5))))
        visible_ids = get_searchable_conversation_ids(request.user, include_hidden=True)
        conversations = ChatConversation.objects.filter(id__in=visible_ids, status=ChatConversation.Status.ACTIVE, name__icontains=keyword).select_related("owner", "group_config")[:limit]
        users = User.objects.filter(Q(username__icontains=keyword) | Q(display_name__icontains=keyword), deleted_at__isnull=True, is_active=True)[:limit]
        messages = ChatMessage.objects.select_related("sender", "conversation").filter(conversation_id__in=visible_ids, content__icontains=keyword).order_by("-created_at")[:limit]
        conversation_payload_map = {item.id: serialize_conversation(item, request.user) for item in conversations}
        message_conversation_ids = {item.conversation_id for item in messages}
        if message_conversation_ids:
            for item in ChatConversation.objects.filter(id__in=message_conversation_ids).select_related("owner", "group_config"):
                conversation_payload_map.setdefault(item.id, serialize_conversation(item, request.user))
        users_payload = []
        for item in users:
            pair_key = build_pair_key(request.user.id, item.id)
            direct_conversation = ChatConversation.objects.filter(direct_pair_key=pair_key, status=ChatConversation.Status.ACTIVE).first()
            direct_member = None if direct_conversation is None else ChatConversationMember.objects.filter(conversation=direct_conversation, user=request.user).first()
            users_payload.append({
                "id": item.id,
                "username": item.username,
                "display_name": item.display_name,
                "avatar": item.avatar,
                "can_open_direct": item.id != request.user.id,
                "direct_conversation": None if direct_conversation is None else {"id": direct_conversation.id, "show_in_list": True if direct_member is None else direct_member.show_in_list},
            })
        return Response({
            "keyword": keyword,
            "conversations": [{"id": item.id, "type": item.type, "name": conversation_payload_map[item.id]["name"], "access_mode": conversation_payload_map[item.id]["access_mode"]} for item in conversations],
            "users": users_payload,
            "messages": [{"conversation_id": item.conversation_id, "conversation_name": conversation_payload_map[item.conversation_id]["name"], "message_id": item.id, "sequence": item.sequence, "message_type": item.message_type, "content_preview": item.content[:80], "sender": None if item.sender is None else user_brief(item.sender), "created_at": to_serializable_datetime(item.created_at)} for item in messages],
        })


class ChatSettingsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference = get_or_create_user_preference(request.user)
        serializer = UserPreferenceSerializer(preference)
        return Response(serializer.data)

    def patch(self, request):
        preference = get_or_create_user_preference(request.user)
        serializer = UserPreferenceSerializer(preference, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AdminConversationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_can_review_all_messages(request.user):
            return Response({"detail": "当前无权查看全部会话"}, status=status.HTTP_403_FORBIDDEN)
        keyword = str(request.query_params.get("keyword", "")).strip()
        conversation_type = str(request.query_params.get("type", "")).strip()
        queryset = ChatConversation.objects.filter(status=ChatConversation.Status.ACTIVE).select_related("owner", "group_config")
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        if conversation_type in {ChatConversation.Type.DIRECT, ChatConversation.Type.GROUP}:
            queryset = queryset.filter(type=conversation_type)
        results = [serialize_conversation(item, request.user) for item in queryset.order_by("-last_message_at")[:100]]
        return Response({"count": len(results), "next": None, "previous": None, "results": results})


class AdminMessageListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_can_review_all_messages(request.user):
            return Response({"detail": "当前无权查看全部聊天记录"}, status=status.HTTP_403_FORBIDDEN)
        queryset = ChatMessage.objects.select_related("sender", "conversation")
        conversation_id = request.query_params.get("conversation_id")
        keyword = str(request.query_params.get("keyword", "")).strip()
        if conversation_id:
            queryset = queryset.filter(conversation_id=int(conversation_id))
        if keyword:
            queryset = queryset.filter(content__icontains=keyword)
        items = [serialize_message(item) | {"conversation_id": item.conversation_id} for item in queryset.order_by("-created_at")[:200]]
        return Response({"count": len(items), "next": None, "previous": None, "results": items})
