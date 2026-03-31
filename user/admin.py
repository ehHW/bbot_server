from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from user.models import AuditLog, Permission, Role, User


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
	list_display = ("id", "code", "name", "updated_at")
	search_fields = ("code", "name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "updated_at")
	search_fields = ("name",)
	filter_horizontal = ("permissions",)


@admin.register(User)
class RBACUserAdmin(UserAdmin):
	fieldsets = UserAdmin.fieldsets + (("RBAC", {"fields": ("display_name", "roles")}),)
	list_display = (
		"id",
		"username",
		"display_name",
		"email",
		"is_superuser",
		"is_staff",
		"is_active",
		"last_login",
	)
	search_fields = ("username", "display_name", "email")
	filter_horizontal = ("groups", "user_permissions", "roles")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
	list_display = ("id", "action", "status", "actor", "target_type", "target_id", "created_at")
	search_fields = ("action", "status", "target_type", "target_id", "target_repr", "detail", "actor__username")
	list_filter = ("action", "status", "target_type")
	readonly_fields = (
		"actor",
		"action",
		"target_type",
		"target_id",
		"target_repr",
		"status",
		"detail",
		"metadata",
		"ip_address",
		"user_agent",
		"created_at",
		"updated_at",
		"deleted_at",
	)
