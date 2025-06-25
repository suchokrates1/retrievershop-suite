# Używamy obrazu Python jako bazy
FROM python:3.9-slim

# Ustawiamy katalog roboczy
WORKDIR /app

# Instalujemy zależności systemowe
RUN apt-get update && apt-get install -y \
    build-essential \
    libsqlite3-dev \
    cups-client \
    && rm -rf /var/lib/apt/lists/*

# Kopiujemy pliki aplikacji do kontenera w podkatalogu
COPY . /app/magazyn

# Instalujemy wymagane pakiety z requirements.txt
RUN pip install --no-cache-dir -r /app/magazyn/requirements.txt

# Ustawiamy port, na którym aplikacja będzie dostępna
EXPOSE 80

# Uruchamiamy aplikację
CMD ["python", "-m", "magazyn.app"]
