# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** RetrieverShop Magazyn
**Generated:** 2026-03-25 14:00:22
**Updated:** 2026-03-27 (ciemny motyw)
**Category:** Internal Warehouse Management System

---

## Global Rules

### Motyw: Ciemny (DaisyUI dark)

Aplikacja uzywa `data-theme="dark"` z DaisyUI 4.12.23 z nadpisanymi zmiennymi:

### Color Palette

| Role | Wartosc | Uzycie |
|------|---------|--------|
| base-100 | `oklch(0.145 0 0)` / ~#1d1d1d | Tlo glowne |
| base-200 | `oklch(0.12 0 0)` / ~#1a1a1a | Tlo kart |
| base-300 | `oklch(0.18 0 0)` / ~#262626 | Naglowki kart, zebra stripes |
| base-content | `oklch(0.93 0 0)` / ~#ededed | Tekst glowny |
| brand | `#17383E` | Navbar, header, branding |
| primary | DaisyUI dark default | Akcenty niebieskie |
| success | DaisyUI dark default | Stany pozytywne |
| error | DaisyUI dark default | Stany negatywne |
| warning | DaisyUI dark default | Ostrzezenia |
| info | DaisyUI dark default | Informacje |

### Naglowki kart (wzorzec)

Zamiast pelnych nasyconych tel (bg-error, bg-success), uzywamy:
```html
<div class="bg-base-300 px-4 py-3 font-semibold rounded-t-2xl border-l-4 border-{kolor}">
    <i class="bi bi-icon mr-2 text-{kolor}"></i>Tytul karty
</div>
```
Kolor akcentu przez lewy border + ikone -- tlo zawsze ciemne.

### Typography

- **Font:** System font (DaisyUI default)
- **Styl:** Czytelny, kompaktowy, bez zdobnikow

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #F97316;
  color: white;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #2563EB;
  border: 2px solid #2563EB;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #F8FAFC;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #2563EB;
  outline: none;
  box-shadow: 0 0 0 3px #2563EB20;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Ciemny minimalizm przemyslowy

**Keywords:** Dark theme, minimal, compact, data-dense, high readability, functional

**Best For:** Wewnetrzne systemy magazynowe, panele administracyjne, dashboardy operacyjne

### Wzorzec kolorow w tabelach

- Tabele uzywaja `table table-zebra table-sm` z DaisyUI
- Zebra stripes sa subtelne (oklch 0.16 vs 0.145)
- Naglowki tabel: `bg-base-200` lub `bg-base-300`
- Badge w tabelach: `badge-error`, `badge-success`, `badge-primary` (te moga byc nasycone)

### Stat cards (dashboard)

```html
<div class="card bg-base-200 border-l-4 border-{kolor} h-full">
    <!-- kolor: success/primary/warning/info -->
</div>
```

---

## Anti-Patterns (Do NOT Use)

- NIE uzywaj jasnych/bialych tel na kartach i tabelach
- NIE uzywaj pelnych nasyconych tel na naglowkach kart (bg-error, bg-success) -- zamiast tego border-l-4
- NIE uzywaj AI gradient purpurowo-rozowych
- NIE uzywaj hardcoded jasnych kolorow (#fff, #f8f8f8, #ccc) -- uzywaj zmiennych DaisyUI
- NIE uzywaj emojis jako ikon -- Bootstrap Icons (bi-*)
- NIE zapominaj o cursor:pointer na klikalnych elementach
- NIE rob natychmiastowych zmian stanow -- uzywaj transitions (150-300ms)

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] Ciemny motyw -- brak jasnych tel, brak bialych elementow
- [ ] Kolory z DaisyUI variables, nie hardcoded hex
- [ ] Ikony z Bootstrap Icons (bi-*)
- [ ] `cursor-pointer` na klikalnych elementach
- [ ] Hover states z transitions (150-300ms)
- [ ] Responsywnosc: 375px, 768px, 1024px+
- [ ] Brak horizontal scroll na mobile
- [ ] Naglowki kart: bg-base-300 + border-l-4 (nie pelne nasycone tla)
