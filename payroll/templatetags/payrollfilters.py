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


@register.filter(name="balance_amount")
def balance_amount(amount, installment):
    balance = amount - paid_amount(installment)
    return balance
