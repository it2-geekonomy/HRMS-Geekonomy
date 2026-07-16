from django.urls import path

from ...api_views.crm.views import CRMDashboardView, CRMDepartmentsView

urlpatterns = [
    path("", CRMDashboardView.as_view(), name="api-crm-dashboard"),
    path("departments/", CRMDepartmentsView.as_view(), name="api-crm-departments"),
]
