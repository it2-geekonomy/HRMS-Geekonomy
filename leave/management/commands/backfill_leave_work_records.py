"""
Management command to backfill work records for existing approved leave requests.
This ensures "L" (Leave) appears in work records for leaves that were approved before the signal was added.
"""

from django.core.management.base import BaseCommand
from django.apps import apps
from django.utils.translation import gettext_lazy as _
from base.methods import get_date_range


class Command(BaseCommand):
    help = 'Backfill work records for existing approved leave requests'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating records',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Check if attendance app is installed
        if not apps.is_installed('attendance'):
            self.stdout.write(self.style.ERROR('Attendance app is not installed.'))
            return
        
        # Lazy imports
        LeaveRequest = apps.get_model('leave', 'LeaveRequest')
        WorkRecords = apps.get_model('attendance', 'WorkRecords')
        
        # Get all approved leave requests
        approved_leaves = LeaveRequest.objects.filter(status='approved')
        
        if not approved_leaves.exists():
            self.stdout.write(self.style.WARNING('No approved leave requests found.'))
            return
        
        self.stdout.write(f'Found {approved_leaves.count()} approved leave request(s).')
        
        created_count = 0
        updated_count = 0
        
        for leave_request in approved_leaves:
            try:
                # Get all dates in the leave period
                period_dates = get_date_range(leave_request.start_date, leave_request.end_date)
                
                for leave_date in period_dates:
                    # Check if work record already exists
                    work_record = WorkRecords.objects.filter(
                        date=leave_date,
                        employee_id=leave_request.employee_id,
                    ).first()
                    
                    if work_record:
                        # Update existing work record if it's not an attendance record
                        if not work_record.is_attendance_record:
                            if not dry_run:
                                work_record.work_record_type = 'L'
                                work_record.is_leave_record = True
                                work_record.leave_request_id = leave_request
                                work_record.message = _("On leave")
                                work_record.save()
                            updated_count += 1
                            self.stdout.write(
                                f'  Updated work record for {leave_request.employee_id} on {leave_date}'
                            )
                        else:
                            # Attendance exists - just mark as leave record
                            if not dry_run:
                                work_record.is_leave_record = True
                                work_record.leave_request_id = leave_request
                                work_record.save()
                            updated_count += 1
                            self.stdout.write(
                                f'  Marked attendance record as leave for {leave_request.employee_id} on {leave_date}'
                            )
                    else:
                        # Create new work record
                        if not dry_run:
                            WorkRecords.objects.create(
                                date=leave_date,
                                employee_id=leave_request.employee_id,
                                work_record_type='L',
                                is_leave_record=True,
                                leave_request_id=leave_request,
                                message=_("On leave"),
                            )
                        created_count += 1
                        self.stdout.write(
                            f'  Created work record for {leave_request.employee_id} on {leave_date}'
                        )
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing leave request {leave_request.id}: {e}'
                    )
                )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No records were actually created/updated.'))
            self.stdout.write(f'Would create: {created_count} work record(s)')
            self.stdout.write(f'Would update: {updated_count} work record(s)')
        else:
            self.stdout.write(self.style.SUCCESS(f'\nSuccessfully created {created_count} work record(s).'))
            self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} work record(s).'))
