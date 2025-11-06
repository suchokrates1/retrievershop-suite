# 🔄 Instrukcje czyszczenia cache przeglądarki

## Problem
Zmiany w CSS/JavaScript nie są widoczne z powodu cache przeglądarki.

## Rozwiązanie - 3 metody

### Metoda 1: Hard Refresh (NAJSZYBSZA)
- **Chrome/Edge**: `Ctrl + Shift + R` lub `Ctrl + F5`
- **Firefox**: `Ctrl + Shift + R` lub `Ctrl + F5`
- **Safari**: `Cmd + Shift + R`

### Metoda 2: DevTools (ZALECANA)
1. Otwórz DevTools: `F12`
2. Kliknij prawym na przycisku Odśwież (refresh)
3. Wybierz **"Empty Cache and Hard Reload"** (Wyczyść cache i przeładuj na twardo)

### Metoda 3: Ręczne czyszczenie
1. **Chrome/Edge**: 
   - `Ctrl + Shift + Delete`
   - Wybierz "Cached images and files"
   - Zakres: "Last hour"
   - Kliknij "Clear data"

2. **Firefox**:
   - `Ctrl + Shift + Delete`
   - Zaznacz "Cache"
   - Zakres: "Last hour"
   - Kliknij "Clear Now"

## 🎨 Co zostało zmienione w discussions.html

### Zmiany wizualne (CSS):
✅ **Grid layout** - dwupanelowy interfejs (lista wątków + czat)
✅ **Modern dark theme** - ciemny motyw z gradientami
✅ **Smooth animations** - animacje wejścia wiadomości
✅ **Responsive design** - dostosowanie do mobile
✅ **Beautiful scrollbars** - stylowane paski przewijania
✅ **Hover effects** - efekty najechania na wątki
✅ **Typing indicators** - wskaźniki pisania
✅ **Unread badges** - znaczniki nieprzeczytanych wiadomości

### Główne klasy CSS:
- `.discussions-layout` - główny kontener grid
- `.threads-panel` - lewy panel z listą wątków
- `.messages-area` - prawy panel z czatem
- `.thread-item` - pojedynczy wątek na liście
- `.message-bubble` - bąbelek wiadomości
- `.composer` - pole wprowadzania wiadomości

## 🔍 Weryfikacja czy cache jest wyczyszczony

1. Otwórz DevTools (`F12`)
2. Przejdź do zakładki **Network**
3. Zaznacz **"Disable cache"**
4. Odśwież stronę (`F5`)
5. Sprawdź w kolumnie **Status** czy pliki mają kod `200` (nie `304 Not Modified`)

## 🚀 Dodatkowe wskazówki

### Dla deweloperów:
- Zawsze pracuj z otwartymi DevTools i włączonym "Disable cache"
- Używaj trybu Incognito dla czystego testu

### Version busting (opcjonalne):
Jeśli problem się powtarza, dodaj wersję do URLi CSS/JS:
```html
<link rel="stylesheet" href="/static/styles.css?v=2">
<script src="/static/app.js?v=2"></script>
```

## ⚠️ Jeśli nadal nie działa:

1. Sprawdź czy serwer Flask działa: `http://localhost:5000`
2. Sprawdź logi serwera w terminalu
3. Sprawdź Console w DevTools (`F12` → Console) czy nie ma błędów JS
4. Spróbuj innej przeglądarki (Chrome → Firefox lub odwrotnie)
5. Uruchom ponownie serwer Flask
