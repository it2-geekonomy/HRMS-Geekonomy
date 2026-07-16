"""
Send reminder emails to reporting managers 7 days before an employee's
Probation Will Complete Date.

Run: python manage.py send_probation_reminders
Or the scheduler runs it daily.
"""

from django.core.management.base import BaseCommand

from employee.probation_reminder import send_probation_reminder_emails


class Command(BaseCommand):
    help = (
        "Send reminder to reporting managers for employees whose "
        "Probation Will Complete Date is 7 days from today."
    )

    def handle(self, *args, **options):
        send_probation_reminder_emails()
        self.stdout.write(
            self.style.SUCCESS("Probation reminder emails sent (if any matched).")
        )
