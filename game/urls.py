from django.urls import path

from game.views import leaderboard_view, my_best_record_view, submit_best_record_view

app_name = "game"

urlpatterns = [
	path("leaderboard/", leaderboard_view, name="leaderboard"),
	path("records/my-best/", my_best_record_view, name="my_best_record"),
	path("records/submit-best/", submit_best_record_view, name="submit_best_record"),
]