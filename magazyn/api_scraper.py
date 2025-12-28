"""
API endpoints for external scraper workers.

Scraper workflow:
1. Scraper polls GET /api/scraper/get_tasks
2. Scraper processes tasks (searches Allegro)
3. Scraper submits POST /api/scraper/submit_results
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from sqlalchemy import text
from magazyn.db import SessionLocal

api_scraper_bp = Blueprint("api_scraper", __name__, url_prefix="/api/scraper")


def with_session(func):
    """Decorator to handle session lifecycle"""
    def wrapper(*args, **kwargs):
        session = SessionLocal()
        try:
            return func(session, *args, **kwargs)
        finally:
            session.close()
    wrapper.__name__ = func.__name__
    return wrapper


@api_scraper_bp.route("/get_tasks", methods=["GET"])
@with_session
def get_tasks(session):
    """
    Returns Allegro offers that need price checking.
    
    Query params:
        limit (int): Max offers to return (default: 10)
    
    Returns:
        {
            "offers": [
                {
                    "offer_id": "12345678901",
                    "url": "https://allegro.pl/oferta/12345678901",
                    "title": "Product name",
                    "my_price": "159.99"
                }
            ],
            "count": 2
        }
    """
    limit = request.args.get("limit", 10, type=int)
    limit = min(limit, 100)  # Max 100 at once
    
    # Get active offers that need price check
    # Only check offers that haven't been checked in the last hour
    result = session.execute(
        text("""
        SELECT
            ao.offer_id,
            ao.title,
            ao.price as my_price,
            COALESCE(aph.price, 0) as last_competitor_price,
            aph.recorded_at as last_check
        FROM allegro_offers ao
        LEFT JOIN (
            SELECT offer_id, price, recorded_at
            FROM allegro_price_history
            WHERE (offer_id, recorded_at) IN (
                SELECT offer_id, MAX(recorded_at)
                FROM allegro_price_history
                GROUP BY offer_id
            )
        ) aph ON ao.offer_id = aph.offer_id
        WHERE ao.offer_id IS NOT NULL
            AND ao.price > 0
            AND (aph.recorded_at IS NULL 
                 OR aph.recorded_at < datetime('now', '-1 hour'))
        ORDER BY COALESCE(aph.recorded_at, '1970-01-01') ASC
        LIMIT :limit
        """),
        {"limit": limit}
    )
    rows = result.fetchall()
    
    offers = [
        {
            "offer_id": row[0],
            "url": f"https://allegro.pl/oferta/{row[0]}#inne-oferty-produktu",
            "title": row[1],
            "my_price": str(row[2])
        }
        for row in rows
    ]
    
    return jsonify({"offers": offers, "count": len(offers)})


@api_scraper_bp.route("/submit_results", methods=["POST"])
@with_session
def submit_results(session):
    """
    Accepts scraper results for Allegro offers.
    
    Body:
        {
            "results": [
                {
                    "offer_id": "12345678901",
                    "competitor_price": "149.99",
                    "competitor_url": "https://allegro.pl/oferta/98765"
                },
                {
                    "offer_id": "12345678902",
                    "error": "No competitors found"
                }
            ]
        }
    
    Returns:
        {"success": true, "processed": 2}
    """
    try:
        data = request.get_json()
        if not data or "results" not in data:
            return jsonify({"error": "Missing 'results' field"}), 400
        
        results = data["results"]
        if not isinstance(results, list):
            return jsonify({"error": "'results' must be an array"}), 400
        
        processed = 0
        
        for result in results:
            offer_id = result.get("offer_id")
            if not offer_id:
                continue
            
            status = result.get("status", "unknown")
            competitor_price = result.get("competitor_price")
            competitor_seller = result.get("competitor_seller")
            competitor_url = result.get("competitor_url")
            competitor_delivery_days = result.get("competitor_delivery_days")
            
            # Get current price from allegro_offers
            my_price_result = session.execute(
                text("SELECT price FROM allegro_offers WHERE offer_id = :offer_id"),
                {"offer_id": offer_id}
            )
            my_price_row = my_price_result.fetchone()
            my_price = my_price_row[0] if my_price_row else 0
            
            # Convert price string to Decimal
            price_decimal = None
            if competitor_price:
                try:
                    price_decimal = Decimal(str(competitor_price))
                except:
                    pass
            
            # Always insert record - with or without competitor data
            session.execute(
                text("""
                INSERT INTO allegro_price_history 
                    (offer_id, price, recorded_at, competitor_price, competitor_seller, competitor_url, competitor_delivery_days)
                VALUES 
                    (:offer_id, :my_price, CURRENT_TIMESTAMP, :competitor_price, :competitor_seller, :competitor_url, :competitor_delivery_days)
                """),
                {
                    "offer_id": offer_id,
                    "my_price": my_price,
                    "competitor_price": price_decimal,
                    "competitor_seller": competitor_seller if status == 'competitor_cheaper' else None,
                    "competitor_url": competitor_url if status == 'competitor_cheaper' else None,
                    "competitor_delivery_days": competitor_delivery_days if status == 'competitor_cheaper' else None
                }
            )
            processed += 1
        
        # Commit AFTER processing all results
        session.commit()
        return jsonify({"success": True, "processed": processed})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_scraper_bp.route("/status", methods=["GET"])
@with_session
def status(session):
    """
    Returns statistics about price checking.
    
    Returns:
        {
            "total_offers": 150,
            "checked_today": 120,
            "pending": 30,
            "last_check": "2025-12-22 10:30:00"
        }
    """
    # Count total offers
    total_result = session.execute(
        text("SELECT COUNT(*) FROM allegro_offers WHERE offer_id IS NOT NULL")
    )
    total_offers = total_result.fetchone()[0]
    
    # Count checked today
    checked_today_result = session.execute(
        text("""
        SELECT COUNT(DISTINCT offer_id)
        FROM allegro_price_history
        WHERE DATE(recorded_at) = DATE('now')
        """)
    )
    checked_today = checked_today_result.fetchone()[0]
    
    # Count pending (not checked in last hour)
    pending_result = session.execute(
        text("""
        SELECT COUNT(*)
        FROM allegro_offers ao
        LEFT JOIN (
            SELECT offer_id, MAX(recorded_at) as last_check
            FROM allegro_price_history
            GROUP BY offer_id
        ) aph ON ao.offer_id = aph.offer_id
        WHERE ao.offer_id IS NOT NULL
            AND (aph.last_check IS NULL 
                 OR aph.last_check < datetime('now', '-1 hour'))
        """)
    )
    pending = pending_result.fetchone()[0]
    
    # Get last check time
    last_check_result = session.execute(
        text("""
        SELECT MAX(recorded_at)
        FROM allegro_price_history
        """)
    )
    last_check = last_check_result.fetchone()[0]
    
    return jsonify({
        "total_offers": total_offers,
        "checked_today": checked_today,
        "pending": pending,
        "last_check": last_check
    })
