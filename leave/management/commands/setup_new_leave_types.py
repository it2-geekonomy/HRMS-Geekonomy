"""
Django management command to setup new leave types:
- Casual Leave (CL)
- Sick Leave (SL)  
- Earned Leave (EL)
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from leave.models import LeaveType
from base.models import Company


class Command(BaseCommand):
    help = 'Setup new leave types: CL, SL, EL with proper configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Replace existing leave types (PL, ML, UL) with new ones',
        )

    def handle(self, *args, **options):
        replace = options['replace']
        
        # Get default company (or first company)
        default_company = Company.objects.first()
        if not default_company:
            self.stdout.write(self.style.ERROR('No company found. Please create a company first.'))
            return
        
        # Get or create Casual Leave (CL)
        with transaction.atomic():
            try:
                cl = LeaveType.objects.get(name="Casual Leave (CL)")
                created = False
            except LeaveType.DoesNotExist:
                cl = LeaveType()
                cl.name = "Casual Leave (CL)"
                created = True
            
            # Set all fields
            cl.company_id = default_company
            cl.payment = 'paid'
            cl.count = 12
            cl.period_in = 'year'
            cl.total_days = 12
            cl.limit_leave = True
            cl.reset = True
            cl.reset_based = 'yearly'
            cl.reset_month = '1'  # January
            cl.reset_day = '1'  # 1st of January
            cl.carryforward_type = 'no carryforward'
            cl.carryforward_max = None
            cl.carryforward_expire_in = None
            cl.carryforward_expire_period = None
            cl.require_approval = 'yes'
            cl.require_attachment = 'no'
            cl.exclude_company_leave = 'no'
            cl.exclude_holiday = 'no'
            
            # Use update() for existing, save() for new (but ensure company_id is set)
            if not created:
                LeaveType.objects.filter(id=cl.id).update(
                    company_id=default_company,
                    payment='paid',
                    count=12,
                    period_in='year',
                    total_days=12,
                    limit_leave=True,
                    reset=True,
                    reset_based='yearly',
                    reset_month='1',
                    reset_day='1',
                    carryforward_type='no carryforward',
                    carryforward_max=None,
                    carryforward_expire_in=None,
                    carryforward_expire_period=None,
                    require_approval='yes',
                    require_attachment='no',
                    exclude_company_leave='no',
                    exclude_holiday='no',
                )
                self.stdout.write(self.style.SUCCESS('Updated: Casual Leave (CL)'))
            else:
                # For new records, set created_at before save to avoid None error
                if not cl.created_at:
                    cl.created_at = timezone.now()
                cl.save()  # New record - company_id is set, so save() should work
                self.stdout.write(self.style.SUCCESS('Created: Casual Leave (CL)'))
        
        # Get or create Sick Leave (SL)
        with transaction.atomic():
            try:
                sl = LeaveType.objects.get(name="Sick Leave (SL)")
                created = False
            except LeaveType.DoesNotExist:
                sl = LeaveType()
                sl.name = "Sick Leave (SL)"
                created = True
            
            # Set all fields
            sl.company_id = default_company
            sl.payment = 'paid'
            sl.count = 7
            sl.period_in = 'year'
            sl.total_days = 7
            sl.limit_leave = True
            sl.reset = True
            sl.reset_based = 'yearly'
            sl.reset_month = '1'  # January
            sl.reset_day = '1'  # 1st of January
            sl.carryforward_type = 'no carryforward'  # Can be changed to 'carryforward' if policy allows
            sl.carryforward_max = None
            sl.carryforward_expire_in = None
            sl.carryforward_expire_period = None
            sl.require_approval = 'yes'
            sl.require_attachment = 'no'  # Not always required - only for requests > 2 days (handled in validation)
            sl.exclude_company_leave = 'no'
            sl.exclude_holiday = 'no'
            
            if not created:
                LeaveType.objects.filter(id=sl.id).update(
                    company_id=default_company,
                    payment='paid',
                    count=7,
                    period_in='year',
                    total_days=7,
                    limit_leave=True,
                    reset=True,
                    reset_based='yearly',
                    reset_month='1',
                    reset_day='1',
                    carryforward_type='no carryforward',
                    carryforward_max=None,
                    carryforward_expire_in=None,
                    carryforward_expire_period=None,
                    require_approval='yes',
                    require_attachment='no',
                    exclude_company_leave='no',
                    exclude_holiday='no',
                )
                self.stdout.write(self.style.SUCCESS('Updated: Sick Leave (SL)'))
            else:
                if not sl.created_at:
                    sl.created_at = timezone.now()
                sl.save()
                self.stdout.write(self.style.SUCCESS('Created: Sick Leave (SL)'))
        
        # Get or create Earned Leave (EL)
        # Note: Monthly accrual (1.25 days/month) requires monthly reset
        # Accumulation limit (30 days) and 3-year expiry need custom logic
        with transaction.atomic():
            try:
                el = LeaveType.objects.get(name="Earned Leave (EL)")
                created = False
            except LeaveType.DoesNotExist:
                el = LeaveType()
                el.name = "Earned Leave (EL)"
                created = True
            
            # Set all fields
            el.company_id = default_company
            el.payment = 'paid'
            el.count = 1.25
            el.period_in = 'month'
            el.total_days = 1.25  # 1.25 days per month
            el.limit_leave = True
            el.reset = True
            el.reset_based = 'monthly'
            el.reset_day = '1'  # 1st of every month
            el.carryforward_type = 'carryforward expire'  # With expiry
            el.carryforward_max = 30  # Can accumulate up to 30 days
            el.carryforward_expire_in = 3  # Expires after 3 years
            el.carryforward_expire_period = 'year'
            el.require_approval = 'yes'
            el.require_attachment = 'no'
            el.exclude_company_leave = 'no'
            el.exclude_holiday = 'no'
            
            if not created:
                LeaveType.objects.filter(id=el.id).update(
                    company_id=default_company,
                    payment='paid',
                    count=1.25,
                    period_in='month',
                    total_days=1.25,
                    limit_leave=True,
                    reset=True,
                    reset_based='monthly',
                    reset_day='1',
                    carryforward_type='carryforward expire',
                    carryforward_max=30,
                    carryforward_expire_in=3,
                    carryforward_expire_period='year',
                    require_approval='yes',
                    require_attachment='no',
                    exclude_company_leave='no',
                    exclude_holiday='no',
                )
                self.stdout.write(self.style.SUCCESS('Updated: Earned Leave (EL)'))
            else:
                if not el.created_at:
                    el.created_at = timezone.now()
                el.save()
                self.stdout.write(self.style.SUCCESS('Created: Earned Leave (EL)'))
        
        # Get or create Intern Sick Leave (ISL) - 1 day per 3 months, interns only
        with transaction.atomic():
            try:
                isl = LeaveType.objects.get(name="Intern Sick Leave (ISL)")
                created = False
            except LeaveType.DoesNotExist:
                isl = LeaveType()
                isl.name = "Intern Sick Leave (ISL)"
                created = True

            isl.company_id = default_company
            isl.payment = "paid"
            isl.count = 1
            isl.period_in = "year"
            isl.total_days = 1
            isl.limit_leave = True
            isl.reset = False  # Managed by fix_leave_balances (1 per 3 months)
            isl.reset_based = "yearly"
            isl.reset_month = "1"
            isl.reset_day = "1"
            isl.carryforward_type = "no carryforward"
            isl.carryforward_max = None
            isl.carryforward_expire_in = None
            isl.carryforward_expire_period = None
            isl.require_approval = "yes"
            isl.require_attachment = "no"
            isl.exclude_company_leave = "no"
            isl.exclude_holiday = "no"

            if not created:
                LeaveType.objects.filter(id=isl.id).update(
                    company_id=default_company,
                    payment="paid",
                    count=1,
                    period_in="year",
                    total_days=1,
                    limit_leave=True,
                    reset=False,
                    reset_based="yearly",
                    reset_month="1",
                    reset_day="1",
                    carryforward_type="no carryforward",
                    carryforward_max=None,
                    carryforward_expire_in=None,
                    carryforward_expire_period=None,
                    require_approval="yes",
                    require_attachment="no",
                    exclude_company_leave="no",
                    exclude_holiday="no",
                )
                self.stdout.write(self.style.SUCCESS("Updated: Intern Sick Leave (ISL)"))
            else:
                if not isl.created_at:
                    isl.created_at = timezone.now()
                isl.save()
                self.stdout.write(self.style.SUCCESS("Created: Intern Sick Leave (ISL)"))

        # Optionally delete old leave types if --replace flag is used
        if replace:
            old_types = LeaveType.objects.filter(
                name__in=['Paid Leave (PL)', 'Menstrual Leave (ML)', 'Unpaid Leave (UL)']
            )
            count = old_types.count()
            if count > 0:
                old_types.delete()
                self.stdout.write(self.style.WARNING(f'Deleted {count} old leave type(s)'))
        
        self.stdout.write(
            self.style.SUCCESS(
                "\nLeave types setup complete!\n"
                "   - Casual Leave (CL): 12 days/year, yearly reset, no carry forward\n"
                "   - Sick Leave (SL): 7 days/year, yearly reset, no carry forward\n"
                "   - Earned Leave (EL): 1.25 days/month, monthly reset, max 30 days, expires after 3 years\n"
                "   - Intern Sick Leave (ISL): 1 day per 3 months, interns only (assign via assign_intern_leave)\n"
                "\nNote: Earned Leave monthly accrual will credit 1.25 days on the 1st of each month.\n"
                "      The 30-day accumulation limit and 3-year expiry are configured."
            )
        )
