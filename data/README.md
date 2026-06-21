# Katalog `data/` (wolumen Docker)

Montowany jako `/app/data` w kontenerze `retrievershop-magazyn`.

Pliki runtime serwera (nie w git) — np. cache, eksporty tymczasowe.

Nie trzymaj tu starych kopii SQLite (`database.db`, `magazyn.db`) — produkcja używa PostgreSQL.
