/**
 * Monitoring page - arm distribution, override rate, confidence, approval stats.
 * Uses Chart.js for visualization.
 */
const MonitoringPage = {
    charts: {},

    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0"><i class="bi bi-bar-chart-line me-2"></i>Monitoring</h4>
                <button class="btn btn-sm btn-outline-primary" id="mon-refresh">
                    <i class="bi bi-arrow-clockwise"></i> Refresh
                </button>
            </div>

            <div class="row mb-3" id="mon-stats-row">
                <div class="col-md-3">
                    <div class="card stat-card">
                        <div class="card-body text-center">
                            <div class="stat-value" id="mon-avg-confidence">--</div>
                            <div class="stat-label">Avg Confidence</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card">
                        <div class="card-body text-center">
                            <div class="stat-value" id="mon-override-rate">--</div>
                            <div class="stat-label">Override Rate</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card">
                        <div class="card-body text-center">
                            <div class="stat-value" id="mon-total-decisions">--</div>
                            <div class="stat-label">Total Decisions</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card">
                        <div class="card-body text-center">
                            <div class="stat-value" id="mon-auto-published">--</div>
                            <div class="stat-label">Auto-Published %</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row">
                <div class="col-md-6">
                    <div class="card shadow-sm mb-3">
                        <div class="card-header bg-light"><strong>Arm Distribution</strong></div>
                        <div class="card-body">
                            <div class="chart-container"><canvas id="mon-arm-chart"></canvas></div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm mb-3">
                        <div class="card-header bg-light"><strong>Approval Status Breakdown</strong></div>
                        <div class="card-body">
                            <div class="chart-container"><canvas id="mon-status-chart"></canvas></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;

        document.getElementById('mon-refresh').addEventListener('click', () => this.loadData());
        this.loadData();
    },

    async loadData() {
        try {
            const metrics = await API.getMetrics({});
            this.renderMetrics(metrics);
        } catch (e) {
            Utils.showToast('Failed to load metrics: ' + e.message, 'error');
        }
    },

    renderMetrics(m) {
        // Stats
        document.getElementById('mon-avg-confidence').textContent =
            m.average_confidence ? (m.average_confidence * 100).toFixed(0) + '%' : 'N/A';
        document.getElementById('mon-override-rate').textContent =
            m.override_rate !== undefined ? (m.override_rate * 100).toFixed(1) + '%' : 'N/A';

        const totalDecisions = Object.values(m.approval_stats || {}).reduce((s, v) => s + v, 0);
        document.getElementById('mon-total-decisions').textContent = totalDecisions || 'N/A';

        const autoCount = (m.approval_stats || {})['auto_published'] || 0;
        document.getElementById('mon-auto-published').textContent =
            totalDecisions > 0 ? ((autoCount / totalDecisions) * 100).toFixed(0) + '%' : 'N/A';

        // Arm distribution chart
        this.renderArmChart(m.arm_distribution || {});
        // Status chart
        this.renderStatusChart(m.approval_stats || {});
    },

    renderArmChart(dist) {
        if (this.charts.arm) this.charts.arm.destroy();
        const labels = Object.keys(dist);
        const values = Object.values(dist).map(v => (v * 100).toFixed(1));
        const colors = labels.map(l => {
            if (l.includes('Discount')) return '#0d6efd';
            if (l.includes('Base')) return '#6c757d';
            if (l.includes('Surge') || l.includes('Peak')) return '#dc3545';
            return '#198754';
        });

        const ctx = document.getElementById('mon-arm-chart').getContext('2d');
        this.charts.arm = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{ data: values, backgroundColor: colors, borderWidth: 2 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } },
                },
            },
        });
    },

    renderStatusChart(stats) {
        if (this.charts.status) this.charts.status.destroy();
        const labels = Object.keys(stats).map(s => s.replace(/_/g, ' '));
        const values = Object.values(stats);
        const colors = {
            'pending approval': '#ffc107',
            'approved': '#198754',
            'rejected': '#dc3545',
            'auto published': '#0d6efd',
        };

        const ctx = document.getElementById('mon-status-chart').getContext('2d');
        this.charts.status = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Count',
                    data: values,
                    backgroundColor: labels.map(l => colors[l] || '#6c757d'),
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
            },
        });
    },
};
