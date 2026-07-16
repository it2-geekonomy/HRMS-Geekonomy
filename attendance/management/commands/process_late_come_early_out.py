"""
Django management command to process Late Come / Early Out for attendances.

Used by the scheduler (attendance.scheduler.process_late_come_early_out_daily) and
can be run manually:

  python manage.py process_late_come_early_out --days 7
  python manage.py process_late_come_early_out --from-date 2026-01-01 --to-date 2026-06-23
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import Attendance
from attendance.late_come_early_out_utils import process_late_come_early_out_for_attendances


class Command(BaseCommand):
    help = "Process Late Come and Early Out for attendances in a date range."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Process attendances from the last N days (ignored if --from-date is set).",
        )
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Start date (YYYY-MM-DD), inclusive.",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            default=None,
            help="End date (YYYY-MM-DD), inclusive. Defaults to today.",
        )

    def handle(self, *args, **options):
        from_date_str = options.get("from_date")
        to_date_str = options.get("to_date")

        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("--from-date must be YYYY-MM-DD") from exc
            if to_date_str:
                try:
                    to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise CommandError("--to-date must be YYYY-MM-DD") from exc
            else:
                to_date = timezone.now().date()
            if from_date > to_date:
                raise CommandError("--from-date cannot be after --to-date")
            range_label = f"{from_date.isoformat()} to {to_date.isoformat()}"
        else:
            days = options["days"] if options["days"] is not None else 7
            to_date = timezone.now().date()
            from_date = to_date - timedelta(days=days)
            range_label = f"last {days} days"

        qs = Attendance.objects.filter(
            attendance_date__gte=from_date,
            attendance_date__lte=to_date,
        )
        total = qs.count()
        count = process_late_come_early_out_for_attendances(qs)
        if options.get("verbosity", 1) >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed Late Come/Early Out for {count} of {total} "
                    f"attendances ({range_label})."
                )
            )
