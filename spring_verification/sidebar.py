"""
spring_verification/sidebar.py
Sidebar menu for BGV - visible to staff/admin only.
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

MENU = _("BGV")
IMG_SRC = "images/ui/connection.png"
ACCESSIBILITY = "spring_verification.sidebar.spring_verification_accessibility"

SUBMENUS = [
    {
        "menu": _("Dashboard"),
        "redirect": reverse_lazy("spring-verification-dashboard"),
    },
    {
        "menu": _("Candidate Data"),
        "redirect": reverse_lazy("spring-verification-candidate-data"),
    },
]


def spring_verification_accessibility(request, menu, user_perms, *args, **kwargs):
    """Staff users or users with BGV view permission can see the menu."""
    if not request.user.is_authenticated:
        return False
    return (
        request.user.is_staff
        or request.user.has_perm("spring_verification.view_springverificationaccess")
    )
