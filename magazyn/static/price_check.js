(function () {
    const logLines = [];
    const screenshotMeta = {
        offerId: null,
        stage: null,
        barcode: null,
    };

    function renderLogs(logText) {
        const logContainer = document.getElementById('price-check-log-container');
        const logContent = document.getElementById('price-check-log-content');

        if (!logContainer || !logContent) {
            return;
        }

        const text = typeof logText === 'string' ? logText : '';
        if (!text.trim()) {
            logContent.textContent = '';
            logContainer.classList.add('d-none');
            return;
        }

        logContent.textContent = text;
        logContainer.classList.remove('d-none');
    }

    function appendDebugStep(label, value, line) {
        const normalizedLabel = typeof label === 'string' ? label : '';
        const normalizedValue = typeof value === 'string' ? value : '';
        const normalizedLine =
            typeof line === 'string' && line
                ? line
                : normalizedValue
                ? normalizedLabel + ': ' + normalizedValue
                : normalizedLabel;

        if (normalizedLine) {
            logLines.push(normalizedLine);
            renderLogs(logLines.join('\n'));
        }
    }

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

    function renderPriceChecks(data) {
        const loading = document.getElementById('price-check-loading');
        const tableContainer = document.getElementById('price-check-table-container');
        const tableBody = document.getElementById('price-check-table-body');
        const errorContainer = document.getElementById('price-check-error');

        if (!loading || !tableContainer || !tableBody || !errorContainer) {
            return;
        }

        loading.classList.add('d-none');
        renderLogs(data.debug_log);

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

    function handleStreamError() {
        const loading = document.getElementById('price-check-loading');
        const errorContainer = document.getElementById('price-check-error');

        if (loading) {
            loading.classList.add('d-none');
        }

        if (errorContainer) {
            errorContainer.className = 'alert alert-warning';
            errorContainer.textContent =
                'Nie udało się pobrać danych cenowych. Odśwież stronę i spróbuj ponownie.';
        }
    }

    function renderScreenshot(eventPayload) {
        const visualContainer = document.getElementById('price-check-visual-container');
        const imageEl = document.getElementById('price-check-visual-image');
        const metaEl = document.getElementById('price-check-visual-meta');

        if (!visualContainer || !imageEl || !metaEl) {
            return;
        }

        if (!eventPayload || typeof eventPayload.image !== 'string') {
            return;
        }

        imageEl.src = 'data:image/png;base64,' + eventPayload.image;
        screenshotMeta.offerId = eventPayload.offer_id || null;
        screenshotMeta.stage = eventPayload.stage || null;
        screenshotMeta.barcode = eventPayload.barcode || null;

        const parts = [];
        if (screenshotMeta.offerId) {
            parts.push('Oferta: ' + screenshotMeta.offerId);
        }
        if (screenshotMeta.stage) {
            parts.push('Etap: ' + screenshotMeta.stage);
        }
        if (screenshotMeta.barcode) {
            parts.push('Kod kreskowy: ' + screenshotMeta.barcode);
        }
        metaEl.textContent = parts.join(' · ');

        visualContainer.classList.remove('d-none');
    }

    function startPriceCheckStream() {
        const streamUrl = window.location.pathname + '/stream';
        const source = new EventSource(streamUrl);

        source.addEventListener('log', (event) => {
            try {
                const payload = JSON.parse(event.data || '{}');
                appendDebugStep(payload.label, payload.value, payload.line);
            } catch (err) {
                // Ignore malformed events
            }
        });

        source.addEventListener('result', (event) => {
            try {
                const payload = JSON.parse(event.data || '{}');
                renderPriceChecks(payload);
            } catch (err) {
                handleStreamError();
            } finally {
                source.close();
            }
        });

        source.addEventListener('screenshot', (event) => {
            try {
                const payload = JSON.parse(event.data || '{}');
                renderScreenshot(payload);
            } catch (err) {
                // ignore invalid payloads
            }
        });

        source.addEventListener('error', () => {
            source.close();
            handleStreamError();
        });
    }

    document.addEventListener('DOMContentLoaded', startPriceCheckStream);
})();
