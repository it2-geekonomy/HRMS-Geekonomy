"""
CRM public API serializers.
Exposes employee summary and list for CRM integration.
"""

from rest_framework import serializers

from base.models import Department
from employee.models import Employee


class CRMEmployeeSerializer(serializers.ModelSerializer):
    """Employee fields for CRM: name, email, phone, alternative_phone, department, job position, joining date, managers, profile_image."""

    name = serializers.SerializerMethodField()
    alternative_phone = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    job_position = serializers.SerializerMethodField()
    employment_type = serializers.SerializerMethodField()
    joining_date = serializers.SerializerMethodField()
    reporting_manager = serializers.SerializerMethodField()
    operation_manager = serializers.SerializerMethodField()
    business_manager = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id",
            "badge_id",
            "name",
            "email",
            "phone",
            "alternative_phone",
            "department",
            "job_position",
            "employment_type",
            "joining_date",
            "reporting_manager",
            "operation_manager",
            "business_manager",
            "is_active",
            "profile_image",
        ]

    def get_name(self, obj):
        parts = [obj.employee_first_name or "", obj.employee_last_name or ""]
        return " ".join(parts).strip() or None

    def get_alternative_phone(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if info and getattr(info, "mobile", None):
            return info.mobile
        return getattr(obj, "emergency_contact", None)

    def get_department(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if info and getattr(info, "department_id", None):
            return getattr(info.department_id, "department", None)
        return None

    def get_job_position(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if info and getattr(info, "job_position_id", None):
            return getattr(info.job_position_id, "job_position", None)
        return None

    def get_employment_type(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if info and getattr(info, "employee_type_id", None):
            return getattr(info.employee_type_id, "employee_type", None)
        return None

    def get_joining_date(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if info and getattr(info, "date_joining", None):
            d = info.date_joining
            return d.isoformat() if d else None
        return None

    def get_reporting_manager(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if not info or not getattr(info, "reporting_manager_id", None):
            return None
        rm = info.reporting_manager_id
        parts = [getattr(rm, "employee_first_name", "") or "", getattr(rm, "employee_last_name", "") or ""]
        return " ".join(parts).strip() or None

    def get_operation_manager(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if not info or not getattr(info, "operation_manager_id", None):
            return None
        om = info.operation_manager_id
        parts = [getattr(om, "employee_first_name", "") or "", getattr(om, "employee_last_name", "") or ""]
        return " ".join(parts).strip() or None

    def get_business_manager(self, obj):
        info = getattr(obj, "employee_work_info", None)
        if not info or not getattr(info, "business_manager_id", None):
            return None
        bm = info.business_manager_id
        parts = [getattr(bm, "employee_first_name", "") or "", getattr(bm, "employee_last_name", "") or ""]
        return " ".join(parts).strip() or None

    def get_profile_image(self, obj):
        if not getattr(obj, "employee_profile", None) or not obj.employee_profile:
            return None
        try:
            url = obj.employee_profile.url
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(url)
            return url
        except Exception:
            return None


class CRMDepartmentSerializer(serializers.ModelSerializer):
    """Department list for CRM: id, name, and teams."""

    name = serializers.CharField(source="department", read_only=True)
    teams = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "teams"]

    def get_teams(self, obj):
        teams = getattr(obj, "department_teams", None)
        if not teams:
            return []
        return [{"id": team.id, "name": team.team_name} for team in teams.filter(is_active=True)]
