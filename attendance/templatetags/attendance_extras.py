from django import template
from datetime import date
from attendance.models import AttendanceActivity

register = template.Library()

@register.filter
def get_latest_out_scan(attendance):
    """
    Get the latest out scan time for an attendance record.
    For current day: show latest scan time from request_description (real-time)
    For past days: show official check-out time from Attendance
    """
    if not attendance:
        return "-"
    
    # Check if it's current day
    if attendance.attendance_date == date.today():
        # For current day, try to get latest scan time from request_description
        if attendance.request_description and attendance.request_description.startswith("Latest scan:"):
            # Extract time from "Latest scan: HH:MM:SS" and convert to 12-hour format
            scan_time_str = attendance.request_description.replace("Latest scan: ", "")
            try:
                from datetime import datetime
                # Parse the 24-hour time and convert to 12-hour format
                time_obj = datetime.strptime(scan_time_str, '%H:%M:%S').time()
                return time_obj.strftime('%I:%M:%S %p')
            except:
                return scan_time_str
        else:
            # Fallback to AttendanceActivity
            latest_activity = AttendanceActivity.objects.filter(
                employee_id=attendance.employee_id,
                attendance_date=attendance.attendance_date
            ).order_by('-id').first()
            
            if latest_activity:
                return latest_activity.clock_in.strftime('%I:%M:%S %p')
            else:
                return "-"
    else:
        # For past days, show the official check-out time
        if attendance.attendance_clock_out:
            return attendance.attendance_clock_out.strftime('%I:%M:%S %p')
        else:
            return "-"

@register.filter
def get_check_out_display(attendance):
    """
    Get the check-out time display for an attendance record.
    Database stores NULL for current day, actual time for past days
    """
    if not attendance:
        return "-"
    
    # Database already stores NULL for current day, actual time for past days
    if attendance.attendance_clock_out:
        return attendance.attendance_clock_out.strftime('%I:%M:%S %p')
    else:
        return "None"
