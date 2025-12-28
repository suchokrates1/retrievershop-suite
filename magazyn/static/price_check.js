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
    
    // Poll scraper queue status every 5 seconds
    let lastCheckTime = null;
    
    function updateQueueStatus() {
        fetch('/api/scraper/status')
            .then(res => res.json())
            .then(data => {
                const statusDiv = document.getElementById('scraper-queue-status');
                if (!statusDiv) return;
                
                // Show status if there are any tasks
                if (data.pending > 0 || data.processing > 0 || data.done > 0) {
                    statusDiv.classList.remove('d-none');
                    document.getElementById('queue-pending').textContent = data.pending || 0;
                    document.getElementById('queue-processing').textContent = data.processing || 0;
                    document.getElementById('queue-done').textContent = data.done || 0;
                    document.getElementById('queue-errors').textContent = data.errors || 0;
                }
            })
            .catch(() => {
                // Silently fail if API not available
            });
    }
    
    function updateRecentChecks() {
        const tableBody = document.getElementById('price-check-table-body');
        if (!tableBody) return;
        
        // Build URL with since parameter
        let url = '/api/scraper/recent_checks?limit=50';
        if (lastCheckTime) {
            url += '&since=' + encodeURIComponent(lastCheckTime);
        }
        
        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (!data.checks || data.checks.length === 0) {
                    return;
                }
                
                // Update last check time
                if (data.checks.length > 0) {
                    lastCheckTime = data.checks[0].recorded_at;
                }
                
                // Add new rows at the TOP of table (newest first)
                data.checks.reverse().forEach(check => {
                    const row = document.createElement('tr');
                    
                    // Offer ID column
                    const offerCell = document.createElement('td');
                    if (check.offer_id) {
                        const link = createLink(
                            'https://allegro.pl/oferta/' + check.offer_id,
                            '',
                            check.title || 'Oferta Allegro'
                        );
                        offerCell.appendChild(link);
                    }
                    row.appendChild(offerCell);
                    
                    // Product title column
                    const titleCell = document.createElement('td');
                    titleCell.textContent = check.title || '';
                    titleCell.style.maxWidth = '300px';
                    titleCell.style.overflow = 'hidden';
                    titleCell.style.textOverflow = 'ellipsis';
                    titleCell.style.whiteSpace = 'nowrap';
                    row.appendChild(titleCell);
                    
                    // My price column
                    const myPriceCell = document.createElement('td');
                    myPriceCell.textContent = check.my_price ? check.my_price.toFixed(2) + ' zł' : '–';
                    row.appendChild(myPriceCell);
                    
                    // Competitor price column
                    const competitorCell = document.createElement('td');
                    if (check.competitor_price) {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'd-flex align-items-center gap-2';
                        
                        const priceSpan = document.createElement('span');
                        priceSpan.textContent = check.competitor_price.toFixed(2) + ' zł';
                        wrapper.appendChild(priceSpan);
                        
                        if (check.competitor_seller) {
                            const sellerBadge = document.createElement('span');
                            sellerBadge.className = 'badge bg-secondary';
                            sellerBadge.textContent = check.competitor_seller;
                            wrapper.appendChild(sellerBadge);
                        }
                        
                        if (check.competitor_url) {
                            const link = createLink(
                                check.competitor_url,
                                null,
                                'Zobacz ofertę konkurencji',
                                'btn btn-outline-secondary btn-sm'
                            );
                            wrapper.appendChild(link);
                        }
                        
                        competitorCell.appendChild(wrapper);
                    } else {
                        competitorCell.className = 'text-muted';
                        competitorCell.textContent = 'Brak konkurencji';
                    }
                    row.appendChild(competitorCell);
                    
                    // Is cheapest column
                    const cheapestCell = document.createElement('td');
                    cheapestCell.className = 'text-center';
                    if (check.is_cheaper) {
                        cheapestCell.innerHTML = '<span class=\"text-success\" title=\"Nasza oferta jest najtańsza\">✓</span>';
                        row.className = 'table-success';
                    } else {
                        cheapestCell.innerHTML = '<span class=\"text-danger\" title=\"Konkurencja ma niższą cenę\">✗</span>';
                        row.className = 'table-warning';
                    }
                    row.appendChild(cheapestCell);
                    
                    // Add row at the TOP
                    tableBody.insertBefore(row, tableBody.firstChild);
                    
                    // Animate row (fade in)
                    row.style.opacity = '0';
                    setTimeout(() => {
                        row.style.transition = 'opacity 0.5s';
                        row.style.opacity = '1';
                    }, 10);
                });
                
                // Show table if it was hidden
                const tableContainer = document.getElementById('price-check-table-container');
                const loading = document.getElementById('price-check-loading');
                if (tableContainer && loading) {
                    loading.classList.add('d-none');
                    tableContainer.classList.remove('d-none');
                }
            })
            .catch(() => {
                // Silently fail
            });
    }
    
    // Update status and checks every 5 seconds
    setInterval(updateQueueStatus, 5000);
    setInterval(updateRecentChecks, 5000);
    updateQueueStatus(); // Initial call
    updateRecentChecks(); // Initial call
})();
