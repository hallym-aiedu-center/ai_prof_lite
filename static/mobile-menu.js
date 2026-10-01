(() => {
    const trigger = document.getElementById('mobile-menu-trigger');
    const root = document.getElementById('mobile-menu-root');
    const sheet = document.getElementById('mobile-menu-sheet');

    if (!trigger || !root || !sheet) {
        return;
    }

    const closeButtons = root.querySelectorAll('[data-mobile-menu-close]');
    let lastFocusedElement = null;

    const getFocusableElements = () => Array.from(
        sheet.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
    ).filter((element) => !element.hasAttribute('hidden'));

    const openMenu = () => {
        lastFocusedElement = document.activeElement;
        root.classList.add('is-open');
        root.setAttribute('aria-hidden', 'false');
        trigger.setAttribute('aria-expanded', 'true');
        document.body.classList.add('mobile-menu-open');
        requestAnimationFrame(() => sheet.focus());
    };

    const closeMenu = () => {
        root.classList.remove('is-open');
        root.setAttribute('aria-hidden', 'true');
        trigger.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('mobile-menu-open');

        if (lastFocusedElement instanceof HTMLElement) {
            lastFocusedElement.focus();
        } else {
            trigger.focus();
        }
    };

    trigger.addEventListener('click', openMenu);
    closeButtons.forEach((button) => button.addEventListener('click', closeMenu));

    root.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeMenu();
            return;
        }

        if (event.key !== 'Tab') {
            return;
        }

        const focusable = getFocusableElements();
        if (focusable.length === 0) {
            event.preventDefault();
            sheet.focus();
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && (document.activeElement === first || document.activeElement === sheet)) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    const desktopMedia = window.matchMedia('(min-width: 1024px)');
    const closeOnDesktop = (event) => {
        if (event.matches && root.classList.contains('is-open')) {
            closeMenu();
        }
    };

    if (typeof desktopMedia.addEventListener === 'function') {
        desktopMedia.addEventListener('change', closeOnDesktop);
    } else if (typeof desktopMedia.addListener === 'function') {
        desktopMedia.addListener(closeOnDesktop);
    }
})();
