#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hyself_server.settings")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import django

django.setup()

from django.db import transaction

from user.models import DEFAULT_USER_ROLE_NAME, SUPER_ADMIN_ROLE_NAME, SYSTEM_ADMIN_ROLE_NAME
from user.models import Permission, Role, User
from user.signals import DEFAULT_ROLE_BASELINE_PERMISSION_CODES
from user.signals import SUPER_ADMIN_ONLY_PERMISSION_CODES, ensure_default_permissions_synced


def _upsert_user(*, username: str, password: str, role: Role, is_superuser: bool, is_staff: bool) -> tuple[User, bool]:
    user = User.all_objects.filter(username=username).first()
    created = user is None

    if created:
        user = User.all_objects.create_user(
            username=username,
            password=password,
            display_name=username,
            is_superuser=is_superuser,
            is_staff=is_staff,
            is_active=True,
        )
    else:
        updates: list[str] = []
        if user.deleted_at is not None:
            user.deleted_at = None
            updates.append("deleted_at")
        if not user.is_active:
            user.is_active = True
            updates.append("is_active")
        if user.display_name != username:
            user.display_name = username
            updates.append("display_name")
        if user.is_superuser != is_superuser:
            user.is_superuser = is_superuser
            updates.append("is_superuser")
        if user.is_staff != is_staff:
            user.is_staff = is_staff
            updates.append("is_staff")
        if updates:
            updates.append("updated_at")
            user.save(update_fields=updates)

        user.set_password(password)
        user.save(update_fields=["password"])

    user.roles.set([role])
    return user, created


@transaction.atomic
def init_db() -> None:
    # 1) 同步基础权限与系统内置角色
    ensure_default_permissions_synced()

    # 2) 确保三类基础角色存在并校准权限
    super_admin_role = Role.all_objects.filter(name=SUPER_ADMIN_ROLE_NAME).first()
    if super_admin_role is None:
        super_admin_role = Role.all_objects.create(
            name=SUPER_ADMIN_ROLE_NAME,
            description="系统内置超级管理员角色，默认拥有全部权限",
        )
    super_admin_role.permissions.set(Permission.objects.all())

    system_admin_role = Role.all_objects.filter(name=SYSTEM_ADMIN_ROLE_NAME).first()
    if system_admin_role is None:
        system_admin_role = Role.all_objects.create(
            name=SYSTEM_ADMIN_ROLE_NAME,
            description="系统管理员，拥有除超级管理员专属能力外的后台与业务权限",
        )
    system_admin_role.permissions.set(
        Permission.objects.exclude(code__in=SUPER_ADMIN_ONLY_PERMISSION_CODES),
    )

    default_user_role = Role.all_objects.filter(name=DEFAULT_USER_ROLE_NAME).first()
    if default_user_role is None:
        default_user_role = Role.all_objects.create(
            name=DEFAULT_USER_ROLE_NAME,
            description="系统默认基础角色",
        )
    default_user_role.permissions.set(
        Permission.objects.filter(code__in=DEFAULT_ROLE_BASELINE_PERMISSION_CODES),
    )

    # 3) 创建基础用户
    users_to_create = [
        {
            "username": "superadmin",
            "password": "sa0000",
            "role": super_admin_role,
            "is_superuser": True,
            "is_staff": True,
        },
        {
            "username": "admin",
            "password": "admin1111",
            "role": system_admin_role,
            "is_superuser": False,
            "is_staff": True,
        },
    ]

    for n in range(1, 6):
        users_to_create.append(
            {
                "username": f"user0{n}",
                "password": f"{n}{n}{n}u{n}{n}{n}",
                "role": default_user_role,
                "is_superuser": False,
                "is_staff": False,
            }
        )

    created_count = 0
    updated_count = 0
    for item in users_to_create:
        _, created = _upsert_user(**item)
        if created:
            created_count += 1
        else:
            updated_count += 1

    print("初始化完成")
    print(f"权限总数: {Permission.objects.count()}")
    print(f"角色总数: {Role.objects.filter(deleted_at__isnull=True).count()}")
    print(f"用户总数: {User.objects.filter(deleted_at__isnull=True).count()}")
    print(f"本次创建用户: {created_count}")
    print(f"本次更新用户: {updated_count}")


if __name__ == "__main__":
    init_db()
