from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0007_recruitment_survey_mandatory"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE recruitment_recruitment
                ADD COLUMN IF NOT EXISTS survey_mandatory boolean NOT NULL DEFAULT false;
            """,
            reverse_sql="""
                ALTER TABLE recruitment_recruitment
                DROP COLUMN IF EXISTS survey_mandatory;
            """,
        ),
    ]
