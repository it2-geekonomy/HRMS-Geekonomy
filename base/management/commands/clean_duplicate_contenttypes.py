"""
Remove duplicate ContentType rows (same app_label + model).

Fixes: "get() returned more than one ContentType -- it returned 2!"

Run on live after backing up DB:
  python manage.py clean_duplicate_contenttypes
  python manage.py clean_duplicate_contenttypes --dry-run
"""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Remove duplicate ContentType rows for the same (app_label, model). "
        "Use --dry-run to only report what would be done."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be done; do not change the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made."))

        # Find (app_label, model) with more than one ContentType
        from django.db.models import Count

        dupes = (
            ContentType.objects.values("app_label", "model")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        if not dupes:
            self.stdout.write(self.style.SUCCESS("No duplicate ContentTypes found."))
            return

        for row in dupes:
            app_label, model_name = row["app_label"], row["model"]
            cts = list(
                ContentType.objects.filter(
                    app_label=app_label, model=model_name
                ).order_by("id")
            )
            keep = cts[0]
            duplicates = cts[1:]
            self.stdout.write(
                f"  {app_label}.{model_name}: keep id={keep.id}, remove ids={[d.id for d in duplicates]}"
            )
            if dry_run:
                continue

            with transaction.atomic():
                for dup in duplicates:
                    self._repoint_and_delete(keep, dup)

        self.stdout.write(self.style.SUCCESS("Done."))

    def _repoint_and_delete(self, keep_ct, dup_ct):
        """Point all references from dup_ct to keep_ct, then delete dup_ct."""
        # 1) Permissions: (content_type, codename) is unique — merge or delete
        for perm in Permission.objects.filter(content_type=dup_ct):
            if Permission.objects.filter(
                content_type=keep_ct, codename=perm.codename
            ).exists():
                perm.delete()
            else:
                perm.content_type = keep_ct
                perm.save()

        # 2) Admin LogEntry (if used)
        try:
            from django.contrib.admin.models import LogEntry

            LogEntry.objects.filter(content_type=dup_ct).update(content_type=keep_ct)
        except Exception:
            pass

        # 3) Notifications: actor_content_type, target_content_type, action_object_content_type
        try:
            from notifications.models import Notification

            Notification.objects.filter(actor_content_type=dup_ct).update(
                actor_content_type=keep_ct
            )
            Notification.objects.filter(target_content_type=dup_ct).update(
                target_content_type=keep_ct
            )
            Notification.objects.filter(action_object_content_type=dup_ct).update(
                action_object_content_type=keep_ct
            )
        except Exception:
            pass

        dup_ct.delete()
