/**
 * Google Sheets Style DatePicker for inFlow Premium
 * Authentic Google Workspace / Google Sheets Material design calendar picker.
 */

(function() {
    'use strict';

    const MONTH_NAMES_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const MONTH_NAMES_FULL = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];
    const DAY_NAMES = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

    let activeInput = null;
    let pickerPopup = null;
    let viewYear = 2026;
    let viewMonth = 9; // 0-indexed, 9 = October
    let selectedDate = null;

    function parseInputDate(val) {
        if (!val) return new Date();
        if (val instanceof Date) return isNaN(val.getTime()) ? new Date() : val;
        val = String(val).trim();
        if (!val) return new Date();

        const valLower = val.toLowerCase();
        const now = new Date();
        if (valLower === 'today' || valLower === 't') {
            return new Date(now.getFullYear(), now.getMonth(), now.getDate());
        }
        if (valLower === 'yesterday' || valLower === 'y') {
            const y = new Date();
            y.setDate(y.getDate() - 1);
            return new Date(y.getFullYear(), y.getMonth(), y.getDate());
        }
        if (valLower === 'tomorrow') {
            const t = new Date();
            t.setDate(t.getDate() + 1);
            return new Date(t.getFullYear(), t.getMonth(), t.getDate());
        }

        // 0. Single day number (e.g. "1", "01", "21") -> day of current month/year
        const singleDayMatch = val.match(/^(\d{1,2})$/);
        if (singleDayMatch) {
            const day = parseInt(singleDayMatch[1], 10);
            if (day >= 1 && day <= 31) {
                const year = (typeof viewYear === 'number' && viewYear > 1970) ? viewYear : now.getFullYear();
                const month = (typeof viewMonth === 'number' && viewMonth >= 0 && viewMonth <= 11) ? viewMonth : now.getMonth();
                const d = new Date(year, month, day);
                if (!isNaN(d.getTime())) return d;
            }
        }

        // 1. DD-MMM-YY, DD-MMM-YYYY, DD MMM YY, DD MMM YYYY (e.g. 21-Sep-26 or 21-Sep-2026)
        const dmyMatch = val.match(/^(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ](\d{2,4})$/);
        if (dmyMatch) {
            const day = parseInt(dmyMatch[1], 10);
            const monStr = dmyMatch[2].slice(0, 3).toLowerCase();
            let year = parseInt(dmyMatch[3], 10);
            if (year < 100) year += (year < 70 ? 2000 : 1900);
            const mIdx = MONTH_NAMES_SHORT.findIndex(m => m.toLowerCase() === monStr);
            if (mIdx !== -1) {
                const d = new Date(year, mIdx, day);
                if (!isNaN(d.getTime())) return d;
            }
        }

        // 2. DD-MMM (e.g. 20-Oct, 20 Oct) - assume current year
        const shortDmyMatch = val.match(/^(\d{1,2})[-/ ]([A-Za-z]{3,9})$/);
        if (shortDmyMatch) {
            const day = parseInt(shortDmyMatch[1], 10);
            const monStr = shortDmyMatch[2].slice(0, 3).toLowerCase();
            const year = now.getFullYear();
            const mIdx = MONTH_NAMES_SHORT.findIndex(m => m.toLowerCase() === monStr);
            if (mIdx !== -1) {
                const d = new Date(year, mIdx, day);
                if (!isNaN(d.getTime())) return d;
            }
        }

        // 3. YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD (ISO) - with optional time
        const isoMatch = val.match(/^(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})/);
        if (isoMatch) {
            const d = new Date(parseInt(isoMatch[1], 10), parseInt(isoMatch[2], 10) - 1, parseInt(isoMatch[3], 10));
            if (!isNaN(d.getTime())) return d;
        }

        // 4. DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY or 2-digit year DD/MM/YY
        const slashDmyMatch = val.match(/^(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2,4})/);
        if (slashDmyMatch) {
            const p1 = parseInt(slashDmyMatch[1], 10);
            const p2 = parseInt(slashDmyMatch[2], 10);
            let year = parseInt(slashDmyMatch[3], 10);
            if (year < 100) year += (year < 70 ? 2000 : 1900);

            // If p1 > 12, it must be DD/MM/YYYY
            // Otherwise default to DD/MM/YYYY (standard in Cambodia & inFlow)
            let day = p1;
            let month = p2 - 1;
            if (p1 <= 12 && p2 > 12) {
                // MM/DD/YYYY
                day = p2;
                month = p1 - 1;
            }
            const d = new Date(year, month, day);
            if (!isNaN(d.getTime())) return d;
        }

        // 5. DD/MM or DD-MM (assume current year)
        const shortNumMatch = val.match(/^(\d{1,2})[-/. ](\d{1,2})$/);
        if (shortNumMatch) {
            const day = parseInt(shortNumMatch[1], 10);
            const month = parseInt(shortNumMatch[2], 10) - 1;
            const year = now.getFullYear();
            const d = new Date(year, month, day);
            if (!isNaN(d.getTime())) return d;
        }

        const fallback = new Date(val);
        return isNaN(fallback.getTime()) ? new Date() : fallback;
    }

    function formatDate(date, targetInput) {
        if (!date || isNaN(date.getTime())) return '';
        const day = date.getDate();
        const dayStr = String(day).padStart(2, '0');
        const monShort = MONTH_NAMES_SHORT[date.getMonth()];
        const fullYear = date.getFullYear();
        const shortYear = String(fullYear).slice(-2);

        const currentVal = targetInput ? (targetInput.value || '').trim() : '';
        const isIso = (targetInput && targetInput.type === 'date') ||
                      (targetInput && targetInput.getAttribute('data-date-format') === 'iso') ||
                      (/^\d{4}-\d{2}-\d{2}$/.test(currentVal));

        if (isIso) {
            const mo = String(date.getMonth() + 1).padStart(2, '0');
            return `${fullYear}-${mo}-${dayStr}`;
        }

        const is4DigitYear = /\d{1,2}-[A-Za-z]{3}-\d{4}/.test(currentVal);
        if (is4DigitYear) {
            return `${dayStr}-${monShort}-${fullYear}`;
        }

        // Default inFlow / Google Sheet display format: DD-MMM-YY (e.g. 20-Oct-26)
        return `${dayStr}-${monShort}-${shortYear}`;
    }

    function createPickerPopup() {
        if (pickerPopup && document.body.contains(pickerPopup)) return pickerPopup;

        const existing = document.getElementById('gsDatepickerPopup');
        if (existing) {
            pickerPopup = existing;
            return pickerPopup;
        }

        pickerPopup = document.createElement('div');
        pickerPopup.id = 'gsDatepickerPopup';
        pickerPopup.className = 'gs-datepicker-popup';
        pickerPopup.innerHTML = `
            <div class="gs-dp-header">
                <div class="gs-dp-title" id="gsDpTitle">October 2026</div>
                <div class="gs-dp-nav-group">
                    <button type="button" class="gs-dp-nav-btn gs-dp-prev-btn" id="gsDpPrevBtn" title="Previous month" aria-label="Previous month">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="15 18 9 12 15 6"></polyline>
                        </svg>
                    </button>
                    <button type="button" class="gs-dp-nav-btn gs-dp-next-btn" id="gsDpNextBtn" title="Next month" aria-label="Next month">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                    </button>
                </div>
            </div>

            <div class="gs-dp-weekdays">
                ${DAY_NAMES.map(d => `<span class="gs-dp-weekday">${d}</span>`).join('')}
            </div>

            <div class="gs-dp-days-grid" id="gsDpDaysGrid"></div>

            <div class="gs-dp-footer">
                <button type="button" class="gs-dp-btn-today" id="gsDpTodayBtn">Today</button>
            </div>
        `;

        document.body.appendChild(pickerPopup);

        // Attach Header Navigation Events
        pickerPopup.querySelector('#gsDpPrevBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            changeMonth(-1);
        });

        pickerPopup.querySelector('#gsDpNextBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            changeMonth(1);
        });

        // Today Button
        pickerPopup.querySelector('#gsDpTodayBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            const today = new Date();
            selectDateAndClose(today);
        });

        // Prevent click inside popup from bubbling to document (which closes it)
        pickerPopup.addEventListener('click', (e) => {
            e.stopPropagation();
        });

        return pickerPopup;
    }

    function changeMonth(delta) {
        viewMonth += delta;
        if (viewMonth < 0) {
            viewMonth = 11;
            viewYear -= 1;
        } else if (viewMonth > 11) {
            viewMonth = 0;
            viewYear += 1;
        }
        renderCalendar();
    }

    function renderCalendar() {
        if (!pickerPopup) return;

        const titleEl = pickerPopup.querySelector('#gsDpTitle');
        if (titleEl) {
            titleEl.textContent = `${MONTH_NAMES_FULL[viewMonth]} ${viewYear}`;
        }

        const grid = pickerPopup.querySelector('#gsDpDaysGrid');
        grid.innerHTML = '';

        const today = new Date();
        const isCurrentTodayYear = today.getFullYear();
        const isCurrentTodayMonth = today.getMonth();
        const isCurrentTodayDay = today.getDate();

        const selectedY = selectedDate ? selectedDate.getFullYear() : null;
        const selectedM = selectedDate ? selectedDate.getMonth() : null;
        const selectedD = selectedDate ? selectedDate.getDate() : null;

        // Compute Grid Days
        const firstDayIndex = new Date(viewYear, viewMonth, 1).getDay(); // 0 is Sunday
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();

        // 1. Previous Month Days
        for (let i = firstDayIndex - 1; i >= 0; i--) {
            const pDay = daysInPrevMonth - i;
            const pYear = viewMonth === 0 ? viewYear - 1 : viewYear;
            const pMonth = viewMonth === 0 ? 11 : viewMonth - 1;
            createDayCell(grid, pDay, pYear, pMonth, false, false, false);
        }

        // 2. Current Month Days
        for (let d = 1; d <= daysInMonth; d++) {
            const isToday = (viewYear === isCurrentTodayYear && viewMonth === isCurrentTodayMonth && d === isCurrentTodayDay);
            const isSelected = (viewYear === selectedY && viewMonth === selectedM && d === selectedD);
            createDayCell(grid, d, viewYear, viewMonth, true, isToday, isSelected);
        }

        // 3. Next Month Days to complete a steady 6-row grid (exactly 42 days total, like Google Sheets)
        const totalRendered = firstDayIndex + daysInMonth;
        const remaining = 42 - totalRendered;
        for (let d = 1; d <= remaining; d++) {
            const nYear = viewMonth === 11 ? viewYear + 1 : viewYear;
            const nMonth = viewMonth === 11 ? 0 : viewMonth + 1;
            createDayCell(grid, d, nYear, nMonth, false, false, false);
        }
    }

    function createDayCell(grid, dayNum, year, month, isCurrentMonth, isToday, isSelected) {
        const cell = document.createElement('div');
        cell.className = 'gs-dp-day-cell';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'gs-dp-day-btn';
        btn.textContent = dayNum;

        if (!isCurrentMonth) {
            btn.classList.add('gs-dp-day-muted');
        }
        if (isToday) {
            btn.classList.add('gs-dp-day-today');
        }
        if (isSelected) {
            btn.classList.add('gs-dp-day-selected');
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const chosen = new Date(year, month, dayNum);
            selectDateAndClose(chosen);
        });

        cell.appendChild(btn);
        grid.appendChild(cell);
    }

    function selectDateAndClose(date) {
        if (!activeInput) return;
        selectedDate = date;
        const formatted = formatDate(date, activeInput);
        activeInput.value = formatted;

        // Dispatch input & change events
        activeInput.dispatchEvent(new Event('input', { bubbles: true }));
        activeInput.dispatchEvent(new Event('change', { bubbles: true }));

        // Call handleBillDateChange if defined on sales order page
        if (typeof window.handleBillDateChange === 'function') {
            window.handleBillDateChange(activeInput);
        }

        // Call markDirty if present in page
        if (typeof window.markDirty === 'function') {
            window.markDirty();
        }

        closePicker();
    }

    function commitInputAndClose() {
        if (!activeInput) {
            closePicker();
            return;
        }
        const val = (activeInput.value || '').trim();
        if (val) {
            const parsed = parseInputDate(val);
            if (parsed && !isNaN(parsed.getTime())) {
                const formatted = formatDate(parsed, activeInput);
                if (formatted && formatted !== activeInput.value) {
                    activeInput.value = formatted;
                    activeInput.dispatchEvent(new Event('input', { bubbles: true }));
                    activeInput.dispatchEvent(new Event('change', { bubbles: true }));
                    if (typeof window.handleBillDateChange === 'function') {
                        window.handleBillDateChange(activeInput);
                    }
                    if (typeof window.markDirty === 'function') {
                        window.markDirty();
                    }
                }
            }
        }
        closePicker();
    }

    function positionPicker(targetInput) {
        if (!pickerPopup || !targetInput) return;

        // Ensure popup is display block before measuring
        pickerPopup.style.display = 'block';
        pickerPopup.style.visibility = 'hidden';

        const rect = targetInput.getBoundingClientRect();
        const popupWidth = 246;
        const popupHeight = pickerPopup.offsetHeight || 292;
        const margin = 8;

        // Horizontal positioning: align right edge if on right side of screen
        let left = rect.left;
        if (left + popupWidth > window.innerWidth - margin) {
            left = rect.right - popupWidth;
        }
        // Clamp inside viewport
        left = Math.max(margin, Math.min(left, window.innerWidth - popupWidth - margin));

        // Vertical positioning: check space below vs above
        let top = rect.bottom + 4;
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;

        if (spaceBelow < popupHeight + margin && spaceAbove > spaceBelow) {
            // Flip above
            top = rect.top - popupHeight - 4;
        }

        // Clamp inside viewport so bottom or top is never clipped off
        top = Math.max(margin, Math.min(top, window.innerHeight - popupHeight - margin));

        pickerPopup.style.position = 'fixed';
        pickerPopup.style.left = `${Math.round(left)}px`;
        pickerPopup.style.top = `${Math.round(top)}px`;
        pickerPopup.style.zIndex = '99999999';
        pickerPopup.style.opacity = '1';
        pickerPopup.style.visibility = 'visible';
    }

    function openPicker(targetInput) {
        if (!targetInput || targetInput.readOnly || targetInput.disabled) return;

        // If targetInput belongs to an iframe or parent document with its own picker, delegate cleanly
        if (targetInput.ownerDocument && targetInput.ownerDocument !== document) {
            const win = targetInput.ownerDocument.defaultView;
            if (win && win.GoogleSheetDatePicker && win.GoogleSheetDatePicker !== api) {
                win.GoogleSheetDatePicker.open(targetInput);
                return;
            }
        }

        createPickerPopup();
        activeInput = targetInput;

        // Parse date from input
        const currentVal = (targetInput.value || '').trim();
        const parsed = parseInputDate(currentVal);
        selectedDate = parsed;
        viewYear = parsed.getFullYear();
        viewMonth = parsed.getMonth();

        renderCalendar();
        positionPicker(targetInput);

        // Add visual active state to wrapper
        const wrapper = targetInput.closest('.gs-datepicker-wrapper');
        if (wrapper) {
            wrapper.classList.add('gs-active');
        }
    }

    function closePicker() {
        if (pickerPopup) {
            pickerPopup.style.display = 'none';
        }
        if (activeInput) {
            const wrapper = activeInput.closest('.gs-datepicker-wrapper');
            if (wrapper) {
                wrapper.classList.remove('gs-active');
            }
        }
        activeInput = null;
    }

    // Attach to single input
    function attachToInput(input) {
        if (!input) return;

        input.classList.add('gs-datepicker-input');

        // Check if already in wrapper; if not, wrap cleanly
        let wrapper = input.closest('.gs-datepicker-wrapper');
        let icon = null;
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'gs-datepicker-wrapper';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);

            // Add calendar icon
            icon = document.createElement('span');
            icon.className = 'gs-datepicker-icon';
            icon.title = 'Select date';
            icon.innerHTML = `
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
            `;
            wrapper.appendChild(icon);
        } else {
            icon = wrapper.querySelector('.gs-datepicker-icon');
        }

        // Calendar icon click toggles picker
        if (icon && !icon.__gsDatepickerAttached) {
            icon.__gsDatepickerAttached = true;
            icon.style.cursor = 'pointer';
            icon.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (activeInput === input && pickerPopup && pickerPopup.style.display !== 'none') {
                    closePicker();
                } else {
                    openPicker(input);
                }
            };
        }

        // Open on input click, dblclick, or focus, and handle typing like Google Sheets
        if (!input.__gsDatepickerAttached) {
            input.__gsDatepickerAttached = true;

            input.addEventListener('click', (e) => {
                e.stopPropagation();
                openPicker(input);
            });

            input.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                openPicker(input);
            });

            // Live-sync calendar while typing if valid date
            input.addEventListener('input', () => {
                if (activeInput === input && pickerPopup && pickerPopup.style.display !== 'none') {
                    const val = (input.value || '').trim();
                    if (val.length >= 3) {
                        const parsed = parseInputDate(val);
                        if (parsed && !isNaN(parsed.getTime())) {
                            selectedDate = parsed;
                            viewYear = parsed.getFullYear();
                            viewMonth = parsed.getMonth();
                            renderCalendar();
                        }
                    }
                }
            });

            // Google Sheets keyboard shortcuts
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closePicker();
                } else if (e.key === 'Enter' || e.key === 'Tab') {
                    commitInputAndClose();
                } else if (e.key === 'ArrowUp') {
                    // Increment day by 1
                    e.preventDefault();
                    const cur = parseInputDate(input.value || '');
                    cur.setDate(cur.getDate() + 1);
                    selectDateAndClose(cur);
                } else if (e.key === 'ArrowDown') {
                    // Decrement day by 1
                    e.preventDefault();
                    const cur = parseInputDate(input.value || '');
                    cur.setDate(cur.getDate() - 1);
                    selectDateAndClose(cur);
                }
            });

            // Normalize typed value on blur
            input.addEventListener('blur', () => {
                setTimeout(() => {
                    if (activeInput !== input) {
                        const val = (input.value || '').trim();
                        if (val) {
                            const parsed = parseInputDate(val);
                            if (parsed && !isNaN(parsed.getTime())) {
                                const formatted = formatDate(parsed, input);
                                if (formatted && formatted !== input.value) {
                                    input.value = formatted;
                                    input.dispatchEvent(new Event('input', { bubbles: true }));
                                    input.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }
                        }
                    }
                }, 150);
            });
        }
    }

    // Global document listeners
    document.addEventListener('click', (e) => {
        if (pickerPopup && pickerPopup.style.display !== 'none') {
            const activeWrapper = activeInput ? activeInput.closest('.gs-datepicker-wrapper') : null;
            if (activeWrapper && activeWrapper.contains(e.target)) {
                return;
            }
            if (!pickerPopup.contains(e.target) && (!activeInput || !activeInput.contains(e.target))) {
                commitInputAndClose();
            }
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && pickerPopup && pickerPopup.style.display !== 'none') {
            closePicker();
        }
    });

    window.addEventListener('resize', () => {
        if (activeInput && pickerPopup && pickerPopup.style.display !== 'none') {
            positionPicker(activeInput);
        }
    });

    window.addEventListener('scroll', () => {
        if (activeInput && pickerPopup && pickerPopup.style.display !== 'none') {
            positionPicker(activeInput);
        }
    }, true);

    // Auto-discover inputs on DOM ready
    function initAll() {
        const selectors = [
            'input.gs-datepicker-input',
            'input[name="order_date"]',
            'input[name="expected_date"]',
            'input[name="due_date"]',
            'input[data-datepicker="google-sheet"]'
        ];
        document.querySelectorAll(selectors.join(',')).forEach(input => {
            attachToInput(input);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

    // Expose API
    const api = {
        attach: attachToInput,
        initAll: initAll,
        open: openPicker,
        close: closePicker,
        formatDate: formatDate,
        parseInputDate: parseInputDate
    };

    window.GoogleSheetDatePicker = api;
    try {
        if (window.parent && window.parent !== window) {
            window.parent.GoogleSheetDatePicker = api;
        }
        if (window.top && window.top !== window) {
            window.top.GoogleSheetDatePicker = api;
        }
    } catch (e) {}

})();
