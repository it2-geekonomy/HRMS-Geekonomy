"""
Management command to fix leave balances for existing employees.

EL rules start from Jan 1, 2026:
- No pre-2026 accumulation. Employees not in probation get 1.25 EL per month from Jan 2026.
- Accrual = 1.25 × (months from Jan 2026 to current), cap 30, minus approved EL taken.

CL/SL: yearly reset (12 / 7 days) from Jan 1 each year.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from leave.models import LeaveType, AvailableLeave, LeaveRequest
from employee.models import Employee, EmployeeWorkInformation
from leave.intern_leave import is_intern, intern_sl_balance, ensure_intern_sl_available_leave

# EL rules apply from this date. No accumulation before this.
EL_EPOCH_DATE = date(2026, 1, 1)


class Command(BaseCommand):
    help = 'Fix leave balances for existing employees based on joining date and leave taken'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--employee-id',
            type=int,
            help='Fix balances for a specific employee only',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        employee_id = options.get('employee_id')
        today = timezone.now().date()
        
        # Get leave types
        try:
            el_type = LeaveType.objects.get(name="Earned Leave (EL)")
            cl_type = LeaveType.objects.get(name="Casual Leave (CL)")
            sl_type = LeaveType.objects.get(name="Sick Leave (SL)")
            isl_type = LeaveType.objects.get(name="Intern Sick Leave (ISL)")
        except LeaveType.DoesNotExist as e:
            self.stdout.write(
                self.style.ERROR(f'Required leave type not found: {e}. Run setup_new_leave_types.')
            )
            return
        
        # Get employees to process
        if employee_id:
            employees = Employee.objects.filter(id=employee_id)
        else:
            employees = Employee.objects.all()
        
        fixed_count = 0
        error_count = 0
        
        for employee in employees:
            try:
                work_info = EmployeeWorkInformation.objects.filter(
                    employee_id=employee
                ).first()
                
                if not work_info or not work_info.date_joining:
                    continue
                
                joining_date = work_info.date_joining
                probation_end_date = joining_date + relativedelta(months=3)
                
                # --- Interns: 1 ISL per 3 months, no CL/EL/SL ---
                if is_intern(employee):
                    balance, block_start, block_end = intern_sl_balance(employee)
                    isl_leave = ensure_intern_sl_available_leave(
                        employee, isl_type, balance, today
                    )
                    block_range = f"{block_start} to {block_end}" if block_start and block_end else "-"
                    if not dry_run:
                        with transaction.atomic():
                            isl_leave.save()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Fixed intern ISL for {employee.get_full_name()}: '
                                f'{isl_leave.available_days:.2f} (1 per 3 months, block ~{block_range})'
                            )
                        )
                    else:
                        self.stdout.write(
                            f'Would fix intern ISL for {employee.get_full_name()}: {balance:.2f}'
                        )
                    fixed_count += 1
                    continue
                
                # Skip if still in probation (full-time, not intern)
                if today < probation_end_date:
                    continue
                
                # EL rules from Jan 1, 2026 only. Accrual start = later of epoch or probation end.
                accrual_start = max(EL_EPOCH_DATE, probation_end_date)
                # Full months from accrual-start month to current month (inclusive)
                el_months = (today.year - accrual_start.year) * 12 + (today.month - accrual_start.month) + 1
                el_months = max(0, el_months)
                
                # Fix EL balance: 1.25 per month from accrual start, no pre-epoch accumulation
                el_leave, _ = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=el_type,
                    defaults={'available_days': 0, 'assigned_date': accrual_start}
                )
                el_leave.assigned_date = accrual_start
                
                total_el_should_be = 1.25 * el_months
                approved_el_requests = LeaveRequest.objects.filter(
                    employee_id=employee,
                    leave_type_id=el_type,
                    status='approved'
                ).aggregate(total=Sum('requested_days'))
                el_taken = approved_el_requests['total'] or 0
                
                max_el = el_type.carryforward_max or 30
                el_balance = min(total_el_should_be - el_taken, max_el)
                el_balance = max(0.0, el_balance)
                
                # available_days = this month's 1.25 (or balance if < 1.25); rest = carryforward
                if el_balance <= el_type.total_days:
                    el_leave.available_days = el_balance
                    el_leave.carryforward_days = 0
                else:
                    el_leave.available_days = el_type.total_days
                    el_leave.carryforward_days = min(
                        el_balance - el_type.total_days,
                        max_el - float(el_type.total_days)
                    )
                
                # Fix CL balance (yearly reset)
                cl_leave, _ = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=cl_type,
                    defaults={'available_days': 0, 'assigned_date': probation_end_date}
                )
                
                # CL: 12 days/year, reset Jan 1. From Jan 1 2026, use 12 for full years.
                current_year = today.year
                if current_year >= EL_EPOCH_DATE.year:
                    cl_should_be = 12.0
                else:
                    cl_should_be = 0.0
                
                # Get approved CL requests for current year
                approved_cl_requests = LeaveRequest.objects.filter(
                    employee_id=employee,
                    leave_type_id=cl_type,
                    status='approved',
                    start_date__year=current_year
                ).aggregate(total=Sum('requested_days'))
                cl_taken = approved_cl_requests['total'] or 0
                
                cl_balance = max(0, cl_should_be - cl_taken)
                cl_leave.available_days = cl_balance
                cl_leave.carryforward_days = 0
                
                # Fix SL balance (yearly reset)
                sl_leave, _ = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=sl_type,
                    defaults={'available_days': 0, 'assigned_date': probation_end_date}
                )
                
                # SL: 7 days/year, reset Jan 1. From Jan 1 2026, use 7.
                if current_year >= EL_EPOCH_DATE.year:
                    sl_should_be = 7.0
                else:
                    sl_should_be = 0.0
                
                # Get approved SL requests for current year
                approved_sl_requests = LeaveRequest.objects.filter(
                    employee_id=employee,
                    leave_type_id=sl_type,
                    status='approved',
                    start_date__year=current_year
                ).aggregate(total=Sum('requested_days'))
                sl_taken = approved_sl_requests['total'] or 0
                
                sl_balance = max(0, sl_should_be - sl_taken)
                sl_leave.available_days = sl_balance
                sl_leave.carryforward_days = 0
                
                if not dry_run:
                    with transaction.atomic():
                        el_leave.save()
                        cl_leave.save()
                        sl_leave.save()
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Fixed balances for {employee.get_full_name()}:\n'
                            f'  EL: {el_leave.available_days:.2f} available (+ {el_leave.carryforward_days:.2f} carryforward) '
                            f'(taken: {el_taken:.2f}, should be: {total_el_should_be:.2f})\n'
                            f'  CL: {cl_leave.available_days:.2f} available (taken: {cl_taken:.2f}, should be: {cl_should_be:.2f})\n'
                            f'  SL: {sl_leave.available_days:.2f} available (taken: {sl_taken:.2f}, should be: {sl_should_be:.2f})'
                        )
                    )
                else:
                    self.stdout.write(
                        f'Would fix balances for {employee.get_full_name()}:\n'
                        f'  EL: {el_balance:.2f} (taken: {el_taken:.2f}, should be: {total_el_should_be:.2f})\n'
                        f'  CL: {cl_balance:.2f} (taken: {cl_taken:.2f}, should be: {cl_should_be:.2f})\n'
                        f'  SL: {sl_balance:.2f} (taken: {sl_taken:.2f}, should be: {sl_should_be:.2f})'
                    )
                
                fixed_count += 1
                
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'Error fixing balances for {employee.get_full_name()}: {e}'
                    )
                )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN MODE ===\n'))
            self.stdout.write(f'Would fix balances for {fixed_count} employee(s)')
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n=== Summary ===\n'
                    f'Fixed: {fixed_count} employee(s)\n'
                    f'Errors: {error_count} employee(s)'
                )
            )
