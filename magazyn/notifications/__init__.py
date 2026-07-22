"""
Modul powiadomien - centralizuje wysylanie wiadomosci.
"""

from .messenger import send_messenger, MessengerClient
from .reports import send_report, ReportGenerator
from .alerts import send_stock_alert, send_email, send_critical_alert

__all__ = [
    'send_messenger',
    'MessengerClient',
    'send_report',
    'ReportGenerator',
    'send_stock_alert',
    'send_email',
    'send_critical_alert',
]
