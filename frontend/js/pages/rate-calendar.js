/**
 * Rate Calendar page - shows all published/pending prices with filters,
 * confidence badges, and context drill-down on row click.
 */
const RateCalendarPage = {
    table: null,

    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0"><i class="bi bi-calendar3 me-2"></i>Rate Calendar</h4>
                <div class="d-flex gap-2">
                    <input type="date" class="form-control form-control-sm" id="rc-start-date" value="${Utils.dateOffset(0)}">
                    <input type="date" class="form-control form-control-sm" id="rc-end-date" value="${Utils.dateOffset(30)}">
                    <select class="form-select form-select-sm" id="rc-room-type" style="width:130px">
                        <option value="">All Rooms</option>
                        <option value="standard">Standard</option>
                        <option value="deluxe">Deluxe</option>
                        <option value="suite">Suite</option>
                    </select>
                    <button class="btn btn-sm btn-primary" id="rc-refresh-btn">
                        <i class="bi bi-arrow-clockwise"></i> Refresh
                    </button>
                </div>
            </div>

            <div class="card shadow-sm">
                <div class="card-body p-0">
                    <table id="rc-table" class="table table-sm table-hover mb-0" style="width:100%">
                        <thead class="table-light">
                            <tr>
                                <th>Stay Date</th>
                                <th>Property</th>
                                <th>Room</th>
                                <th>Rate Plan</th>
                                <th>Ref. Rate</th>
                                <th>Price</th>
                                <th>Arm</th>
                                <th>Offset</th>
                                <th>Confidence</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <!-- Context detail panel (shown on row click) -->
            <div class="offcanvas offcanvas-end" id="rc-context-panel" style="width:450px">
                <div class="offcanvas-header">
                    <h5 class="offcanvas-title">Decision Context</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="offcanvas"></button>
                </div>
                <div class="offcanvas-body" id="rc-context-body">
                </div>
            </div>
        </div>`;

        // Bind events
        document.getElementById('rc-refresh-btn').addEventListener('click', () => this.loadData());
        document.getElementById('rc-start-date').addEventListener('change', () => this.loadData());
        document.getElementById('rc-end-date').addEventListener('change', () => this.loadData());
        document.getElementById('rc-room-type').addEventListener('change', () => this.loadData());

        // Init DataTable
        this.table = $('#rc-table').DataTable({
            order: [[0, 'asc']],
            pageLength: 25,
            language: { emptyTable: 'No rate decisions found. Run the bootstrap pipeline first.' },
            columns: [
                { data: 'stay_date' },
                { data: 'property_id' },
                { data: 'room_type' },
                { data: 'rate_plan' },
                { data: 'reference_rate', render: (d) => Utils.currency(d) },
                { data: 'published_price', render: (d) => `<strong>${Utils.currency(d)}</strong>` },
                { data: 'arm_label', render: (d, t, row) => Utils.armLabel(d, row.arm_offset_pct) },
                { data: 'arm_offset_pct', render: (d) => (d >= 0 ? '+' : '') + (d * 100).toFixed(1) + '%' },
                { data: 'confidence_score', render: (d, t, row) => Utils.confidenceBadge(d, row.confidence_label) },
                { data: 'status', render: (d) => Utils.statusBadge(d) },
            ],
        });

        // Row click -> show context
        $('#rc-table tbody').on('click', 'tr', (e) => {
            const data = this.table.row(e.currentTarget).data();
            if (data) this.showContext(data);
        });

        this.loadData();
    },

    async loadData() {
        try {
            const params = {
                property_id: App.selectedProperty,
                start_date: document.getElementById('rc-start-date')?.value,
                end_date: document.getElementById('rc-end-date')?.value,
                room_type: document.getElementById('rc-room-type')?.value,
            };
            const data = await API.getRateCalendar(params);
            this.table.clear().rows.add(data).draw();
        } catch (e) {
            Utils.showToast('Failed to load rate calendar: ' + e.message, 'error');
        }
    },

    showContext(row) {
        const ctx = row.context || {};
        const body = document.getElementById('rc-context-body');
        body.innerHTML = `
            <div class="mb-3">
                <h6 class="text-muted">Decision Summary</h6>
                <table class="table table-sm">
                    <tr><td class="fw-bold">Decision ID</td><td><code>${row.decision_id}</code></td></tr>
                    <tr><td class="fw-bold">Property</td><td>${row.property_id}</td></tr>
                    <tr><td class="fw-bold">Stay Date</td><td>${Utils.formatDate(row.stay_date)}</td></tr>
                    <tr><td class="fw-bold">Room / Plan</td><td>${row.room_type} / ${row.rate_plan}</td></tr>
                    <tr><td class="fw-bold">LOS Bucket</td><td>${row.los_bucket}</td></tr>
                    <tr><td class="fw-bold">Reference Rate</td><td>${Utils.currency(row.reference_rate)}</td></tr>
                    <tr><td class="fw-bold">Published Price</td><td><strong>${Utils.currency(row.published_price)}</strong></td></tr>
                    <tr><td class="fw-bold">Arm</td><td>${Utils.armLabel(row.arm_label, row.arm_offset_pct)} (${(row.arm_offset_pct * 100).toFixed(1)}%)</td></tr>
                    <tr><td class="fw-bold">Confidence</td><td>${Utils.confidenceBadge(row.confidence_score, row.confidence_label)}</td></tr>
                    <tr><td class="fw-bold">Status</td><td>${Utils.statusBadge(row.status)}</td></tr>
                    <tr><td class="fw-bold">Decision Time</td><td>${Utils.formatDateTime(row.decision_ts)}</td></tr>
                </table>
            </div>
            <div class="mb-3">
                <h6 class="text-muted">Context Features</h6>
                <div class="context-panel">
                    ${this.renderContextFeatures(ctx)}
                </div>
            </div>
        `;
        const offcanvas = new bootstrap.Offcanvas(document.getElementById('rc-context-panel'));
        offcanvas.show();
    },

    renderContextFeatures(ctx) {
        const groups = {
            'Demand Signals': ['occupancy_pct', 'adr_trend_pct', 'pace_vs_stly_pct', 'pickup_last_7d', 'remaining_inventory_pct'],
            'Comp Set': ['comp_set_avg_rate', 'our_rate_vs_compset_index', 'compset_rate_trend_pct', 'compset_dispersion'],
            'Events': ['event_flag', 'event_intensity'],
            'Segment / Calendar': ['segment', 'day_of_week', 'lead_time_days', 'los_bucket'],
        };
        let html = '';
        for (const [group, keys] of Object.entries(groups)) {
            html += `<div class="fw-bold text-primary mt-2 mb-1">${group}</div>`;
            for (const key of keys) {
                const val = ctx[key];
                if (val === undefined) continue;
                let display = val;
                if (typeof val === 'number') display = val.toFixed(2);
                if (typeof val === 'boolean') display = val ? '<i class="bi bi-check-circle-fill text-success"></i> Yes' : '<i class="bi bi-x-circle text-muted"></i> No';
                html += `<div class="d-flex justify-content-between py-1 border-bottom">
                    <span class="context-key">${key.replace(/_/g, ' ')}</span>
                    <span class="context-value">${display}</span>
                </div>`;
            }
        }
        return html;
    },
};
