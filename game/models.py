from django.conf import settings
from django.db import models
from django.utils import timezone

from utils.soft_delete import SoftDeleteModel


class GameBestRecord(SoftDeleteModel):
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="game_best_records",
		verbose_name="所属用户",
	)
	game_code = models.CharField(max_length=64, db_index=True, verbose_name="游戏编码")
	game_name = models.CharField(max_length=100, blank=True, default="", verbose_name="游戏名称")
	best_score = models.PositiveIntegerField(default=0, verbose_name="最高分")
	board_snapshot = models.JSONField(default=list, blank=True, verbose_name="结束棋盘快照")
	finished_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="达成时间")

	class Meta:
		db_table = "game_best_record"
		ordering = ["-best_score", "finished_at", "id"]
		constraints = [
			models.UniqueConstraint(fields=["user", "game_code"], name="uniq_game_best_record_user_game"),
		]
		indexes = [
			models.Index(fields=["game_code", "-best_score", "finished_at"]),
		]

	def __str__(self) -> str:
		return f"{self.user_id}:{self.game_code}:{self.best_score}"
