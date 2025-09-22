(function () {
    function createLink(url, label, visuallyHiddenText, extraClasses) {
        if (!url) {
            return label || '';
        }
        const link = document.createElement('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = extraClasses || 'link-dark';
        if (label) {
            link.textContent = label;
        } else {
            const icon = document.createElement('i');
            icon.className = 'bi bi-link-45deg';
            icon.setAttribute('aria-hidden', 'true');
            link.appendChild(icon);
            if (visuallyHiddenText) {
                const span = document.createElement('span');
                span.className = 'visually-hidden';
                span.textContent = visuallyHiddenText;
                link.appendChild(span);
            }
        }
        return link;
    }

    function renderDebugSteps(steps) {
        const debugContainer = document.getElementById('price-check-debug-container');
        const debugList = document.getElementById('price-check-debug-list');

        if (!debugContainer || !debugList) {
            return;
        }

        const items = Array.isArray(steps) ? steps : [];
        debugList.innerHTML = '';

        if (!items.length) {
            debugContainer.classList.add('d-none');
            return;
        }

        debugContainer.classList.remove('d-none');

        items.forEach((step) => {
            const label = document.createElement('dt');
            label.className = 'fw-semibold';
            label.textContent = step && step.label ? step.label : '';
            debugList.appendChild(label);

            const valueWrapper = document.createElement('dd');
            valueWrapper.className = 'mb-2 text-break';
            const pre = document.createElement('pre');
            pre.className = 'mb-0';
            pre.textContent = step && step.value ? step.value : '';
            valueWrapper.appendChild(pre);
            debugList.appendChild(valueWrapper);
        });
    }

    function renderPriceChecks(data) {
        const loading = document.getElementById('price-check-loading');
        const tableContainer = document.getElementById('price-check-table-container');
        const tableBody = document.getElementById('price-check-table-body');
        const errorContainer = document.getElementById('price-check-error');

        if (!loading || !tableContainer || !tableBody || !errorContainer) {
            return;
        }

        loading.classList.add('d-none');
        renderDebugSteps(data.debug_steps);

        if (data.auth_error) {
            errorContainer.className = 'alert alert-warning';
            errorContainer.textContent = data.auth_error;
            return;
        }

        tableContainer.classList.remove('d-none');
        tableBody.innerHTML = '';

        const priceChecks = Array.isArray(data.price_checks) ? data.price_checks : [];
        if (priceChecks.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 5;
            cell.className = 'text-center text-muted';
            cell.textContent = 'Brak powiązanych ofert Allegro.';
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        priceChecks.forEach((item) => {
            const row = document.createElement('tr');

            const offerCell = document.createElement('td');
            if (item.offer_id) {
                const offerLink = createLink(
                    'https://allegro.pl/oferta/' + item.offer_id,
                    '',
                    item.title || 'Oferta Allegro'
                );
                offerCell.appendChild(offerLink);
            } else {
                offerCell.textContent = item.title || '';
            }
            row.appendChild(offerCell);

            const labelCell = document.createElement('td');
            labelCell.textContent = item.label || '';
            row.appendChild(labelCell);

            const ownPriceCell = document.createElement('td');
            ownPriceCell.textContent = item.own_price ? item.own_price + ' zł' : '–';
            if (!item.own_price) {
                ownPriceCell.classList.add('text-muted');
            }
            row.appendChild(ownPriceCell);

            const competitorCell = document.createElement('td');
            if (item.error) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-secondary';
                badge.textContent = item.error;
                competitorCell.appendChild(badge);
            } else if (item.competitor_price) {
                const wrapper = document.createElement('div');
                wrapper.className = 'd-flex align-items-center gap-2';
                const priceSpan = document.createElement('span');
                priceSpan.textContent = item.competitor_price + ' zł';
                wrapper.appendChild(priceSpan);
                if (item.competitor_offer_url) {
                    const competitorLink = createLink(
                        item.competitor_offer_url,
                        null,
                        'Zobacz ofertę konkurencji',
                        'btn btn-outline-secondary btn-sm'
                    );
                    const icon = competitorLink.querySelector('i');
                    if (!icon) {
                        const iconEl = document.createElement('i');
                        iconEl.className = 'bi bi-diagram-3';
                        competitorLink.prepend(iconEl);
                    } else {
                        icon.className = 'bi bi-diagram-3';
                    }
                    wrapper.appendChild(competitorLink);
                }
                competitorCell.appendChild(wrapper);
            } else {
                competitorCell.className = 'text-muted';
                competitorCell.textContent = 'Brak danych';
            }
            row.appendChild(competitorCell);

            const lowestCell = document.createElement('td');
            lowestCell.className = 'text-center';
            if (item.is_lowest === null || item.is_lowest === undefined) {
                lowestCell.innerHTML = '<span class="text-muted">–</span>';
            } else if (item.is_lowest) {
                lowestCell.innerHTML = '<span class="text-success" title="Nasza oferta jest najtańsza">✓</span>';
            } else {
                lowestCell.innerHTML = '<span class="text-danger" title="Konkurencja ma niższą cenę">✗</span>';
            }
            row.appendChild(lowestCell);

            tableBody.appendChild(row);
        });
    }

    function fetchPriceChecks() {
        const url = window.location.pathname + '?format=json';
        fetch(url, { headers: { Accept: 'application/json' } })
            .then((response) => response.json())
            .then(renderPriceChecks)
            .catch(() => {
                renderPriceChecks({
                    price_checks: [],
                    auth_error: 'Nie udało się pobrać danych cenowych. Odśwież stronę i spróbuj ponownie.',
                });
            });
    }

    document.addEventListener('DOMContentLoaded', fetchPriceChecks);
})();
