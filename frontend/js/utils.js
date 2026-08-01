/**
 * Shared utility functions for the dashboard.
 */
const Utils = {
    // Format currency
    currency(val, decimals = 2) {
        return '$' + Number(val).toFixed(decimals);
    },

    // Format percentage
    pct(val, decimals = 1) {
        return (Number(val) * 100).toFixed(decimals) + '%';
    },

    // Confidence badge HTML
    confidenceBadge(score, label) {
        const cls = score > 0.7 ? 'high' : score >= 0.4 ? 'medium' : 'low';
        return `<span class="badge badge-confidence-${cls}">${label || cls.charAt(0).toUpperCase() + cls.slice(1)} (${(score * 100).toFixed(0)}%)</span>`;
    },

    // Status badge HTML
    statusBadge(status) {
        const map = {
            'pending_approval': ['status-pending', 'Pending'],
            'approved': ['status-approved', 'Approved'],
            'rejected': ['status-rejected', 'Rejected'],
            'auto_published': ['status-auto', 'Auto-Published'],
        };
        const [cls, text] = map[status] || ['bg-secondary', status];
        return `<span class="badge ${cls}">${text}</span>`;
    },

    // Arm label with color
    armLabel(label, offsetPct) {
        let cls = 'arm-base';
        if (offsetPct < -0.01) cls = 'arm-discount';
        else if (offsetPct > 0.2) cls = 'arm-surge';
        else if (offsetPct > 0.01) cls = 'arm-premium';
        return `<span class="${cls}">${label}</span>`;
    },

    // Format date for display
    formatDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    },

    // Format datetime
    formatDateTime(dtStr) {
        if (!dtStr) return '';
        const d = new Date(dtStr);
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },

    // Show toast notification
    showToast(message, type = 'success') {
        const container = document.getElementById('toast-container');
        const icons = { success: 'check-circle-fill', error: 'exclamation-triangle-fill', info: 'info-circle-fill' };
        const colors = { success: 'text-success', error: 'text-danger', info: 'text-primary' };
        const id = 'toast-' + Date.now();
        container.innerHTML += `
            <div id="${id}" class="toast align-items-center border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">
                        <i class="bi bi-${icons[type]} ${colors[type]} me-2"></i>${message}
                    </div>
                    <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>`;
        const toast = new bootstrap.Toast(document.getElementById(id), { delay: 4000 });
        toast.show();
        setTimeout(() => document.getElementById(id)?.remove(), 5000);
    },

    // Date input default (today + N days)
    dateOffset(days) {
        const d = new Date();
        d.setDate(d.getDate() + days);
        return d.toISOString().split('T')[0];
    },

    // Debounce
    debounce(fn, ms = 300) {
        let timer;
        return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
    },
};
