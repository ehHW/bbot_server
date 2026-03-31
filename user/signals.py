from django.apps import apps
from django.db.models.signals import post_save
from django.db.models.signals import post_migrate
from django.dispatch import receiver

DEFAULT_PERMISSIONS = [
    ("user.view_user", "查看用户"),
    ("user.create_user", "创建用户"),
    ("user.update_user", "修改用户"),
    ("user.delete_user", "删除用户"),
    ("user.view_role", "查看角色"),
    ("user.create_role", "创建角色"),
    ("user.update_role", "修改角色"),
    ("user.delete_role", "删除角色"),
    ("user.view_permission", "查看权限"),
    ("user.create_permission", "创建权限"),
    ("user.update_permission", "修改权限"),
    ("user.delete_permission", "删除权限"),
]

SUPER_ADMIN_ROLE_NAME = "超级管理员"


@receiver(post_migrate)
def bootstrap_default_permissions(sender, **kwargs):
    if getattr(sender, "name", "") != "user":
        return

    Permission = apps.get_model("user", "Permission")
    Role = apps.get_model("user", "Role")
    User = apps.get_model("user", "User")

    for code, name in DEFAULT_PERMISSIONS:
        permission = Permission.all_objects.filter(code=code).first()
        if permission is None:
            Permission.all_objects.create(code=code, name=name)
        else:
            updates = []
            if permission.name != name:
                permission.name = name
                updates.append("name")
            if permission.deleted_at is not None:
                permission.deleted_at = None
                updates.append("deleted_at")
            if updates:
                updates.append("updated_at")
                permission.save(update_fields=updates)

    super_admin_role = Role.all_objects.filter(name=SUPER_ADMIN_ROLE_NAME).first()
    if super_admin_role is None:
        super_admin_role = Role.all_objects.create(
            name=SUPER_ADMIN_ROLE_NAME,
            description="系统内置超级管理员角色，默认拥有全部权限",
        )
    elif super_admin_role.deleted_at is not None:
        super_admin_role.deleted_at = None
        super_admin_role.save(update_fields=["deleted_at", "updated_at"])
    super_admin_role.permissions.set(Permission.objects.all())

    for user in User.objects.filter(is_superuser=True):
        user.roles.add(super_admin_role)


@receiver(post_save)
def bind_super_admin_role(sender, instance, created, **kwargs):
    sender_meta = getattr(sender, "_meta", None)
    if not sender_meta:
        return
    if sender_meta.app_label != "user" or sender_meta.model_name != "user":
        return
    if not getattr(instance, "is_superuser", False):
        return

    Role = apps.get_model("user", "Role")
    Permission = apps.get_model("user", "Permission")
    role = Role.all_objects.filter(name=SUPER_ADMIN_ROLE_NAME).first()
    if role is None:
        role = Role.all_objects.create(
            name=SUPER_ADMIN_ROLE_NAME,
            description="系统内置超级管理员角色，默认拥有全部权限",
        )
    elif role.deleted_at is not None:
        role.deleted_at = None
        role.save(update_fields=["deleted_at", "updated_at"])
    if role.permissions.count() != Permission.objects.count():
        role.permissions.set(Permission.objects.all())
    instance.roles.add(role)


@receiver(post_save)
def bind_new_permission_to_super_admin(sender, instance, created, **kwargs):
    sender_meta = getattr(sender, "_meta", None)
    if not sender_meta:
        return
    if sender_meta.app_label != "user" or sender_meta.model_name != "permission":
        return
    if not created:
        return

    Role = apps.get_model("user", "Role")
    role = Role.all_objects.filter(name=SUPER_ADMIN_ROLE_NAME).first()
    if role is None:
        role = Role.all_objects.create(
            name=SUPER_ADMIN_ROLE_NAME,
            description="系统内置超级管理员角色，默认拥有全部权限",
        )
    elif role.deleted_at is not None:
        role.deleted_at = None
        role.save(update_fields=["deleted_at", "updated_at"])
    role.permissions.add(instance)
