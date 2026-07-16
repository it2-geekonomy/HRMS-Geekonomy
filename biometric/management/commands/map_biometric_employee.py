"""
Map an existing Horilla employee to a biometric device user_id.

Use this when the employee is already enrolled on the device (e.g. user_id=30)
but not yet mapped in BiometricEmployees. After mapping, sync will import
attendance for this employee.

Example:
  python manage.py map_biometric_employee --employee "Sai Akash" --user-id 30
  python manage.py map_biometric_employee --employee EMP0033 --user-id 30 --device "eSSL Office Device"
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from biometric.models import BiometricDevices, BiometricEmployees
from employee.models import Employee


class Command(BaseCommand):
    help = "Map an employee to a biometric device user_id (for already-enrolled device users)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee",
            type=str,
            required=True,
            help='Employee: ID, badge_id (e.g. EMP0033), or name search (e.g. "Sai Akash")',
        )
        parser.add_argument(
            "--user-id",
            type=str,
            required=True,
            help="Biometric device user_id (e.g. 30)",
        )
        parser.add_argument(
            "--device",
            type=str,
            default="eSSL Office Device",
            help='Biometric device name (default: "eSSL Office Device")',
        )
        parser.add_argument(
            "--uid",
            type=int,
            default=None,
            help="Optional: device uid if known (for dual matching)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without creating the mapping",
        )

    def handle(self, *args, **options):
        employee_arg = options["employee"].strip()
        user_id = str(options["user_id"]).strip()
        device_name = options["device"].strip()
        uid = options["uid"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN ===\n"))

        # Resolve device
        try:
            device = BiometricDevices.objects.get(name=device_name)
        except BiometricDevices.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Device "{device_name}" not found.')
            )
            return

        # Resolve employee (ID, badge_id, or name)
        employee = None
        if employee_arg.isdigit():
            try:
                employee = Employee.objects.get(id=int(employee_arg))
            except Employee.DoesNotExist:
                pass
        if not employee:
            try:
                employee = Employee.objects.get(badge_id__iexact=employee_arg)
            except (Employee.DoesNotExist, Employee.MultipleObjectsReturned):
                pass
        if not employee:
            from django.db.models import Q
            q = (
                Q(employee_first_name__icontains=employee_arg)
                | Q(employee_last_name__icontains=employee_arg)
            )
            matches = list(Employee.objects.filter(q)[:5])
            if len(matches) == 1:
                employee = matches[0]
            elif len(matches) > 1:
                self.stdout.write(
                    self.style.WARNING(
                        f'Multiple employees match "{employee_arg}": '
                        + ", ".join(f"{e.get_full_name()} (id={e.id})" for e in matches)
                    )
                )
                self.stdout.write(
                    self.style.WARNING('Use --employee <id> or --employee <badge_id> to pick one.')
                )
                return

        if not employee:
            self.stdout.write(
                self.style.ERROR(f'Employee "{employee_arg}" not found.')
            )
            return

        # Check existing mapping
        existing = BiometricEmployees.objects.filter(
            device_id=device, user_id=user_id
        ).first()
        if existing:
            if existing.employee_id_id == employee.id:
                self.stdout.write(
                    self.style.WARNING(
                        f'Employee {employee.get_full_name()} is already mapped to user_id={user_id} on "{device_name}".'
                    )
                )
                return
            self.stdout.write(
                self.style.ERROR(
                    f'user_id={user_id} on "{device_name}" is already mapped to '
                    f'{existing.employee_id.get_full_name()}. Remove that mapping first if you need to reassign.'
                )
            )
            return

        same_employee_other_device = BiometricEmployees.objects.filter(
            employee_id=employee, device_id=device
        ).first()
        if same_employee_other_device:
            self.stdout.write(
                self.style.ERROR(
                    f'{employee.get_full_name()} is already mapped on this device '
                    f'with user_id={same_employee_other_device.user_id}. '
                    f'Update or delete that mapping first.'
                )
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Would create: {employee.get_full_name()} (id={employee.id}) '
                    f'<-> user_id={user_id} on "{device_name}"'
                )
            )
            return

        with transaction.atomic():
            BiometricEmployees.objects.create(
                employee_id=employee,
                user_id=user_id,
                device_id=device,
                uid=uid,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Mapped {employee.get_full_name()} (id={employee.id}) to user_id={user_id} on "{device_name}". '
                f'Run sync (or wait for scheduled sync) to import attendance.'
            )
        )
