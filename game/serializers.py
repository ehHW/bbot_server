from rest_framework import serializers

from game.models import GameBestRecord


class GameBestRecordSerializer(serializers.ModelSerializer):
	user_id = serializers.IntegerField(source="user.id", read_only=True)
	username = serializers.CharField(source="user.username", read_only=True)
	display_name = serializers.CharField(source="user.display_name", read_only=True)
	avatar = serializers.CharField(source="user.avatar", read_only=True)

	class Meta:
		model = GameBestRecord
		fields = [
			"id",
			"user_id",
			"username",
			"display_name",
			"avatar",
			"game_code",
			"game_name",
			"best_score",
			"board_snapshot",
			"finished_at",
		]


class SubmitBestRecordSerializer(serializers.Serializer):
	game_code = serializers.CharField(max_length=64)
	game_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
	score = serializers.IntegerField(min_value=0)
	board_snapshot = serializers.ListField(
		child=serializers.ListField(child=serializers.IntegerField(min_value=0), allow_empty=True),
		required=False,
		default=list,
	)

	def validate_game_code(self, value: str) -> str:
		return value.strip().lower()