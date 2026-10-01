(() => {
    const select = document.getElementById('header-language');

    if (!(select instanceof HTMLSelectElement) || !select.form) {
        return;
    }

    select.addEventListener('change', () => {
        if (typeof select.form.requestSubmit === 'function') {
            select.form.requestSubmit();
        } else {
            select.form.submit();
        }
    });
})();
