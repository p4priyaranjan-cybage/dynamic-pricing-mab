/**
 * Main application controller - handles page navigation, property selection,
 * keyboard shortcuts, and periodic data refresh.
 */
const App = {
    currentPage: 'rate-calendar',
    properties: [],
    selectedProperty: null,
    refreshInterval: null,

    async init() {
        // Load properties for the global selector
        try {
            this.properties = await API.getProperties();
            this.populatePropertySelector();
        } catch (e) {
            Utils.showToast('Failed to connect to API: ' + e.message, 'error');
        }

        // Set up navigation
        document.querySelectorAll('[data-page]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigate(el.dataset.page);
            });
        });

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
                case '3': this.navigate('ota-storefront'); break;
                case '4': this.navigate('scenario-sim'); break;
                case '5': this.navigate('monitoring'); break;
                case '6': this.navigate('recommendations'); break;
                case '7': this.navigate('model-health'); break;
                case 'r': case 'R': this.refreshCurrentPage(); break;
            }
        });

        // Navigate to initial page
        this.navigate('rate-calendar');

        // Update approval count periodically
        this.startPeriodicRefresh();
    },

    populatePropertySelector() {
        const sel = document.getElementById('property-selector');
        sel.innerHTML = '<option value="">All Properties</option>';
        this.properties.forEach(p => {
            sel.innerHTML += `<option value="${p.property_id}">${p.name} (${p.chain} - ${p.region})</option>`;
        });
    },

    navigate(page) {
        this.currentPage = page;
        // Update nav active state
        document.querySelectorAll('[data-page]').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });
        // Render page
        this.renderPage(page);
    },

    renderPage(page) {
        const content = document.getElementById('main-content');
        // Clean up OTA storefront timer if navigating away
        if (this.currentPage !== 'ota-storefront' && OTAStorefrontPage.refreshTimer) {
            OTAStorefrontPage.destroy();
        }
        switch(page) {
            case 'rate-calendar': RateCalendarPage.render(content); break;
            case 'approval-queue': ApprovalQueuePage.render(content); break;
            case 'ota-storefront': OTAStorefrontPage.render(content); break;
            case 'scenario-sim': ScenarioSimPage.render(content); break;
            case 'monitoring': MonitoringPage.render(content); break;
            case 'recommendations': RecommendationsPage.render(content); break;
            case 'model-health': ModelHealthPage.render(content); break;
            default: content.innerHTML = '<p>Page not found</p>';
        }
    },

    refreshCurrentPage() {
        this.renderPage(this.currentPage);
    },

    async updateApprovalCount() {
        try {
            const queue = await API.getApprovalQueue(this.selectedProperty);
            document.getElementById('approval-count').textContent = queue.length;
        } catch (e) { /* silent */ }
    },

    startPeriodicRefresh() {
        this.updateApprovalCount();
        this.refreshInterval = setInterval(() => this.updateApprovalCount(), 10000);
    },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
