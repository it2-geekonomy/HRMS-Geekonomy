from django.urls import include, path

urlpatterns = [
    path("auth/", include("horilla_api.api_urls.auth.urls")),
    path("asset/", include("horilla_api.api_urls.asset.urls")),
    path("base/", include("horilla_api.api_urls.base.urls")),
    path("crm/", include("horilla_api.api_urls.crm.urls")),
    path("employee/", include("horilla_api.api_urls.employee.urls")),
    path("notifications/", include("horilla_api.api_urls.notifications.urls")),
    path("payroll/", include("horilla_api.api_urls.payroll.urls")),
    path("attendance/", include("horilla_api.api_urls.attendance.urls")),
    path("leave/", include("horilla_api.api_urls.leave.urls")),
    path("slack/", include("horilla_api.api_urls.slack.urls")),
    path("recruitment/", include("horilla_api.api_urls.recruitment.urls")),
]
