// inFlow Premium Frontend Controller

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initGlobalSearch();
    initKeyboardShortcuts();
    initGlobalSaveButtonDirtyWatcher();
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

// =========================================================================
// Global Save Button Unsaved / Dirty Red Dot Controller
// Ensures every Save button in inFlow displays a vibrant red dot indicator
// when user has unsaved edits, and hides it when saved / pristine.
// =========================================================================

function isSaveButton(btn) {
    if (!btn || btn.nodeType !== 1) return false;
    if (btn.tagName !== 'BUTTON' && (btn.tagName !== 'INPUT' || btn.type !== 'submit')) return false;

    // Ignore Discard / Don't save / Cancel / Delete buttons
    const cls = (btn.className || '').toLowerCase();
    const txt = (btn.textContent || btn.value || '').trim().toLowerCase();
    const title = (btn.getAttribute('title') || '').toLowerCase();
    const id = (btn.id || '').toLowerCase();

    if (cls.includes('dont-save') || cls.includes('discard') || cls.includes('cancel') || cls.includes('delete') || cls.includes('btn-close')) {
        return false;
    }
    if (txt.includes("don't save") || txt.includes("dont save") || txt.includes("discard") || txt.includes("cancel") || txt.includes("delete")) {
        return false;
    }

    if (id.includes('save') || cls.includes('save') || cls.includes('btn-so-save') || cls.includes('po-top-save-btn') || cls.includes('inflow-cat-save-btn')) {
        return true;
    }
    if (txt.includes('save') || txt.includes('រក្សាទុក')) {
        return true;
    }
    if (title.includes('save') || title.includes('រក្សាទុក')) {
        return true;
    }
    if (btn.type === 'submit' && !txt.includes('search') && !txt.includes('filter') && !txt.includes('delete') && !txt.includes('print')) {
        return true;
    }
    return false;
}

function ensureSaveButtonDot(btn) {
    if (!btn) return null;
    let dot = btn.querySelector('.inflow-unsaved-dot');
    if (!dot) {
        dot = document.createElement('span');
        dot.className = 'inflow-unsaved-dot';
        dot.style.display = 'none';
        dot.title = 'Unsaved changes';
        btn.appendChild(dot);
    }
    return dot;
}

function setSaveButtonDirty(btn, isDirty) {
    if (!btn) return;
    const dot = ensureSaveButtonDot(btn);
    if (dot) {
        dot.style.display = isDirty ? 'inline-block' : 'none';
    }
    if (isDirty) {
        btn.classList.add('has-unsaved');
    } else {
        btn.classList.remove('has-unsaved');
    }
}

function initGlobalSaveButtonDirtyWatcher() {
    // 1. Initial attachment to all existing Save buttons
    document.querySelectorAll('button, input[type="submit"]').forEach(btn => {
        if (isSaveButton(btn)) {
            ensureSaveButtonDot(btn);
        }
    });

    // 2. Track form edits globally
    const trackedForms = new WeakSet();

    function watchForm(form) {
        if (!form || trackedForms.has(form)) return;
        trackedForms.add(form);

        // Capture initial values of form fields
        const initialValues = new WeakMap();
        form.querySelectorAll('input:not([type="hidden"]):not([type="button"]):not([type="submit"]), select, textarea').forEach(input => {
            if (input.type === 'checkbox' || input.type === 'radio') {
                initialValues.set(input, input.checked);
            } else {
                initialValues.set(input, input.value);
            }
        });

        function checkFormDirty() {
            let isDirty = false;
            const fields = form.querySelectorAll('input:not([type="hidden"]):not([type="button"]):not([type="submit"]), select, textarea');
            for (const input of fields) {
                // Ignore search/filter bars inside form
                if (input.classList.contains('inflow-filter-input') || input.id.includes('Search') || input.id.includes('Filter')) {
                    continue;
                }
                if (input.type === 'checkbox' || input.type === 'radio') {
                    if (initialValues.has(input) && input.checked !== initialValues.get(input)) {
                        isDirty = true;
                        break;
                    }
                } else {
                    if (initialValues.has(input) && input.value !== initialValues.get(input)) {
                        isDirty = true;
                        break;
                    }
                }
            }

            // Find save button(s) for this form
            const formSaveBtns = form.querySelectorAll('button, input[type="submit"]');
            formSaveBtns.forEach(btn => {
                if (isSaveButton(btn)) {
                    setSaveButtonDirty(btn, isDirty);
                }
            });

            // Also check outside save button linked via form attribute
            if (form.id) {
                document.querySelectorAll(`button[form="${form.id}"]`).forEach(btn => {
                    if (isSaveButton(btn)) {
                        setSaveButtonDirty(btn, isDirty);
                    }
                });
            }
        }

        form.addEventListener('input', checkFormDirty);
        form.addEventListener('change', checkFormDirty);

        form.addEventListener('submit', () => {
            const formSaveBtns = form.querySelectorAll('button, input[type="submit"]');
            formSaveBtns.forEach(btn => {
                if (isSaveButton(btn)) {
                    setSaveButtonDirty(btn, false);
                }
            });
        });

        form.addEventListener('reset', () => {
            setTimeout(checkFormDirty, 20);
        });
    }

    document.querySelectorAll('form').forEach(watchForm);

    // 3. Dynamic Observer for dynamically added forms and buttons (e.g. modals, dynamic tabs)
    if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(mutations => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === 1) {
                        if (node.tagName === 'FORM') {
                            watchForm(node);
                        } else if (node.querySelectorAll) {
                            node.querySelectorAll('form').forEach(watchForm);
                            node.querySelectorAll('button, input[type="submit"]').forEach(btn => {
                                if (isSaveButton(btn)) {
                                    ensureSaveButtonDot(btn);
                                }
                            });
                        }
                    }
                }
            }
        });
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }
}
window.initGlobalSaveButtonDirtyWatcher = initGlobalSaveButtonDirtyWatcher;
window.setSaveButtonDirty = setSaveButtonDirty;

