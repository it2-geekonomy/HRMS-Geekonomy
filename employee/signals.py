"""
Employee Signals
Signals for employee-related events
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from employee.models import Employee, EmployeeWorkInformation
from base.models import EmployeeShift


@receiver(post_save, sender=Employee)
def link_new_employee_to_slack(sender, instance, created, **kwargs):
    """
    When a new employee is created with an email, try to set slack_user_id from
    Slack (users.list match by email). Slack User ID is not shown in the form;
    it is set automatically.
    """
    if not created:
        return
    from employee.slack_presence import link_employee_to_slack

    link_employee_to_slack(instance)


@receiver(post_save, sender=Employee)
def assign_default_shift_to_new_employee(sender, instance, created, **kwargs):
    """
    Automatically assign default shift to new employees
    
    This signal ensures that every new employee gets assigned the 'Regular Shift'
    (9:00 AM - 6:00 PM) automatically, which enables Late Come/Early Out tracking
    to work immediately without manual intervention.
    """
    if created:  # Only for newly created employees
        try:
            # Get the default shift
            default_shift = EmployeeShift.objects.filter(employee_shift="Regular Shift").first()
            
            if default_shift:
                # Create work information with default shift
                work_info, work_info_created = EmployeeWorkInformation.objects.get_or_create(
                    employee_id=instance,
                    defaults={
                        'shift_id': default_shift,
                    }
                )
                
                if not work_info_created:
                    # Update existing work info if no shift assigned
                    if not work_info.shift_id:
                        work_info.shift_id = default_shift
                        work_info.save()
                        print(f"[OK] Updated shift assignment for {instance.employee_first_name}")
                else:
                    print(f"[OK] Automatically assigned 'Regular Shift' to {instance.employee_first_name}")
                    
            else:
                print(f"[WARNING] Default shift 'Regular Shift' not found for {instance.employee_first_name}")
                
        except Exception as e:
            print(f"[ERROR] Error assigning shift to {instance.employee_first_name}: {e}")


