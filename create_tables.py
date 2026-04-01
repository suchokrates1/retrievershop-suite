#!/usr/bin/env python3
"""Create missing tables using SQLAlchemy models."""

from magazyn.factory import create_app
from magazyn.models import Base

# Create Flask app (which initializes the engine)
app = create_app()

with app.app_context():
    from magazyn.db import engine
    from sqlalchemy import text
    
    # Create the OrderEvent table if it doesn't exist
    Base.metadata.tables['order_events'].create(engine, checkfirst=True)
    print("✓ order_events table created/verified successfully")
    
    # Also create indexes
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_events_order_id ON order_events(order_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_events_allegro_event_id ON order_events(allegro_event_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_events_occurred_at ON order_events(occurred_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_events_event_type ON order_events(event_type)"))
        conn.commit()
        print("✓ Indexes created successfully")

print("\nDatabase setup completed!")

