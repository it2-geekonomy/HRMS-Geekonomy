#!/usr/bin/env python
"""
Script to fetch biometric punch data for March 25, 2026
This script directly queries the biometric device to get raw punch times
"""
import os
import sys
import django
from datetime import datetime, date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from biometric.models import BiometricDevices, BiometricEmployees
from employee.models import Employee
from zk import ZK
from zk import exception as zk_exception

def get_biometric_data_for_date(target_date_str):
    """
    Fetch biometric punch data for a specific date
    
    Args:
        target_date_str: Date in YYYY-MM-DD format
    """
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    print(f"Fetching biometric data for: {target_date.strftime('%B %d, %Y')}")
    print("=" * 60)
    
    try:
        # Get biometric devices
        devices = BiometricDevices.objects.filter(machine_type='zk', is_live=True)
        
        if not devices:
            print("❌ No active ZKTeco biometric devices found")
            print("Available devices:")
            all_devices = BiometricDevices.objects.all()
            for device in all_devices:
                print(f"  - {device.name} ({device.machine_type}) - {'Live' if device.is_live else 'Not Live'}")
            return
        
        device = devices.first()
        print(f"📱 Using device: {device.name}")
        print(f"🌐 Device IP: {device.machine_ip}:{device.port}")
        
        # Connect to device
        print("\n🔌 Connecting to biometric device...")
        try:
            zk = ZK(device.machine_ip, port=device.port, timeout=30, ommit_ping=True)
            conn = zk.connect()
            print("✅ Connected successfully!")
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            print("Please check:")
            print("  1. Device is powered on")
            print("  2. Device is on same network")
            print("  3. IP address is correct")
            return
        
        try:
            # Get all attendance records
            print("\n📥 Fetching attendance records from device...")
            attendances = conn.get_attendance()
            print(f"📊 Total records on device: {len(attendances):,}")
            
            # Filter for target date
            target_attendances = []
            for att in attendances:
                if att.timestamp.date() == target_date:
                    target_attendances.append(att)
            
            print(f"🎯 Records for {target_date}: {len(target_attendances)}")
            
            if not target_attendances:
                print(f"\n❌ No attendance records found for {target_date}")
                return
            
            # Get employee mappings
            biometric_employees = BiometricEmployees.objects.filter(device_id=device)
            bio_id_map = {}
            
            for bio in biometric_employees:
                if bio.user_id:
                    bio_id_map[(device.id, str(bio.user_id))] = bio
                if bio.uid is not None:
                    bio_id_map[(device.id, str(bio.uid))] = bio
            
            # Get device users for names
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
                print(f"   ⚠️ Could not fetch device users: {e}")
            
            # Group by employee
            employee_records = {}
            
            for att in target_attendances:
                device_user_id = str(att.user_id) if hasattr(att, 'user_id') and att.user_id is not None else None
                device_uid = str(att.uid) if hasattr(att, 'uid') and att.uid is not None else None
                
                # Find employee mapping
                bio_id = None
                if device_user_id:
                    bio_id = bio_id_map.get((device.id, device_user_id))
                if not bio_id and device_uid:
                    bio_id = bio_id_map.get((device.id, device_uid))
                
                if bio_id:
                    employee = bio_id.employee_id
                    if employee.id not in employee_records:
                        employee_records[employee.id] = {
                            'employee': employee,
                            'punches': []
                        }
                    employee_records[employee.id]['punches'].append(att.timestamp)
                else:
                    # Unmapped record
                    identifier = device_user_id or device_uid or "unknown"
                    device_user_name = None
                    if device_user_id and device_user_id in device_users_map:
                        device_user_name = device_users_map[device_user_id].get('name')
                    elif device_uid and f'uid_{device_uid}' in device_users_map:
                        device_user_name = device_users_map[f'uid_{device_uid}'].get('name')
                    
                    print(f"⚠️ Unmapped punch: {identifier} at {att.timestamp} (Device name: {device_user_name})")
            
            # Display results
            print(f"\n👥 Employee Punch Data for {target_date}:")
            print("=" * 80)
            
            if not employee_records:
                print("❌ No mapped employee records found for this date")
                print("\n💡 To map employees:")
                print("1. Go to Biometric → Employees in Biometric Device")
                print("2. Map employee badge IDs to device user IDs")
                return
            
            for emp_id, data in sorted(employee_records.items()):
                employee = data['employee']
                punches = sorted(data['punches'])
                
                print(f"\n👤 {employee.employee_first_name} {employee.employee_last_name}")
                print(f"   🏷️  Badge ID: {employee.badge_id}")
                print(f"   📧 Email: {employee.email}")
                print(f"   📱 Phone: {employee.phone}")
                
                if punches:
                    first_punch = punches[0]
                    last_punch = punches[-1]
                    
                    print(f"   📍 Check-IN:  {first_punch.strftime('%I:%M:%S %p')}")
                    print(f"   📍 Check-OUT: {last_punch.strftime('%I:%M:%S %p')}")
                    print(f"   📊 Total Punches: {len(punches)}")
                    
                    if len(punches) > 2:
                        print(f"   ⏰ All Punches:")
                        for i, punch in enumerate(punches, 1):
                            print(f"      {i}. {punch.strftime('%I:%M:%S %p')}")
                    
                    # Calculate work hours if multiple punches
                    if len(punches) >= 2:
                        work_duration = last_punch - first_punch
                        total_seconds = int(work_duration.total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        print(f"   ⏱️  Work Duration: {hours}h {minutes}m")
                else:
                    print("   ❌ No punches recorded")
            
            print(f"\n📈 Summary:")
            print(f"   👥 Total Employees: {len(employee_records)}")
            print(f"   📊 Total Punches: {sum(len(data['punches']) for data in employee_records.values())}")
            
        finally:
            conn.disconnect()
            print("\n🔌 Disconnected from device")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    # Get March 25, 2026 data
    get_biometric_data_for_date("2026-03-25")
