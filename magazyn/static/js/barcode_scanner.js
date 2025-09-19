(function () {
    const form = document.getElementById('global-barcode-form');
    const input = document.getElementById('global-barcode-input');
    const csrfInput = document.getElementById('barcode-csrf-token');
    const beepSound = document.getElementById('barcode-beep');
    const toast = document.getElementById('global-barcode-toast');
    const toastSuccess = toast ? toast.querySelector('[data-barcode-result]') : null;
    const toastError = toast ? toast.querySelector('[data-barcode-error]') : null;
    const AUTO_HIDE_DELAY = 6000;
    let hideToastTimer = null;

    if (!form || !input) {
        return;
    }

    const getCsrfToken = () => (csrfInput ? csrfInput.value : '');

    const focusInput = () => {
        if (document.activeElement === input) {
            return;
        }
        input.focus({ preventScroll: true });
        input.select();
    };

    const hideToast = () => {
        if (!toast) {
            return;
        }
        toast.classList.add('d-none');
        if (toastSuccess) {
            toastSuccess.classList.add('d-none');
            toastSuccess.textContent = '';
        }
        if (toastError) {
            toastError.classList.add('d-none');
            toastError.textContent = '';
        }
    };

    const scheduleToastHide = () => {
        if (!toast) {
            return;
        }
        if (hideToastTimer) {
            window.clearTimeout(hideToastTimer);
        }
        hideToastTimer = window.setTimeout(hideToast, AUTO_HIDE_DELAY);
    };

    const playBeep = () => {
        if (!beepSound) {
            return;
        }
        try {
            beepSound.currentTime = 0;
            const playPromise = beepSound.play();
            if (playPromise instanceof Promise) {
                playPromise.catch((err) => {
                    console.warn('Nie udało się odtworzyć dźwięku', err);
                });
            }
        } catch (err) {
            console.warn('Nie udało się odtworzyć dźwięku', err);
        }
    };

    const speak = (message) => {
        if (!message || !('speechSynthesis' in window)) {
            return;
        }
        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(message);
            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.warn('Nie udało się odtworzyć komunikatu głosowego', err);
        }
    };

    const formatProductInfo = (data) => {
        const parts = [];
        if (data.name) {
            parts.push(data.name);
        }
        if (data.color) {
            parts.push(`kolor ${data.color}`);
        }
        if (data.size) {
            parts.push(`rozmiar ${data.size}`);
        }
        return parts.join(', ');
    };

    const formatSpeechInfo = (data) => {
        const parts = [];
        if (data.name) {
            parts.push(`Produkt ${data.name}`);
        }
        if (data.size) {
            parts.push(`Rozmiar ${data.size}`);
        }
        if (data.color) {
            parts.push(`Kolor ${data.color}`);
        }
        return parts.join('. ');
    };

    const updateElements = (selector, updater) => {
        document.querySelectorAll(selector).forEach((element) => {
            updater(element);
        });
    };

    const showSuccess = (data, code) => {
        const info = formatProductInfo(data);
        const message = info ? `Znaleziono produkt: ${info}` : 'Znaleziono produkt.';
        updateElements('[data-barcode-result]', (element) => {
            element.textContent = message;
            element.classList.remove('d-none');
            element.setAttribute('role', 'status');
        });
        updateElements('[data-barcode-error]', (element) => {
            element.classList.add('d-none');
            element.textContent = '';
        });
        updateElements('[data-barcode-code]', (element) => {
            element.textContent = code || '';
        });
        if (toast) {
            toast.classList.remove('d-none');
        }
        playBeep();
        speak(formatSpeechInfo(data));
        scheduleToastHide();
        document.dispatchEvent(new CustomEvent('barcode:success', { detail: { data, code } }));
    };

    const showError = (message = 'Nie znaleziono produktu o podanym kodzie kreskowym.') => {
        updateElements('[data-barcode-result]', (element) => {
            if (!element.hasAttribute('data-barcode-persistent')) {
                element.classList.add('d-none');
                element.textContent = '';
            }
        });
        updateElements('[data-barcode-error]', (element) => {
            element.textContent = message;
            element.classList.remove('d-none');
            element.setAttribute('role', 'alert');
        });
        if (toast) {
            toast.classList.remove('d-none');
        }
        speak(message);
        scheduleToastHide();
        document.dispatchEvent(new CustomEvent('barcode:error', { detail: { message } }));
    };

    const submitCode = (code) => {
        if (!code) {
            showError('Wprowadź kod kreskowy.');
            return Promise.resolve();
        }

        return fetch('/barcode_scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'Accept': 'application/json',
            },
            body: JSON.stringify({ barcode: code }),
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('request-failed');
                }
                return response.json();
            })
            .then((data) => {
                if (!data || typeof data !== 'object') {
                    throw new Error('invalid-response');
                }
                showSuccess(data, code);
            })
            .catch(() => {
                showError();
            });
    };

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const code = (input.value || '').trim();
        input.value = '';
        submitCode(code).finally(() => {
            focusInput();
        });
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            focusInput();
        }
    });

    window.addEventListener('focus', focusInput);
    window.addEventListener('pageshow', focusInput);

    focusInput();
})();
