"""
Django management command to credit accumulated leave after probation period (3 months).

Policy:
- First 3 months: No CL, SL, or EL allowed (probation period)
- After 3 months: Credit leave. EL rules from Jan 1 2026 — 1.25/month only, no lump sum.
  - EL = 1.25 days (first month; scheduler adds 1.25 each month thereafter)
  - CL = 3 days (1 × 3 months)
  - SL = 2 days (0.58 × 3 months, rounded to 2)
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from leave.models import LeaveType, AvailableLeave
from leave.intern_leave import is_intern
from employee.models import Employee, EmployeeWorkInformation


class Command(BaseCommand):
    help = 'Credit accumulated leave for employees who completed 3 months probation period'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()
        
        # Get leave types
        try:
            el_type = LeaveType.objects.get(name="Earned Leave (EL)")
            cl_type = LeaveType.objects.get(name="Casual Leave (CL)")
            sl_type = LeaveType.objects.get(name="Sick Leave (SL)")
        except LeaveType.DoesNotExist as e:
            self.stdout.write(
                self.style.ERROR(f'Required leave type not found: {e}')
            )
            return
        
        # Find employees who completed 3 months probation
        # Probation end date = joining_date + 3 months
        probation_end_date = today - relativedelta(months=3)
        
        employees_to_credit = []
        work_infos = EmployeeWorkInformation.objects.filter(
            date_joining__lte=probation_end_date,
            date_joining__isnull=False
        ).select_related('employee_id')
        
        credited_count = 0
        skipped_count = 0
        error_count = 0
        
        for work_info in work_infos:
            employee = work_info.employee_id
            joining_date = work_info.date_joining
            
            if not joining_date:
                continue
            if is_intern(employee):
                continue
            
            # Calculate probation end date for this employee
            employee_probation_end = joining_date + relativedelta(months=3)
            
            # Only process if probation period has ended
            if today < employee_probation_end:
                continue
            
            # Check if leave has already been credited (check if AvailableLeave exists)
            # We'll use assigned_date to track when it was first credited
            el_exists = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id=el_type
            ).exists()
            cl_exists = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id=cl_type
            ).exists()
            sl_exists = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id=sl_type
            ).exists()
            
            # If all three exist, skip (already credited)
            if el_exists and cl_exists and sl_exists:
                skipped_count += 1
                if not dry_run:
                    self.stdout.write(
                        f'Skipped: {employee.get_full_name()} (already credited)'
                    )
                continue
            
            # EL from Jan 1 2026: 1.25/month only. First credit = 1.25.
            el_days = 1.25
            cl_days = 1 * 3  # 3 days
            sl_days = 2  # 2 days (0.58 × 3 rounded to 2)
            
            employees_to_credit.append({
                'employee': employee,
                'el_days': el_days,
                'cl_days': cl_days,
                'sl_days': sl_days,
                'el_exists': el_exists,
                'cl_exists': cl_exists,
                'sl_exists': sl_exists,
            })
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN MODE ===\n'))
            self.stdout.write(f'Found {len(employees_to_credit)} employee(s) to credit leave:\n')
            for emp_data in employees_to_credit:
                self.stdout.write(
                    f"  - {emp_data['employee'].get_full_name()}: "
                    f"EL={emp_data['el_days']}, CL={emp_data['cl_days']}, SL={emp_data['sl_days']}"
                )
            self.stdout.write(f'\nWould credit leave for {len(employees_to_credit)} employee(s)')
            return
        
        # Credit leave for eligible employees
        with transaction.atomic():
            for emp_data in employees_to_credit:
                employee = emp_data['employee']
                try:
                    # Credit Earned Leave (EL)
                    if not emp_data['el_exists']:
                        el_leave, created = AvailableLeave.objects.get_or_create(
                            employee_id=employee,
                            leave_type_id=el_type,
                            defaults={
                                'available_days': emp_data['el_days'],
                                'assigned_date': today,
                            }
                        )
                        if not created:
                            # If exists but wasn't credited, update it
                            el_leave.available_days = emp_data['el_days']
                            el_leave.assigned_date = today
                            el_leave.save()
                    
                    # Credit Casual Leave (CL)
                    if not emp_data['cl_exists']:
                        cl_leave, created = AvailableLeave.objects.get_or_create(
                            employee_id=employee,
                            leave_type_id=cl_type,
                            defaults={
                                'available_days': emp_data['cl_days'],
                                'assigned_date': today,
                            }
                        )
                        if not created:
                            cl_leave.available_days = emp_data['cl_days']
                            cl_leave.assigned_date = today
                            cl_leave.save()
                    
                    # Credit Sick Leave (SL)
                    if not emp_data['sl_exists']:
                        sl_leave, created = AvailableLeave.objects.get_or_create(
                            employee_id=employee,
                            leave_type_id=sl_type,
                            defaults={
                                'available_days': emp_data['sl_days'],
                                'assigned_date': today,
                            }
                        )
                        if not created:
                            sl_leave.available_days = emp_data['sl_days']
                            sl_leave.assigned_date = today
                            sl_leave.save()
                    
                    credited_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Credited leave for {employee.get_full_name()}: '
                            f'EL={emp_data["el_days"]}, CL={emp_data["cl_days"]}, SL={emp_data["sl_days"]}'
                        )
                    )
                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error crediting leave for {employee.get_full_name()}: {e}'
                        )
                    )
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f'\n=== Summary ===\n'
                f'Credited: {credited_count} employee(s)\n'
                f'Skipped: {skipped_count} employee(s)\n'
                f'Errors: {error_count} employee(s)'
            )
        )
