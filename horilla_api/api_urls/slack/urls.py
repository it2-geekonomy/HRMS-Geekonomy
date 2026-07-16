from django.urls import path

from ...api_views.slack.views import SlackEventsView

urlpatterns = [
    path("events/", SlackEventsView.as_view()),
]
