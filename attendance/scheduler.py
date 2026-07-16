import datetime
import sys

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings

from base.backends import logger


def create_work_record():
    from attendance.models import WorkRecords
    from employee.models import Employee
    from base.methods import is_company_leave, is_holiday

    date = datetime.datetime.today().date()
    employees = Employee.objects.filter(is_active=True)
    created_count = 0
    
    # Skip creating work records for company leave days (e.g., Sundays)
    if is_company_leave(date) or is_holiday(date):
        print(f"Skipping work record creation for {date} - Company leave/holiday")
        return

    for employee in employees:
        try:
            shift_schedule = employee.get_shift_schedule()
            if shift_schedule is None:
                continue

            shift = employee.get_shift()
            
            # Use get_or_create to prevent duplicates
            work_record, created = WorkRecords.objects.get_or_create(
                employee_id=employee,
                date=date,
                defaults={
                    'work_record_type': "DFT",
                    'shift_id': shift,
                    'message': "",
                }
            )
            
            if created:
                created_count += 1
                
        except Exception as e:
            logger.error(f"Error creating work record for {employee}: {e}")

    logger.info(f"Created {created_count} new work records for {date}.")


def sync_biometric_attendance(recent_only=True):
    """
    Sync biometric attendance data automatically
    Uses file locking to prevent multiple workers from syncing simultaneously
    
    Args:
        recent_only: If True, only sync last 20 days. If False, sync all data.
    """
    import os
    import tempfile
    import time
    from pathlib import Path
    from django.core.management import call_command
    from django.core.management.base import CommandError
    
    # Use file-based locking (works on all platforms and across processes)
    lock_file = Path(tempfile.gettempdir()) / 'horilla_biometric_sync.lock'
    
    try:
        # Try to create lock file exclusively (atomic operation)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        
        try:
            # Write PID to lock file for debugging
            os.write(fd, str(os.getpid()).encode())
            
            # Small delay to ensure device is ready
            time.sleep(1)
            
            # Ensure Django apps are loaded
            from django.apps import apps
            if not apps.ready:
                # If apps aren't ready, wait a bit and try again
                time.sleep(2)
            
            # Run the sync with appropriate flag
            sync_success = False
            try:
                if recent_only:
                    call_command('sync_biometric_attendance', '--recent-only', verbosity=0)
                else:
                    call_command('sync_biometric_attendance', verbosity=0)
                sync_success = True
            except (CommandError, Exception) as e:
                # If command not found, try importing and calling directly
                error_str = str(e)
                if 'Unknown command' in error_str:
                    # Silently fall back to direct call - this is expected in some deployment scenarios
                    try:
                        from attendance.management.commands.sync_biometric_attendance import Command as SyncCommand
                        command = SyncCommand()
                        # Build options dict matching the command's expected arguments
                        options = {
                            'device_name': 'eSSL Office Device',
                            'recent_only': recent_only,
                            'force': False,
                            'from_date': None,
                            'to_date': None
                        }
                        command.handle(**options)
                        sync_success = True
                    except Exception as direct_error:
                        # Only log if direct call also fails
                        logger.error(f"Error in biometric sync (both methods failed): {direct_error}")
                else:
                    # For other errors, log and re-raise
                    logger.error(f"Error in biometric sync: {e}")
                    raise
        finally:
            # Clean up
            os.close(fd)
            try:
                os.unlink(str(lock_file))
            except:
                pass
                
    except FileExistsError:
        # Another process is already syncing, skip silently
        # Check if lock is stale (older than 10 minutes)
        try:
            if lock_file.exists():
                import time
                lock_age = time.time() - lock_file.stat().st_mtime
                if lock_age > 600:  # 10 minutes
                    # Remove stale lock and retry
                    os.unlink(str(lock_file))
                    sync_biometric_attendance(recent_only=recent_only)  # Retry once
        except:
            pass
    except Exception as e:
        # Only log if it's not a command discovery issue that was handled
        if 'Unknown command' not in str(e):
            logger.error(f"Error in biometric sync: {e}")

def sync_biometric_attendance_full():
    """
    Full sync of all biometric attendance data (no date limit)
    Runs daily to catch up on any missed data
    """
    sync_biometric_attendance(recent_only=False)


def process_late_come_early_out_daily():
    """
    Process Late Come / Early Out for recent attendances (last 7 days).
    Runs daily so LCO/EO appear automatically without manual script.
    """
    from django.core.management import call_command
    from django.core.management.base import CommandError
    try:
        call_command("process_late_come_early_out", days=7, verbosity=0)
        logger.info("process_late_come_early_out: completed.")
    except CommandError as e:
        logger.warning("process_late_come_early_out: %s", e)
    except Exception as e:
        logger.error("process_late_come_early_out: %s", e)


import os as _os

# Only start the scheduler in the actual worker process.
# Django's dev server runs TWO processes: the main reloader and the child worker.
# Both import this module, but only the child has RUN_MAIN='true'.
# Starting the scheduler in the reloader causes duplicate syncs with stale module caches.
_is_reloader = "runserver" in sys.argv and _os.environ.get("RUN_MAIN") != "true"

if not _is_reloader and not any(
    cmd in sys.argv
    for cmd in ["makemigrations", "migrate", "compilemessages", "flush", "shell"]
):
    """
    Initializes and starts background tasks using APScheduler when the server is running.
    """
    scheduler = BackgroundScheduler(timezone=pytz.timezone(settings.TIME_ZONE))

    scheduler.add_job(
        create_work_record, "interval", minutes=30, misfire_grace_time=3600 * 3
    )
    scheduler.add_job(
        create_work_record,
        "cron",
        hour=0,
        minute=30,
        misfire_grace_time=3600 * 9,
        id="create_daily_work_record",
        replace_existing=True,
    )
    
    # Biometric attendance sync — fixed daily times (recent = last 20 days)
    recent_sync_times = [
        (9, 0, "biometric_sync_0900"),
        (9, 30, "biometric_sync_0930"),
        (10, 0, "biometric_sync_1000"),
        (11, 0, "biometric_sync_1100"),
        (17, 30, "biometric_sync_1730"),
        (18, 30, "biometric_sync_1830"),
        (23, 30, "biometric_sync_2330"),
    ]
    for hour, minute, job_id in recent_sync_times:
        scheduler.add_job(
            sync_biometric_attendance,
            "cron",
            hour=hour,
            minute=minute,
            misfire_grace_time=3600,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    # Daily full sync (all device records) at 2:00 AM
    scheduler.add_job(
        sync_biometric_attendance_full,
        "cron",
        hour=2,
        minute=0,
        misfire_grace_time=3600 * 3,
        id="biometric_sync_full_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Late Come / Early Out: run daily so LCO/EO appear automatically (no manual script)
    scheduler.add_job(
        process_late_come_early_out_daily,
        "cron",
        hour=23,
        minute=0,
        misfire_grace_time=3600,
        id="process_late_come_early_out_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
