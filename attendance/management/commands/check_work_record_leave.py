"""
Management command to check why 'L' (Leave) appears for an employee on a specific date.
Usage: python manage.py check_work_record_leave --employee EMP0010 --date 2026-01-19
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date
from attendance.models import WorkRecords
from employee.models import Employee


class Command(BaseCommand):
    help = 'Check why L (Leave) appears for an employee on a specific date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--employee',
            type=str,
            help='Employee ID (e.g., EMP0010) or employee name',
            required=True
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Date in YYYY-MM-DD format (e.g., 2026-01-19)',
            required=True
        )

    def handle(self, *args, **options):
        employee_id_or_name = options['employee']
        date_str = options['date']
        
        try:
            check_date = date.fromisoformat(date_str)
        except ValueError:
            self.stdout.write(self.style.ERROR(f'Invalid date format: {date_str}. Use YYYY-MM-DD'))
            return
        
        # Find employee
        try:
            if employee_id_or_name.startswith('EMP'):
                employee = Employee.objects.get(employee_id=employee_id_or_name)
            else:
                # Try to find by name
                employee = Employee.objects.filter(
                    employee_first_name__icontains=employee_id_or_name
                ).first()
                if not employee:
                    employee = Employee.objects.get(id=int(employee_id_or_name))
        except Employee.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Employee not found: {employee_id_or_name}'))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error finding employee: {e}'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Work Record Check ==='))
        self.stdout.write(f'Employee: {employee} ({employee.employee_id})')
        self.stdout.write(f'Date: {check_date}\n')
        
        # Get work record
        try:
            work_record = WorkRecords.objects.get(
                employee_id=employee,
                date=check_date
            )
            
            self.stdout.write(self.style.SUCCESS('Work Record Found:'))
            self.stdout.write(f'  - Work Record Type: {work_record.work_record_type}')
            self.stdout.write(f'  - Is Leave Record: {work_record.is_leave_record}')
            self.stdout.write(f'  - Is Attendance Record: {work_record.is_attendance_record}')
            self.stdout.write(f'  - Message: {work_record.message}')
            
            if work_record.leave_request_id:
                leave_request = work_record.leave_request_id
                self.stdout.write(self.style.SUCCESS('\nLeave Request Details:'))
                self.stdout.write(f'  - Leave Request ID: {leave_request.id}')
                self.stdout.write(f'  - Status: {leave_request.status}')
                self.stdout.write(f'  - Leave Type: {leave_request.leave_type_id}')
                self.stdout.write(f'  - Start Date: {leave_request.start_date}')
                self.stdout.write(f'  - End Date: {leave_request.end_date}')
                self.stdout.write(f'  - Requested Days: {leave_request.requested_days}')
                self.stdout.write(f'  - Created By: {leave_request.created_by}')
                self.stdout.write(f'  - Created At: {leave_request.created_at}')
            else:
                self.stdout.write(self.style.WARNING('\nNo leave request linked to this work record'))
            
            if work_record.attendance_id:
                attendance = work_record.attendance_id
                self.stdout.write(self.style.SUCCESS('\nAttendance Record Found:'))
                self.stdout.write(f'  - Attendance ID: {attendance.id}')
                self.stdout.write(f'  - Attendance Date: {attendance.attendance_date}')
                self.stdout.write(f'  - Worked Hours: {attendance.attendance_worked_hour}')
                self.stdout.write(f'  - Validated: {attendance.attendance_validated}')
                if work_record.is_leave_record and work_record.work_record_type == 'HD':
                    self.stdout.write(self.style.WARNING(
                        '\n  Note: This is a "HD" (Holiday/Leave) - employee was on leave but also has attendance.'
                    ))
            
        except WorkRecords.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'No work record found for {employee} on {check_date}'))
            self.stdout.write('This means the cell should be blank or show "A" (Absent) if after joining date.')
            
            # Check if there's a leave request anyway
            if hasattr(employee, 'employee_leave_requests'):
                leave_requests = employee.employee_leave_requests.filter(
                    start_date__lte=check_date,
                    end_date__gte=check_date,
                    status='approved'
                )
                if leave_requests.exists():
                    self.stdout.write(self.style.ERROR(
                        f'\nWARNING: Found {leave_requests.count()} approved leave request(s) covering this date, but no work record exists!'
                    ))
                    for lr in leave_requests:
                        self.stdout.write(f'  - Leave Request ID: {lr.id}, Type: {lr.leave_type_id}, Dates: {lr.start_date} to {lr.end_date}')
        
        # Check all leave requests for this employee around this date
        if hasattr(employee, 'employee_leave_requests'):
            all_leaves = employee.employee_leave_requests.filter(
                start_date__lte=check_date,
                end_date__gte=check_date
            ).order_by('-created_at')
            
            if all_leaves.exists():
                self.stdout.write(self.style.SUCCESS(f'\nAll Leave Requests covering {check_date}:'))
                for lr in all_leaves:
                    status_style = self.style.SUCCESS if lr.status == 'approved' else self.style.WARNING
                    self.stdout.write(status_style(
                        f'  - ID: {lr.id}, Status: {lr.status}, Type: {lr.leave_type_id}, '
                        f'Dates: {lr.start_date} to {lr.end_date}'
                    ))
        
        self.stdout.write('\n')
