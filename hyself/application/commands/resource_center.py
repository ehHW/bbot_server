from __future__ import annotations

from pathlib import Path

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from hyself.auth.permissions import ensure_reference_can_be_saved_to_resource
from hyself.infrastructure.event_bus import notify_resource_entry_created, notify_resource_entry_deleted, notify_resource_entry_moved, notify_resource_entry_updated
from hyself.application.services.resource_center import (
    entry_is_within_recycle_bin_tree,
    get_parent_dir,
    is_reserved_system_folder_name,
    resolve_existing_upload_file,
)
from hyself.models import Asset, AssetReference, UploadedFile
from hyself.recycle_bin import is_recycle_bin_folder, move_entry_to_recycle_bin, restore_entry_from_recycle_bin
from hyself.utils.upload import build_stored_name, get_upload_root


User = get_user_model()


def hard_delete_uploaded_entry(entry: UploadedFile) -> dict:
    subtree_ids = [entry.id]
    cursor = [entry.id]
    while cursor:
        child_ids = list(UploadedFile.all_objects.filter(parent_id__in=cursor).values_list("id", flat=True))
        if not child_ids:
            break
        subtree_ids.extend(child_ids)
        cursor = child_ids

    items = list(UploadedFile.all_objects.filter(id__in=subtree_ids).order_by("-is_dir", "-id"))
    asset_refs = list(AssetReference.all_objects.select_related("asset").filter(legacy_uploaded_file_id__in=subtree_ids))
    asset_ids = {item.asset_id for item in asset_refs if item.asset_id}
    # 收集每个 relative_path 对应的 asset_id，便于后续对照清理
    path_to_asset_id: dict[str, int] = {}
    for ref in asset_refs:
        if ref.asset_id and ref.relative_path_cache:
            path_to_asset_id[ref.relative_path_cache] = ref.asset_id
    file_paths = {str(item.relative_path or "") for item in items if not item.is_dir and item.relative_path}

    removed_db_files = sum(1 for item in items if not item.is_dir)
    removed_db_dirs = sum(1 for item in items if item.is_dir)

    # 先删除本批次的 AssetReference 和 UploadedFile
    AssetReference.all_objects.filter(id__in=[item.id for item in asset_refs]).hard_delete()
    UploadedFile.all_objects.filter(id__in=subtree_ids).hard_delete()

    # 同步删除同一 file_md5 的其他 UploadedFile 引用（同用户通过秒传复用产生的冗余条目）
    md5_set = {str(item.file_md5 or "") for item in items if not item.is_dir and item.file_md5}
    if md5_set:
        dangling_entries = list(UploadedFile.all_objects.filter(file_md5__in=md5_set, is_dir=False).values_list("id", flat=True))
        if dangling_entries:
            AssetReference.all_objects.filter(legacy_uploaded_file_id__in=dangling_entries).hard_delete()
            UploadedFile.all_objects.filter(id__in=dangling_entries).hard_delete()
            removed_db_files += len(dangling_entries)

    removed_disk_files = 0
    deleted_asset_ids: set[int] = set()
    for relative_path in file_paths:
        # 物理文件是否还被其他条目或 Asset 引用
        still_used_by_entry = UploadedFile.all_objects.filter(relative_path=relative_path).exists()
        still_used_by_other_asset = Asset.all_objects.filter(storage_key=relative_path).exclude(id__in=asset_ids).exists()
        if still_used_by_entry or still_used_by_other_asset:
            continue
        target_path = get_upload_root() / Path(relative_path)
        if target_path.exists() and target_path.is_file():
            target_path.unlink()
            removed_disk_files += 1
        # 记录该路径对应的 asset_id，后续强制清理
        matched_asset_id = path_to_asset_id.get(relative_path)
        if matched_asset_id:
            deleted_asset_ids.add(matched_asset_id)

    for asset_id in asset_ids:
        if asset_id in deleted_asset_ids:
            # 物理文件已被删除，强制清理所有残留引用及 Asset 记录
            AssetReference.all_objects.filter(asset_id=asset_id).hard_delete()
            Asset.all_objects.filter(id=asset_id).hard_delete()
        else:
            # 物理文件仍存在（被其他引用占用），无引用时才清理 Asset
            if not AssetReference.all_objects.filter(asset_id=asset_id).exists():
                Asset.all_objects.filter(id=asset_id).hard_delete()

    return {
        "removed_db_files": removed_db_files,
        "removed_db_dirs": removed_db_dirs,
        "removed_disk_files": removed_disk_files,
    }


def reset_system_resource_center(*, acting_user) -> dict:
    if not acting_user.is_superuser:
        raise PermissionDenied("当前无权重置系统资源")

    root_entries = list(
        UploadedFile.all_objects.filter(parent_id__isnull=True).order_by("-is_dir", "-id")
    )

    removed_db_files = 0
    removed_db_dirs = 0
    removed_disk_files = 0
    for entry in root_entries:
        result = hard_delete_uploaded_entry(entry)
        removed_db_files += int(result.get("removed_db_files", 0) or 0)
        removed_db_dirs += int(result.get("removed_db_dirs", 0) or 0)
        removed_disk_files += int(result.get("removed_disk_files", 0) or 0)

    return {
        "detail": "系统资源已归零",
        "removed_db_files": removed_db_files,
        "removed_db_dirs": removed_db_dirs,
        "removed_disk_files": removed_disk_files,
    }


def save_chat_attachment_to_resource(*, user, source_asset_reference_id: int, parent_id: int | None, display_name: str = "") -> UploadedFile:
    parent = get_parent_dir(user, parent_id)
    if parent_id is not None and parent is None:
        raise ValidationError({"detail": "目录不存在"})
    if parent is not None and is_recycle_bin_folder(parent):
        raise ValidationError({"detail": "资源中心目录不能选择回收站"})

    source_reference = AssetReference.objects.select_related("asset").filter(id=source_asset_reference_id, deleted_at__isnull=True).first()
    if source_reference is None or source_reference.asset is None:
        raise ValidationError({"detail": "聊天附件不存在"})
    ensure_reference_can_be_saved_to_resource(user, source_reference)

    resolved_display_name = display_name.strip() or source_reference.display_name or source_reference.asset.original_name or "附件"
    if "/" in resolved_display_name or "\\" in resolved_display_name:
        raise ValidationError({"detail": "文件名不合法"})

    source_relative_path = source_reference.relative_path_cache or source_reference.asset.storage_key or ""
    existing, restored_from_recycle, restored_from_parent_id = resolve_existing_upload_file(
        user,
        source_reference.asset.file_md5 or "",
        parent,
        resolved_display_name,
        relative_path=source_relative_path,
        business="",
    )
    if existing is not None:
        if restored_from_recycle:
            notify_resource_entry_moved(
                owner_user_id=existing.created_by_id,
                entry_id=existing.id,
                entry_kind='directory' if existing.is_dir else 'file',
                entry=existing,
                from_parent_id=restored_from_parent_id,
                to_parent_id=existing.parent_id,
                updated_at=existing.updated_at,
            )
        return existing

    relative_path = source_relative_path
    stored_name = Path(relative_path).name or build_stored_name(resolved_display_name)
    entry = UploadedFile.objects.create(
        created_by=user,
        parent=parent,
        is_dir=False,
        business="",
        display_name=resolved_display_name,
        stored_name=stored_name,
        file_md5=source_reference.asset.file_md5 or "",
        file_size=source_reference.asset.file_size,
        relative_path=relative_path,
    )
    notify_resource_entry_created(entry)
    return entry


def delete_resource_entry(*, acting_user, entry_id: int, system_scope: bool) -> dict:
    entry_queryset = UploadedFile.objects.filter(id=entry_id)
    if not system_scope:
        entry_queryset = entry_queryset.filter(created_by=acting_user)
    entry = entry_queryset.first()
    if not entry:
        raise ValidationError({"detail": "文件或目录不存在"})
    if is_recycle_bin_folder(entry):
        raise ValidationError({"detail": "回收站目录不可删除"})
    if system_scope and entry.created_by_id != acting_user.id and entry_is_within_recycle_bin_tree(entry):
        raise PermissionDenied("系统资源中不能删除其他用户回收站内的文件或目录")

    owner_user_id = entry.created_by_id
    original_parent_id = entry.parent_id

    if system_scope:
        result = {"detail": "已彻底删除", **hard_delete_uploaded_entry(entry)}
        notify_resource_entry_deleted(
            owner_user_id=owner_user_id,
            entry_id=entry.id,
            parent_id=original_parent_id,
            deleted_mode="hard",
            updated_at=timezone.now(),
        )
        return result

    if entry.recycled_at is not None:
        raise ValidationError({"detail": "该文件已在回收站，请前往回收站还原"})

    moved_count = move_entry_to_recycle_bin(entry)
    entry.refresh_from_db(fields=["updated_at"])
    notify_resource_entry_deleted(
        owner_user_id=owner_user_id,
        entry_id=entry.id,
        parent_id=original_parent_id,
        deleted_mode="recycle",
        updated_at=entry.updated_at,
    )
    return {"detail": "已移入回收站", "moved_count": moved_count}


def rename_resource_entry(*, user, entry_id: int, new_name: str) -> UploadedFile:
    normalized_name = str(new_name).strip()
    if not normalized_name:
        raise ValidationError({"detail": "参数不合法"})
    if "/" in normalized_name or "\\" in normalized_name:
        raise ValidationError({"detail": "名称不合法"})
    if is_reserved_system_folder_name(normalized_name):
        raise ValidationError({"detail": '“回收站”是系统保留目录名称，请使用其他名称'})

    entry = UploadedFile.objects.filter(id=entry_id, created_by=user).first()
    if not entry:
        raise ValidationError({"detail": "文件或目录不存在"})
    if is_recycle_bin_folder(entry):
        raise ValidationError({"detail": "回收站目录不可重命名"})

    conflict = UploadedFile.objects.filter(
        created_by=user,
        parent=entry.parent,
        display_name=normalized_name,
    ).exclude(id=entry.id)
    if conflict.exists():
        raise ValidationError({"detail": "同名文件或文件夹已存在"})

    entry.display_name = normalized_name
    entry.save(update_fields=["display_name", "updated_at"])
    notify_resource_entry_updated(entry, previous_parent_id=entry.parent_id)
    return entry


def restore_resource_entry(*, user, entry_id: int) -> UploadedFile:
    entry = UploadedFile.objects.filter(id=entry_id, created_by=user).first()
    if not entry:
        raise ValidationError({"detail": "文件或目录不存在"})

    try:
        from_parent_id = entry.parent_id
        restored = restore_entry_from_recycle_bin(entry)
        notify_resource_entry_moved(
            owner_user_id=restored.created_by_id,
            entry_id=restored.id,
            entry_kind='directory' if restored.is_dir else 'file',
            entry=restored,
            from_parent_id=from_parent_id,
            to_parent_id=restored.parent_id,
            updated_at=restored.updated_at,
        )
        return restored
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
