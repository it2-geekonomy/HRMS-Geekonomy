"""
federal_tax.py

India New Regime TDS (computeTaxNewRegime):
- Standard deduction: ₹50,000 (applied to yearly gross)
- Slabs: 0–3L (0%), 3–7L (5%), 7–10L (10%), 10–12L (15%), 12–15L (20%), 15L+ (30%)
- Section 87A: zero tax only if taxable_income <= ₹7L (legal limit)
- Health & Education Cess: 4%
"""

STANDARD_DEDUCTION = 50000
CESS_RATE = 0.04


def calculate_federal_tax_india_new_regime(yearly_income, **kwargs):
    """
    India New Regime TDS (computeTaxNewRegime). yearly_income = annual taxable gross.
    Returns annual tax (after standard deduction, slabs, 87A, 4% cess).
    For taxable ~15,10,000: annual tax ₹1,48,720 → monthly TDS ₹12,393.33.
    """
    taxable_income = max(0.0, float(yearly_income) - STANDARD_DEDUCTION)
    tax = 0.0
    if taxable_income <= 300000:
        tax = 0
    elif taxable_income <= 700000:
        tax = 0.05 * (taxable_income - 300000)
    elif taxable_income <= 1000000:
        tax = 0.05 * 400000  # 20,000
        tax += 0.10 * (taxable_income - 700000)
    elif taxable_income <= 1200000:
        tax = 0.05 * 400000  # 20,000
        tax += 0.10 * 300000  # 30,000
        tax += 0.15 * (taxable_income - 1000000)
    elif taxable_income <= 1500000:
        tax = 0.05 * 400000  # 20,000
        tax += 0.10 * 300000  # 30,000
        tax += 0.15 * 200000  # 30,000
        tax += 0.20 * (taxable_income - 1200000)
    else:
        tax = 0.05 * 400000  # 20,000
        tax += 0.10 * 300000  # 30,000
        tax += 0.15 * 200000  # 30,000
        tax += 0.20 * 300000  # 60,000
        tax += 0.30 * (taxable_income - 1500000)
    # Section 87A rebate: applies only up to ₹7,00,000 (as per Indian income tax rules)
    if taxable_income <= 700000:
        tax = 0
    tax_with_cess = tax * (1 + CESS_RATE)
    return round(tax_with_cess, 2)


# Default Python code for FilingStatus when use_py=True (India New Regime – computeTaxNewRegime)
CODE = '''
"""
India New Regime TDS (computeTaxNewRegime). Standard deduction ₹50,000.
Slabs: 0-3L, 3-7L (5%%), 7-10L (10%%), 10-12L (15%%), 12-15L (20%%), 15L+ (30%%).
Section 87A: zero tax only if taxable_income <= 7L. 4%% cess.
"""
STANDARD_DEDUCTION = 50000
CESS_RATE = 0.04

def calculate_federal_tax(yearly_income, **kwargs):
    taxable_income = max(0, float(yearly_income) - STANDARD_DEDUCTION)
    tax = 0.0
    if taxable_income <= 300000:
        tax = 0
    elif taxable_income <= 700000:
        tax = 0.05 * (taxable_income - 300000)
    elif taxable_income <= 1000000:
        tax = 0.05 * 400000
        tax += 0.10 * (taxable_income - 700000)
    elif taxable_income <= 1200000:
        tax = 0.05 * 400000 + 0.10 * 300000
        tax += 0.15 * (taxable_income - 1000000)
    elif taxable_income <= 1500000:
        tax = 0.05 * 400000 + 0.10 * 300000 + 0.15 * 200000
        tax += 0.20 * (taxable_income - 1200000)
    else:
        tax = 0.05 * 400000 + 0.10 * 300000 + 0.15 * 200000 + 0.20 * 300000
        tax += 0.30 * (taxable_income - 1500000)
    if taxable_income <= 700000:
        tax = 0
    tax_with_cess = tax * (1 + CESS_RATE)
    return round(tax_with_cess, 2)

def formated_result(brackets, taxable_amount):
    pass
'''
