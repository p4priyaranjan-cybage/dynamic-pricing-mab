/**
 * Recommendations page - on-demand daily/weekly/monthly price recommendations.
 * Full context overrides (all API-supported fields) + context detail popover per day.
 */
const RecommendationsPage = {
    results: [],
    chart: null,

    async render(container) {
        container.innerHTML = this.getHTML();
        this.bindEvents();
        if (App.selectedProperty) {
            document.getElementById('rec-property').value = App.selectedProperty;
            this.loadPropertyConfig(App.selectedProperty);
        }
    },

    getHTML() {
        return `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <div>
                    <h4 class="mb-0"><i class="bi bi-calendar-range me-2"></i>On-Demand Recommendations</h4>
                    <small class="text-muted">Generate pricing recommendations, review context per day, then approve or adjust.</small>
                </div>
            </div>
            <div class="row">
                <div class="col-md-4">${this.getControlsHTML()}</div>
                <div class="col-md-8"><div id="rec-results">${this.getEmptyState()}</div></div>
            </div>
            ${this.getContextModalHTML()}
        </div>`;
    },

    getControlsHTML() {
        return `
            <div class="card shadow-sm">
                <div class="card-header bg-light"><strong>Generate Recommendations</strong></div>
                <div class="card-body">
                    <div class="mb-2">
                        <label class="form-label form-label-sm">Property</label>
                        <select class="form-select form-select-sm" id="rec-property">
                            ${App.properties.map(p => `<option value="${p.property_id}">${p.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="row mb-2">
                        <div class="col-6">
                            <label class="form-label form-label-sm">Room Type</label>
                            <select class="form-select form-select-sm" id="rec-room-type">
                                <option value="standard">Standard</option>
                                <option value="deluxe">Deluxe</option>
                                <option value="suite">Suite</option>
                            </select>
                        </div>
                        <div class="col-6">
                            <label class="form-label form-label-sm">Rate Plan</label>
                            <select class="form-select form-select-sm" id="rec-rate-plan">
                                <option value="bar_best_available">BAR (Best Available)</option>
                                <option value="government_military">Government/Military</option>
                                <option value="senior">Senior</option>
                                <option value="special_offer">Special Offer</option>
                            </select>
                        </div>
                    </div>
                    <div class="row mb-2">
                        <div class="col-6">
                            <label class="form-label form-label-sm">LOS (nights)</label>
                            <input type="number" class="form-control form-control-sm" id="rec-los" value="2" min="1" max="14">
                        </div>
                    </div>
                    <hr>
                    <h6 class="text-muted small">Date Range</h6>
                    <div class="btn-group w-100 mb-2" role="group">
                        <button class="btn btn-sm btn-outline-primary active rec-range-btn" data-days="7">7d</button>
                        <button class="btn btn-sm btn-outline-primary rec-range-btn" data-days="14">14d</button>
                        <button class="btn btn-sm btn-outline-primary rec-range-btn" data-days="30">30d</button>
                    </div>
                    <div class="row mb-2">
                        <div class="col-6">
                            <input type="date" class="form-control form-control-sm" id="rec-start" value="${Utils.dateOffset(1)}">
                        </div>
                        <div class="col-6">
                            <input type="date" class="form-control form-control-sm" id="rec-end" value="${Utils.dateOffset(7)}">
                        </div>
                    </div>

                    <hr>
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="text-muted small mb-0">Context Overrides</h6>
                        <button class="btn btn-xs btn-link p-0 text-decoration-none" type="button" data-bs-toggle="collapse" data-bs-target="#rec-overrides-panel">
                            <i class="bi bi-chevron-down"></i> expand
                        </button>
                    </div>
                    <div class="collapse show" id="rec-overrides-panel">
                        ${this.getOverridesHTML()}
                    </div>

                    <button class="btn btn-primary w-100 mt-3" id="rec-generate-btn">
                        <i class="bi bi-lightning-fill"></i> Generate Recommendations
                    </button>
                </div>
            </div>`;
    },

    getOverridesHTML() {
        return `
            <small class="text-muted d-block mb-2">Leave blank = auto-generated from property data. Fill in to override.</small>
            <div class="row g-2">
                <div class="col-6">
                    <label class="form-label form-label-sm">Occupancy %</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-occupancy" placeholder="Auto" min="5" max="99">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">ADR Trend %</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-adr-trend" placeholder="Auto" step="0.1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Pace vs STLY %</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-pace" placeholder="Auto" step="0.1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Pickup (7d)</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-pickup" placeholder="Auto" min="0" step="1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Remaining Inv. %</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-remaining" placeholder="Auto" min="1" max="100">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Comp Set Avg Rate</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-compset-rate" placeholder="Auto" min="50" step="1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Our vs Compset Index</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-compset-index" placeholder="Auto" min="0.5" max="2" step="0.01">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Compset Trend %</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-compset-trend" placeholder="Auto" step="0.1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Compset Dispersion</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-compset-disp" placeholder="Auto" min="0" max="1" step="0.01">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Event Intensity</label>
                    <input type="number" class="form-control form-control-sm" id="rec-ov-event" placeholder="Auto" min="0" max="1" step="0.1">
                </div>
                <div class="col-6">
                    <label class="form-label form-label-sm">Segment</label>
                    <select class="form-select form-select-sm" id="rec-ov-segment">
                        <option value="">Auto</option>
                        <option value="transient">Transient</option>
                        <option value="corporate">Corporate</option>
                        <option value="leisure">Leisure</option>
                        <option value="group">Group</option>
                    </select>
                </div>
            </div>`;
    },

    getContextModalHTML() {
        return `
            <div class="modal fade" id="rec-context-modal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="bi bi-info-circle me-2"></i>Full Decision Context</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="rec-context-modal-body"></div>
                    </div>
                </div>
            </div>`;
    },

    getEmptyState() {
        return `<div class="text-center text-muted py-5">
            <i class="bi bi-calendar-plus" style="font-size:3rem"></i>
            <p class="mt-2">Configure parameters and click "Generate Recommendations"<br>
            to preview what the model would price for each day.</p>
            <p class="text-muted small">Preview only — nothing is published until you approve.</p>
        </div>`;
    },

    bindEvents() {
        document.querySelectorAll('.rec-range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.rec-range-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('rec-end').value = Utils.dateOffset(parseInt(btn.dataset.days));
            });
        });
        document.getElementById('rec-property').addEventListener('change', (e) => this.loadPropertyConfig(e.target.value));
        document.getElementById('rec-generate-btn').addEventListener('click', () => this.generate());
    },

    async loadPropertyConfig(propertyId) {
        try {
            const config = await API.getPropertyConfig(propertyId);
            document.getElementById('rec-room-type').innerHTML = config.room_types.map(rt => `<option value="${rt}">${rt}</option>`).join('');
            document.getElementById('rec-rate-plan').innerHTML = config.rate_plans.map(rp => `<option value="${rp}">${rp}</option>`).join('');
        } catch (e) { /* use defaults */ }
    },

    buildOverrides() {
        const ov = {};
        const fields = [
            { id: 'rec-ov-occupancy', key: 'occupancy_pct', type: 'float' },
            { id: 'rec-ov-adr-trend', key: 'adr_trend_pct', type: 'float' },
            { id: 'rec-ov-pace', key: 'pace_vs_stly_pct', type: 'float' },
            { id: 'rec-ov-pickup', key: 'pickup_last_7d', type: 'float' },
            { id: 'rec-ov-remaining', key: 'remaining_inventory_pct', type: 'float' },
            { id: 'rec-ov-compset-rate', key: 'comp_set_avg_rate', type: 'float' },
            { id: 'rec-ov-compset-index', key: 'our_rate_vs_compset_index', type: 'float' },
            { id: 'rec-ov-compset-trend', key: 'compset_rate_trend_pct', type: 'float' },
            { id: 'rec-ov-compset-disp', key: 'compset_dispersion', type: 'float' },
            { id: 'rec-ov-event', key: 'event_intensity', type: 'float' },
        ];
        for (const f of fields) {
            const val = document.getElementById(f.id)?.value;
            if (val !== '' && val !== null && val !== undefined) {
                ov[f.key] = parseFloat(val);
            }
        }
        // event_flag derived from event_intensity
        if (ov.event_intensity !== undefined) {
            ov.event_flag = ov.event_intensity > 0;
        }
        // segment
        const seg = document.getElementById('rec-ov-segment')?.value;
        if (seg) ov.segment = seg;

        return Object.keys(ov).length > 0 ? ov : null;
    },

    async generate() {
        const btn = document.getElementById('rec-generate-btn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Generating...';
        try {
            const payload = {
                property_id: document.getElementById('rec-property').value,
                room_type: document.getElementById('rec-room-type').value,
                rate_plan: document.getElementById('rec-rate-plan').value,
                start_date: document.getElementById('rec-start').value,
                end_date: document.getElementById('rec-end').value,
                los_nights: parseInt(document.getElementById('rec-los').value),
                persist: false,
                context_overrides: this.buildOverrides(),
            };
            this.results = await API.getRecommendations(payload);
            this.renderResults();
        } catch (e) {
            Utils.showToast('Failed to generate: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-lightning-fill"></i> Generate Recommendations';
        }
    },

    renderResults() {
        if (!this.results.length) {
            document.getElementById('rec-results').innerHTML = '<div class="alert alert-info">No results.</div>';
            return;
        }
        const el = document.getElementById('rec-results');
        el.innerHTML = `
            <div class="row mb-3">
                <div class="col-md-3"><div class="card stat-card"><div class="card-body text-center">
                    <div class="stat-value">${this.results.length}</div><div class="stat-label">Days</div>
                </div></div></div>
                <div class="col-md-3"><div class="card stat-card"><div class="card-body text-center">
                    <div class="stat-value">${Utils.currency(this.avg('published_price'))}</div><div class="stat-label">Avg Price</div>
                </div></div></div>
                <div class="col-md-3"><div class="card stat-card"><div class="card-body text-center">
                    <div class="stat-value">${this.results.filter(r => r.requires_approval).length}</div><div class="stat-label">Need Approval</div>
                </div></div></div>
                <div class="col-md-3"><div class="card stat-card"><div class="card-body text-center">
                    <div class="stat-value">${(this.avg('confidence_score') * 100).toFixed(0)}%</div><div class="stat-label">Avg Confidence</div>
                </div></div></div>
            </div>
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-light d-flex justify-content-between align-items-center">
                    <strong>Price Curve (recommended vs reference)</strong>
                    <button class="btn btn-sm btn-success" id="rec-approve-all"><i class="bi bi-check-all"></i> Approve All</button>
                </div>
                <div class="card-body"><div class="chart-container"><canvas id="rec-price-chart"></canvas></div></div>
            </div>
            <div class="card shadow-sm">
                <div class="card-header bg-light"><strong>Day-by-Day</strong> <small class="text-muted">— click <i class="bi bi-eye"></i> to see full context</small></div>
                <div class="card-body p-0">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr><th>Date</th><th>Price</th><th>Ref Rate</th><th>Arm</th><th>Offset</th><th>Confidence</th><th>Actions</th></tr>
                        </thead>
                        <tbody>${this.results.map((r, i) => this.dayRow(r, i)).join('')}</tbody>
                    </table>
                </div>
            </div>`;

        document.getElementById('rec-approve-all').addEventListener('click', () => this.approveAll());
        el.querySelectorAll('.rec-ctx-btn').forEach(btn => {
            btn.addEventListener('click', () => this.showContext(parseInt(btn.dataset.idx)));
        });
        el.querySelectorAll('.rec-approve-day').forEach(btn => {
            btn.addEventListener('click', () => this.approveDay(parseInt(btn.dataset.idx)));
        });
        el.querySelectorAll('.rec-modify-day').forEach(btn => {
            btn.addEventListener('click', () => this.modifyDay(parseInt(btn.dataset.idx)));
        });
        this.renderChart();
    },

    dayRow(r, idx) {
        const d = new Date(r.stay_date);
        const day = d.toLocaleDateString('en-US', { weekday: 'short' });
        const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return `<tr id="rec-row-${idx}">
            <td><strong>${day}</strong> ${date}</td>
            <td><strong>${Utils.currency(r.published_price)}</strong></td>
            <td class="text-muted">${Utils.currency(r.reference_rate)}</td>
            <td>${Utils.armLabel(r.chosen_arm_label, r.chosen_arm_offset_pct)}</td>
            <td>${(r.chosen_arm_offset_pct >= 0 ? '+' : '')}${(r.chosen_arm_offset_pct * 100).toFixed(1)}%</td>
            <td>${Utils.confidenceBadge(r.confidence_score, r.confidence_label)}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-info rec-ctx-btn" data-idx="${idx}" title="View full context">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-outline-success rec-approve-day" data-idx="${idx}" title="Approve & publish">
                        <i class="bi bi-check-lg"></i>
                    </button>
                    <button class="btn btn-outline-warning rec-modify-day" data-idx="${idx}" title="Modify price">
                        <i class="bi bi-pencil"></i>
                    </button>
                </div>
            </td>
        </tr>`;
    },

    showContext(idx) {
        const r = this.results[idx];
        const ctx = r.context || {};
        const d = new Date(r.stay_date);
        const body = document.getElementById('rec-context-modal-body');
        body.innerHTML = `
            <div class="row">
                <div class="col-md-5">
                    <h6 class="text-primary">Decision Summary</h6>
                    <table class="table table-sm">
                        <tr><td class="fw-bold">Date</td><td>${d.toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric', year:'numeric'})}</td></tr>
                        <tr><td class="fw-bold">Price</td><td><strong>${Utils.currency(r.published_price)}</strong></td></tr>
                        <tr><td class="fw-bold">Reference Rate</td><td>${Utils.currency(r.reference_rate)}</td></tr>
                        <tr><td class="fw-bold">Arm</td><td>${Utils.armLabel(r.chosen_arm_label, r.chosen_arm_offset_pct)} (${(r.chosen_arm_offset_pct*100).toFixed(1)}%)</td></tr>
                        <tr><td class="fw-bold">Confidence</td><td>${Utils.confidenceBadge(r.confidence_score, r.confidence_label)}</td></tr>
                        <tr><td class="fw-bold">Requires Approval</td><td>${r.requires_approval ? 'Yes' : 'No'}</td></tr>
                    </table>
                    <h6 class="text-primary mt-3">Excluded Arms</h6>
                    ${r.excluded_arms && r.excluded_arms.length ? `<ul class="list-unstyled small">${r.excluded_arms.map(e => `<li><i class="bi bi-shield-x text-warning me-1"></i><strong>${e.arm.label}</strong>: ${e.reason}</li>`).join('')}</ul>` : '<p class="text-muted small">None excluded</p>'}
                    <h6 class="text-primary mt-3">All Arm Probabilities</h6>
                    <table class="table table-sm">
                        <thead><tr><th>Arm</th><th>Prob</th></tr></thead>
                        <tbody>${(r.all_arms||[]).map(a => `<tr><td>${Utils.armLabel(a.label, a.offset_pct)}</td><td>${(a.probability*100).toFixed(1)}%</td></tr>`).join('')}</tbody>
                    </table>
                </div>
                <div class="col-md-7">
                    <h6 class="text-primary">Full Context Features</h6>
                    <div class="context-panel" style="max-height:500px; overflow-y:auto;">
                        ${this.renderContextGroups(ctx)}
                    </div>
                </div>
            </div>`;
        new bootstrap.Modal(document.getElementById('rec-context-modal')).show();
    },

    renderContextGroups(ctx) {
        const groups = {
            'Demand / Operational': [
                { key: 'occupancy_pct', label: 'Occupancy %' },
                { key: 'adr_trend_pct', label: 'ADR Trend %' },
                { key: 'pace_vs_stly_pct', label: 'Pace vs STLY %' },
                { key: 'pickup_last_7d', label: 'Pickup (last 7d)' },
                { key: 'remaining_inventory_pct', label: 'Remaining Inv. %' },
            ],
            'Competitive Set': [
                { key: 'comp_set_avg_rate', label: 'Comp Set Avg Rate' },
                { key: 'our_rate_vs_compset_index', label: 'Our Rate / Compset' },
                { key: 'compset_rate_trend_pct', label: 'Compset Trend %' },
                { key: 'compset_rank', label: 'Compset Rank' },
                { key: 'compset_dispersion', label: 'Compset Dispersion' },
            ],
            'Events': [
                { key: 'event_flag', label: 'Event Active' },
                { key: 'event_intensity', label: 'Event Intensity' },
            ],
            'Segment / Calendar': [
                { key: 'segment', label: 'Segment' },
                { key: 'day_of_week', label: 'Day of Week' },
                { key: 'lead_time_days', label: 'Lead Time (days)' },
                { key: 'los_bucket', label: 'LOS Bucket' },
                { key: 'room_type', label: 'Room Type' },
                { key: 'rate_plan', label: 'Rate Plan' },
            ],
            'Identity': [
                { key: 'property_id', label: 'Property' },
                { key: 'cluster_id', label: 'Cluster' },
                { key: 'tenant_id', label: 'Tenant' },
            ],
        };
        let html = '';
        for (const [group, fields] of Object.entries(groups)) {
            html += `<div class="fw-bold text-primary mt-2 mb-1 small">${group}</div>`;
            for (const f of fields) {
                const val = ctx[f.key];
                if (val === undefined) continue;
                let display = val;
                if (typeof val === 'number') display = val.toFixed(val % 1 === 0 ? 0 : 2);
                if (typeof val === 'boolean') display = val ? '<i class="bi bi-check-circle-fill text-success"></i> Yes' : '<i class="bi bi-x-circle text-muted"></i> No';
                html += `<div class="d-flex justify-content-between py-1 border-bottom">
                    <span class="context-key small">${f.label}</span>
                    <span class="context-value small fw-bold">${display}</span>
                </div>`;
            }
        }
        return html;
    },

    renderChart() {
        if (this.chart) this.chart.destroy();
        const ctx = document.getElementById('rec-price-chart').getContext('2d');
        const labels = this.results.map(r => {
            const d = new Date(r.stay_date);
            return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
        });
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'Recommended Price', data: this.results.map(r => r.published_price), borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.1)', fill: true, tension: 0.3, pointRadius: 5 },
                    { label: 'Reference Rate', data: this.results.map(r => r.reference_rate), borderColor: '#6c757d', borderDash: [5,5], pointRadius: 2, fill: false },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, scales: { y: { title: { display: true, text: 'Price ($)' } } } },
        });
    },

    async approveDay(idx) {
        const r = this.results[idx];
        try {
            const payload = {
                property_id: r.property_id, room_type: r.room_type, rate_plan: r.rate_plan,
                stay_date: r.stay_date, los_nights: parseInt(document.getElementById('rec-los').value),
                dry_run: false,
            };
            // Apply same overrides so the persisted decision matches what was previewed
            const overrides = this.buildOverrides();
            if (overrides) payload.context_overrides = overrides;

            const result = await API.score(payload);
            Utils.showToast(`${Utils.formatDate(r.stay_date)}: ${Utils.currency(result.published_price)} published!`, 'success');
            const row = document.getElementById(`rec-row-${idx}`);
            if (row) { row.classList.add('table-success'); row.querySelector('.rec-approve-day').disabled = true; }
        } catch (e) { Utils.showToast('Failed: ' + e.message, 'error'); }
    },

    async modifyDay(idx) {
        const r = this.results[idx];
        const newPrice = prompt(`Modify price for ${Utils.formatDate(r.stay_date)}\nRecommended: ${Utils.currency(r.published_price)}\n\nEnter new price:`, r.published_price.toFixed(2));
        if (!newPrice || isNaN(parseFloat(newPrice))) return;
        try {
            const payload = {
                property_id: r.property_id, room_type: r.room_type, rate_plan: r.rate_plan,
                stay_date: r.stay_date, los_nights: parseInt(document.getElementById('rec-los').value),
                dry_run: false,
            };
            const overrides = this.buildOverrides();
            if (overrides) payload.context_overrides = overrides;

            const result = await API.score(payload);
            if (result.decision_id) {
                await API.override(result.decision_id, 'revenue_manager', parseFloat(newPrice));
                Utils.showToast(`${Utils.formatDate(r.stay_date)}: Overridden to ${Utils.currency(newPrice)} and published!`, 'success');
            }
            const row = document.getElementById(`rec-row-${idx}`);
            if (row) row.classList.add('table-warning');
        } catch (e) { Utils.showToast('Failed: ' + e.message, 'error'); }
    },

    async approveAll() {
        if (!confirm(`Approve and publish all ${this.results.length} days?`)) return;
        let success = 0;
        for (let i = 0; i < this.results.length; i++) {
            try { await this.approveDay(i); success++; } catch(e) {}
        }
        Utils.showToast(`Published ${success}/${this.results.length} recommendations.`, 'success');
    },

    avg(field) {
        if (!this.results.length) return 0;
        return this.results.reduce((s, r) => s + r[field], 0) / this.results.length;
    },
};
