// inFlow Premium Frontend Controller

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initGlobalSearch();
    initKeyboardShortcuts();
});

// Modal Management
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        modal.style.display = 'flex';
        const firstInput = modal.querySelector('input:not([type="hidden"]), select, textarea');
        if (firstInput) firstInput.focus();
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        modal.style.display = 'none';
    }
}

function initModals() {
    document.querySelectorAll('.modal-overlay, .modal-backdrop').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.classList.remove('active');
                overlay.style.display = 'none';
            }
        });
    });

    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', () => {
            const modal = btn.closest('.modal-overlay, .modal-backdrop');
            if (modal) {
                modal.classList.remove('active');
                modal.style.display = 'none';
            }
        });
    });
}

// Global Quick Search (Ctrl + K)
function initGlobalSearch() {
    const trigger = document.getElementById('globalSearchTrigger');
    const modal = document.getElementById('globalSearchModal');
    const input = document.getElementById('globalSearchInput');
    const resultsContainer = document.getElementById('globalSearchResults');

    if (!trigger || !modal || !input) return;

    trigger.addEventListener('click', () => {
        openModal('globalSearchModal');
    });

    let debounceTimer;
    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        if (query.length < 2) {
            resultsContainer.innerHTML = '<div style="padding: 16px; color: #94A3B8; text-align: center;">Type at least 2 characters to search...</div>';
            return;
        }

        debounceTimer = setTimeout(() => {
            fetch(`/api/products/search?q=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(products => {
                    if (products.length === 0) {
                        resultsContainer.innerHTML = '<div style="padding: 16px; color: #94A3B8; text-align: center;">No matching products found.</div>';
                        return;
                    }

                    let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
                    products.forEach(p => {
                        html += `
                            <a href="/products/${p.id}" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #F8FAFC; border-radius: 8px; text-decoration: none; color: inherit; border: 1px solid #E2E8F0; transition: background 0.15s ease;">
                                <div>
                                    <div style="font-weight: 600; font-size: 0.9rem;">${p.name}</div>
                                    <div style="font-size: 0.75rem; color: #64748B;">SKU: ${p.sku} | Barcode: ${p.barcode || '-'}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-weight: 700; color: #0F766E;">$${parseFloat(p.default_price || 0).toFixed(2)}</div>
                                    <div style="font-size: 0.75rem; color: #64748B;">Stock: ${parseFloat(p.on_hand || 0)} ${p.uom}</div>
                                </div>
                            </a>
                        `;
                    });
                    html += '</div>';
                    resultsContainer.innerHTML = html;
                })
                .catch(err => {
                    resultsContainer.innerHTML = `<div style="padding: 16px; color: #EF4444; text-align: center;">Search error: ${err.message}</div>`;
                });
        }, 200);
    });
}

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl + K or Cmd + K: Open global search
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            const modal = document.getElementById('globalSearchModal');
            if (modal) {
                if (modal.classList.contains('active')) {
                    closeModal('globalSearchModal');
                } else {
                    openModal('globalSearchModal');
                }
            }
        }

        // Escape: Close any open modal
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        }
    });
}

// Toast notification helper
function showToast(message, type = 'success') {
    const container = document.querySelector('.toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span style="font-weight: 600;">${type === 'success' ? '✓' : 'ℹ'}</span>
        <span>${message}</span>
    `;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function createToastContainer() {
    const cont = document.createElement('div');
    cont.className = 'toast-container';
    document.body.appendChild(cont);
    return cont;
}
