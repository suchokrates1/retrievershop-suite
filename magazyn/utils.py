"""
Funkcje uzytkownikowe wspoldzielone w aplikacji.

Zawiera proste funkcje pomocnicze uzywane w wielu miejscach.
"""


def short_preview(text: str, limit: int = 140, normalize_whitespace: bool = False) -> str:
    """
    Skraca tekst do podanego limitu znakow.
    
    Args:
        text: Tekst do skrocenia
        limit: Maksymalna dlugosc (domyslnie 140)
        normalize_whitespace: Czy zamienic znaki nowej linii na spacje
        
    Returns:
        Skrocony tekst z "..." jesli byl dluzszy niz limit
    """
    if not text:
        return ""
    
    clean = text.strip()
    if normalize_whitespace:
        clean = clean.replace("\n", " ")
    
    if len(clean) <= limit:
        return clean
    
    return clean[:max(limit - 3, 0)] + "..."
