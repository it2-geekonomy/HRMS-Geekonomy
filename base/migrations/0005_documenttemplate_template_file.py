# Add optional uploaded Word template; body can be blank when using upload

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0004_add_default_employment_agreement_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttemplate",
            name="template_file",
            field=models.FileField(
                blank=True,
                help_text="Upload a Word (.docx) file with placeholders like {{ employee_name }}, {{ company_name }}, {{ job_position }}, {{ agreement_date }}. The generated document will keep your exact layout and formatting.",
                null=True,
                upload_to="base/document_templates/",
                verbose_name="Upload Template (Word .docx)",
            ),
        ),
        migrations.AlterField(
            model_name="documenttemplate",
            name="body",
            field=models.TextField(
                blank=True,
                help_text="Use {{ variable }} for placeholders. Ignored when an uploaded template file is used.",
                verbose_name="Template Content",
            ),
        ),
    ]
