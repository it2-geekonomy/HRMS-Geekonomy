"""
Recalculate all work records based on the new logic:
- MP (Missing Punch): Check-in == Check-out (same time) OR no check-out for past day
- HP (Half Day Present): Worked > 0 hours but < 8 hours
- P (Present/FDP): Worked >= 8 hours
"""
from datetime import date
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from attendance.models import Attendance, WorkRecords
from attendance.methods.utils import strtime_seconds


class Command(BaseCommand):
    help = 'Recalculate all work records based on new MP/HP/P logic'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        FULL_DAY_SECONDS = 28800  # 8 hours
        today = date.today()
        
        # Get all attendance records
        attendances = Attendance.objects.all()
        total = attendances.count()
        
        self.stdout.write(f'Processing {total} attendance records...')
        self.stdout.write('=' * 80)
        
        updated_count = 0
        mp_count = 0
        hp_count = 0
        fdp_count = 0
        conf_count = 0
        
        for idx, attendance in enumerate(attendances, 1):
            at_work_second = strtime_seconds(attendance.attendance_worked_hour)
            if at_work_second is None:
                at_work_second = 0
            
            # MP threshold: Less than 5 minutes (300 seconds) is considered missing punch
            MP_THRESHOLD_SECONDS = 300
            
            # Check for Missing Punch conditions
            is_missing_punch = False
            
            # Condition 1: No check-out for past day
            if not attendance.attendance_clock_out:
                if attendance.attendance_date == today:
                    is_missing_punch = False
                else:
                    is_missing_punch = True
            # Condition 2: Worked less than 5 minutes (includes same time, 1-2 seconds, etc.)
            elif at_work_second < MP_THRESHOLD_SECONDS and attendance.attendance_date != today:
                is_missing_punch = True
            
            # Determine status
            if not attendance.attendance_validated:
                new_status = "CONF"
                conf_count += 1
            elif is_missing_punch:
                new_status = "MP"
                mp_count += 1
            elif not attendance.attendance_clock_out and attendance.attendance_date == today:
                new_status = "HDP"
                hp_count += 1
            elif at_work_second >= FULL_DAY_SECONDS:
                new_status = "FDP"
                fdp_count += 1
            elif at_work_second > 0:
                new_status = "HDP"
                hp_count += 1
            else:
                new_status = "ABS"
            
            # Update work record
            try:
                work_record = WorkRecords.objects.filter(
                    date=attendance.attendance_date,
                    employee_id=attendance.employee_id,
                ).first()
                
                if work_record:
                    old_status = work_record.work_record_type
                    if old_status != new_status:
                        if not dry_run:
                            work_record.work_record_type = new_status
                            work_record.at_work_second = at_work_second
                            work_record.save()
                        updated_count += 1
                        
                        if dry_run:
                            self.stdout.write(
                                f'  [{idx}/{total}] {attendance.employee_id} ({attendance.attendance_date}): '
                                f'{old_status} -> {new_status}'
                            )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Error: {e}'))
        
        self.stdout.write('=' * 80)
        self.stdout.write(f'\nSummary:')
        self.stdout.write(f'  Total attendance records: {total}')
        self.stdout.write(f'  Records updated: {updated_count}')
        self.stdout.write(f'\nNew status counts:')
        self.stdout.write(f'  CONF (Conflict): {conf_count}')
        self.stdout.write(f'  FDP (Present): {fdp_count}')
        self.stdout.write(f'  HDP (Half Day): {hp_count}')
        self.stdout.write(f'  MP (Missing Punch): {mp_count}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] No changes were made. Run without --dry-run to apply.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\nSuccessfully updated {updated_count} work records!'))
