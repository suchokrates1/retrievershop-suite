from magazyn.db import get_session, configure_engine
from magazyn.config import settings
from magazyn.models import PriceReport, PriceReportItem
configure_engine(settings.DB_PATH)

with get_session() as s:
    reports = s.query(PriceReport).order_by(PriceReport.id.desc()).limit(3).all()
    for r in reports:
        errors = s.query(PriceReportItem).filter(PriceReportItem.report_id == r.id, PriceReportItem.error != None).count()
        ok = s.query(PriceReportItem).filter(PriceReportItem.report_id == r.id, PriceReportItem.error == None).count()
        print(f"Raport #{r.id}: status={r.status}, checked={r.items_checked}/{r.items_total}, ok={ok}, errors={errors}")
