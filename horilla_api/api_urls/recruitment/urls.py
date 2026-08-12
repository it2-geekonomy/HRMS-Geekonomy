from django.urls import path

from ...api_views.recruitment.views import ClosersFellowshipSubmitView

urlpatterns = [
    path(
        "closers-fellowship/",
        ClosersFellowshipSubmitView.as_view(),
        name="api-closers-fellowship-submit",
    ),
]
