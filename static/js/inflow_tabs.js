/**
 * inFlow Inventory MDI Top Window Tabs & Multi-Document Workspace System
 *
 * Rules matching inFlow Inventory Desktop Edition:
 * 1. "tab won't be created if stay in same category only create when step to others":
 *    - Example: Inside Product, navigating between products or product tabs stays in current tab.
 *    - Stepping to others: In Product -> Order History, double-clicking a Sales Order or Purchase Order
 *      steps to another category (product -> sales / purchase), so it CREATES A NEW TAB!
 * 2. "If I add new tab it will go to home page":
 *    - Clicking '+' creates a new tab with Homepage ('/').
 * 3. "if I select category below it will transform tab to that not create new tab":
 *    - When on Homepage (or on a newly created Homepage tab), selecting any category/workflow node below
 *      TRANSFORMS that Homepage tab into that category. It does NOT create a new tab!
 * 4. Switching tabs is 0ms instantaneous: scroll positions, form data, sub-tabs, and filters remain 100% intact.
 */

(function () {
    const STORAGE_KEY = 'inflow_mdi_tabs_v5';
    const ACTIVE_TAB_KEY = 'inflow_mdi_active_tab_v5';

    const isHostShell = (window.self === window.top);

    function getCleanPath(url) {
        if (!url) return '/';
        try {
            if (url.startsWith('http://') || url.startsWith('https://')) {
                return new URL(url).pathname;
            }
        } catch (e) { }
        return url.split('?')[0].split('#')[0];
    }

    // Module Type Detection & Icon Definitions
    function detectTypeFromUrl(url) {
        if (!url) return 'home';
        const clean = getCleanPath(url).toLowerCase();
        if (clean === '/' || clean === '' || clean.includes('/dashboard') || clean.includes('/workspace')) return 'home';
        if (clean.includes('/sales') || clean.includes('/customers') || clean.includes('/contacts/customers')) return 'sales';
        if (clean.includes('/purchase') || clean.includes('/vendors') || clean.includes('/contacts/vendors')) return 'purchase';
        if (clean.includes('/product') || clean.includes('/inventory') || clean.includes('/locations')) return 'product';
        if (clean.includes('/reports')) return 'reports';
        if (clean.includes('/expenses')) return 'expenses';
        if (clean.includes('/settings') || clean.includes('/migration') || clean.includes('/data')) return 'settings';
        return 'default';
    }

    function getTabIconSvg(type) {
        switch (type) {
            case 'expenses':
                return `<span class="inflow-tab-icon icon-expenses" title="Monthly Expenses & Cash Flow">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <rect x="2" y="5" width="20" height="14" rx="2.5" fill="#CCFBF1" stroke="#0F766E" stroke-width="1.6"/>
                        <path d="M16 12h4" stroke="#0F766E" stroke-width="2" stroke-linecap="round"/>
                        <circle cx="17.5" cy="12" r="1" fill="#0F766E"/>
                    </svg>
                </span>`;
            case 'product':
                return `<span class="inflow-tab-icon icon-product" title="Product / Inventory">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M12 2L2 7l10 5 10-5-10-5z" fill="#FDBA74" stroke="#EA580C" stroke-width="1.5"/>
                        <path d="M2 17l10 5V12L2 7v10z" fill="#FB923C" stroke="#EA580C" stroke-width="1.5"/>
                        <path d="M22 17l-10 5V12l10-5v10z" fill="#F97316" stroke="#EA580C" stroke-width="1.5"/>
                    </svg>
                </span>`;
            case 'sales':
                return `<span class="inflow-tab-icon icon-sales" title="Sales">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M4 3h11l5 5v13H4V3z" fill="#FFFFFF" stroke="#84C225" stroke-width="1.5"/>
                        <path d="M15 3v5h5" fill="#E2F8CB" stroke="#84C225" stroke-width="1.5"/>
                        <text x="11" y="17" font-size="11" font-weight="900" fill="#689F38" text-anchor="middle">$</text>
                    </svg>
                </span>`;
            case 'purchase':
                return `<span class="inflow-tab-icon icon-purchase" title="Purchasing">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M4 3h11l5 5v13H4V3z" fill="#FFFFFF" stroke="#F5A623" stroke-width="1.5"/>
                        <path d="M15 3v5h5" fill="#FEF3C7" stroke="#F5A623" stroke-width="1.5"/>
                        <circle cx="12" cy="14" r="3.2" fill="#EA580C"/>
                        <path d="M10 14h4" stroke="#FFFFFF" stroke-width="1.2"/>
                    </svg>
                </span>`;
            case 'reports':
                return `<span class="inflow-tab-icon icon-reports" title="Reports">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M4 3h12l4 4v14H4V3z" fill="#FFFFFF" stroke="#4338CA" stroke-width="1.5"/>
                        <path d="M8 17v-4M12 17v-8M16 17v-2" stroke="#4338CA" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                </span>`;
            case 'settings':
                return `<span class="inflow-tab-icon icon-settings" title="Settings">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="#64748B">
                        <path d="M12 15a3 3 0 100-6 3 3 0 000 6z"/>
                        <path fill-rule="evenodd" d="M10.3 2.3c.4-.2.9-.3 1.4-.3s1 .1 1.4.3l.6 1.4c.5.2 1 .4 1.4.8l1.4-.5c.8-.3 1.7 0 2.2.7l1 1.7c.4.7.3 1.6-.2 2.2l-1.1 1c.1.5.2 1 .2 1.5s-.1 1-.2 1.5l1.1 1c.5.6.6 1.5.2 2.2l-1 1.7c-.5.7-1.4 1-2.2.7l-1.4-.5c-.4.4-.9.6-1.4.8l-.6 1.4c-.4.8-1.2 1.3-2.1 1.3s-1.7-.5-2.1-1.3l-.6-1.4c-.5-.2-1-.4-1.4-.8l-1.4.5c-.8.3-1.7 0-2.2-.7l-1-1.7c-.4-.7-.3-1.6.2-2.2l1.1-1c-.1-.5-.2-1-.2-1.5s.1-1 .2-1.5l-1.1-1c-.5-.6-.6-1.5-.2-2.2l1-1.7c.5-.7 1.4-1 2.2-.7l1.4.5c.4-.4.9-.6 1.4-.8l.6-1.4z" clip-rule="evenodd"/>
                    </svg>
                </span>`;
            case 'home':
            default:
                return `<span class="inflow-tab-icon icon-home" title="Homepage">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="#3B82F6" stroke="#1D4ED8" stroke-width="1.2">
                        <path d="M3 10l9-7 9 7v10a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1V10z"/>
                    </svg>
                </span>`;
        }
    }

    function appendEmbedParam(url) {
        if (!url) return '/?embed=1';
        if (url.includes('embed=1')) return url;
        const sep = url.includes('?') ? '&' : '?';
        return url + sep + 'embed=1';
    }

    function getUkFlagSvg(w = 19, h = 13) {
        return `<svg width="${w}" height="${h}" viewBox="0 0 60 40" style="border-radius: 2px; overflow: hidden; box-shadow: 0 0 1px rgba(0,0,0,0.4); vertical-align: middle; flex-shrink: 0;" aria-label="UK Flag">
            <rect width="60" height="40" fill="#012169"/>
            <path stroke="#FFFFFF" stroke-width="7" d="M0 0 L60 40 M60 0 L0 40"/>
            <path stroke="#C8102E" stroke-width="4" d="M0 0 L60 40 M60 0 L0 40"/>
            <path fill="#FFFFFF" d="M25 0h10v40H25z M0 15h60v10H0z"/>
            <path fill="#C8102E" d="M27 0h6v40H27z M0 17h60v6H0z"/>
        </svg>`;
    }

    function getKhmerFlagSvg(w = 19, h = 13) {
        return `<svg width="${w}" height="${h}" viewBox="0 0 60 40" style="border-radius: 2px; overflow: hidden; box-shadow: 0 0 1px rgba(0,0,0,0.4); vertical-align: middle; flex-shrink: 0;" aria-label="Khmer Flag">
            <rect width="60" height="10" fill="#032EA6"/>
            <rect y="10" width="60" height="20" fill="#ED1B24"/>
            <rect y="30" width="60" height="10" fill="#032EA6"/>
            <g fill="#FFFFFF">
                <rect x="17" y="26.5" width="26" height="2" rx="0.3"/>
                <rect x="19" y="24.5" width="22" height="2"/>
                <rect x="21" y="22.5" width="18" height="2"/>
                <path d="M28.5 13.5 L31.5 13.5 L32 18 L32.5 22.5 L27.5 22.5 L28 18 Z"/>
                <polygon points="30,11 28,13.5 32,13.5"/>
                <path d="M23.5 16 L26.5 16 L27 19.5 L27.5 22.5 L22.5 22.5 L23 19.5 Z"/>
                <polygon points="25,13.5 23,16 27,16"/>
                <path d="M33.5 16 L36.5 16 L37 19.5 L37.5 22.5 L32.5 22.5 L33 19.5 Z"/>
                <polygon points="35,13.5 33,16 37,16"/>
                <polygon points="20,19.5 19,22.5 21.5,22.5"/>
                <polygon points="40,19.5 38.5,22.5 41,22.5"/>
            </g>
        </svg>`;
    }

    /* ==========================================================================
       HOST SHELL MANAGER (Runs in the top browser window)
       ========================================================================== */
    if (isHostShell) {
        document.body.classList.add('inflow-mdi-host');
        document.documentElement.classList.add('is-shell-host');
        document.body.classList.remove('sales-order-body-fullscreen');

        // Clean up direct content in host shell so no duplicate elements or split view exist
        const directContent = document.getElementById('inflowDirectContent');
        if (directContent) {
            directContent.style.display = 'none';
            directContent.innerHTML = '';
        }

        const MdiShell = {
            tabs: [],
            activeTabId: null,

            init: function () {
                const storeCtx = window.INFLOW_STORE_CONTEXT || {};
                const currentStoreId = (storeCtx.is_branch_mode && storeCtx.current_branch)
                    ? String(storeCtx.current_branch.id)
                    : '0';
                const savedStoreId = localStorage.getItem('inflow_active_store_id');
                if (savedStoreId !== null && savedStoreId !== currentStoreId) {
                    // Store context switched! Clear stale tabs from storage to avoid loading wrong store iframe
                    localStorage.removeItem(STORAGE_KEY);
                    localStorage.removeItem(ACTIVE_TAB_KEY);
                }
                localStorage.setItem('inflow_active_store_id', currentStoreId);

                this.loadTabsFromStorage();

                const currentPath = window.location.pathname + window.location.search;
                const cleanCurrent = currentPath.replace(/[?&]embed=1/, '');

                if (this.tabs.length === 0) {
                    const isBranchMode = !!storeCtx.is_branch_mode;
                    const currentBranch = storeCtx.current_branch;

                    if (isBranchMode && currentBranch) {
                        const bCode = currentBranch.code || 'STM';
                        const homeUrl = `/branches/${currentBranch.id}/workspace`;
                        this.tabs = [
                            { id: 'tab-branch-home-' + Date.now(), type: 'home', title: `${bCode} Workspace`, label: `${bCode} Workspace`, url: homeUrl }
                        ];
                        this.activeTabId = this.tabs[0].id;
                    } else if (cleanCurrent !== '/' && cleanCurrent !== '' && !cleanCurrent.startsWith('/login')) {
                        const type = detectTypeFromUrl(cleanCurrent);
                        const title = this.guessTitle(cleanCurrent, type);
                        this.tabs = [
                            { id: 'tab-init-' + Date.now(), type: type, title: title, label: title, url: cleanCurrent }
                        ];
                        this.activeTabId = this.tabs[0].id;
                    } else {
                        // Default tab: Homepage / Main Store Dashboard
                        // title: 'Homepage'
                        this.tabs = [
                            { id: 'tab-home-' + Date.now(), type: 'home', title: 'Main Store Dashboard', label: 'Main Store Dashboard', url: '/dashboard' }
                        ];
                        this.activeTabId = this.tabs[0].id;
                    }
                } else {
                    if (cleanCurrent !== '/' && cleanCurrent !== '' && !cleanCurrent.startsWith('/login')) {
                        let existing = this.tabs.find(t => {
                            const tu = (t.url || '').replace(/[?&]embed=1/, '');
                            return tu === cleanCurrent;
                        });
                        if (existing) {
                            this.activeTabId = existing.id;
                        } else {
                            const type = detectTypeFromUrl(cleanCurrent);
                            const title = this.guessTitle(cleanCurrent, type);
                            const newTab = { id: 'tab-init-' + Date.now(), type: type, title: title, label: title, url: cleanCurrent };
                            this.tabs.push(newTab);
                            this.activeTabId = newTab.id;
                        }
                    } else if (!this.activeTabId || !this.tabs.find(t => t.id === this.activeTabId)) {
                        this.activeTabId = this.tabs[0].id;
                    }
                }

                this.renderTabBar();
                this.mountAllViewports();
                this.switchTab(this.activeTabId);
                this.bindGlobalEvents();
                this.updateLangUi(this.getLanguage());
            },

            guessTitle: function (url, type) {
                if (url.includes('/workspace')) {
                    const storeCtx = window.INFLOW_STORE_CONTEXT || {};
                    const bCode = (storeCtx.current_branch && storeCtx.current_branch.code) ? storeCtx.current_branch.code : '';
                    return bCode ? `${bCode} Workspace` : 'Branch Workspace';
                }
                if (type === 'sales') {
                    if (url.includes('/create') || url.includes('/new')) return 'Sales Order';
                    if (url.includes('/customers')) return 'Customer List';
                    return 'Sales Order';
                }
                if (type === 'purchase') {
                    if (url.includes('/create') || url.includes('/new')) return 'Purchase Order';
                    if (url.includes('/vendors')) return 'Vendor List';
                    return 'Purchase Order';
                }
                if (type === 'product') {
                    if (url.includes('/new')) return 'Product';
                    return 'Product';
                }
                if (type === 'reports') {
                    if (url.includes('/view/')) {
                        try {
                            const repKey = url.split('/view/')[1].split('?')[0].split('/')[0];
                            if (repKey) {
                                return repKey.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                            }
                        } catch (e) { }
                    }
                    if (url.includes('/list') || url.includes('/reports')) return 'Reports List';
                    return 'Reports';
                }
                if (type === 'expenses') return 'Monthly Expenses';
                if (url.includes('/data/import')) return 'Import Data';
                if (url.includes('/data/export')) return 'Export Data';
                if (type === 'settings') return 'Settings';
                return 'Homepage';
            },

            loadTabsFromStorage: function () {
                try {
                    const raw = localStorage.getItem(STORAGE_KEY);
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (Array.isArray(parsed) && parsed.length > 0) {
                            this.tabs = parsed.map(t => {
                                const clean = (t.url || '').replace(/[?&]embed=1/, '');
                                if (!clean || clean === '/' || clean.startsWith('/login') || (t.title && t.title.toLowerCase().includes('sign in'))) {
                                    return {
                                        ...t,
                                        url: '/dashboard',
                                        title: 'Main Store Dashboard',
                                        label: 'Main Store Dashboard',
                                        origTitleEn: 'Main Store Dashboard',
                                        type: 'home'
                                    };
                                }
                                return t;
                            }).filter(t => t && t.url && !t.url.startsWith('/login'));
                        }
                    }
                    this.activeTabId = localStorage.getItem(ACTIVE_TAB_KEY);
                } catch (e) {
                    console.warn('Could not read saved tabs:', e);
                }
            },

            saveTabsToStorage: function () {
                try {
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.tabs));
                    if (this.activeTabId) {
                        localStorage.setItem(ACTIVE_TAB_KEY, this.activeTabId);
                    }
                } catch (e) {
                    console.warn('Could not save tabs:', e);
                }
            },

            renderTabBar: function () {
                const container = document.getElementById('inflowTopTabBar');
                if (!container) return;

                let html = `
                    <div class="inflow-bar-left">
                        <div class="inflow-nav-buttons">
                            <button type="button" class="inflow-nav-btn" id="inflowNavBackBtn" title="Back" onclick="window.inflowMdi.back(event)">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="15 18 9 12 15 6"></polyline>
                                </svg>
                            </button>
                            <button type="button" class="inflow-nav-btn" id="inflowNavForwardBtn" title="Forward" onclick="window.inflowMdi.forward(event)">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="9 18 15 12 9 6"></polyline>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="inflow-tabs-scroll-area" id="inflowTabsTrack">
                `;

                const currentLangForTabs = this.getLanguage ? this.getLanguage() : (localStorage.getItem('inflow_app_lang') || 'en');
                this.tabs.forEach(tab => {
                    const isActive = (tab.id === this.activeTabId);
                    const activeClass = isActive ? 'active' : '';
                    const typeClass = `tab-${tab.type || 'default'}`;
                    const rawTitle = tab.origTitleEn || tab.label || tab.title;
                    if (!tab.origTitleEn) tab.origTitleEn = rawTitle;
                    const displayTitle = (currentLangForTabs === 'km') ? this.translateTabTitle(rawTitle, 'km') : rawTitle;

                    html += `
                        <div class="inflow-tab-item ${typeClass} ${activeClass}" 
                             id="tab-item-${tab.id}"
                             onclick="window.inflowMdi.switchTab('${tab.id}')" 
                             title="${displayTitle}">
                            ${getTabIconSvg(tab.type)}
                            <span class="inflow-tab-label" id="tab-label-${tab.id}">${displayTitle}</span>
                            <button type="button" class="inflow-tab-close" 
                                    onclick="window.inflowMdi.closeTab('${tab.id}', event)" title="Close tab">✕</button>
                        </div>
                    `;
                });

                html += `
                        <div class="inflow-tab-add-wrapper">
                            <button type="button" class="inflow-tab-add-btn" id="inflowTabAddBtn" onclick="window.addNewHomepageTab(event)" title="New Tab (Homepage)">+</button>
                        </div>
                    </div>
                `;

                // Top Store Context Switcher Pill & Dropdown
                try {
                    const storeCtx = window.INFLOW_STORE_CONTEXT || {};
                    const isBranchMode = !!storeCtx.is_branch_mode;
                    const currentBranch = storeCtx.current_branch || null;
                    const allBranches = Array.isArray(storeCtx.all_branches) ? storeCtx.all_branches : [];

                    // Show ONLY CODE as required by user
                    const storeCode = (isBranchMode && currentBranch) ? (currentBranch.code || 'STM') : 'HQ';
                    const storeIcon = isBranchMode ? '🏪' : '🏢';
                    const storeClass = isBranchMode ? 'store-pill-branch' : 'store-pill-main';
                    const storeTooltip = isBranchMode && currentBranch 
                        ? `${currentBranch.name} (${storeCode}) - Click to Switch Store` 
                        : 'Main Store (HQ Enterprise) - Click to Switch Store';

                    let branchOptionsHtml = `
                        <a href="/branches/switch/0" onclick="window.inflowMdi.switchStoreContext(0, event)" class="inflow-store-dropdown-item ${!isBranchMode ? 'active' : ''}">
                            <span>🏢 Main Store (HQ Enterprise)</span>
                            ${!isBranchMode ? '<span class="check">✓</span>' : ''}
                        </a>
                        <div class="inflow-store-dropdown-divider"></div>
                    `;

                    allBranches.forEach(b => {
                        const isThisActive = isBranchMode && currentBranch && currentBranch.id === b.id;
                        branchOptionsHtml += `
                            <a href="/branches/switch/${b.id}" onclick="window.inflowMdi.switchStoreContext(${b.id}, event)" class="inflow-store-dropdown-item ${isThisActive ? 'active' : ''}">
                                <span>🏪 ${b.name} (${b.code})</span>
                                ${isThisActive ? '<span class="check">✓</span>' : ''}
                            </a>
                        `;
                    });

                    branchOptionsHtml += `
                        <div class="inflow-store-dropdown-divider"></div>
                        <a href="/branches/launch" onclick="window.inflowMdi.openTabOrNavigateTop('/branches/launch', 'Branch Launcher', event)" class="inflow-store-dropdown-item launch-btn-highlight" style="color: #0284C7; font-weight: 700; background: #F0F9FF; display: flex; align-items: center; justify-content: space-between;">
                            <span>🚀 Launch Branch System (បើកប្រព័ន្ធ)</span>
                            <span style="font-size: 10px; background: #0284C7; color: #fff; padding: 2px 6px; border-radius: 4px; font-weight: 700;">PORTAL</span>
                        </a>
                        <a href="/branches" onclick="window.inflowMdi.openTabOrNavigateTop('/branches', 'Branches', event)" class="inflow-store-dropdown-item manage" style="color: #475569; font-weight: 500;">
                            <span>⚙️ Manage Branches & Perms...</span>
                        </a>
                    `;

                    // Top User Account Pill & Dropdown
                    const currentUser = storeCtx.current_user || null;
                    const userName = currentUser ? (currentUser.display_name || currentUser.username) : 'Administrator';
                    const userRole = currentUser ? currentUser.role : 'main_admin';
                    const isMainAdmin = (userRole === 'main_admin');
                    const userRoleBadge = isMainAdmin ? '👑 HQ Admin' : '🏪 Branch';
                    const userPillClass = isMainAdmin ? 'user-pill-admin' : 'user-pill-branch';

                    const currentLang = this.getLanguage ? this.getLanguage() : (localStorage.getItem('inflow_app_lang') || 'en');

                    html += `
                        <div class="inflow-bar-right-store" id="inflowStoreContextWrapper">
                            <div class="inflow-store-pill ${storeClass}" id="inflowStorePill" onclick="window.inflowMdi.toggleStoreDropdown(event)" title="${storeTooltip}">
                                <span class="store-icon">${storeIcon}</span>
                                <span class="store-code">${storeCode}</span>
                                <span class="store-chevron" style="font-size: 9px; opacity: 0.8; margin-left: 2px;">▼</span>
                            </div>
                            <div class="inflow-store-dropdown" id="inflowStoreDropdown">
                                <div class="inflow-store-dropdown-header">Store Context (ជ្រើសរើសទីតាំងហាង)</div>
                                ${branchOptionsHtml}
                            </div>
                        </div>

                        <!-- Language Switcher Pill Button (near user login) -->
                        <div class="inflow-bar-right-lang" id="inflowLangContextWrapper" style="position: relative; display: flex; align-items: center; margin-left: 6px; flex-shrink: 0;">
                            <div class="inflow-lang-pill-btn ${currentLang === 'km' ? 'lang-km' : 'lang-en'}" id="inflowLangBtn" onclick="window.inflowMdi.toggleLanguageDirect(event)" title="${currentLang === 'km' ? 'ភាសាខ្មែរ (ចុចដើម្បីប្តូរទៅ English / Click for English)' : 'English (Click to Switch to ភាសាខ្មែរ)'}">
                                <span id="inflowLangFlagIcon" style="display: inline-flex; align-items: center; line-height: 1;">${currentLang === 'km' ? getKhmerFlagSvg(19, 13) : getUkFlagSvg(19, 13)}</span>
                                <span id="inflowLangBadgeText" style="font-weight: 800; font-size: 11px; margin-left: 2px; line-height: 1;">${currentLang === 'km' ? 'KH' : 'EN'}</span>
                                <span class="lang-chevron-arrow" onclick="window.inflowMdi.toggleLangDropdown(event)" title="Select Language / ជ្រើសរើសភាសា">▼</span>
                            </div>
                            <div class="inflow-lang-dropdown" id="inflowLangDropdown">
                                <div class="inflow-lang-dropdown-header">Select Language / ជ្រើសរើសភាសា</div>
                                <a href="javascript:void(0)" onclick="window.inflowMdi.switchLanguage('en', event)" class="inflow-store-dropdown-item ${currentLang === 'en' ? 'active' : ''}" id="langItemEn" style="display: flex; align-items: center; justify-content: space-between; padding: 9px 12px; cursor: pointer;">
                                    <span style="display: flex; align-items: center; gap: 10px;">
                                        ${getUkFlagSvg(22, 15)}
                                        <span style="font-weight: 700; color: #0F172A; font-size: 13px;">English</span>
                                        <span style="font-size: 9.5px; background: #E2E8F0; color: #475569; padding: 1px 6px; border-radius: 4px; font-weight: 700;">Default</span>
                                    </span>
                                    <span class="check" id="langCheckEn" style="color: #0284C7; font-weight: 800; font-size: 14px; ${currentLang === 'en' ? '' : 'display: none;'}">✓</span>
                                </a>
                                <a href="javascript:void(0)" onclick="window.inflowMdi.switchLanguage('km', event)" class="inflow-store-dropdown-item ${currentLang === 'km' ? 'active' : ''}" id="langItemKm" style="display: flex; align-items: center; justify-content: space-between; padding: 9px 12px; cursor: pointer;">
                                    <span style="display: flex; align-items: center; gap: 10px;">
                                        ${getKhmerFlagSvg(22, 15)}
                                        <span style="font-weight: 700; color: #0F172A; font-size: 13px;">ភាសាខ្មែរ (Khmer)</span>
                                    </span>
                                    <span class="check" id="langCheckKm" style="color: #0284C7; font-weight: 800; font-size: 14px; ${currentLang === 'km' ? '' : 'display: none;'}">✓</span>
                                </a>
                                <div class="inflow-store-dropdown-divider"></div>
                                <div style="padding: 6px 10px; background: #F8FAFC; text-align: center;">
                                    <button type="button" onclick="window.inflowMdi.toggleLanguageDirect(event)" style="background: none; border: none; color: #0284C7; font-size: 11px; font-weight: 700; cursor: pointer; padding: 3px 6px; display: inline-flex; align-items: center; gap: 5px;">
                                        <span>⇄ Quick Switch (ប្តូរភាសា)</span>
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div class="inflow-bar-right-user" id="inflowUserContextWrapper" style="position: relative; display: flex; align-items: center; margin-left: 6px; flex-shrink: 0;">
                            <div class="inflow-user-circle-btn ${isMainAdmin ? 'user-circle-admin' : 'user-circle-branch'}" id="inflowUserPill" onclick="window.inflowMdi.toggleUserDropdown(event)" title="Logged in as: ${userName} (${userRole})">
                                <span style="font-size: 13px; line-height: 1;">${isMainAdmin ? '👑' : '👤'}</span>
                            </div>
                            <div class="inflow-user-dropdown" id="inflowUserDropdown">
                                <div style="padding: 10px 14px; border-bottom: 1px solid #E2E8F0; background: #F8FAFC;">
                                    <div style="font-weight: 800; font-size: 12.5px; color: #0F172A;">${userName}</div>
                                    <div style="font-size: 11px; color: #64748B;">@${currentUser ? currentUser.username : 'admin'} • ${isMainAdmin ? 'Main Store HQ (Full Control)' : 'Branch Admin (Restricted)'}</div>
                                </div>
                                ${isMainAdmin ? `
                                <a href="/settings?tab=tabUsers" onclick="window.inflowMdi.openTabOrNavigateTop('/settings?tab=tabUsers', 'Settings', event)" class="inflow-store-dropdown-item" style="color: #334155; font-weight: 600; padding: 8px 14px;">
                                    <span>👥 Users & Permissions</span>
                                </a>` : `
                                <a href="/branches/${currentBranch ? currentBranch.id : 1}/settings?tab=users" onclick="window.inflowMdi.openTabOrNavigateTop('/branches/${currentBranch ? currentBranch.id : 1}/settings?tab=users', 'Branch Settings', event)" class="inflow-store-dropdown-item" style="color: #334155; font-weight: 600; padding: 8px 14px;">
                                    <span>👥 Branch Users</span>
                                </a>`}
                                <a href="/login?switch=1" target="_top" class="inflow-store-dropdown-item" style="color: #0284C7; font-weight: 600; padding: 8px 14px;">
                                    <span>🔄 Switch Account / Login</span>
                                </a>
                                <div class="inflow-store-dropdown-divider"></div>
                                <a href="/logout" target="_top" class="inflow-store-dropdown-item" style="color: #EF4444; font-weight: 700; padding: 8px 14px;">
                                    <span>🚪 Sign Out</span>
                                </a>
                            </div>
                        </div>
                    `;
                } catch (e) {
                    console.warn('Error rendering store switcher:', e);
                }

                container.innerHTML = html;
            },

            mountAllViewports: function () {
                const workspace = document.getElementById('inflowTabWorkspace');
                if (!workspace) return;

                this.tabs.forEach(tab => {
                    let viewport = document.getElementById(`viewport-${tab.id}`);
                    if (!viewport) {
                        viewport = this.createViewportElement(tab);
                        workspace.appendChild(viewport);
                    }
                });
            },

            createViewportElement: function (tab) {
                const viewport = document.createElement('div');
                viewport.className = 'inflow-tab-viewport';
                viewport.id = `viewport-${tab.id}`;
                if (tab.id === this.activeTabId) {
                    viewport.classList.add('active');
                    viewport.style.display = 'block';
                } else {
                    viewport.style.display = 'none';
                }

                const iframe = document.createElement('iframe');
                iframe.className = 'inflow-tab-iframe';
                iframe.name = `frame-${tab.id}`;
                iframe.src = appendEmbedParam(tab.url);
                iframe.setAttribute('frameborder', '0');

                iframe.onload = () => {
                    try {
                        const frameDoc = iframe.contentDocument || iframe.contentWindow.document;
                        if (frameDoc) {
                            frameDoc.addEventListener('click', () => {
                                if (typeof window.closeSidebarFlyout === 'function') {
                                    window.closeSidebarFlyout();
                                }
                            });

                            const newPath = iframe.contentWindow.location.pathname;

                            // Prevent tab from ever displaying /login inside inFlow workspace
                            if (newPath && newPath.startsWith('/login')) {
                                console.warn('Tab iframe redirected to /login. Redirecting tab to /dashboard...');
                                tab.url = '/dashboard';
                                tab.title = 'Main Store Dashboard';
                                tab.label = 'Main Store Dashboard';
                                tab.type = 'home';
                                iframe.contentWindow.location.replace('/dashboard?embed=1');
                                return;
                            }

                            tab.url = newPath + iframe.contentWindow.location.search;

                            const docTitle = frameDoc.title || '';
                            const pageTitle = docTitle.split('|')[0].split('-')[0].trim();
                            if (pageTitle && pageTitle.toLowerCase() !== 'inflow premium' && pageTitle.length > 0) {
                                tab.origTitleEn = pageTitle;
                                const curL = MdiShell.getLanguage ? MdiShell.getLanguage() : (localStorage.getItem('inflow_app_lang') || 'en');
                                const finalTitle = (curL === 'km') ? MdiShell.translateTabTitle(pageTitle, 'km') : pageTitle;
                                tab.title = finalTitle;
                                tab.label = finalTitle;
                                const lbl = document.getElementById(`tab-label-${tab.id}`);
                                if (lbl) lbl.textContent = finalTitle;
                            }

                            // Ensure newly loaded iframe receives current language immediately
                            const curAppLang = MdiShell.getLanguage ? MdiShell.getLanguage() : (localStorage.getItem('inflow_app_lang') || 'en');
                            try {
                                iframe.contentWindow.localStorage.setItem('inflow_app_lang', curAppLang);
                                if (typeof iframe.contentWindow.inflowApplyI18n === 'function') {
                                    iframe.contentWindow.inflowApplyI18n(curAppLang);
                                }
                                iframe.contentWindow.postMessage({ type: 'INFLOW_LANG_CHANGE', lang: curAppLang }, '*');
                            } catch (e) {}

                            // Ensure newly loaded iframe receives current view mode (desktop/mobile) immediately
                            const curViewMode = localStorage.getItem('inflow_view_mode') || (window.innerWidth <= 768 ? 'mobile' : 'desktop');
                            try {
                                iframe.contentWindow.localStorage.setItem('inflow_view_mode', curViewMode);
                                if (typeof iframe.contentWindow.applyViewMode === 'function') {
                                    iframe.contentWindow.applyViewMode(curViewMode, false);
                                } else {
                                    const frameDoc = iframe.contentDocument || iframe.contentWindow.document;
                                    if (frameDoc && frameDoc.documentElement) {
                                        frameDoc.documentElement.setAttribute('data-view-mode', curViewMode);
                                        if (curViewMode === 'mobile') {
                                            frameDoc.documentElement.classList.add('is-mobile-view');
                                            frameDoc.documentElement.classList.remove('is-desktop-view');
                                        } else {
                                            frameDoc.documentElement.classList.add('is-desktop-view');
                                            frameDoc.documentElement.classList.remove('is-mobile-view');
                                        }
                                    }
                                }
                                iframe.contentWindow.postMessage({ type: 'INFLOW_VIEW_MODE_CHANGE', mode: curViewMode }, '*');
                            } catch (e) {}

                            // Sync tab category type if page redirected
                            const detected = detectTypeFromUrl(newPath);
                            if (detected && detected !== 'default' && detected !== tab.type) {
                                tab.type = detected;
                                const tabElem = document.getElementById(`tab-item-${tab.id}`);
                                if (tabElem) {
                                    tabElem.className = `inflow-tab-item tab-${detected} ${tab.id === MdiShell.activeTabId ? 'active' : ''}`.trim();
                                    const iconSpan = tabElem.querySelector('.inflow-tab-icon');
                                    if (iconSpan) {
                                        iconSpan.outerHTML = getTabIconSvg(detected);
                                    }
                                }
                                if (tab.id === MdiShell.activeTabId) {
                                    const accentLine = document.getElementById('inflowTabAccentLine');
                                    if (accentLine) accentLine.className = `inflow-tab-accent-line theme-${detected}`;
                                }
                            }

                            MdiShell.saveTabsToStorage();
                        }
                    } catch (err) { }
                };

                viewport.appendChild(iframe);
                return viewport;
            },

            /**
             * Core Smart Tab Routing:
             * 1. If active tab is Homepage ('home') -> Transform current tab (NO new tab).
             * 2. If staying in same category -> Transform / navigate current tab (NO new tab).
             * 3. Only create new tab when stepping to another category (e.g. Product -> Order History -> Sales Order).
             */
            navigateOrOpenTab: function (url, title, type, forceNew = false) {
                if (!url) url = '/';
                const cleanUrl = url.replace(/[?&]embed=1/, '');
                const targetCategory = type || detectTypeFromUrl(cleanUrl);
                const displayTitle = title || this.guessTitle(cleanUrl, targetCategory);

                if (forceNew) {
                    this.createTab(cleanUrl, displayTitle, targetCategory);
                    return;
                }

                const activeTab = this.tabs.find(t => t.id === this.activeTabId);
                const currentCategory = activeTab ? (activeTab.type || 'home') : 'home';

                // Rule A: On Homepage tab -> transform tab to selected category below
                if (currentCategory === 'home') {
                    this.transformTab(this.activeTabId, cleanUrl, displayTitle, targetCategory);
                    return;
                }

                // Rule B: Staying in same category -> navigate/transform within current tab
                if (currentCategory === targetCategory) {
                    this.transformTab(this.activeTabId, cleanUrl, displayTitle, targetCategory);
                    return;
                }

                // Rule C: Stepping to others (different category) -> Create new tab
                // First check if an existing tab already has this specific URL open
                const existing = this.tabs.find(t => t.url.replace(/[?&]embed=1/, '') === cleanUrl);
                if (existing) {
                    this.switchTab(existing.id);
                    return;
                }

                // Create new tab for the foreign category document
                this.createTab(cleanUrl, displayTitle, targetCategory);
            },

            openTab: function (url, title, type, forceNew = false) {
                this.navigateOrOpenTab(url, title, type, forceNew);
            },

            /**
             * Transforms an existing tab in-place (URL, Category, Icon, Accent Color).
             * Used when staying in same category or when selecting from Homepage.
             */
            transformTab: function (tabId, url, title, newType) {
                const tab = this.tabs.find(t => t.id === tabId);
                if (!tab) return;

                const cleanUrl = url.replace(/[?&]embed=1/, '');
                if (tab.url === cleanUrl) return;

                const vpCheck = document.getElementById(`viewport-${tabId}`);
                if (vpCheck) {
                    const ifr = vpCheck.querySelector('iframe');
                    if (ifr && ifr.contentWindow && typeof ifr.contentWindow.handleTabCloseAttempt === 'function') {
                        const canProceed = ifr.contentWindow.handleTabCloseAttempt(cleanUrl);
                        if (!canProceed) return;
                    }
                }

                const detectedType = newType || detectTypeFromUrl(cleanUrl);
                const displayTitle = title || this.guessTitle(cleanUrl, detectedType);

                tab.url = cleanUrl;
                tab.type = detectedType;
                tab.title = displayTitle;
                tab.label = displayTitle;

                const isActive = (this.activeTabId === tabId);

                // Update DOM tab item in tab bar
                const tabElem = document.getElementById(`tab-item-${tab.id}`);
                if (tabElem) {
                    tabElem.className = `inflow-tab-item tab-${detectedType} ${isActive ? 'active' : ''}`.trim();
                    tabElem.title = displayTitle;
                    tabElem.innerHTML = `
                        ${getTabIconSvg(detectedType)}
                        <span class="inflow-tab-label" id="tab-label-${tab.id}">${displayTitle}</span>
                        <button type="button" class="inflow-tab-close" 
                                onclick="window.inflowMdi.closeTab('${tab.id}', event)" title="Close tab">✕</button>
                    `;
                }

                // Update Accent Line if active
                if (isActive) {
                    const accentLine = document.getElementById('inflowTabAccentLine');
                    if (accentLine) {
                        accentLine.className = `inflow-tab-accent-line theme-${detectedType}`;
                    }
                }

                // Update iframe src
                const vp = document.getElementById(`viewport-${tab.id}`);
                if (vp) {
                    const ifr = vp.querySelector('iframe');
                    if (ifr) {
                        ifr.src = appendEmbedParam(cleanUrl);
                    }
                }

                // Update address bar if active
                if (isActive && window.history && window.history.replaceState) {
                    window.history.replaceState(null, '', cleanUrl || '/');
                }

                this.saveTabsToStorage();
            },

            createTab: function (cleanUrl, displayTitle, detectedType) {
                const newId = `tab-${detectedType}-${Date.now()}`;
                const newTab = {
                    id: newId,
                    type: detectedType,
                    title: displayTitle,
                    label: displayTitle,
                    url: cleanUrl
                };

                this.tabs.push(newTab);

                // Append viewport
                const workspace = document.getElementById('inflowTabWorkspace');
                if (workspace) {
                    const vp = this.createViewportElement(newTab);
                    workspace.appendChild(vp);
                }

                this.renderTabBar();
                this.switchTab(newId);
                this.saveTabsToStorage();

                setTimeout(() => {
                    const tabElem = document.getElementById(`tab-item-${newId}`);
                    if (tabElem) tabElem.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'end' });
                }, 50);
            },

            switchTab: function (tabId) {
                const targetTab = this.tabs.find(t => t.id === tabId);
                if (!targetTab) return;

                this.activeTabId = tabId;

                // Update Tab Elements in strip
                document.querySelectorAll('.inflow-tab-item').forEach(el => {
                    el.classList.remove('active');
                });
                const activeElem = document.getElementById(`tab-item-${tabId}`);
                if (activeElem) activeElem.classList.add('active');

                // Update Viewports in Workspace
                document.querySelectorAll('.inflow-tab-viewport').forEach(vp => {
                    vp.classList.remove('active');
                    vp.style.display = 'none';
                });
                const activeVp = document.getElementById(`viewport-${tabId}`);
                if (activeVp) {
                    activeVp.classList.add('active');
                    activeVp.style.display = 'block';

                    const ifr = activeVp.querySelector('iframe');
                    if (ifr && ifr.contentWindow) {
                        try { ifr.contentWindow.focus(); } catch (e) { }
                    }
                }

                // Update Tab Theme Accent Line
                const accentLine = document.getElementById('inflowTabAccentLine');
                if (accentLine) {
                    accentLine.className = `inflow-tab-accent-line theme-${targetTab.type || 'home'}`;
                }

                // Update browser URL
                if (window.history && window.history.replaceState) {
                    const cleanPath = targetTab.url.replace(/[?&]embed=1/, '');
                    window.history.replaceState(null, '', cleanPath || '/');
                }

                this.saveTabsToStorage();
            },

            closeTab: function (tabId, event) {
                if (event) {
                    event.stopPropagation();
                    event.preventDefault();
                }

                const idx = this.tabs.findIndex(t => t.id === tabId);
                if (idx < 0) return;

                const vpCheck = document.getElementById(`viewport-${tabId}`);
                if (vpCheck) {
                    const ifr = vpCheck.querySelector('iframe');
                    if (ifr && ifr.contentWindow && typeof ifr.contentWindow.handleTabCloseAttempt === 'function') {
                        const canClose = ifr.contentWindow.handleTabCloseAttempt('__CLOSE__');
                        if (!canClose) return;
                    }
                }

                // If only 1 tab remains, reset to Homepage or Branch Workspace
                if (this.tabs.length <= 1) {
                    const storeCtx = window.INFLOW_STORE_CONTEXT || {};
                    const isBranchMode = !!storeCtx.is_branch_mode;
                    const currentBranch = storeCtx.current_branch;
                    if (isBranchMode && currentBranch) {
                        const bCode = currentBranch.code || 'STM';
                        this.transformTab(this.tabs[0].id, `/branches/${currentBranch.id}/workspace`, `${bCode} Workspace`, 'home');
                    } else {
                        this.transformTab(this.tabs[0].id, '/dashboard', 'Main Store Dashboard', 'home');
                    }
                    return;
                }

                const wasActive = (this.activeTabId === tabId);
                const nextTab = this.tabs[idx > 0 ? idx - 1 : 1];

                this.tabs.splice(idx, 1);

                const vp = document.getElementById(`viewport-${tabId}`);
                if (vp) vp.remove();

                const tabElem = document.getElementById(`tab-item-${tabId}`);
                if (tabElem) tabElem.remove();

                if (wasActive && nextTab) {
                    this.switchTab(nextTab.id);
                }

                this.saveTabsToStorage();
            },

            closeActiveTab: function () {
                if (this.activeTabId) {
                    this.closeTab(this.activeTabId);
                }
            },

            /**
             * "If I add new tab it will go to home page"
             */
            addNewHomepageTab: function (event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                const storeCtx = window.INFLOW_STORE_CONTEXT || {};
                const isBranchMode = !!storeCtx.is_branch_mode;
                const currentBranch = storeCtx.current_branch;
                if (isBranchMode && currentBranch) {
                    const bCode = currentBranch.code || 'STM';
                    this.createTab(`/branches/${currentBranch.id}/workspace`, `${bCode} Workspace`, 'home');
                } else {
                    this.createTab('/dashboard', 'Main Store Dashboard', 'home');
                }
            },

            back: function (event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                const activeVp = document.getElementById(`viewport-${this.activeTabId}`);
                if (activeVp) {
                    const ifr = activeVp.querySelector('iframe');
                    if (ifr && ifr.contentWindow) {
                        try {
                            ifr.contentWindow.history.back();
                            return;
                        } catch (err) { }
                    }
                }
                window.history.back();
            },

            forward: function (event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                const activeVp = document.getElementById(`viewport-${this.activeTabId}`);
                if (activeVp) {
                    const ifr = activeVp.querySelector('iframe');
                    if (ifr && ifr.contentWindow) {
                        try {
                            ifr.contentWindow.history.forward();
                            return;
                        } catch (err) { }
                    }
                }
                window.history.forward();
            },

            getActiveIframe: function () {
                const activeVp = document.getElementById(`viewport-${this.activeTabId}`);
                return activeVp ? activeVp.querySelector('iframe') : null;
            },

            bindGlobalEvents: function () {
                // Intercept Main Menu Links
                document.querySelectorAll('#inflowMainMenuOverlay a.inflow-sub-item, #inflowMainMenuOverlay a.inflow-sub-sub-item').forEach(link => {
                    link.addEventListener('click', (e) => {
                        e.preventDefault();
                        const url = link.getAttribute('href');
                        const label = link.textContent.trim().replace(/^[\p{Emoji}\s]+/u, '');
                        const cat = link.closest('.inflow-submenu-content')?.id || '';
                        let type = 'default';
                        if (cat.includes('sales')) type = 'sales';
                        else if (cat.includes('purchas')) type = 'purchase';
                        else if (cat.includes('invent')) type = 'product';
                        else if (cat.includes('report')) type = 'reports';
                        else if (cat.includes('sett')) type = 'settings';
                        else if (cat.includes('gen')) type = 'home';

                        window.toggleInflowMainMenu();
                        MdiShell.navigateOrOpenTab(url, label, type);
                    });
                });

                // Keyboard shortcuts (Ctrl+W to close tab, Ctrl+T for new tab)
                window.addEventListener('keydown', (e) => {
                    if (e.ctrlKey && e.key.toLowerCase() === 'w') {
                        e.preventDefault();
                        MdiShell.closeActiveTab();
                    } else if (e.ctrlKey && e.key.toLowerCase() === 't') {
                        e.preventDefault();
                        MdiShell.addNewHomepageTab();
                    }
                });

                // Close dropdowns on outside click
                document.addEventListener('click', (e) => {
                    const wrapper = document.getElementById('inflowStoreContextWrapper');
                    if (wrapper && !wrapper.contains(e.target)) {
                        MdiShell.closeStoreDropdown();
                    }
                    const langWrapper = document.getElementById('inflowLangContextWrapper');
                    if (langWrapper && !langWrapper.contains(e.target)) {
                        MdiShell.closeLangDropdown();
                    }
                    const userWrapper = document.getElementById('inflowUserContextWrapper');
                    if (userWrapper && !userWrapper.contains(e.target)) {
                        MdiShell.closeUserDropdown();
                    }
                });
            },

            currentLang: null,

            getLanguage: function () {
                if (this.currentLang === 'km' || this.currentLang === 'en') {
                    return this.currentLang;
                }
                try {
                    const saved = localStorage.getItem('inflow_app_lang');
                    this.currentLang = (saved === 'km') ? 'km' : 'en';
                } catch(e) {
                    this.currentLang = 'en';
                }
                return this.currentLang;
            },

            toggleLangDropdown: function (e) {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                this.closeStoreDropdown();
                this.closeUserDropdown();
                const dd = document.getElementById('inflowLangDropdown');
                if (dd) {
                    dd.classList.toggle('show');
                }
            },

            closeLangDropdown: function () {
                const dd = document.getElementById('inflowLangDropdown');
                if (dd) {
                    dd.classList.remove('show');
                }
            },

            toggleLanguageDirect: function (e) {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                const cur = this.getLanguage();
                const next = (cur === 'km') ? 'en' : 'km';
                this.switchLanguage(next, e);
            },

            switchLanguage: function (lang, event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                this.closeLangDropdown();
                const targetLang = (lang === 'km') ? 'km' : 'en';
                this.currentLang = targetLang;
                try {
                    localStorage.setItem('inflow_app_lang', targetLang);
                    document.cookie = `inflow_lang=${targetLang}; path=/; max-age=31536000; SameSite=Lax`;
                } catch(err) {
                    console.warn('Error saving language:', err);
                }

                this.updateLangUi(targetLang);
                this.broadcastLanguage(targetLang);

                // Notify backend session asynchronously
                try {
                    fetch(`/api/set-language/${targetLang}`).catch(() => {});
                } catch(e) {}

                // Show brief mini toast
                const toastMsg = targetLang === 'en' ? 'Language: English' : 'ភាសា៖ ភាសាខ្មែរ (Khmer)';
                this.showMiniToast(toastMsg);
            },

            updateLangUi: function (lang) {
                this.currentLang = lang;
                const badge = document.getElementById('inflowLangBadgeText');
                const btn = document.getElementById('inflowLangBtn');
                const flagIcon = document.getElementById('inflowLangFlagIcon');
                const optEn = document.getElementById('langItemEn');
                const optKm = document.getElementById('langItemKm');
                const checkEn = document.getElementById('langCheckEn');
                const checkKm = document.getElementById('langCheckKm');

                if (flagIcon) {
                    flagIcon.innerHTML = (lang === 'km') ? getKhmerFlagSvg(19, 13) : getUkFlagSvg(19, 13);
                }
                if (badge) {
                    badge.textContent = (lang === 'km') ? 'KH' : 'EN';
                }
                if (btn) {
                    btn.className = `inflow-lang-pill-btn ${lang === 'km' ? 'lang-km' : 'lang-en'}`;
                    btn.setAttribute('title', lang === 'km' 
                        ? 'ភាសាខ្មែរ (ចុចដើម្បីប្តូរទៅ English / Click for English)' 
                        : 'English (Click to Switch to ភាសាខ្មែរ)');
                }
                if (optEn) optEn.classList.toggle('active', lang === 'en');
                if (optKm) optKm.classList.toggle('active', lang === 'km');
                if (checkEn) checkEn.style.display = (lang === 'en') ? 'inline' : 'none';
                if (checkKm) checkKm.style.display = (lang === 'km') ? 'inline' : 'none';

                document.documentElement.setAttribute('data-lang', lang);
                document.documentElement.setAttribute('lang', lang);

                // Translate or restore all open tab titles in MDI shell
                this.tabs.forEach(tab => {
                    const lbl = document.getElementById(`tab-label-${tab.id}`);
                    if (!lbl) return;
                    if (!tab.origTitleEn) {
                        tab.origTitleEn = tab.title || tab.label;
                    }
                    if (lang === 'km') {
                        const tr = this.translateTabTitle(tab.origTitleEn, 'km');
                        tab.label = tr;
                        tab.title = tr;
                        lbl.textContent = tr;
                    } else {
                        tab.label = tab.origTitleEn;
                        tab.title = tab.origTitleEn;
                        lbl.textContent = tab.origTitleEn;
                    }
                });

                // Apply translations on host window
                if (typeof window.inflowApplyI18n === 'function') {
                    window.inflowApplyI18n(lang);
                }
            },

            translateTabTitle: function (title, lang) {
                if (!title) return '';
                if (lang !== 'km') return title;
                const TAB_I18N = {
                    'Homepage': 'ទំព័រដើម',
                    'Home': 'ទំព័រដើម',
                    'Sales Orders': 'បញ្ជីការលក់',
                    'Sales Order': 'ការបញ្ជាទិញលក់',
                    'New Sales Order': 'បង្កើតការបញ្ជាទិញថ្មី',
                    'Create Sales Order': 'បង្កើតការបញ្ជាទិញ',
                    'Products Master Catalog': 'កាតាឡុកទំនិញមេ',
                    'Products Catalog': 'កាតាឡុកទំនិញ',
                    'Products': 'ទំនិញ',
                    'Product': 'ទំនិញ',
                    'New Product': 'បង្កើតទំនិញថ្មី',
                    'Customers CRM': 'បញ្ជីអតិថិជន',
                    'Customers': 'អតិថិជន',
                    'Customer': 'អតិថិជន',
                    'New Customer': 'បង្កើតអតិថិជនថ្មី',
                    'Delivery Person Directory': 'បញ្ជីអ្នកដឹកជញ្ជូន',
                    'Delivery Persons': 'អ្នកដឹកជញ្ជូន',
                    'Delivery Person List': 'បញ្ជីអ្នកដឹកជញ្ជូន',
                    'Purchase Orders': 'ការបញ្ជាទិញចូល',
                    'Purchase Order': 'ការទិញទំនិញចូល',
                    'New Purchase Order': 'បង្កើតការទិញចូលថ្មី',
                    'Purchasing': 'ការទិញទំនិញ',
                    'Vendors': 'អ្នកផ្គត់ផ្គង់',
                    'Vendor': 'អ្នកផ្គត់ផ្គង់',
                    'Current Stock': 'ទំនិញក្នុងស្តុក',
                    'Inventory': 'ឃ្លាំងទំនិញ',
                    'Adjust Stock': 'កែសម្រួលស្តុក',
                    'Transfer Stock': 'ផ្ទេរស្តុក',
                    'Monthly Expenses': 'ចំណាយប្រចាំខែ',
                    'Company Settings': 'ការកំណត់ក្រុមហ៊ុន',
                    'Settings': 'ការកំណត់',
                    'Reports': 'របាយការណ៍',
                    'Branch Launcher': 'បើកប្រព័ន្ធសាខា',
                    'Branches': 'គ្រប់គ្រងសាខា'
                };
                if (TAB_I18N[title]) return TAB_I18N[title];
                if (title.startsWith('Sales Order:')) {
                    return 'ការបញ្ជាទិញ៖ ' + title.replace('Sales Order:', '').trim();
                }
                if (title.startsWith('Purchase Order:')) {
                    return 'ការទិញចូល៖ ' + title.replace('Purchase Order:', '').trim();
                }
                if (title.startsWith('PO:')) {
                    return 'ប័ណ្ណទិញចូល៖ ' + title.replace('PO:', '').trim();
                }
                if (title.startsWith('Product:')) {
                    return 'ទំនិញ៖ ' + title.replace('Product:', '').trim();
                }
                if (title.startsWith('Customer:')) {
                    return 'អតិថិជន៖ ' + title.replace('Customer:', '').trim();
                }
                if (title.endsWith('Workspace')) {
                    return 'កន្លែងការងារ ' + title.replace('Workspace', '').trim();
                }
                return title;
            },

            broadcastLanguage: function (lang) {
                // Synchronously update and post message to all iframe viewports
                document.querySelectorAll('.inflow-tab-viewport iframe').forEach(iframe => {
                    try {
                        if (iframe.contentWindow) {
                            try {
                                iframe.contentWindow.localStorage.setItem('inflow_app_lang', lang);
                                if (typeof iframe.contentWindow.inflowApplyI18n === 'function') {
                                    iframe.contentWindow.inflowApplyI18n(lang);
                                }
                            } catch(e) {}
                            iframe.contentWindow.postMessage({ type: 'INFLOW_LANG_CHANGE', lang: lang }, '*');
                        }
                    } catch(e) {}
                });
            },

            showMiniToast: function (msg) {
                let toast = document.getElementById('inflowMiniLangToast');
                if (!toast) {
                    toast = document.createElement('div');
                    toast.id = 'inflowMiniLangToast';
                    toast.style.cssText = 'position: fixed; top: 44px; right: 20px; z-index: 999999; background: #0F172A; color: #FFFFFF; font-size: 12px; font-weight: 600; padding: 7px 14px; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); display: flex; align-items: center; gap: 8px; transition: opacity 0.25s ease, transform 0.25s ease; opacity: 0; pointer-events: none;';
                    document.body.appendChild(toast);
                }
                toast.innerHTML = `<span>🌐</span> <span>${msg}</span>`;
                toast.style.opacity = '1';
                toast.style.transform = 'translateY(0)';
                clearTimeout(this._langToastTimer);
                this._langToastTimer = setTimeout(() => {
                    toast.style.opacity = '0';
                    toast.style.transform = 'translateY(-6px)';
                }, 2000);
            },

            toggleStoreDropdown: function (e) {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                this.closeUserDropdown();
                this.closeLangDropdown();
                const dd = document.getElementById('inflowStoreDropdown');
                if (dd) {
                    dd.classList.toggle('show');
                }
            },

            closeStoreDropdown: function () {
                const dd = document.getElementById('inflowStoreDropdown');
                if (dd) {
                    dd.classList.remove('show');
                }
            },

            toggleUserDropdown: function (e) {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                this.closeStoreDropdown();
                this.closeLangDropdown();
                const dd = document.getElementById('inflowUserDropdown');
                if (dd) {
                    dd.classList.toggle('show');
                }
            },

            closeUserDropdown: function () {
                const dd = document.getElementById('inflowUserDropdown');
                if (dd) {
                    dd.classList.remove('show');
                }
            },

            switchStoreContext: function (branchId, event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                this.closeStoreDropdown();

                const targetId = String(branchId !== undefined ? branchId : 0);

                try {
                    localStorage.removeItem(STORAGE_KEY);
                    localStorage.removeItem(ACTIVE_TAB_KEY);
                    localStorage.setItem('inflow_active_store_id', targetId);
                } catch (e) { }

                const targetUrl = targetId === '0' ? '/branches/switch/0' : `/branches/switch/${targetId}`;
                if (window.top) {
                    window.top.location.href = targetUrl;
                } else {
                    window.location.href = targetUrl;
                }
            },

            openTabOrNavigateTop: function (url, title, event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                this.closeStoreDropdown();
                this.navigateOrOpenTab(url, title);
            }
        };

        // Export public API
        window.inflowMdi = MdiShell;
        window.initInflowTabs = function () { MdiShell.init(); };
        window.switchInflowTab = function (id) { MdiShell.switchTab(id); };
        window.closeInflowTab = function (id, e) { MdiShell.closeTab(id, e); };
        window.addNewHomepageTab = function (e) { MdiShell.addNewHomepageTab(e); };
        window.switchInflowStoreContext = function (id, e) { MdiShell.switchStoreContext(id, e); };

        document.addEventListener('DOMContentLoaded', function () {
            MdiShell.init();
        });
    }

    /* ==========================================================================
       EMBEDDED IFRAME CLIENT (Runs inside each tab)
       ========================================================================== */
    else {
        document.documentElement.classList.add('is-embedded');
        document.body.classList.add('inflow-embedded');

        // Proxy commands to parent MDI Shell
        window.inflowMdi = {
            openTab: function (url, title, type, forceNew) {
                if (window.top && window.top.inflowMdi) {
                    window.top.inflowMdi.openTab(url, title, type, forceNew);
                } else {
                    window.location.href = url;
                }
            },
            navigateOrOpenTab: function (url, title, type, forceNew) {
                if (window.top && window.top.inflowMdi) {
                    window.top.inflowMdi.navigateOrOpenTab(url, title, type, forceNew);
                } else {
                    window.location.href = url;
                }
            },
            transformTab: function (tabId, url, title, type) {
                if (window.top && window.top.inflowMdi) {
                    window.top.inflowMdi.transformTab(tabId, url, title, type);
                }
            },
            switchStoreContext: function (branchId, e) {
                if (window.top && window.top.inflowMdi && typeof window.top.inflowMdi.switchStoreContext === 'function') {
                    window.top.inflowMdi.switchStoreContext(branchId, e);
                } else {
                    window.top.location.href = (branchId == 0 ? '/branches/switch/0' : '/branches/switch/' + branchId);
                }
            },
            closeActiveTab: function () {
                if (window.top && window.top.inflowMdi) {
                    window.top.inflowMdi.closeActiveTab();
                } else {
                    window.location.href = '/';
                }
            },
            switchTab: function (id) {
                if (window.top && window.top.inflowMdi) {
                    window.top.inflowMdi.switchTab(id);
                }
            }
        };

        window.openInTab = window.inflowMdi.openTab;
        window.closeInflowTab = window.inflowMdi.closeActiveTab;
        window.switchInflowStoreContext = window.inflowMdi.switchStoreContext;
        window.initInflowTabs = function () { };

        // Global Navigation Link Interceptor for Embedded Tabs
        // Enforces:
        // 1. Homepage tab transforms into selected category below (NO new tab)
        // 2. Same-category navigation navigates/transforms current tab in-place (NO new tab)
        // 3. Cross-category navigation (e.g. Product -> Order History -> Sales Order) creates a new tab
        document.addEventListener('DOMContentLoaded', function () {
            document.addEventListener('click', function (e) {
                const link = e.target.closest('a');
                if (!link) return;

                const href = link.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href.startsWith('#')) return;
                if (link.getAttribute('target') === '_blank' || link.hasAttribute('download')) return;
                if (link.getAttribute('data-no-tab') === 'true') return;
                if (href.includes('/export') || href.includes('/download') || href.includes('.xlsx') || href.includes('.pdf') || href.includes('.csv') || href.includes('.zip')) return;

                // If link already had custom handler that called preventDefault, don't re-handle
                if (e.defaultPrevented) return;

                // Handle store switcher links explicitly at top-window level
                if (href.includes('/branches/switch/')) {
                    e.preventDefault();
                    const match = href.match(/\/branches\/switch\/(\d+)/);
                    const branchId = match ? parseInt(match[1], 10) : 0;
                    if (window.top && window.top.inflowMdi && typeof window.top.inflowMdi.switchStoreContext === 'function') {
                        window.top.inflowMdi.switchStoreContext(branchId, e);
                    } else {
                        window.top.location.href = href;
                    }
                    return;
                }

                if (link.getAttribute('target') === '_top') {
                    return; // Let browser navigate top window naturally
                }

                const text = link.textContent.trim().replace(/^[+\s]+/u, '');
                const targetCategory = detectTypeFromUrl(href);

                if (window.top && window.top.inflowMdi) {
                    e.preventDefault();
                    window.top.inflowMdi.navigateOrOpenTab(href, text, targetCategory);
                }
            });
        });
    }

    // Main Menu Drawer Toggle (Orb button)
    window.toggleInflowMainMenu = function (event) {
        if (event) event.stopPropagation();
        const menuOverlay = document.getElementById('inflowMainMenuOverlay');
        if (menuOverlay) {
            menuOverlay.classList.toggle('open');
        }
    };

    window.showMenuSection = function (sectionId) {
        document.querySelectorAll('.inflow-menu-cat').forEach(cat => {
            if (cat.getAttribute('data-target') === sectionId) {
                cat.classList.add('active');
            } else {
                cat.classList.remove('active');
            }
        });
        document.querySelectorAll('.inflow-submenu-content').forEach(pane => {
            if (pane.id === sectionId) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });
    };

    // Legacy menu cleanup if present
    document.addEventListener('click', function (e) {
        const menuOverlay = document.getElementById('inflowMainMenuOverlay');
        if (menuOverlay && menuOverlay.classList.contains('open')) {
            const menuContent = menuOverlay.querySelector('.inflow-main-menu');
            if (menuContent && !menuContent.contains(e.target)) {
                menuOverlay.classList.remove('open');
            }
        }
    });

})();
