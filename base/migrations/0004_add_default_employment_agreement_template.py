# Data migration: create default Employment Agreement document template

from django.db import migrations


DEFAULT_EMPLOYMENT_AGREEMENT_BODY = """EMPLOYMENT AGREEMENT

This Employment Agreement ("Agreement") is made on {{ agreement_date }}

BETWEEN
{{ company_name }},
a company incorporated under the Companies Act, 2013, having its registered office at {{ company_address }}, and operating in accordance with applicable laws of the State of Karnataka,
(hereinafter referred to as the "Company" or "Geekonomy")
AND
{{ employee_name }},
an Indian citizen, residing at {{ employee_address }} (hereinafter referred to as the "Employee" or "You").
The Company and the Employee shall individually be referred to as a "Party" and collectively as the "Parties".

1. APPOINTMENT & COMMENCEMENT
1.1 The Company appoints you as {{ job_position }} on a full-time basis with effect from {{ employment_commencement_date }} ("Employment Commencement Date").
1.2 You shall devote your entire professional time, attention, skill, and effort exclusively to the business of the Company.
1.3 This Agreement constitutes the complete, binding, and exclusive terms governing your employment with the Company.

2. PROBATION
2.1 You shall be on probation for a period of three (3) months from the Employment Commencement Date.
2.2 The Company may extend the probation period at its sole discretion based on performance, conduct, attendance, or business requirements in compliance with the employee handbook.
2.3 During probation, the Company may terminate your employment without notice or payment in lieu thereof, subject to applicable law.
2.4 Confirmation of employment shall be at the discretion of the Company and shall not be deemed automatic.

3. DUTIES, RESPONSIBILITIES & OBLIGATIONS
3.1 You shall perform all duties and responsibilities assigned by the Company diligently, efficiently, and in good faith.
3.2 You shall act at all times in the best interests of the Company, its clients, and stakeholders and shall not engage in any act or omission that may be prejudicial to the Company.
3.3 The Company reserves the right to modify your role, responsibilities, reporting structure, designation, or department at any time based on business needs.

4. WORKING HOURS, AVAILABILITY & LOCATION
4.1 Your employment is outcome-based and not restricted to fixed working hours.
4.2 You may be required to work beyond standard working hours, including weekends or holidays, to meet business, project, or client requirements.
4.3 Your primary work location shall be at our office, located at {{ work_location }}.
4.4 Any remote or hybrid work arrangement is a revocable privilege and may be withdrawn by the Company at any time. In case of any ad-hoc remote work, it should be approved by the Reporting Manager.
4.5 Unauthorized absence for not more than 3 days, poor availability, or repeated attendance issues may result in disciplinary action.

5. COMPENSATION, CONFIDENTIALITY & RECOVERY
5.1 Your compensation shall be communicated separately by the Company in annexure -1 of the appointment letter and may be revised at the Company's discretion.
5.2 Compensation details are strictly confidential and must not be disclosed to any unauthorized person.
5.3 All payments shall be subject to applicable statutory deductions and contributions.
5.4 The Company reserves the right to recover losses, damages, costs, or liabilities caused due to your negligence, misconduct, breach of trust, or violation of this Agreement, to the extent permitted by law.

6. LEAVE & HOLIDAYS
6.1 The leave year shall be from January 1 to December 31.
6.2 Leave Entitlements:
• Casual Leave: 12 days per year (non-carry forward)
• Sick Leave: 7 days per year (non-carry forward; medical proof will be required on crossing 3 days)
• Earned Leave: 15 days per year earned on a pro-rata basis of 1.25 days per month, accruing progressively, with carry forward permitted up to a maximum of 30 days.
6.3 Unused Casual Leave and Sick Leave shall lapse at the end of the leave year.
6.4 Leave is subject to management approval and business continuity requirements.

7. CODE OF CONDUCT & WORKPLACE BEHAVIOUR
7.1 You shall maintain the highest standards of professionalism, integrity, discipline, and ethical conduct.
7.2 The Company maintains zero tolerance for harassment, discrimination, intimidation, abuse, violence or threats, substance abuse during work hours, or any unlawful or unethical conduct. Any violation may result in immediate disciplinary action, including termination.

8. PERFORMANCE & ACCOUNTABILITY
8.1 You are expected to meet performance, quality, and delivery standards as defined by the company.
8.2 Persistent underperformance, negligence, or failure to meet expectations may result in warnings, performance action, or termination.

9. CONFIDENTIALITY
9.1 You shall maintain strict confidentiality of all non-public information relating to the Company, its clients, vendors, employees, and business operations.
9.2 Confidentiality obligations will remain in effect indefinitely following the termination of employment.

10. INTELLECTUAL PROPERTY
10.1 All work, inventions, designs, software, content, documentation, processes, improvements, and concepts created during the course of employment shall be the exclusive property of the Company and/or its clients.
10.2 You irrevocably assign all intellectual property rights arising from such work to the Company.

11. TERMINATION
11.1 Either Party may terminate this Agreement by providing thirty (30) days written notice or payment in lieu thereof.
11.2 The Company may terminate employment without notice in cases of gross misconduct, breach of confidentiality or intellectual property, loss of trust, or reputational risk.

12. GOVERNING LAW & JURISDICTION
This Agreement shall be governed by and construed in accordance with the laws of India, as applicable in the State of Karnataka. The courts at Bengaluru, Karnataka, shall have exclusive jurisdiction.

13. ENTIRE AGREEMENT
This Agreement constitutes the entire understanding between the Parties and supersedes all prior discussions or communications.

14. ACCEPTANCE
By signing below, you confirm that you have read, understood, and agreed to all terms and conditions of this Agreement.

For {{ company_name }}
Authorized Signatory
Name: {{ signatory_name }}
Designation: {{ signatory_designation }}
Signature:
Date:

Employee
Name: {{ employee_name }}
Signature:
Date:

END OF AGREEMENT
"""


def create_default_template(apps, schema_editor):
    DocumentTemplate = apps.get_model("base", "DocumentTemplate")
    if DocumentTemplate.objects.filter(template_type="employment_agreement").exists():
        return
    DocumentTemplate.objects.create(
        name="Employment Agreement",
        template_type="employment_agreement",
        body=DEFAULT_EMPLOYMENT_AGREEMENT_BODY,
        signatory_name="",
        signatory_designation="Human Resources",
    )


def reverse_create(apps, schema_editor):
    DocumentTemplate = apps.get_model("base", "DocumentTemplate")
    DocumentTemplate.objects.filter(name="Employment Agreement", template_type="employment_agreement").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0003_add_document_template"),
    ]

    operations = [
        migrations.RunPython(create_default_template, reverse_create),
    ]
