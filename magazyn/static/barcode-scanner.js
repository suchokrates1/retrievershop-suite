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
        // Uzyj tts_name jesli dostepne (krotszy format dla produktow Uniwersalnych)
        // np. "Pas samochodowy rozowy", "Amortyzator czarny"
        if (data.tts_name) {
            return data.tts_name;
        }
        
        const speechParts = [];
        // Series or name
        if (data.series) {
            speechParts.push(data.series);
        } else if (data.name) {
            speechParts.push(data.name);
        }
        // Size
        if (data.size) {
            speechParts.push(data.size);
        }
        // Color
        if (data.color) {
            speechParts.push(data.color);
        }
        return speechParts.join(' ');
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
            return deliveryMethod;
        }

        const productTexts = products.map((item) => {
            const parts = [];
            // Series or name
            if (item.series) {
                parts.push(item.series);
            } else if (item.name) {
                parts.push(item.name);
            }
            // Size
            if (item.size) {
                parts.push(item.size);
            }
            // Color
            if (item.color) {
                parts.push(item.color);
            }
            return parts.join(' ');
        });

        return `${deliveryMethod} zawiera: ${productTexts.join(', ')}`;
    };

    const showSuccess = (data, beepElement, asLabel) => {
        const info = asLabel ? buildLabelInfoText(data) : buildProductInfoText(data);
        const message = asLabel
            ? (info || 'Znaleziono paczkę.')
            : (info ? `Znaleziono produkt: ${info}` : 'Znaleziono produkt.');
        getResultElements().forEach((element) => showElement(element, message, SUCCESS_CLASS));
        getErrorElements().forEach((element) => hideElement(element));
        playBeep(beepElement);
        // TTS - tylko krotki format (tts_name lub series+size+color)
        const speechMessage = asLabel ? buildLabelSpeechText(data) : buildProductSpeechText(data);
        speak(speechMessage);
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

    // Global barcode scanner detector - detects fast keyboard input from BT scanners
    // without stealing focus from other inputs
    class GlobalBarcodeDetector {
        constructor(options) {
            this.buffer = '';
            this.lastKeyTime = 0;
            this.maxTimeBetweenKeys = options.maxTimeBetweenKeys || 50; // ms - scanners type very fast
            this.minBarcodeLength = options.minBarcodeLength || 4;
            this.onScan = options.onScan || (() => {});
            this.enabled = true;
            this.clearBufferTimeout = null;
        }

        isInputElement(element) {
            if (!element) return false;
            const tagName = element.tagName ? element.tagName.toLowerCase() : '';
            return ['input', 'textarea', 'select'].includes(tagName) || element.isContentEditable;
        }

        handleKeyDown(event) {
            if (!this.enabled) return;

            const now = Date.now();
            const timeSinceLastKey = now - this.lastKeyTime;

            // Clear buffer if too much time passed (user typing normally)
            if (timeSinceLastKey > this.maxTimeBetweenKeys && this.buffer.length > 0) {
                this.buffer = '';
            }

            // Only intercept if NOT in an input field OR if typing is scanner-fast
            const inInputField = this.isInputElement(document.activeElement);
            const isScannerSpeed = timeSinceLastKey < this.maxTimeBetweenKeys;

            if (event.key === 'Enter' && this.buffer.length >= this.minBarcodeLength) {
                // We have a complete barcode!
                const barcode = this.buffer;
                this.buffer = '';
                this.lastKeyTime = 0;
                
                // If we're in an input field and it was scanner speed, prevent normal submit
                if (inInputField && isScannerSpeed) {
                    event.preventDefault();
                    event.stopPropagation();
                    // Clear the input field that received scanner input
                    if (document.activeElement.value) {
                        document.activeElement.value = document.activeElement.value.slice(0, -barcode.length);
                    }
                }
                
                this.onScan(barcode);
                return;
            }

            // Only capture printable characters
            if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
                // For input fields - only track if scanner-speed or starting fresh
                if (inInputField) {
                    if (this.buffer.length === 0 || isScannerSpeed) {
                        this.buffer += event.key;
                        this.lastKeyTime = now;
                    } else {
                        // User is typing normally - reset
                        this.buffer = '';
                    }
                } else {
                    // Not in input - capture everything
                    this.buffer += event.key;
                    this.lastKeyTime = now;
                }

                // Auto-clear buffer after timeout
                clearTimeout(this.clearBufferTimeout);
                this.clearBufferTimeout = setTimeout(() => {
                    this.buffer = '';
                }, 200);
            }
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const hiddenInput = document.getElementById('barcode-scanner-input');
        const beepElement = document.getElementById('barcode-beep-sound');
        const csrfElement = document.getElementById('barcode-csrf-token');
        const csrfToken = csrfElement ? csrfElement.value : '';

        // Initialize global barcode detector
        const globalDetector = new GlobalBarcodeDetector({
            maxTimeBetweenKeys: 50,
            minBarcodeLength: 4,
            onScan: (barcode) => {
                console.log('[Scanner] Detected barcode:', barcode);
                submitBarcode(barcode, {
                    csrfToken,
                    input: hiddenInput,
                    beepElement
                });
            }
        });

        // Listen globally for keyboard events
        document.addEventListener('keydown', (event) => {
            globalDetector.handleKeyDown(event);
        }, true); // Use capture phase to intercept before other handlers

        // Keep hidden input for backward compatibility and explicit scanning
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
            // Reduced aggressiveness - only refocus after longer delay and if nothing else focused
            hiddenInput.addEventListener('blur', () => {
                setTimeout(() => {
                    if (!globalDetector.isInputElement(document.activeElement)) {
                        focusScannerInput(hiddenInput);
                    }
                }, 500);
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
            // Don't auto-refocus from manual inputs - let user control focus
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
