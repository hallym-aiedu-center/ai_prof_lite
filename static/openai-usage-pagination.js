(() => {
    "use strict";

    const PAGE_SIZE = 10;

    const init = () => {
        const mobileItems = Array.from(
            document.querySelectorAll('[data-usage-page-item="mobile"]')
        );
        const desktopItems = Array.from(
            document.querySelectorAll('[data-usage-page-item="desktop"]')
        );

        const pager = document.getElementById("usage-pagination");
        const previousButton = document.getElementById("usage-prev");
        const nextButton = document.getElementById("usage-next");
        const status = document.getElementById("usage-page-status");

        if (!pager || !previousButton || !nextButton || !status) {
            return;
        }

        const totalItems = Math.max(
            mobileItems.length,
            desktopItems.length
        );

        if (totalItems === 0) {
            return;
        }

        const totalPages = Math.ceil(totalItems / PAGE_SIZE);
        let currentPage = 1;

        const renderItems = (items, start, end) => {
            items.forEach((item, index) => {
                item.classList.toggle(
                    "hidden",
                    index < start || index >= end
                );
            });
        };

        const render = () => {
            const start = (currentPage - 1) * PAGE_SIZE;
            const end = start + PAGE_SIZE;

            renderItems(mobileItems, start, end);
            renderItems(desktopItems, start, end);

            status.textContent = `${currentPage} / ${totalPages}`;

            previousButton.disabled = currentPage <= 1;
            nextButton.disabled = currentPage >= totalPages;

            if (totalPages > 1) {
                pager.classList.remove("hidden");
                pager.classList.add("flex");
            } else {
                pager.classList.add("hidden");
                pager.classList.remove("flex");
            }
        };

        previousButton.addEventListener("click", () => {
            if (currentPage <= 1) {
                return;
            }

            currentPage -= 1;
            render();

            pager.closest("section")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        });

        nextButton.addEventListener("click", () => {
            if (currentPage >= totalPages) {
                return;
            }

            currentPage += 1;
            render();

            pager.closest("section")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        });

        render();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
