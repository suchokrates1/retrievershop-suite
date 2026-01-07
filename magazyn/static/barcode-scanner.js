(function () {
    const SUCCESS_CLASS = 'alert-success';
    const ERROR_CLASS = 'alert-danger';
    const HIDDEN_CLASS = 'd-none';
    const configElement = document.getElementById('barcode-config');
    const BARCODE_ENDPOINT = (configElement && configElement.dataset && configElement.dataset.barcodeEndpoint)
        ? configElement.dataset.barcodeEndpoint
        : '/barcode_scan';
    const LABEL_ENDPOINT = (configElement && configElement.dataset && configElement.dataset.labelEndpoint)
        ? configElement.dataset.labelEndpoint
        : '/label_scan';
    const BARCODE_MODE = (configElement && configElement.dataset && configElement.dataset.barcodeMode)
        ? configElement.dataset.barcodeMode.toLowerCase()
        : 'product';
    const SCAN_ERROR_MESSAGE = (configElement && configElement.dataset && configElement.dataset.barcodeError)
        ? configElement.dataset.barcodeError
        : 'Nie znaleziono produktu o podanym kodzie kreskowym.';
    const isLabelMode = BARCODE_MODE === 'label';
    const isAutoMode = BARCODE_MODE === 'auto';

    const speechSupport = () => 'speechSynthesis' in window;

    const getResultElements = () => Array.from(document.querySelectorAll('[data-barcode-result]'));
    const getErrorElements = () => Array.from(document.querySelectorAll('[data-barcode-error]'));

    const hideElement = (element) => {
        if (!element || element.classList.contains(HIDDEN_CLASS)) {
            return;
        }
        element.classList.add(HIDDEN_CLASS);
    };

    const showElement = (element, text, className) => {
        if (!element) {
            return;
        }
        element.textContent = text;
        element.classList.remove(HIDDEN_CLASS, SUCCESS_CLASS, ERROR_CLASS);
        if (className) {
            element.classList.add(className);
        }
    };

    const speak = (message) => {
        if (!speechSupport() || !message) {
            return;
        }
        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(message);
            window.speechSynthesis.speak(utterance);
        } catch (error) {
            console.warn('Nie udało się odtworzyć komunikatu głosowego', error);
        }
    };

    const playBeep = (audioElement) => {
        if (!audioElement) {
            return;
        }
        try {
            audioElement.currentTime = 0;
            void audioElement.play();
        } catch (error) {
            console.warn('Nie udało się odtworzyć dźwięku', error);
        }
    };

    const focusScannerInput = (input) => {
        if (!input) {
            return;
        }
        const active = document.activeElement;
        if (active && active !== document.body && active !== document.documentElement) {
            const tagName = active.tagName ? active.tagName.toLowerCase() : '';
            const isTextual = ['input', 'textarea', 'select'].includes(tagName) || active.isContentEditable;
            if (isTextual && active !== input) {
                return;
            }
        }
        input.focus({ preventScroll: true });
        input.select();
    };

    const buildProductInfoText = (data) => {
        const infoParts = [];
        if (data.name) {
            infoParts.push(data.name);
        }
        if (data.color) {
            infoParts.push(`kolor ${data.color}`);
        }
        if (data.size) {
            infoParts.push(`rozmiar ${data.size}`);
        }
        return infoParts.join(', ');
    };

    const buildProductSpeechText = (data) => {
        const speechParts = [];
        if (data.name) {
            speechParts.push(`Produkt ${data.name}`);
        }
        if (data.size) {
            speechParts.push(`${data.size}`);
        }
        if (data.color) {
            speechParts.push(`${data.color}`);
        }
        return speechParts.join('. ');
    };

    const buildLabelInfoText = (data) => {
        const parts = [];
        const products = Array.isArray(data.products) ? data.products : [];
        products.forEach((item) => {
            const name = item.name || 'Produkt';
            const qty = item.quantity ? ` x${item.quantity}` : '';
            const size = item.size ? `, rozmiar ${item.size}` : '';
            const color = item.color ? `, kolor ${item.color}` : '';
            parts.push(`${name}${size}${color}${qty}`);
        });
        const headline = data.order_id ? `Paczka ${data.order_id}` : '';
        const summary = parts.join(' | ');
        return [headline, summary].filter(Boolean).join(' — ');
    };

    const buildLabelSpeechText = (data) => {
        const products = Array.isArray(data.products) ? data.products : [];
        // Use delivery_method for better description (e.g., "Paczkomat InPost")
        const deliveryMethod = data.delivery_method || data.courier_code || 'paczka';
        if (!products.length) {
            return `Paczka ${deliveryMethod}`;
        }

        const productTexts = products.map((item) => {
            const qtyText = item.quantity ? `${item.quantity} sztuki` : '1 sztuka';
            const name = item.name || 'produkt';
            const size = item.size ? `rozmiar ${item.size}` : '';
            const color = item.color ? `kolor ${item.color}` : '';
            const details = [name, size, color].filter(Boolean).join(', ');
            return `${qtyText}: ${details}`.trim();
        });

        return `Paczka ${deliveryMethod} zawiera: ${productTexts.join('; ')}`;
    };

    const showSuccess = (data, beepElement, asLabel) => {
        const info = asLabel ? buildLabelInfoText(data) : buildProductInfoText(data);
        const message = asLabel
            ? (info || 'Znaleziono paczkę.')
            : (info ? `Znaleziono produkt: ${info}` : 'Znaleziono produkt.');
        getResultElements().forEach((element) => showElement(element, message, SUCCESS_CLASS));
        getErrorElements().forEach((element) => hideElement(element));
        playBeep(beepElement);
        const speechMessage = asLabel ? buildLabelSpeechText(data) : buildProductSpeechText(data);
        speak(speechMessage);
        
        // Read flash messages via TTS (e.g., auto-packing confirmation)
        setTimeout(() => {
            const flashMessages = document.querySelectorAll('.alert.alert-success:not([data-tts-read])');
            flashMessages.forEach((alert) => {
                const text = alert.textContent.trim();
                if (text) {
                    speak(text);
                    alert.setAttribute('data-tts-read', 'true');
                }
            });
        }, 1500); // Wait 1.5s after main message
    };

    const showError = (message) => {
        const errorMessage = message || SCAN_ERROR_MESSAGE;
        getErrorElements().forEach((element) => showElement(element, errorMessage, ERROR_CLASS));
        getResultElements().forEach((element) => hideElement(element));
        speak(errorMessage);
    };

    const fetchBarcode = (endpoint, barcode, csrfToken) => {
        return fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken || ''
            },
            body: JSON.stringify({ barcode })
        }).then((response) => {
            if (!response.ok) {
                const error = new Error('request-failed');
                error.status = response.status;
                throw error;
            }
            return response.json();
        });
    };

    const detectBarcodeType = (barcode) => {
        // EAN-13: 13 cyfr i zaczyna się od "69"
        const isEan13 = /^\d{13}$/.test(barcode);
        const startsWithSixtyNine = barcode.startsWith('69');
        
        if (isEan13 && startsWithSixtyNine) {
            return 'product';
        }
        return 'label';
    };

    const submitBarcode = (barcode, options) => {
        const { csrfToken, input, beepElement } = options || {};
        if (!barcode) {
            showError('Wprowadź kod kreskowy.');
            if (input) {
                input.value = '';
                focusScannerInput(input);
            }
            return;
        }
        
        let endpoints;
        if (isLabelMode) {
            endpoints = [{ url: LABEL_ENDPOINT, asLabel: true }];
        } else if (isAutoMode) {
            // Auto-detection: check if it's EAN (13 digits starting with "69")
            const detectedType = detectBarcodeType(barcode);
            if (detectedType === 'product') {
                // Try product endpoint first, then label as fallback
                endpoints = [
                    { url: BARCODE_ENDPOINT, asLabel: false },
                    { url: LABEL_ENDPOINT, asLabel: true }
                ];
            } else {
                // Try label endpoint first, then product as fallback
                endpoints = [
                    { url: LABEL_ENDPOINT, asLabel: true },
                    { url: BARCODE_ENDPOINT, asLabel: false }
                ];
            }
        } else {
            endpoints = [{ url: BARCODE_ENDPOINT, asLabel: false }];
        }

        const tryNext = (index) => {
            if (index >= endpoints.length) {
                showError(SCAN_ERROR_MESSAGE);
                if (input) {
                    input.value = '';
                    focusScannerInput(input);
                }
                return;
            }

            const { url, asLabel } = endpoints[index];
            fetchBarcode(url, barcode, csrfToken)
                .then((data) => {
                    showSuccess(data, beepElement, asLabel);
                    if (input) {
                        input.value = '';
                        focusScannerInput(input);
                    }
                })
                .catch(() => {
                    tryNext(index + 1);
                });
        };

        tryNext(0);
    };

    document.addEventListener('DOMContentLoaded', () => {
        const hiddenInput = document.getElementById('barcode-scanner-input');
        const beepElement = document.getElementById('barcode-beep-sound');
        const csrfElement = document.getElementById('barcode-csrf-token');
        const csrfToken = csrfElement ? csrfElement.value : '';

        focusScannerInput(hiddenInput);
        if (hiddenInput) {
            hiddenInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    submitBarcode(hiddenInput.value.trim(), {
                        csrfToken,
                        input: hiddenInput,
                        beepElement
                    });
                }
            });
            hiddenInput.addEventListener('blur', () => {
                setTimeout(() => focusScannerInput(hiddenInput), 50);
            });
        }

        document.querySelectorAll('[data-barcode-source="manual"]').forEach((input) => {
            const form = input.form;
            if (form) {
                form.addEventListener('submit', (event) => {
                    event.preventDefault();
                    submitBarcode(input.value.trim(), {
                        csrfToken,
                        input,
                        beepElement
                    });
                });
            } else {
                input.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        submitBarcode(input.value.trim(), {
                            csrfToken,
                            input,
                            beepElement
                        });
                    }
                });
            }
            input.addEventListener('blur', () => {
                setTimeout(() => focusScannerInput(hiddenInput), 100);
            });
        });

        document.addEventListener('barcode:scan', (event) => {
            const detail = event.detail || {};
            const barcode = detail.barcode;
            if (!barcode) {
                return;
            }
            submitBarcode(barcode, {
                csrfToken,
                input: hiddenInput,
                beepElement
            });
        });
    });
})();
