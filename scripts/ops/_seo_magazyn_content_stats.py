#!/usr/bin/env python3
import os

os.environ["DISABLE_SCHEDULERS"] = "1"

from sqlalchemy import func

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer

app = create_app()
with app.app_context():
    with get_session() as db:
        total = db.query(AllegroOffer).count()
        by = dict(
            db.query(AllegroOffer.publication_status, func.count())
            .group_by(AllegroOffer.publication_status)
            .all()
        )
        with_html = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.description_html.isnot(None),
                AllegroOffer.description_html != "",
            )
            .count()
        )
        active = by.get("ACTIVE", 0)
        active_html = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.publication_status == "ACTIVE",
                AllegroOffer.description_html.isnot(None),
                AllegroOffer.description_html != "",
            )
            .count()
        )
        ended = by.get("ENDED", 0)
        ended_html = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.publication_status == "ENDED",
                AllegroOffer.description_html.isnot(None),
                AllegroOffer.description_html != "",
            )
            .count()
        )
        print("offers_total", total)
        print("by_status", by)
        print("with_description_html", with_html)
        print("ACTIVE_with_html", f"{active_html}/{active}")
        print("ENDED_with_html", f"{ended_html}/{ended}")
