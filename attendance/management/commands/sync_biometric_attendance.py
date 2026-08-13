"""
Django management command for real-time biometric attendance synchronization
"""
import logging
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from biometric.models import BiometricDevices, BiometricEmployees
from attendance.methods.utils import strtime_seconds
from attendance.models import Attendance, AttendanceRequestLog
from attendance.views.clock_in_out import clock_in, clock_out
from base.models import EmployeeShiftDay
from employee.models import Employee
from zk import ZK
from zk import exception as zk_exception

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sync biometric attendance data with Django application'

    def add_arguments(self, parser):
        parser.add_argument(
            '--device-name',
            type=str,
            default='eSSL Office Device',
            help='Name of the biometric device to sync from'
        )
        parser.add_argument(
            '--recent-only',
            action='store_true',
            help='Sync only recent records (last 20 days)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync even if device was recently synced'
        )
        parser.add_argument(
            '--no-incremental',
            action='store_true',
            dest='no_incremental',
            help='Reprocess the full recent window (do not skip punches before last_fetch). '
                 'Use for overnight catch-up so yesterday clock-out is set.',
        )
        parser.add_argument(
            '--from-date',
            type=str,
            default=None,
            help='Sync from this date (YYYY-MM-DD). Use with --to-date for date range sync.'
        )
        parser.add_argument(
            '--to-date',
            type=str,
            default=None,
            help='Sync to this date (YYYY-MM-DD). Use with --from-date for date range sync.'
        )

    def handle(self, *args, **options):
        device_name = options['device_name']
        recent_only = options['recent_only']
        force = options['force']
        no_incremental = options.get('no_incremental', False)
        from_date_str = options.get('from_date')
        to_date_str = options.get('to_date')
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting biometric attendance sync for device: {device_name}')
        )
        
        try:
            # Get biometric device
            device = BiometricDevices.objects.get(name=device_name)
            self.stdout.write(f'Found device: {device.name} at {device.machine_ip}:{device.port}')
            
            # Auto-detect IP if device not reachable (DHCP IP may have changed)
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((device.machine_ip, device.port))
            sock.close()
            
            if result != 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'Device not reachable at {device.machine_ip}. '
                        f'IP may have changed (DHCP). Attempting to find device...'
                    )
                )
                # Quick search nearby IPs
                ip_parts = device.machine_ip.split('.')
                if len(ip_parts) == 4:
                    base_ip = '.'.join(ip_parts[:3])
                    last_octet = int(ip_parts[3])
                    found = False
                    
                    for offset in range(-10, 11):
                        if offset == 0:
                            continue
                        test_ip = f"{base_ip}.{last_octet + offset}"
                        if 1 <= last_octet + offset <= 254:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1)
                            if sock.connect_ex((test_ip, device.port)) == 0:
                                sock.close()
                                # Test if it's ZKTeco device
                                try:
                                    test_zk = ZK(test_ip, port=device.port, timeout=5, ommit_ping=True)
                                    test_conn = test_zk.connect()
                                    test_conn.disconnect()
                                    # Found it!
                                    device.machine_ip = test_ip
                                    device.save()
                                    self.stdout.write(
                                        self.style.SUCCESS(
                                            f'Auto-updated device IP to {test_ip} (was {ip_parts[3]})'
                                        )
                                    )
                                    found = True
                                    break
                                except:
                                    pass
                            else:
                                sock.close()
                    
                    if not found:
                        self.stdout.write(
                            self.style.ERROR(
                                f'Could not find device. Please check:\n'
                                f'  1. Device is powered on\n'
                                f'  2. Device is on same network\n'
                                f'  3. Set Static IP on device to prevent this issue'
                            )
                        )
                        return
            
            # Check if we should skip sync (unless forced)
            if not force and device.last_fetch_date and device.last_fetch_time:
                last_sync = datetime.combine(device.last_fetch_date, device.last_fetch_time)
                if datetime.now() - last_sync < timedelta(minutes=2):
                    self.stdout.write(
                        self.style.WARNING('Skipping sync - device was synced recently')
                    )
                    return
            
            # Use last_fetch to only process NEW records (much faster!)
            # Incremental is skipped when:
            # - last_fetch is today (need all of today's punches), or
            # - --no-incremental / full sync (need yesterday + recent days fully, e.g. 2 AM job)
            today = datetime.now().date()
            use_incremental = (
                device.last_fetch_date
                and device.last_fetch_time
                and not from_date_str
                and not no_incremental
                and recent_only
                and device.last_fetch_date < today
            )
            
            # Connect to biometric device
            import time
            self.stdout.write('Device is reachable, connecting...')
            
            # Connect with reasonable timeout
            max_retries = 2
            conn = None
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        self.stdout.write(f'Retrying connection (attempt {attempt + 1}/{max_retries})...')
                        time.sleep(5)
                    
                    # Use 30 second timeout - fail fast if device doesn't respond
                    zk = ZK(device.machine_ip, port=device.port, timeout=30, ommit_ping=True)
                    conn = zk.connect()
                    self.stdout.write('[OK] Connected to biometric device')
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.stdout.write(
                            self.style.ERROR(
                                f'Failed to connect: {str(e)}\n'
                                f'Device may be busy or not responding. Try again in a few minutes.'
                            )
                        )
                        return
                    continue
            
            if conn is None:
                self.stdout.write(self.style.ERROR('Failed to connect after retries'))
                return
            
            try:
                
                # Get attendance data
                # NOTE: Device API doesn't support date filtering, so we must fetch ALL records first
                # However, we can filter immediately after fetch to only process new records
                self.stdout.write('Fetching attendance records from device...')
                if use_incremental:
                    self.stdout.write(f'   Using incremental sync (only records after {device.last_fetch_date} {device.last_fetch_time})')
                    self.stdout.write('   This will be faster as we only process new records')
                else:
                    self.stdout.write('   Fetching all records (this may take 2-5 minutes)')
                
                try:
                    # Fetch all records (device limitation - can't filter at device level)
                    # This is the slow part - device sends all historical data
                    import time
                    fetch_start = time.time()
                    self.stdout.write('Fetching records from device (this is the slow part - 2-10 min)...')
                    self.stdout.write('   Progress: Device is sending all records...')
                    
                    all_attendances = conn.get_attendance()
                    fetch_time = time.time() - fetch_start
                    total_records = len(all_attendances)
                    self.stdout.write(f'Retrieved {total_records:,} total records in {fetch_time:.1f} seconds ({fetch_time/60:.1f} minutes)')
                    
                    # Store original for last_fetch update (need max from ALL records)
                    original_attendances = list(all_attendances)
                    
                    # Immediately filter if using incremental sync (before processing)
                    # IMPORTANT: For today's date, get ALL records (not just after last_fetch_time)
                    # This ensures we don't miss records from employees who clocked in earlier
                    # SAFETY: Add 5 minute buffer before last_fetch_time to account for clock drift/timing issues
                    if use_incremental and total_records > 0:
                        before_filter = total_records
                        today = datetime.now().date()
                        
                        # Calculate buffer time (5 minutes before last_fetch_time to catch any missed records)
                        from datetime import time as time_class
                        last_fetch_datetime = datetime.combine(device.last_fetch_date, device.last_fetch_time)
                        buffer_datetime = last_fetch_datetime - timedelta(minutes=5)
                        buffer_time = buffer_datetime.time()
                        
                        attendances = [
                            att for att in all_attendances
                            if (
                                # Records from future dates (shouldn't happen, but include them)
                                att.timestamp.date() > device.last_fetch_date
                            ) or (
                                # Records from today - get ALL of them (not just after last_fetch_time)
                                att.timestamp.date() == today
                            ) or (
                                # Records from last_fetch_date but after buffer_time (5 min safety margin)
                                # This ensures we don't miss records due to clock drift or timing issues
                                att.timestamp.date() == device.last_fetch_date
                                and att.timestamp.time() >= buffer_time
                            )
                        ]
                        self.stdout.write(f'Filtered to {len(attendances)} new records (skipped {before_filter - len(attendances)} already synced, using 5-min safety buffer)')
                    else:
                        attendances = all_attendances
                        
                except Exception as e:
                    if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                        self.stdout.write(
                            self.style.ERROR('Device timeout - device may be busy. Will retry automatically.')
                        )
                    raise
                
                if not attendances:
                    self.stdout.write(
                        self.style.WARNING('No attendance records found on device')
                    )
                    return
                
                # Filter records by date range if requested (incremental already filtered above)
                if from_date_str or to_date_str:
                    from datetime import date as date_class
                    from_date = None
                    to_date = None
                    
                    if from_date_str:
                        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                    if to_date_str:
                        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                    
                    self.stdout.write(f'Filtering records from {from_date or "start"} to {to_date or "end"}...')
                    filtered = []
                    total = len(attendances)
                    for idx, att in enumerate(attendances):
                        if idx > 0 and idx % 1000 == 0:
                            self.stdout.write(f'   Filtered {idx}/{total} records...')
                        att_date = att.timestamp.date()
                        if from_date and att_date < from_date:
                            continue
                        if to_date and att_date > to_date:
                            continue
                        filtered.append(att)
                    
                    attendances = filtered
                    self.stdout.write(f'[OK] Filtered to {len(attendances)} records in date range')
                elif recent_only:
                    twenty_days_ago = datetime.now() - timedelta(days=20)
                    attendances = [
                        att for att in attendances 
                        if att.timestamp.date() >= twenty_days_ago.date()
                    ]
                    self.stdout.write(f'Filtered to {len(attendances)} recent records (last 20 days)')
                
                # Process attendance data
                synced_count = 0
                updated_count = 0
                skipped_count = 0
                error_count = 0
                self._skipped_records = {}  # Track skipped records for detailed reporting
                
                # Fetch device users to get names for unmapped user_ids
                device_users_map = {}
                try:
                    device_users = conn.get_users()
                    for user in device_users:
                        user_id_str = str(user.user_id) if hasattr(user, 'user_id') and user.user_id is not None else None
                        uid_str = str(user.uid) if hasattr(user, 'uid') and user.uid is not None else None
                        name = getattr(user, 'name', '') or getattr(user, 'user_name', '') or 'Unknown'
                        if user_id_str:
                            device_users_map[user_id_str] = {'name': name, 'uid': uid_str}
                        if uid_str:
                            device_users_map[f'uid_{uid_str}'] = {'name': name, 'user_id': user_id_str}
                except Exception as e:
                    self.stdout.write(f'   [Note] Could not fetch device users: {e}')
                
                # Get biometric employee mappings
                # Match by both UID and user_id - device may use either field
                biometric_employees = BiometricEmployees.objects.filter(device_id=device)
                
                # Create mapping dictionaries for both uid and user_id
                bio_id_map_by_uid = {}
                bio_id_map_by_user_id = {}
                
                for bio in biometric_employees:
                    # Map by UID (if available)
                    if bio.uid is not None:
                        bio_id_map_by_uid[(device.id, str(bio.uid))] = bio
                    # Map by user_id (always available)
                    if bio.user_id:
                        bio_id_map_by_user_id[(device.id, str(bio.user_id))] = bio
                
                # Group attendance by employee and date
                employee_daily_records = {}
                
                for att in attendances:
                    # Match by user_id first (as per original code in biometric/views.py)
                    # The old code uses: bio_id_map.get((device_id, user_id))
                    # where user_id comes from attendance.user_id
                    device_user_id = None
                    if hasattr(att, 'user_id'):
                        # Convert to string to match database storage (user_id is CharField)
                        device_user_id = str(att.user_id) if att.user_id is not None else None
                    
                    # Fallback to UID if user_id is not available
                    device_uid = None
                    if not device_user_id and hasattr(att, 'uid'):
                        device_uid = str(att.uid) if att.uid is not None else None
                    
                    # Try user_id first (original matching method - same as biometric/views.py line 2253)
                    bio_id = None
                    if device_user_id:
                        bio_id = bio_id_map_by_user_id.get((device.id, device_user_id))
                    
                    # Fallback to UID if user_id didn't match
                    if not bio_id and device_uid:
                        bio_id = bio_id_map_by_uid.get((device.id, device_uid))
                    
                    if not bio_id:
                        skipped_count += 1
                        # Log unmapped record for debugging - show what we're looking for
                        identifier = device_user_id or device_uid or "unknown"
                        att_date = att.timestamp.date()
                        att_time = att.timestamp.time()
                        
                        # Get device user name if available
                        device_user_name = None
                        if device_user_id and device_user_id in device_users_map:
                            device_user_name = device_users_map[device_user_id].get('name')
                        elif device_uid and f'uid_{device_uid}' in device_users_map:
                            device_user_name = device_users_map[f'uid_{device_uid}'].get('name')
                        
                        # Check for potential employee matches by badge_id
                        potential_employees = []
                        if device_user_id:
                            # Check if any employee has this badge_id
                            matching_employees = Employee.objects.filter(
                                badge_id=device_user_id,
                                is_active=True
                            )
                            for emp in matching_employees:
                                potential_employees.append({
                                    'id': emp.id,
                                    'name': f"{emp.employee_first_name} {emp.employee_last_name}".strip(),
                                    'badge_id': emp.badge_id
                                })
                        
                        # Track skipped records by user_id for summary
                        key = f"user_id={device_user_id}" if device_user_id else f"uid={device_uid}"
                        if key not in self._skipped_records:
                            self._skipped_records[key] = {
                                'count': 0,
                                'first_seen': att.timestamp,
                                'last_seen': att.timestamp,
                                'dates': set(),
                                'device_user_name': device_user_name,
                                'potential_employees': potential_employees
                            }
                        
                        self._skipped_records[key]['count'] += 1
                        self._skipped_records[key]['dates'].add(att_date)
                        if att.timestamp > self._skipped_records[key]['last_seen']:
                            self._skipped_records[key]['last_seen'] = att.timestamp
                        if att.timestamp < self._skipped_records[key]['first_seen']:
                            self._skipped_records[key]['first_seen'] = att.timestamp
                        
                        # Show detailed info for first few occurrences of each unmapped user_id
                        if self._skipped_records[key]['count'] <= 3:
                            device_name_info = f" (Device name: {device_user_name})" if device_user_name else ""
                            potential_info = ""
                            if potential_employees:
                                emp_names = [f"{e['name']} (ID: {e['id']})" for e in potential_employees]
                                potential_info = f" | Potential match: {', '.join(emp_names)}"
                            
                            sample_mappings = list(bio_id_map_by_user_id.items())[:3]
                            sample_text = ", ".join([f"user_id={k[1]}" for k, v in sample_mappings])
                            self.stdout.write(
                                self.style.WARNING(
                                    f'   Skipped unmapped: device user_id={device_user_id}, uid={device_uid}{device_name_info} | '
                                    f'Date: {att_date} {att_time}{potential_info}'
                                )
                            )
                        continue
                    
                    employee = bio_id.employee_id
                    att_date = att.timestamp.date()
                    att_time = att.timestamp.time()
                    
                    key = (employee.id, att_date)
                    if key not in employee_daily_records:
                        employee_daily_records[key] = {
                            'employee': employee,
                            'date': att_date,
                            'times': []
                        }
                    
                    employee_daily_records[key]['times'].append(att_time)
                
                # Fast processing: Get existing records in bulk
                total_records = len(employee_daily_records)
                self.stdout.write(f'Processing {total_records} employee-day records (using bulk operations)...')
                
                # Get all existing attendances in one query
                employee_ids = [r['employee'].id for r in employee_daily_records.values()]
                dates_list = [r['date'] for r in employee_daily_records.values()]
                existing_attendances = {
                    (att.employee_id_id, att.attendance_date): att
                    for att in Attendance.objects.filter(
                        employee_id__in=employee_ids,
                        attendance_date__in=dates_list
                    ).select_related('employee_id')
                }

                existing_pks = [
                    att.pk for att in existing_attendances.values() if getattr(att, "pk", None)
                ]
                manager_approved_attendance_pks = set(
                    AttendanceRequestLog.objects.filter(
                        action=AttendanceRequestLog.ACTION_APPROVED,
                        attendance_id__in=existing_pks,
                    ).values_list("attendance_id_id", flat=True)
                )
                
                # Prepare bulk create and update lists
                from datetime import date as date_class

                today = date_class.today()
                attendances_to_create = []
                attendances_to_update = []
                # Do not overwrite manager-approved rows: sync uses first/last device punch
                # and erases approved corrections (e.g. half-day). Also skip partial-day heuristic
                # when at_work_second is still full-day (approval recalculation skipped).
                FULL_DAY_SECONDS = 28800  # 8 hours
                MP_THRESHOLD_SECONDS = 300  # 5 minutes

                for key, record_data in employee_daily_records.items():
                    employee = record_data['employee']
                    date = record_data['date']
                    times = sorted(record_data['times'])
                    
                    if not times:
                        continue
                    
                    first_time = times[0]
                    last_time = times[-1]
                    
                    # Check if exists
                    existing = existing_attendances.get((employee.id, date))
                    
                    if existing:
                        if date < today:
                            _guard_match = (
                                existing.pk
                                and existing.pk in manager_approved_attendance_pks
                                and existing.attendance_validated
                                and not existing.is_validate_request
                            )
                            if _guard_match:
                                continue
                            # Extra guard: even if logs are missing/delayed, never overwrite
                            # a manager-approved/corrected row.
                            if (
                                getattr(existing, "is_validate_request_approved", False)
                                and existing.attendance_validated
                                and not existing.is_validate_request
                            ):
                                continue
                            aw = existing.at_work_second
                            if aw is None and existing.attendance_worked_hour:
                                try:
                                    aw = strtime_seconds(existing.attendance_worked_hour)
                                except (ValueError, TypeError, AttributeError):
                                    aw = 0
                            if aw is None:
                                aw = 0
                        # Update existing
                        needs_update = False
                        
                        if not existing.attendance_clock_in or existing.attendance_clock_in > first_time:
                            existing.attendance_clock_in = first_time
                            existing.attendance_clock_in_date = date
                            needs_update = True
                        
                        if date == today:
                            existing.attendance_clock_out = None
                            existing.attendance_clock_out_date = None
                            existing.request_description = f"Latest scan: {last_time.strftime('%H:%M:%S')}"
                            needs_update = True
                        else:
                            if not existing.attendance_clock_out or existing.attendance_clock_out < last_time:
                                existing.attendance_clock_out = last_time
                                existing.attendance_clock_out_date = date
                                needs_update = True
                        
                        # Calculate worked hours
                        if existing.attendance_clock_in:
                            clock_in_dt = datetime.combine(date, existing.attendance_clock_in)
                            if date == today:
                                clock_out_dt = datetime.combine(date, last_time)
                            else:
                                clock_out_dt = datetime.combine(date, existing.attendance_clock_out or last_time)
                            
                            if clock_out_dt < clock_in_dt:
                                clock_out_dt += timedelta(days=1)
                            
                            worked_duration = clock_out_dt - clock_in_dt
                            total_seconds = int(worked_duration.total_seconds())
                            hours = total_seconds // 3600
                            minutes = (total_seconds % 3600) // 60
                            seconds = total_seconds % 60
                            worked_hours = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                            
                            existing.attendance_worked_hour = worked_hours
                            existing.at_work_second = total_seconds  # Set at_work_second
                            existing.attendance_validated = True
                            needs_update = True
                        
                        # Set minimum_hour if missing (required for work records calculation)
                        if not existing.minimum_hour:
                            existing.minimum_hour = '08:00'
                            needs_update = True
                        
                        # Set attendance_day (required for Day column)
                        try:
                            day_name = date.strftime("%A").lower()
                            existing.attendance_day = EmployeeShiftDay.objects.get(day=day_name)
                        except EmployeeShiftDay.DoesNotExist:
                            pass  # Day will be set on save if EmployeeShiftDay exists
                        
                        if needs_update:
                            attendances_to_update.append(existing)
                    else:
                        # Create new
                        clock_out = None if date == today else last_time
                        clock_out_date = None if date == today else date
                        
                        # Calculate worked hours
                        clock_in_dt = datetime.combine(date, first_time)
                        if date == today:
                            clock_out_dt = datetime.combine(date, last_time)
                        else:
                            clock_out_dt = datetime.combine(date, last_time)
                        
                        if clock_out_dt < clock_in_dt:
                            clock_out_dt += timedelta(days=1)
                        
                        worked_duration = clock_out_dt - clock_in_dt
                        total_seconds = int(worked_duration.total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        seconds = total_seconds % 60
                        worked_hours = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        
                        # Set attendance_day (required for Day column)
                        day_name = date.strftime("%A").lower()
                        try:
                            attendance_day = EmployeeShiftDay.objects.get(day=day_name)
                        except EmployeeShiftDay.DoesNotExist:
                            attendance_day = None
                        
                        new_attendance = Attendance(
                            employee_id=employee,
                            attendance_date=date,
                            attendance_day=attendance_day,
                            attendance_clock_in=first_time,
                            attendance_clock_in_date=date,
                            attendance_clock_out=clock_out,
                            attendance_clock_out_date=clock_out_date,
                            attendance_worked_hour=worked_hours,
                            at_work_second=total_seconds,  # Set at_work_second
                            attendance_validated=True,
                            minimum_hour='08:00',
                            attendance_overtime='00:00',
                            attendance_overtime_approve=False,
                            request_description=f"Latest scan: {last_time.strftime('%H:%M:%S')}" if date == today else ""
                        )
                        attendances_to_create.append(new_attendance)
                
                # Bulk create and update (fast) - then manually update work records using signal logic
                from django.db import transaction
                from attendance.models import WorkRecords
                from datetime import date as date_class
                
                with transaction.atomic():
                    # Defense-in-depth: re-query approved PKs right before write
                    # to protect against stale module caches or race conditions.
                    if attendances_to_update:
                        update_pks = [a.pk for a in attendances_to_update if a.pk]
                        approved_pks_now = set(
                            AttendanceRequestLog.objects.filter(
                                action=AttendanceRequestLog.ACTION_APPROVED,
                                attendance_id__in=update_pks,
                            ).values_list("attendance_id_id", flat=True)
                        )
                        if approved_pks_now:
                            before = len(attendances_to_update)
                            attendances_to_update = [
                                a for a in attendances_to_update
                                if a.pk not in approved_pks_now
                            ]
                            skipped = before - len(attendances_to_update)
                            if skipped:
                                self.stdout.write(
                                    f'Protected {skipped} manager-approved record(s) from overwrite'
                                )

                    # Fast bulk operations
                    if attendances_to_create:
                        Attendance.objects.bulk_create(attendances_to_create, batch_size=100)
                        self.stdout.write(f'Bulk created {len(attendances_to_create)} records')
                    
                    if attendances_to_update:
                        Attendance.objects.bulk_update(
                            attendances_to_update,
                            ['attendance_clock_in', 'attendance_clock_in_date', 'attendance_clock_out',
                             'attendance_clock_out_date', 'attendance_worked_hour', 'at_work_second', 'attendance_validated',
                             'request_description', 'attendance_day', 'minimum_hour'],
                            batch_size=100
                        )
                        self.stdout.write(f'Bulk updated {len(attendances_to_update)} records')
                    
                    # Manually update work records using same logic as signals (bulk operations bypass signals)
                    all_processed_attendances = list(attendances_to_create) + list(attendances_to_update)
                    
                    if all_processed_attendances:
                        # Refresh from DB to get IDs for newly created records
                        employee_ids = [att.employee_id.id for att in all_processed_attendances]
                        dates_list = [att.attendance_date for att in all_processed_attendances]
                        created_attendances = Attendance.objects.filter(
                            employee_id__in=employee_ids,
                            attendance_date__in=dates_list
                        ).select_related(
                            'employee_id',
                            'employee_id__employee_work_info__shift_id',
                        )
                        
                        work_records_to_create = []
                        work_records_to_update = []
                        
                        for att in created_attendances:
                            try:
                                # Use same logic as signals.py
                                min_hour_str = att.minimum_hour if att.minimum_hour else '08:00'
                                at_work_str = att.attendance_worked_hour if att.attendance_worked_hour else '00:00'
                                
                                min_hour_second = strtime_seconds(min_hour_str)
                                at_work_second = strtime_seconds(at_work_str)
                                
                                FULL_DAY_SECONDS = 28800  # 8 hours
                                MP_THRESHOLD_SECONDS = 300  # 5 minutes
                                SHORT_PRESENCE_SECONDS = 7200  # 2 hours
                                
                                # Check for Missing Punch (same logic as signals.py)
                                is_missing_punch = False
                                if not att.attendance_clock_out:
                                    if att.attendance_date == date_class.today():
                                        is_missing_punch = False
                                    else:
                                        is_missing_punch = True
                                elif at_work_second < MP_THRESHOLD_SECONDS and att.attendance_date != date_class.today():
                                    is_missing_punch = True
                                
                                # Determine status (same as signals.py)
                                if not att.attendance_validated:
                                    status, message = "CONF", "Validate the attendance"
                                elif is_missing_punch:
                                    status, message = "MP", "Missing Punch"
                                elif not att.attendance_clock_out and att.attendance_date == date_class.today():
                                    status, message = "HDP", "Currently working"
                                elif at_work_second >= FULL_DAY_SECONDS:
                                    status, message = "FDP", "Present"
                                elif at_work_second >= SHORT_PRESENCE_SECONDS:
                                    status, message = "HDP", "Half Day Present"
                                elif at_work_second > 0:
                                    status, message = "SP", "Short Presence"
                                else:
                                    status, message = "ABS", "Absent"
                                
                                # Get or create work record
                                try:
                                    work_record = WorkRecords.objects.get(
                                        date=att.attendance_date,
                                        employee_id=att.employee_id
                                    )
                                    # Protect SP records from being overwritten by sync for past dates
                                    if work_record.work_record_type == "SP" and date < date_class.today():
                                        continue
                                    # Update existing
                                    work_record.at_work = att.attendance_worked_hour
                                    work_record.min_hour = att.minimum_hour
                                    work_record.min_hour_second = min_hour_second
                                    work_record.at_work_second = at_work_second
                                    work_record.work_record_type = status
                                    work_record.message = message
                                    work_record.is_attendance_record = True
                                    work_record.attendance_id = att
                                    work_record.shift_id = att.shift_id
                                    if att.attendance_validated:
                                        if status == "FDP":
                                            work_record.day_percentage = 1.00
                                        elif status == "HDP":
                                            work_record.day_percentage = 0.50
                                        elif status == "SP":
                                            work_record.day_percentage = 0.25
                                        else:
                                            work_record.day_percentage = 1.00 if at_work_second > min_hour_second / 2 else 0.50
                                    work_records_to_update.append(work_record)
                                except WorkRecords.DoesNotExist:
                                    # Create new
                                    work_record = WorkRecords(
                                        employee_id=att.employee_id,
                                        date=att.attendance_date,
                                        at_work=att.attendance_worked_hour,
                                        min_hour=att.minimum_hour,
                                        min_hour_second=min_hour_second,
                                        at_work_second=at_work_second,
                                        work_record_type=status,
                                        message=message,
                                        is_attendance_record=True,
                                        attendance_id=att,
                                        shift_id=att.shift_id,
                                        day_percentage=(
                                            1.00 if status == "FDP" and att.attendance_validated else
                                            0.50 if status == "HDP" and att.attendance_validated else
                                            0.25 if status == "SP" and att.attendance_validated else
                                            1.00 if att.attendance_validated and at_work_second > min_hour_second / 2 else
                                            0.50 if att.attendance_validated else 0.0
                                        )
                                    )
                                    work_records_to_create.append(work_record)
                            except Exception as e:
                                employee_name = getattr(att.employee_id, 'employee_first_name', 'Unknown')
                                self.stdout.write(
                                    self.style.ERROR(
                                        f'Error processing work record for {employee_name} on {att.attendance_date}: {str(e)}'
                                    )
                                )
                                error_count += 1
                        
                        # Bulk create/update work records
                        if work_records_to_create:
                            WorkRecords.objects.bulk_create(work_records_to_create, batch_size=100)
                            self.stdout.write(f'Created {len(work_records_to_create)} work records')
                        
                        if work_records_to_update:
                            # Protect SP records for past dates from being overwritten by bulk_update
                            from datetime import date as date_class
                            filtered_work_records = []
                            for wr in work_records_to_update:
                                if wr.work_record_type == "SP" and wr.date < date_class.today():
                                    continue
                                else:
                                    filtered_work_records.append(wr)
                            
                            if filtered_work_records:
                                WorkRecords.objects.bulk_update(
                                    filtered_work_records,
                                    ['at_work', 'min_hour', 'min_hour_second', 'at_work_second',
                                     'work_record_type', 'message', 'is_attendance_record',
                                     'attendance_id', 'shift_id', 'day_percentage'],
                                    batch_size=100
                                )
                                self.stdout.write(f'Updated {len(filtered_work_records)} work records')

                        # Late Come / Early Out: run automatically for synced attendances
                        try:
                            from attendance.late_come_early_out_utils import (
                                process_late_come_early_out_for_attendances,
                            )
                            lco_count = process_late_come_early_out_for_attendances(
                                created_attendances
                            )
                            if lco_count > 0:
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f'Processed Late Come/Early Out for {lco_count} attendances'
                                    )
                                )
                        except ImportError as e:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Skipping Late Come/Early Out: {e}'
                                )
                            )
                        except Exception as e:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Late Come/Early Out processing failed (sync continued): {e}'
                                )
                            )
                
                # Update counters from actual operations
                synced_count = len(attendances_to_create)
                updated_count = len(attendances_to_update)
                
                # Update device last fetch time (only if we processed records)
                if employee_daily_records and (synced_count > 0 or updated_count > 0):
                    # Always use max from ALL records fetched (not just processed ones)
                    # This ensures we don't miss any records on next sync
                    if original_attendances:
                        latest_scan = max(original_attendances, key=lambda x: x.timestamp)
                        updated_datetime = latest_scan.timestamp + timedelta(seconds=1)
                        device.last_fetch_date = updated_datetime.date()
                        device.last_fetch_time = updated_datetime.time()
                        device.save()
                        self.stdout.write(f'Updated last_fetch to: {device.last_fetch_date} {device.last_fetch_time}')
                
                # Summary
                sync_type = "Recent-only (last 20 days)" if recent_only else "Full sync (all records)"
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\nBiometric sync completed! ({sync_type})\n'
                        f'   New records: {synced_count}\n'
                        f'   Updated records: {updated_count}\n'
                        f'   Skipped (no mapping): {skipped_count}\n'
                        f'   Errors: {error_count}'
                    )
                )
                if recent_only:
                    self.stdout.write(
                        self.style.WARNING(
                            f'   Note: This was a recent-only sync. Full sync runs daily at 2 AM to catch any missed records.'
                        )
                    )
                
                # Detailed summary of skipped records
                if self._skipped_records:
                    self.stdout.write(
                        self.style.WARNING(
                            f'\nSkipped Records Details (no employee mapping found):'
                        )
                    )
                    for key, info in sorted(self._skipped_records.items()):
                        dates_str = ', '.join(sorted([str(d) for d in info['dates']])[:5])
                        if len(info['dates']) > 5:
                            dates_str += f' ... (+{len(info["dates"]) - 5} more dates)'
                        
                        # Build detailed info string
                        details_parts = [
                            f'{info["count"]} records',
                            f'Date range: {info["first_seen"].date()} to {info["last_seen"].date()}'
                        ]
                        
                        # Add device user name if available
                        if info.get('device_user_name'):
                            details_parts.append(f'Device name: "{info["device_user_name"]}"')
                        
                        # Add potential employee matches
                        if info.get('potential_employees'):
                            emp_list = []
                            for emp in info['potential_employees']:
                                emp_list.append(f'{emp["name"]} (badge_id={emp["badge_id"]}, emp_id={emp["id"]})')
                            details_parts.append(f'Potential match: {", ".join(emp_list)}')
                        
                        details_str = ' | '.join(details_parts)
                        
                        self.stdout.write(
                            self.style.WARNING(
                                f'   {key}: {details_str}'
                            )
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f'      Dates: {dates_str}'
                            )
                        )
                    
                    self.stdout.write(
                        self.style.WARNING(
                            f'\nTo fix: Create BiometricEmployees entries for these user_ids/uid in device "{device.name}"'
                        )
                    )
                    if any(info.get('potential_employees') for info in self._skipped_records.values()):
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'   Tip: Employees with matching badge_id found above - you can map them directly!'
                            )
                        )
                
            except zk_exception.ZKErrorResponse as e:
                self.stdout.write(
                    self.style.ERROR(f'ZK Device Error: {str(e)}')
                )
            except Exception as e:
                error_msg = str(e)
                if "Broken pipe" in error_msg or "Connection" in error_msg:
                    self.stdout.write(
                        self.style.WARNING(f'Device busy or connection lost, will retry on next scheduled run')
                    )
                    # Don't raise - let it fail gracefully and retry on next schedule
                    return
                else:
                    self.stdout.write(
                        self.style.ERROR(f'Connection Error: {error_msg}')
                    )
            finally:
                if 'conn' in locals() and conn is not None:
                    try:
                        # Properly cleanup connection
                        conn.disconnect()
                    except:
                        pass  # Ignore errors on disconnect
                    
        except BiometricDevices.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Device not found: {device_name}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Unexpected error: {str(e)}')
            )


