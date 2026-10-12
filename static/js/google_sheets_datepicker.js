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

        // 1. DD-MMM-YY or DD-MMM-YYYY (e.g. 09-Oct-26 or 09-Oct-2026)
        const dmyMatch = val.match(/^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$/);
        if (dmyMatch) {
            const day = parseInt(dmyMatch[1], 10);
            const monStr = dmyMatch[2].toLowerCase();
            let year = parseInt(dmyMatch[3], 10);
            if (year < 100) year += (year < 70 ? 2000 : 1900);
            const mIdx = MONTH_NAMES_SHORT.findIndex(m => m.toLowerCase() === monStr);
            if (mIdx !== -1) {
                const d = new Date(year, mIdx, day);
                if (!isNaN(d.getTime())) return d;
            }
        }

        // 2. YYYY-MM-DD (ISO)
        const isoMatch = val.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
        if (isoMatch) {
            const d = new Date(parseInt(isoMatch[1], 10), parseInt(isoMatch[2], 10) - 1, parseInt(isoMatch[3], 10));
            if (!isNaN(d.getTime())) return d;
        }

        // 3. DD/MM/YYYY or MM/DD/YYYY
        const slashMatch = val.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        if (slashMatch) {
            const d = new Date(parseInt(slashMatch[3], 10), parseInt(slashMatch[2], 10) - 1, parseInt(slashMatch[1], 10));
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

        // Determine format based on existing input value or attribute
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

        // Default inFlow format: DD-MMM-YY (e.g. 09-Oct-26)
        return `${dayStr}-${monShort}-${shortYear}`;
    }

    function createPickerPopup() {
        if (pickerPopup) return pickerPopup;

        pickerPopup = document.createElement('div');
        pickerPopup.id = 'gsDatepickerPopup';
        pickerPopup.className = 'gs-datepicker-popup';
        pickerPopup.innerHTML = `
            <div class="gs-dp-header">
                <div class="gs-dp-title-group">
                    <span class="gs-dp-month-label" id="gsDpMonthLabel"></span>
                    <span class="gs-dp-year-label" id="gsDpYearLabel"></span>
                </div>
                <div class="gs-dp-nav-buttons">
                    <button type="button" class="gs-dp-nav-btn" id="gsDpPrevBtn" title="Previous month" aria-label="Previous month">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="15 18 9 12 15 6"></polyline>
                        </svg>
                    </button>
                    <button type="button" class="gs-dp-nav-btn" id="gsDpNextBtn" title="Next month" aria-label="Next month">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                    </button>
                </div>
            </div>

            <!-- Month & Year Jump Selector Dropdowns -->
            <div class="gs-dp-fast-selectors" id="gsDpFastSelectors">
                <select class="gs-dp-select" id="gsDpMonthSelect">
                    ${MONTH_NAMES_FULL.map((m, i) => `<option value="${i}">${m}</option>`).join('')}
                </select>
                <select class="gs-dp-select" id="gsDpYearSelect"></select>
            </div>

            <div class="gs-dp-weekdays">
                ${DAY_NAMES.map(d => `<span class="gs-dp-weekday">${d}</span>`).join('')}
            </div>

            <div class="gs-dp-days-grid" id="gsDpDaysGrid"></div>

            <div class="gs-dp-footer">
                <button type="button" class="gs-dp-btn-today" id="gsDpTodayBtn">Today</button>
                <button type="button" class="gs-dp-btn-close" id="gsDpCloseBtn">Done</button>
            </div>
        `;

        document.body.appendChild(pickerPopup);

        // Populate Years (Current Year - 10 to Current Year + 15)
        const yearSelect = pickerPopup.querySelector('#gsDpYearSelect');
        const currentYear = new Date().getFullYear();
        for (let y = currentYear - 10; y <= currentYear + 15; y++) {
            const opt = document.createElement('option');
            opt.value = y;
            opt.textContent = y;
            yearSelect.appendChild(opt);
        }

        // Attach Header Events
        pickerPopup.querySelector('#gsDpPrevBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            changeMonth(-1);
        });

        pickerPopup.querySelector('#gsDpNextBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            changeMonth(1);
        });

        pickerPopup.querySelector('#gsDpMonthSelect').addEventListener('change', (e) => {
            viewMonth = parseInt(e.target.value, 10);
            renderCalendar();
        });

        pickerPopup.querySelector('#gsDpYearSelect').addEventListener('change', (e) => {
            viewYear = parseInt(e.target.value, 10);
            renderCalendar();
        });

        // Today Button
        pickerPopup.querySelector('#gsDpTodayBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            const today = new Date();
            selectDateAndClose(today);
        });

        // Done / Close Button
        pickerPopup.querySelector('#gsDpCloseBtn').addEventListener('click', (e) => {
            e.stopPropagation();
            closePicker();
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

        // Update Labels & Selects
        const monthLabel = pickerPopup.querySelector('#gsDpMonthLabel');
        const yearLabel = pickerPopup.querySelector('#gsDpYearLabel');
        const monthSelect = pickerPopup.querySelector('#gsDpMonthSelect');
        const yearSelect = pickerPopup.querySelector('#gsDpYearSelect');

        if (monthLabel) monthLabel.textContent = MONTH_NAMES_FULL[viewMonth];
        if (yearLabel) yearLabel.textContent = viewYear;
        if (monthSelect) monthSelect.value = viewMonth;
        if (yearSelect) yearSelect.value = viewYear;

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

        // 3. Next Month Days to complete row
        const totalRendered = firstDayIndex + daysInMonth;
        const remaining = (7 - (totalRendered % 7)) % 7;
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

        // Call markDirty if present in page
        if (typeof window.markDirty === 'function') {
            window.markDirty();
        }

        closePicker();
    }

    function positionPicker(targetInput) {
        if (!pickerPopup || !targetInput) return;

        const rect = targetInput.getBoundingClientRect();
        const popupWidth = 280;
        const popupHeight = 320;
        const scrollX = window.scrollX || window.pageXOffset || 0;
        const scrollY = window.scrollY || window.pageYOffset || 0;

        // Calculate left position (align right if close to right edge)
        let left = rect.left + scrollX;
        if (left + popupWidth > window.innerWidth - 12) {
            left = (rect.right + scrollX) - popupWidth;
        }
        if (left < 10) left = 10;

        // Calculate top position (show above if bottom overflows window)
        let top = rect.bottom + scrollY + 4;
        if (rect.bottom + popupHeight > window.innerHeight - 10 && rect.top > popupHeight + 10) {
            top = rect.top + scrollY - popupHeight - 4;
        }

        pickerPopup.style.left = `${left}px`;
        pickerPopup.style.top = `${top}px`;
    }

    function openPicker(targetInput) {
        if (!targetInput || targetInput.readOnly || targetInput.disabled) return;

        createPickerPopup();
        activeInput = targetInput;

        // Parse date from input
        const currentVal = (targetInput.value || '').trim();
        const parsed = parseInputDate(currentVal);
        selectedDate = parsed;
        viewYear = parsed.getFullYear();
        viewMonth = parsed.getMonth();

        renderCalendar();
        pickerPopup.style.display = 'block';
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
        if (!input || input.__gsDatepickerAttached) return;
        input.__gsDatepickerAttached = true;

        input.classList.add('gs-datepicker-input');

        // Check if already in wrapper; if not, wrap cleanly
        let wrapper = input.closest('.gs-datepicker-wrapper');
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'gs-datepicker-wrapper';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);

            // Add calendar icon
            const icon = document.createElement('span');
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

            icon.addEventListener('click', (e) => {
                e.stopPropagation();
                if (activeInput === input && pickerPopup && pickerPopup.style.display !== 'none') {
                    closePicker();
                } else {
                    openPicker(input);
                }
            });
        }

        // Open on input click or focus
        input.addEventListener('click', (e) => {
            e.stopPropagation();
            openPicker(input);
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closePicker();
            }
        });
    }

    // Global document listeners
    document.addEventListener('click', (e) => {
        if (pickerPopup && pickerPopup.style.display !== 'none') {
            if (!pickerPopup.contains(e.target) && (!activeInput || !activeInput.contains(e.target))) {
                closePicker();
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
    window.GoogleSheetDatePicker = {
        attach: attachToInput,
        initAll: initAll,
        open: openPicker,
        close: closePicker
    };

})();
