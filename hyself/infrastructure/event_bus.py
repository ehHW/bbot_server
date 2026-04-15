from __future__ import annotations

from django.contrib.auth import get_user_model

from chat.domain.common import to_serializable_datetime
from hyself.application.payloads.resource_center import build_resource_reference_payload
from hyself.application.services.resource_center import entry_is_within_recycle_bin_tree
from hyself.asset_compat import ensure_asset_compat_for_uploaded_file
from ws.event_bus import publish_user_event


RESOURCE_DOMAIN = "resource"
User = get_user_model()


def _build_change_token(entry_id: int, updated_at: str | None) -> str:
    return f"resource:{entry_id}:{updated_at or 'unknown'}"


def _serialize_resource_entry(entry) -> dict:
    reference = ensure_asset_compat_for_uploaded_file(entry)[1]
    payload = build_resource_reference_payload(
        reference,
        entry_is_within_recycle_bin_tree=entry_is_within_recycle_bin_tree,
    )
    return _make_event_payload_serializable(payload)


def _make_event_payload_serializable(value):
    if isinstance(value, dict):
        return {key: _make_event_payload_serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_make_event_payload_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [_make_event_payload_serializable(item) for item in value]
    if hasattr(value, "isoformat"):
        return to_serializable_datetime(value)
    return value


def _iter_resource_recipient_ids(owner_user_id: int | None) -> list[int]:
    recipient_ids = set(User.objects.filter(is_superuser=True).values_list("id", flat=True))
    if owner_user_id:
        recipient_ids.add(owner_user_id)
    return sorted(recipient_ids)


def _publish_resource_event(owner_user_id: int | None, event_type: str, payload: dict) -> None:
    for recipient_id in _iter_resource_recipient_ids(owner_user_id):
        publish_user_event(
            recipient_id,
            event_type,
            payload,
            domain=RESOURCE_DOMAIN,
        )


def notify_resource_entry_created(entry) -> None:
    owner_user_id = getattr(entry, "created_by_id", None)
    if not _iter_resource_recipient_ids(owner_user_id):
        return
    updated_at = to_serializable_datetime(getattr(entry, "updated_at", None))
    _publish_resource_event(
        owner_user_id,
        "resource.entry.created",
        {
            "entry": _serialize_resource_entry(entry),
            "scope": "user",
            "owner_user_id": owner_user_id,
            "parent_id": entry.parent_id,
            "change_token": _build_change_token(entry.id, updated_at),
        },
    )


def notify_resource_entry_updated(entry, *, previous_parent_id: int | None = None) -> None:
    owner_user_id = getattr(entry, "created_by_id", None)
    if not _iter_resource_recipient_ids(owner_user_id):
        return
    updated_at = to_serializable_datetime(getattr(entry, "updated_at", None))
    _publish_resource_event(
        owner_user_id,
        "resource.entry.updated",
        {
            "entry": _serialize_resource_entry(entry),
            "previous_parent_id": previous_parent_id if previous_parent_id is not None else entry.parent_id,
            "scope": "user",
            "owner_user_id": owner_user_id,
            "change_token": _build_change_token(entry.id, updated_at),
        },
    )


def notify_resource_entry_moved(*, owner_user_id: int | None, entry_id: int, entry_kind: str, entry=None, from_parent_id: int | None, to_parent_id: int | None, updated_at) -> None:
    if not _iter_resource_recipient_ids(owner_user_id):
        return
    serialized_updated_at = to_serializable_datetime(updated_at)
    _publish_resource_event(
        owner_user_id,
        "resource.entry.moved",
        {
            "entry_id": entry_id,
            "entry_kind": entry_kind,
            "entry": None if entry is None else _serialize_resource_entry(entry),
            "from_parent_id": from_parent_id,
            "to_parent_id": to_parent_id,
            "updated_at": serialized_updated_at,
            "change_token": _build_change_token(entry_id, serialized_updated_at),
            "scope": "user",
            "owner_user_id": owner_user_id,
        },
    )


def notify_resource_entry_deleted(*, owner_user_id: int | None, entry_id: int, parent_id: int | None, deleted_mode: str, updated_at) -> None:
    if not _iter_resource_recipient_ids(owner_user_id):
        return
    serialized_updated_at = to_serializable_datetime(updated_at)
    owner_has_entries = bool(owner_user_id and User.objects.filter(id=owner_user_id, uploaded_files__deleted_at__isnull=True).exists())
    _publish_resource_event(
        owner_user_id,
        "resource.entry.deleted",
        {
            "entry_id": entry_id,
            "parent_id": parent_id,
            "deleted_mode": deleted_mode,
            "updated_at": serialized_updated_at,
            "change_token": _build_change_token(entry_id, serialized_updated_at),
            "scope": "user",
            "owner_user_id": owner_user_id,
            "owner_has_entries": owner_has_entries,
        },
    )