# Używamy obrazu Python jako bazy
FROM python:3.9-slim

# Ustawiamy katalog roboczy
WORKDIR /app

# Instalujemy zależności systemowe
RUN apt-get update && apt-get install -y \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Kopiujemy pliki aplikacji do kontenera
COPY . /app

# Instalujemy wymagane pakiety z requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Tworzymy bazę danych
RUN python -c "from app import init_db; init_db()"

# Ustawiamy port, na którym aplikacja będzie dostępna
EXPOSE 5001

# Uruchamiamy aplikację
CMD ["python", "app.py"]
