import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, AllegroOffer
import random
from datetime import datetime

# Skopiuj konfigurację z db.py
DATABASE_URL = "sqlite:///./allegro.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Utwórz tabele
Base.metadata.create_all(bind=engine)

session = SessionLocal()

# Dodaj przykładową ofertę jeśli brak
if session.query(AllegroOffer).count() == 0:
    sample_offer = AllegroOffer(
        offer_id="123456789",
        title="Przykładowa oferta",
        price=100.0,
        synced_at=datetime.now(),
        publication_status="ACTIVE"
    )
    session.add(sample_offer)
    session.commit()
    print("Dodano przykładową ofertę")

offers = session.query(AllegroOffer).all()
print(f"Liczba ofert: {len(offers)}")
if not offers:
    print("Brak ofert w bazie")
else:
    random_offer = random.choice(offers)
    print(f"Wybrana oferta: ID={random_offer.offer_id}, tytuł={random_offer.title}")
session.close()