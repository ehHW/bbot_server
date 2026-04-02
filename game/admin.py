from django.contrib import admin

from game.models import GameBestRecord


@admin.register(GameBestRecord)
class GameBestRecordAdmin(admin.ModelAdmin):
	list_display = ("id", "game_code", "user", "best_score", "finished_at", "updated_at")
	search_fields = ("game_code", "game_name", "user__username", "user__display_name")
	list_filter = ("game_code", "finished_at")
