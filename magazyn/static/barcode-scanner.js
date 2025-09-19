(function () {
    const SUCCESS_CLASS = 'alert-success';
    const ERROR_CLASS = 'alert-danger';
    const HIDDEN_CLASS = 'd-none';
    const SCAN_ERROR_MESSAGE = 'Nie znaleziono produktu o podanym kodzie kreskowym.';

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

    const buildInfoText = (data) => {
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

    const buildSpeechText = (data) => {
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

    const showSuccess = (data, beepElement) => {
        const info = buildInfoText(data);
        const message = info ? `Znaleziono produkt: ${info}` : 'Znaleziono produkt.';
        getResultElements().forEach((element) => showElement(element, message, SUCCESS_CLASS));
        getErrorElements().forEach((element) => hideElement(element));
        playBeep(beepElement);
        const speechMessage = buildSpeechText(data);
        speak(speechMessage);
    };

    const showError = (message) => {
        const errorMessage = message || SCAN_ERROR_MESSAGE;
        getErrorElements().forEach((element) => showElement(element, errorMessage, ERROR_CLASS));
        getResultElements().forEach((element) => hideElement(element));
        speak(errorMessage);
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
        fetch('/barcode_scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken || ''
            },
            body: JSON.stringify({ barcode })
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('request-failed');
                }
                return response.json();
            })
            .then((data) => {
                showSuccess(data, beepElement);
            })
            .catch(() => {
                showError(SCAN_ERROR_MESSAGE);
            })
            .finally(() => {
                if (input) {
                    input.value = '';
                    focusScannerInput(input);
                }
            });
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
