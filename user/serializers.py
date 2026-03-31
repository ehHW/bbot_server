from django.contrib.auth import authenticate
from django.conf import settings
from rest_framework import serializers

from user.models import Permission, Role, User


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True)

    def validate(self, attrs):
        raw_username = str(attrs.get("username", "")).strip()
        target_user = User.objects.filter(username=raw_username).first()
        if target_user and not target_user.is_active:
            raise serializers.ValidationError("此账号已被停用，请联系管理员")

        user = authenticate(username=raw_username, password=attrs["password"])
        if not user:
            raise serializers.ValidationError("用户名或密码错误")
        if not user.is_active:
            raise serializers.ValidationError("此账号已被停用，请联系管理员")
        attrs["user"] = user
        return attrs


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "code", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class RoleSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        source="permissions", queryset=Permission.objects.all(), many=True, write_only=True, required=False
    )
    permissions = PermissionSerializer(many=True, read_only=True)

    def get_fields(self):
        fields = super().get_fields()
        instance = self.instance if isinstance(self.instance, Role) else None
        if instance and instance.is_super_admin_role():
            for field_name in ["name", "description", "permission_ids"]:
                fields[field_name].read_only = True
        return fields

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "description",
            "permission_ids",
            "permissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    role_ids = serializers.PrimaryKeyRelatedField(
        source="roles", queryset=Role.objects.all(), many=True, write_only=True, required=False
    )
    roles = RoleSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["is_superuser"].read_only = True
        fields["is_staff"].read_only = True

        instance = self.instance if isinstance(self.instance, User) else None
        if instance is not None:
            fields["username"].read_only = True
            if instance.has_super_admin_role():
                for field_name in ["email", "display_name", "avatar", "phone_number", "is_active", "role_ids"]:
                    fields[field_name].read_only = True
        return fields

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "password",
            "email",
            "display_name",
            "avatar",
            "phone_number",
            "is_active",
            "is_staff",
            "is_superuser",
            "roles",
            "role_ids",
            "last_login",
            "created_at",
            "updated_at",
            "deleted_at",
        ]
        read_only_fields = ["id", "last_login", "created_at", "updated_at", "deleted_at", "is_superuser", "is_staff"]

    def _validate_roles(self, roles):
        if any(role.is_super_admin_role() for role in roles):
            raise serializers.ValidationError({"role_ids": "禁止分配超级管理员角色"})

    def create(self, validated_data):
        roles = validated_data.pop("roles", [])
        self._validate_roles(roles)
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "创建用户时必须提供密码"})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        if roles:
            user.roles.set(roles)
        return user

    def update(self, instance, validated_data):
        roles = validated_data.pop("roles", None)
        password = validated_data.pop("password", None)
        if roles is not None:
            self._validate_roles(roles)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if roles is not None:
            instance.roles.set(roles)
        return instance


class ProfileSerializer(serializers.ModelSerializer):
    roles = RoleSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "display_name",
            "avatar",
            "phone_number",
            "is_superuser",
            "roles",
            "created_at",
            "updated_at",
            "deleted_at",
        ]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "display_name", "avatar", "phone_number"]

    def validate_avatar(self, value):
        avatar = str(value or "").strip()
        if not avatar:
            return ""

        media_prefix = settings.MEDIA_URL.rstrip("/") + "/"
        if not avatar.startswith(media_prefix):
            raise serializers.ValidationError("头像地址不合法")
        if "/avatars/" not in avatar:
            raise serializers.ValidationError("头像地址必须来自头像上传目录")
        if ".." in avatar:
            raise serializers.ValidationError("头像地址不合法")
        if len(avatar) > 500:
            raise serializers.ValidationError("头像地址过长")
        return avatar

    def update(self, instance, validated_data):
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save(update_fields=[*validated_data.keys(), "updated_at"])
        return instance
