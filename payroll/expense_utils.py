"""Helpers for expense category breakups."""

import io
import os
import re
import zipfile
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext_lazy as _

from payroll.models.models import Expense, ExpenseBreakup


def get_expense_category_groups(expense=None):
    """Build category + line structure for the expense form."""
    default = [
        {
            "name": "",
            "name_error": "",
            "lines": [
                {
                    "particular": "",
                    "amount": "",
                    "errors": {},
                }
            ],
        }
    ]
    if not expense or not expense.pk:
        return default
    groups = OrderedDict()
    for line in expense.breakups.all().order_by("id"):
        category = line.category or ""
        groups.setdefault(category, []).append(
            {
                "particular": line.particular,
                "amount": line.amount,
                "errors": {},
            }
        )
    if not groups:
        return default
    return [
        {"name": name, "name_error": "", "lines": lines}
        for name, lines in groups.items()
    ]


def parse_category_breakups_from_post(post):
    """Parse cat_{n}_name and cat_{n}_line_{m}_* fields from POST data."""
    cat_indices = set()
    for key in post:
        match = re.match(r"cat_(\d+)_name", key)
        if match:
            cat_indices.add(int(match.group(1)))

    categories = []
    for cat_index in sorted(cat_indices):
        name = (post.get(f"cat_{cat_index}_name") or "").strip()
        line_indices = set()
        for key in post:
            match = re.match(rf"cat_{cat_index}_line_(\d+)_particular", key)
            if match:
                line_indices.add(int(match.group(1)))

        lines = []
        for line_index in sorted(line_indices):
            particular = (
                post.get(f"cat_{cat_index}_line_{line_index}_particular") or ""
            ).strip()
            amount_raw = post.get(f"cat_{cat_index}_line_{line_index}_amount") or "0"
            try:
                amount = Decimal(str(amount_raw).replace(",", "").strip() or "0")
            except (InvalidOperation, ValueError):
                amount = Decimal("0")
            if particular or amount:
                lines.append({"particular": particular, "amount": amount})

        if name or lines:
            categories.append({"name": name, "lines": lines})

    return categories


def category_groups_from_post(post):
    """Return template-friendly groups from POST (for re-render on validation errors)."""
    categories = parse_category_breakups_from_post(post)
    if not categories:
        return get_expense_category_groups()
    result = []
    for category in categories:
        lines = category["lines"] or [{"particular": "", "amount": ""}]
        result.append(
            {
                "name": category["name"],
                "name_error": "",
                "lines": [
                    {
                        "particular": line["particular"],
                        "amount": line["amount"],
                        "errors": {},
                    }
                    for line in lines
                ],
            }
        )
    return result


def validate_expense_category_groups(category_groups):
    """
    Validate category breakup rows and attach inline errors for the template.
    Returns (is_valid, general_errors, category_groups).
    """
    general_errors = []
    is_valid = True
    has_valid_line = False

    if not category_groups:
        category_groups = get_expense_category_groups()

    for group in category_groups:
        group["name_error"] = ""
        name = (group.get("name") or "").strip()
        if not name:
            group["name_error"] = _("This field is required.")
            is_valid = False

        lines = group.get("lines") or [{"particular": "", "amount": ""}]
        group_has_valid_line = False

        for line in lines:
            line_errors = {}
            particular = (str(line.get("particular") or "")).strip()
            amount_raw = line.get("amount")
            if isinstance(amount_raw, Decimal):
                amount = amount_raw
            else:
                amount_text = str(amount_raw or "").strip().replace(",", "")
                try:
                    amount = Decimal(amount_text or "0")
                except (InvalidOperation, ValueError):
                    amount = Decimal("0")

            if not particular:
                line_errors["particular"] = _("This field is required.")
            if not amount or amount <= 0:
                line_errors["amount"] = _("Enter a valid amount greater than 0.")

            line["errors"] = line_errors

            if particular and amount > 0:
                group_has_valid_line = True
                has_valid_line = True
            elif line_errors:
                is_valid = False

        if name and not group_has_valid_line:
            is_valid = False

    if not has_valid_line:
        general_errors.append(
            _("Please add at least one category with particular and amount.")
        )
        is_valid = False

    return is_valid, general_errors, category_groups


def validate_expense_category_breakups(categories):
    """Validate parsed category data (used when saving from POST)."""
    category_groups = []
    for category in categories:
        category_groups.append(
            {
                "name": category.get("name") or "",
                "lines": [
                    {
                        "particular": line.get("particular") or "",
                        "amount": line.get("amount") or "",
                    }
                    for line in category.get("lines") or []
                ]
                or [{"particular": "", "amount": ""}],
            }
        )
    is_valid, general_errors, _ = validate_expense_category_groups(category_groups)
    if is_valid:
        return True, None
    if general_errors:
        return False, general_errors[0]
    for group in category_groups:
        if group.get("name_error"):
            return False, _("Category name is required.")
        for line in group.get("lines") or []:
            errors = line.get("errors") or {}
            if errors.get("particular"):
                return False, _("Particular is required for each breakup line.")
            if errors.get("amount"):
                return False, _("Amount is required for each breakup line.")
    return False, _("Please complete all required breakup fields.")


def save_expense_category_breakups(expense, categories):
    """Replace breakup lines from validated category groups."""
    expense.breakups.all().delete()
    for category in categories:
        name = category["name"]
        for line in category["lines"]:
            if not line["particular"]:
                continue
            ExpenseBreakup.objects.create(
                expense=expense,
                category=name,
                particular=line["particular"],
                amount=line["amount"] or 0,
            )
    return True, None


def archive_expenses_for_month(queryset, year, month, remove_receipts=False):
    """
    Archive all non-archived expenses in queryset for the given calendar month.
    Optionally delete receipt files from storage to free disk space.
    Returns (archived_count, receipts_removed_count).
    """
    expenses = queryset.filter(
        expense_date__year=year,
        expense_date__month=month,
        archived=False,
    )
    archived_count = 0
    receipts_removed = 0
    for expense in expenses:
        update_fields = ["archived"]
        if remove_receipts and expense.attachment:
            try:
                expense.attachment.delete(save=False)
            except Exception:
                pass
            expense.attachment = None
            update_fields.append("attachment")
            receipts_removed += 1
        expense.archived = True
        expense.save(update_fields=update_fields)
        archived_count += 1
    return archived_count, receipts_removed


def _expense_receipt_upload_date(expense):
    """Date used for receipt file naming (upload / created date)."""
    if expense.created_at:
        return expense.created_at.date()
    return expense.expense_date


def receipt_filename_for_expense(expense, used_names=None):
    """
    Build a zip entry name from the receipt upload date.
    Example: 2025-06-06_Rajesh_Kumar_42.pdf
    """
    used_names = used_names if used_names is not None else set()
    upload_date = _expense_receipt_upload_date(expense)
    date_str = upload_date.strftime("%Y-%m-%d")
    employee_name = ""
    if expense.added_by_id:
        employee_name = expense.added_by.get_full_name() or str(expense.added_by)
    safe_employee = re.sub(r"[^\w\-]+", "_", employee_name.strip()) or "employee"
    ext = os.path.splitext(expense.attachment.name)[1].lower()
    base = f"{date_str}_{safe_employee}_{expense.id}{ext}"
    if base not in used_names:
        used_names.add(base)
        return base
    counter = 2
    while True:
        candidate = f"{date_str}_{safe_employee}_{expense.id}_{counter}{ext}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        counter += 1


def build_expense_receipts_zip(expenses):
    """
    Pack expense receipt files into an in-memory zip.
    Returns (BytesIO buffer, files_added_count).
    """
    buffer = io.BytesIO()
    used_names = set()
    files_added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for expense in expenses:
            if not expense.attachment:
                continue
            try:
                if not expense.attachment.storage.exists(expense.attachment.name):
                    continue
                archive_name = receipt_filename_for_expense(expense, used_names)
                with expense.attachment.open("rb") as receipt_file:
                    archive.writestr(archive_name, receipt_file.read())
                files_added += 1
            except Exception:
                continue
    buffer.seek(0)
    return buffer, files_added
