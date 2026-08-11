/**
 * Main application controller - handles page navigation, property selection,
 * sidebar collapse, dark mode, KPI bar, and periodic data refresh.
 */
const App = {
    currentPage: 'rate-calendar',
    properties: [],
    selectedProperty: null,
    refreshInterval: null,
    sidebarCollapsed: false,
    darkMode: false,

    pageTitles: {
        'rate-calendar': 'Rate Calendar',
        'approval-queue': 'Approval Queue',
        'recommendations': 'Recommendations',
        'scenario-sim': 'Scenario Simulator',
        'model-health': 'Model Health',
        'architecture': 'How It Works',
    },

    async init() {
        // Restore preferences from localStorage
        this.restorePreferences();

        // Load properties for the global selector
        try {
            this.properties = await API.getProperties();
            this.populatePropertySelector();
        } catch (e) {
            Utils.showToast('Failed to connect to API: ' + e.message, 'error');
            document.getElementById('connection-status').innerHTML =
                '<i class="bi bi-circle-fill text-danger"></i><span>Disconnected</span>';
        }

        // Set up sidebar navigation
        document.querySelectorAll('[data-page]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigate(el.dataset.page);
            });
        });

        // Sidebar collapse button
        const collapseBtn = document.getElementById('sidebar-collapse-btn');
        if (collapseBtn) {
            collapseBtn.addEventListener('click', () => this.toggleSidebar());
        }

        // Sidebar toggle (mobile + desktop)
        const toggleBtn = document.getElementById('sidebar-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                if (window.innerWidth <= 768) {
                    document.getElementById('sidebar').classList.toggle('open');
                } else {
                    this.toggleSidebar();
                }
            });
        }

        // Dark mode toggle
        const themeBtn = document.getElementById('theme-toggle');
        if (themeBtn) {
            themeBtn.addEventListener('click', () => this.toggleDarkMode());
        }

        // Property selector change
        document.getElementById('property-selector').addEventListener('change', (e) => {
            this.selectedProperty = e.target.value || null;
            this.refreshCurrentPage();
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
            switch(e.key) {
                case '1': this.navigate('rate-calendar'); break;
                case '2': this.navigate('approval-queue'); break;
                case '3': this.navigate('recommendations'); break;
                case '4': this.navigate('scenario-sim'); break;
                case '5': this.navigate('model-health'); break;
                case '6': this.navigate('architecture'); break;
                case 'r': case 'R': this.refreshCurrentPage(); break;
                case 'b': case 'B': this.toggleSidebar(); break;
                case 'd': case 'D': this.toggleDarkMode(); break;
            }
        });

        // Navigate to initial page
        this.navigate('rate-calendar');

        // Start periodic data refresh
        this.startPeriodicRefresh();
        this.refreshKPIs();
    },

    // --- Sidebar ---
    toggleSidebar() {
        this.sidebarCollapsed = !this.sidebarCollapsed;
        document.getElementById('sidebar').classList.toggle('collapsed', this.sidebarCollapsed);
        document.body.classList.toggle('sidebar-collapsed', this.sidebarCollapsed);
        localStorage.setItem('sidebar-collapsed', this.sidebarCollapsed);
    },

    // --- Dark Mode ---
    toggleDarkMode() {
        this.darkMode = !this.darkMode;
        document.documentElement.setAttribute('data-bs-theme', this.darkMode ? 'dark' : 'light');
        const icon = document.querySelector('#theme-toggle i');
        if (icon) icon.className = this.darkMode ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
        localStorage.setItem('dark-mode', this.darkMode);
    },

    // --- Preferences ---
    restorePreferences() {
        // Sidebar state
        if (localStorage.getItem('sidebar-collapsed') === 'true') {
            this.sidebarCollapsed = true;
            document.getElementById('sidebar').classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        }
        // Dark mode
        if (localStorage.getItem('dark-mode') === 'true') {
            this.darkMode = true;
            document.documentElement.setAttribute('data-bs-theme', 'dark');
            const icon = document.querySelector('#theme-toggle i');
            if (icon) icon.className = 'bi bi-sun-fill';
        }
    },

    // --- Navigation ---
    populatePropertySelector() {
        const sel = document.getElementById('property-selector');
        sel.innerHTML = '<option value="">All Properties</option>';
        this.properties.forEach(p => {
            sel.innerHTML += `<option value="${p.property_id}">${p.name} (${p.chain} - ${p.region})</option>`;
        });
    },

    navigate(page) {
        this.currentPage = page;
        // Update sidebar active state
        document.querySelectorAll('[data-page]').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });
        // Update page title
        const titleEl = document.getElementById('page-title');
        if (titleEl) titleEl.textContent = this.pageTitles[page] || page;
        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');
        // Render page
        this.renderPage(page);
    },

    renderPage(page) {
        const content = document.getElementById('main-content');
        switch(page) {
            case 'rate-calendar': RateCalendarPage.render(content); break;
            case 'approval-queue': ApprovalQueuePage.render(content); break;
            case 'scenario-sim': ScenarioSimPage.render(content); break;
            case 'recommendations': RecommendationsPage.render(content); break;
            case 'model-health': ModelHealthPage.render(content); break;
            case 'architecture': ArchitecturePage.render(content); break;
            default: content.innerHTML = '<p>Page not found</p>';
        }
    },

    refreshCurrentPage() {
        this.renderPage(this.currentPage);
    },

    // --- KPI Bar ---
    async refreshKPIs() {
        try {
            const metrics = await API.getMetrics({});
            const stats = metrics.approval_stats || {};
            const total = Object.values(stats).reduce((s, v) => s + v, 0);
            const autoCount = stats['auto_published'] || 0;
            const pendingCount = stats['pending_approval'] || 0;

            this.animateKPI('kpi-decisions', total || '--');
            this.animateKPI('kpi-confidence', metrics.average_confidence
                ? (metrics.average_confidence * 100).toFixed(0) + '%' : '--');
            this.animateKPI('kpi-pending', pendingCount);
            this.animateKPI('kpi-autopub', total > 0
                ? ((autoCount / total) * 100).toFixed(0) + '%' : '--');
            this.animateKPI('kpi-override', metrics.override_rate !== undefined
                ? (metrics.override_rate * 100).toFixed(1) + '%' : '--');
        } catch (e) { /* silent */ }
    },

    animateKPI(id, value) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.textContent !== String(value)) {
            el.style.transform = 'translateY(-4px)';
            el.style.opacity = '0';
            setTimeout(() => {
                el.textContent = value;
                el.style.transform = 'translateY(0)';
                el.style.opacity = '1';
            }, 150);
        }
    },

    // --- Periodic Refresh ---
    async updateApprovalCount() {
        try {
            const queue = await API.getApprovalQueue(this.selectedProperty);
            const badge = document.getElementById('approval-count');
            if (badge) badge.textContent = queue.length;
        } catch (e) { /* silent */ }
    },

    startPeriodicRefresh() {
        this.updateApprovalCount();
        this.refreshInterval = setInterval(() => {
            this.updateApprovalCount();
            this.refreshKPIs();
        }, 15000);
    },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
