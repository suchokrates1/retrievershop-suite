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
    Returns pending scraper tasks.
    
    Query params:
        limit (int): Max tasks to return (default: 10)
    
    Returns:
        {
            "tasks": [
                {"id": 1, "ean": "5903229331393"},
                {"id": 2, "ean": "5903033320434"}
            ],
            "count": 2
        }
    """
    limit = request.args.get("limit", 10, type=int)
    limit = min(limit, 100)  # Max 100 tasks at once
    
    # Mark old processing tasks as pending again (timeout: 5 minutes)
    timeout = datetime.now() - timedelta(minutes=5)
    session.execute(
        text("""
        UPDATE scraper_tasks
        SET status = 'pending', processing_started_at = NULL
        WHERE status = 'processing' AND processing_started_at < :timeout
        """),
        {"timeout": timeout}
    )
    session.commit()
    
    # Get pending tasks
    result = session.execute(
        text("""
        SELECT id, ean
        FROM scraper_tasks
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT :limit
        """),
        {"limit": limit}
    )
    rows = result.fetchall()
    
    if not rows:
        return jsonify({"tasks": [], "count": 0})
    
    # Mark as processing
    task_ids = [row[0] for row in rows]  # row[0] is id
    placeholders = ",".join([f":id{i}" for i in range(len(task_ids))])
    params = {f"id{i}": task_id for i, task_id in enumerate(task_ids)}
    params["now"] = datetime.now()
    
    session.execute(
        text(f"""
        UPDATE scraper_tasks
        SET status = 'processing', processing_started_at = :now
        WHERE id IN ({placeholders})
        """),
        params
    )
    session.commit()
    
    tasks = [{"id": row[0], "ean": row[1]} for row in rows]
    
    return jsonify({"tasks": tasks, "count": len(tasks)})


@api_scraper_bp.route("/submit_results", methods=["POST"])
@with_session
def submit_results(session):
    """
    Accepts scraper results.
    
    Body:
        {
            "results": [
                {"id": 1, "price": "159.89", "url": "https://allegro.pl/..."},
                {"id": 2, "error": "Not found"}
            ]
        }
    
    Returns:
        {"success": true, "processed": 2}
    """
    data = request.get_json()
    if not data or "results" not in data:
        return jsonify({"error": "Missing 'results' field"}), 400
    
    results = data["results"]
    if not isinstance(results, list):
        return jsonify({"error": "'results' must be an array"}), 400
    
    processed = 0
    
    for result in results:
        task_id = result.get("id")
        if not task_id:
            continue
        
        price = result.get("price")
        url = result.get("url")
        error = result.get("error")
        
        # Convert price string to Decimal
        price_decimal = None
        if price:
            try:
                price_decimal = Decimal(str(price))
            except:
                error = f"Invalid price format: {price}"
        
        session.execute(
            text("""
            UPDATE scraper_tasks
            SET status = 'done',
                price = :price,
                url = :url,
                error = :error,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """),
            {
                "price": price_decimal,
                "url": url,
                "error": error,
                "id": task_id
            }
        )
        processed += 1
    
    session.commit()
    
    return jsonify({"success": True, "processed": processed})


@api_scraper_bp.route("/status", methods=["GET"])
@with_session
def status(session):
    """
    Returns scraper queue status.
    
    Returns:
        {
            "pending": 5,
            "processing": 2,
            "done": 100,
            "errors": 3
        }
    """
    result_stats = session.execute(
        text("""
        SELECT 
            status,
            COUNT(*) as count
        FROM scraper_tasks
        GROUP BY status
        """)
    )
    stats = result_stats.fetchall()
    
    result = {
        "pending": 0,
        "processing": 0,
        "done": 0,
        "errors": 0
    }
    
    for row in stats:
        status = row[0]  # First column
        count = row[1]   # Second column
        if status in result:
            result[status] = count
    
    # Count errors separately
    error_result = session.execute(
        text("""
        SELECT COUNT(*) as count
        FROM scraper_tasks
        WHERE status = 'done' AND error IS NOT NULL
        """)
    )
    error_count = error_result.fetchone()
    result["errors"] = error_count[0] if error_count else 0
    
    return jsonify(result)
