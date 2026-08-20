import calendar
from django import template

register = template.Library()


@register.filter(name="month_abbr")
def month_abbr(month_num):
    """Return abbreviated month name (Jan, Feb, ...) for month number 1-12."""
    if month_num is None:
        return ""
    try:
        n = int(month_num)
        if 1 <= n <= 12:
            return calendar.month_abbr[n]
        return str(month_num)
    except (ValueError, TypeError, IndexError):
        return str(month_num)


@register.filter(name="subtract")
def subtract(value, arg):
    """Return value - arg (for template arithmetic)."""
    try:
        return float(value) - float(arg)
    except (TypeError, ValueError):
        return value


@register.filter(name="paid_amount")
def paid_amount(installment):
    paid = [
        deduction.amount for deduction in installment if deduction.installment_payslip()
    ]

    return sum(paid)


def _is_professional_tax_title(title):
    compact = (title or "").lower().replace(" ", "").replace("(", "").replace(")", "")
    return compact in ("professionaltax", "pt", "ptprofessionaltax") or "professionaltax" in compact


@register.filter(name="is_professional_tax")
def is_professional_tax(title):
    """True if this deduction title is Professional Tax / PT."""
    return _is_professional_tax_title(title)


def _is_income_tax_title(title):
    compact = (title or "").lower().replace(" ", "").replace("(", "").replace(")", "")
    return compact in ("incometax", "federaltax") or "incometax" in compact


@register.filter(name="is_income_tax")
def is_income_tax(title):
    """True if this deduction title is Income Tax / federal tax."""
    return _is_income_tax_title(title)


@register.simple_tag
def professional_tax_amount(*deduction_lists):
    """Return the Professional Tax amount from any payslip deduction list."""
    for items in deduction_lists:
        for item in items or []:
            if isinstance(item, dict):
                title = item.get("title") or ""
                amount = item.get("amount") or 0
            else:
                title = getattr(item, "title", "") or ""
                amount = getattr(item, "amount", 0) or 0
            if _is_professional_tax_title(title):
                return amount
    return 0


@register.filter(name="format_days")
def format_days(value):
    """Show day counts as 21 or 0.5 — no trailing .0 for whole numbers."""
    if value is None or value == "":
        return "0"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num == int(num):
        return str(int(num))
    return f"{num:.1f}".rstrip("0").rstrip(".")


@register.filter(name="balance_amount")
def balance_amount(amount, installment):
    balance = amount - paid_amount(installment)
    return balance
