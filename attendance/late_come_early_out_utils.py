"""
Late Come / Early Out utilities for batch processing (biometric sync, scheduled jobs).

Syncs AttendanceLateComeEarlyOut records from actual punch times using the same
rules as the Late / Early page (9:11 AM late, 5:00 PM early out).
"""

from attendance.views.clock_in_out import early_out, late_come


def sync_late_come_early_out_for_attendance(attendance):
    """
    Create, update, or remove Late Come / Early Out for one attendance row.

    Returns True when late_come and/or early_out was evaluated.
    """
    late_come(attendance)
    early_out(attendance)
    return True


def process_late_come_early_out_for_attendances(attendances):
    """
    Sync Late Come and Early Out for attendances from punch times.

    Does not require shift/schedule — every attendance with punch data is evaluated.

    Returns:
        int: Number of attendances processed.
    """
    processed = 0
    for att in attendances:
        try:
            if sync_late_come_early_out_for_attendance(att):
                processed += 1
        except Exception:
            continue
    return processed
