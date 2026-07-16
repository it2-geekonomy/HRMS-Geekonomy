"""
Django management command to delete specific leave types:
- Unpaid Leave
- Paid Leave (PL)
"""
from django.core.management.base import BaseCommand
from django.db import transaction, connection
from leave.models import LeaveType, AvailableLeave, LeaveRequest


class Command(BaseCommand):
    help = 'Delete Unpaid Leave and Paid Leave (PL) leave types'

    def handle(self, *args, **options):
        # Delete Paid Leave (PL)
        try:
            pl = LeaveType.objects.get(name='Paid Leave (PL)')
            
            # First, delete all related AvailableLeave records
            available_leaves = AvailableLeave.objects.filter(leave_type_id=pl)
            available_count = available_leaves.count()
            available_leaves.delete()
            self.stdout.write(f'Deleted {available_count} AvailableLeave record(s) for Paid Leave (PL)')
            
            # Then, delete all related LeaveRequest records
            leave_requests = LeaveRequest.objects.filter(leave_type_id=pl)
            request_count = leave_requests.count()
            leave_requests.delete()
            self.stdout.write(f'Deleted {request_count} LeaveRequest record(s) for Paid Leave (PL)')
            
            # Delete from leave_accrual_leaveaccrualconfig if table exists
            with connection.cursor() as cursor:
                try:
                    cursor.execute("""
                        SELECT COUNT(*) FROM information_schema.tables 
                        WHERE table_name = 'leave_accrual_leaveaccrualconfig'
                    """)
                    table_exists = cursor.fetchone()[0] > 0
                    if table_exists:
                        cursor.execute("""
                            DELETE FROM leave_accrual_leaveaccrualconfig 
                            WHERE leave_type_id = %s
                        """, [pl.id])
                        accrual_count = cursor.rowcount
                        self.stdout.write(f'Deleted {accrual_count} LeaveAccrualConfig record(s) for Paid Leave (PL)')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'Note: Could not delete from leave_accrual table: {e}'))
            
            # Finally, delete the leave type
            pl.delete()
            self.stdout.write(self.style.SUCCESS('Deleted: Paid Leave (PL)'))
        except LeaveType.DoesNotExist:
            self.stdout.write(self.style.WARNING('Paid Leave (PL) not found'))

        # Delete Unpaid Leave
        try:
            ul = LeaveType.objects.get(name='Unpaid Leave')
            
            # First, delete all related AvailableLeave records
            available_leaves = AvailableLeave.objects.filter(leave_type_id=ul)
            available_count = available_leaves.count()
            available_leaves.delete()
            self.stdout.write(f'Deleted {available_count} AvailableLeave record(s) for Unpaid Leave')
            
            # Then, delete all related LeaveRequest records
            leave_requests = LeaveRequest.objects.filter(leave_type_id=ul)
            request_count = leave_requests.count()
            leave_requests.delete()
            self.stdout.write(f'Deleted {request_count} LeaveRequest record(s) for Unpaid Leave')
            
            # Delete from leave_accrual_leaveaccrualconfig if table exists
            with connection.cursor() as cursor:
                try:
                    cursor.execute("""
                        SELECT COUNT(*) FROM information_schema.tables 
                        WHERE table_name = 'leave_accrual_leaveaccrualconfig'
                    """)
                    table_exists = cursor.fetchone()[0] > 0
                    if table_exists:
                        cursor.execute("""
                            DELETE FROM leave_accrual_leaveaccrualconfig 
                            WHERE leave_type_id = %s
                        """, [ul.id])
                        accrual_count = cursor.rowcount
                        self.stdout.write(f'Deleted {accrual_count} LeaveAccrualConfig record(s) for Unpaid Leave')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'Note: Could not delete from leave_accrual table: {e}'))
            
            # Finally, delete the leave type
            ul.delete()
            self.stdout.write(self.style.SUCCESS('Deleted: Unpaid Leave'))
        except LeaveType.DoesNotExist:
            self.stdout.write(self.style.WARNING('Unpaid Leave not found'))

        self.stdout.write(self.style.SUCCESS('\nDone!'))
