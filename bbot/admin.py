from django.contrib import admin

from bbot.models import UploadedFile


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
	list_display = ("id", "display_name", "is_dir", "parent_id", "created_by", "file_size", "deleted_at")
	list_filter = ("is_dir", "created_by", "deleted_at")
	search_fields = ("display_name", "stored_name", "relative_path", "file_md5")
