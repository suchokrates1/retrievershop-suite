# Orders Page Overrides

> **PROJECT:** RetrieverShop Magazyn
> **Generated:** 2026-03-25 14:00:05
> **Page Type:** Checkout / Payment

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** 1. Hero, 2. Problem intro, 3. Comparison table (product vs competitors), 4. Pricing (optional), 5. CTA

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Table: Alternating rows (white/light grey). Your product: Highlight #FFFACD (light yellow) or green. Text: Dark

### Component Overrides

- Avoid: Wide tables breaking layout
- Avoid: Use arbitrary large z-index values
- Avoid: No feedback after submit

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Deal movement animations, metric updates, leaderboard ranking changes, gauge needle movements, status change highlights
- Responsive: Use horizontal scroll or card layout
- Layout: Define z-index scale system (10 20 30 50)
- Forms: Show loading then success/error state
- CTA Placement: Table: Right column. CTA: Below table
