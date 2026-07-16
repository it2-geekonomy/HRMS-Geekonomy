"""
Module: payroll.tax_calc

This module contains a function for calculating the taxable amount for an employee
based on their contract details and income information.
"""

import datetime
import logging

from payroll.methods.methods import (
    compute_yearly_taxable_amount,
    convert_year_tax_to_period,
)
from payroll.methods.federal_tax import calculate_federal_tax_india_new_regime
from payroll.methods.payslip_calc import (
    calculate_gross_pay,
    calculate_taxable_gross_pay,
)
from payroll.models.models import Contract
from payroll.models.tax_models import TaxBracket

logger = logging.getLogger(__name__)


def calculate_taxable_amount(**kwargs):
    """Calculate the taxable amount for a given employee within a specific period.

    Args:
        employee (int): The ID of the employee.
        start_date (datetime.date): The start date of the period.
        end_date (datetime.date): The end date of the period.
        allowances (int): The number of allowances claimed by the employee.
        total_allowance (float): The total allowance amount.
        basic_pay (float): The basic pay amount.
        day_dict (dict): A dictionary containing specific day-related information.

    Returns:
        float: The federal tax amount for the specified period.
    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    basic_pay = kwargs["basic_pay"]
    contract = Contract.objects.filter(
        employee_id=employee, contract_status="active"
    ).first()
    if not contract:
        return 0
    filing = contract.filing_status
    if not filing:
        return 0
    federal_tax_for_period = 0
    tax_brackets = TaxBracket.objects.filter(filing_status_id=filing).order_by(
        "min_income"
    )
    num_days = (end_date - start_date).days + 1
    calculation_functions = {
        "taxable_gross_pay": calculate_taxable_gross_pay,
        "gross_pay": calculate_gross_pay,
    }
    based = filing.based_on
    if based in calculation_functions:
        calculation_function = calculation_functions[based]
        income = calculation_function(**kwargs)
        income = float(income[based])
    else:
        income = float(basic_pay)

    year = end_date.year
    check_start_date = datetime.date(year, 1, 1)
    check_end_date = datetime.date(year, 12, 31)
    total_days = (check_end_date - check_start_date).days + 1
    # Use India New Regime when: Python Code is on, or Filing Status name suggests "New" / "India" / "TDS"
    _name = (getattr(filing, "filing_status", None) or "").strip().lower()
    use_india_new_regime = filing.use_py or any(
        x in _name for x in ("new", "india", "tds")
    )
    if use_india_new_regime:
        # India TDS: annualize by months (period income = monthly × months_in_period, so yearly = income × 12 / months)
        months_in_period = (
            (end_date.year - start_date.year) * 12
            + (end_date.month - start_date.month)
            + 1
        )
        yearly_income = income * (12 / months_in_period) if months_in_period else income
    else:
        yearly_income = income / num_days * total_days
    yearly_income = compute_yearly_taxable_amount(income, yearly_income)
    yearly_income = round(yearly_income, 2)
    federal_tax = 0
    if use_india_new_regime:
        federal_tax = calculate_federal_tax_india_new_regime(yearly_income)
    elif filing is not None and not filing.use_py:
        brackets = [
            {
                "rate": item["tax_rate"],
                "min": item["min_income"],
                "max": min(item["max_income"], yearly_income),
            }
            for item in tax_brackets.values("tax_rate", "min_income", "max_income")
        ]
        filterd_brackets = []
        for bracket in brackets:
            if bracket["max"] > bracket["min"]:
                bracket["diff"] = bracket["max"] - bracket["min"]
                bracket["calculated_rate"] = (bracket["rate"] / 100) * bracket["diff"]
                filterd_brackets.append(bracket)
                continue
            break
        federal_tax = sum(bracket["calculated_rate"] for bracket in filterd_brackets)

    federal_tax_for_period = 0
    if federal_tax and (tax_brackets.exists() or use_india_new_regime):
        # India New Regime: monthly TDS = annual_tax / 12 per month
        if use_india_new_regime:
            months_in_period = (
                (end_date.year - start_date.year) * 12
                + (end_date.month - start_date.month)
                + 1
            )
            federal_tax_for_period = federal_tax * (months_in_period / 12)
        else:
            daily_federal_tax = federal_tax / total_days
            federal_tax_for_period = daily_federal_tax * num_days

    federal_tax_for_period = convert_year_tax_to_period(
        federal_tax_for_period=federal_tax_for_period,
        yearly_tax=federal_tax,
        total_days=total_days,
        start_date=start_date,
        end_date=end_date,
    )
    return federal_tax_for_period
