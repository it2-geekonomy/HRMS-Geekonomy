"""
spring_verification/urls.py
"""

from django.urls import path

from spring_verification import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="spring-verification-dashboard"),
    path("candidate-data/", views.candidate_data, name="spring-verification-candidate-data"),
    path("employee/<int:emp_id>/bgv-tab/", views.employee_bgv_tab, name="spring-verification-employee-bgv-tab"),
]
