/**
 * Scenario Simulator - what-if pricing tool with FULL context overrides.
 * RM can override any signal and see what the model would recommend.
 */
const ScenarioSimPage = {
    chart: null,

    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <div>
                    <h4 class="mb-0"><i class="bi bi-sliders me-2"></i>Scenario Simulator</h4>
                    <small class="text-muted">What-if pricing — side-effect-free. Adjust any market signal to see model response.</small>
                </div>
            </div>
            <div class="row">
                <div class="col-lg-5">
                    <div class="card shadow-sm">
                        <div class="card-header bg-light d-flex justify-content-between">
                            <strong>Scenario Parameters</strong>
                            <button class="btn btn-xs btn-outline-secondary" id="sim-reset">Reset All</button>
                        </div>
                        <div class="card-body" style="max-height:75vh; overflow-y:auto;">
                            ${this.controlsHTML()}
                        </div>
                    </div>
                </div>
                <div class="col-lg-7">
                    <div id="sim-results">${this.emptyState()}</div>
                </div>
            </div>
        </div>`;
        this.bindEvents();
        if (App.selectedProperty) {
            document.getElementById('sim-property').value = App.selectedProperty;
            this.loadConfig(App.selectedProperty);
        }
    },

    controlsHTML() {
        return `
            <!-- Basic -->
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Property & Stay</h6>
            <div class="mb-2">
                <label class="form-label form-label-sm mb-0">Property</label>
                <select class="form-select form-select-sm" id="sim-property">
                    ${App.properties.map(p => `<option value="${p.property_id}">${p.name}</option>`).join('')}
                </select>
            </div>
            <div class="row g-2 mb-2">
                <div class="col-4">
                    <label class="form-label form-label-sm mb-0">Room</label>
                    <select class="form-select form-select-sm" id="sim-room-type">
                        <option value="standard">Standard</option>
                        <option value="deluxe">Deluxe</option>
                        <option value="suite">Suite</option>
                    </select>
                </div>
                <div class="col-4">
                    <label class="form-label form-label-sm mb-0">Rate Plan</label>
                    <select class="form-select form-select-sm" id="sim-rate-plan">
                        <option value="bar_best_available">BAR</option>
                        <option value="government_military">Govt/Military</option>
                        <option value="senior">Senior</option>
                        <option value="special_offer">Special Offer</option>
                    </select>
                </div>
                <div class="col-4">
                    <label class="form-label form-label-sm mb-0">Stay Date</label>
                    <input type="date" class="form-control form-control-sm" id="sim-stay-date" value="${Utils.dateOffset(7)}">
                </div>
            </div>
            <div class="row g-2 mb-3">
                <div class="col-4">
                    <label class="form-label form-label-sm mb-0">LOS</label>
                    <input type="number" class="form-control form-control-sm" id="sim-los" value="2" min="1" max="14">
                </div>
            </div>

            <hr class="my-2">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Demand & Operational</h6>
            ${this.sliderField('sim-occupancy', 'Occupancy %', 5, 99, 65, '%')}
            ${this.sliderField('sim-adr-trend', 'ADR Trend %', -15, 15, 0, '%')}
            ${this.sliderField('sim-pace', 'Pace vs STLY %', -30, 30, 0, '%')}
            ${this.sliderField('sim-pickup', 'Pickup (last 7d)', 0, 50, 10, ' rooms')}
            ${this.sliderField('sim-remaining', 'Remaining Inventory %', 5, 95, 40, '%')}

            <hr class="my-2">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Competitive Set</h6>
            ${this.numberField('sim-compset-rate', 'Comp Set Avg Rate ($)', 100, 600, 220)}
            ${this.sliderField('sim-compset-index', 'Our Rate / Compset', 0.6, 1.6, 1.0, 'x', 0.01)}
            ${this.sliderField('sim-compset-trend', 'Compset Trend %', -10, 10, 0, '%')}
            ${this.sliderField('sim-compset-disp', 'Compset Dispersion', 0, 0.3, 0.08, '', 0.01)}

            <hr class="my-2">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Events & Segment</h6>
            ${this.sliderField('sim-event', 'Event Intensity', 0, 1, 0, '', 0.05)}
            <div class="mb-2">
                <label class="form-label form-label-sm mb-0">Segment</label>
                <select class="form-select form-select-sm" id="sim-segment">
                    <option value="transient">Transient</option>
                    <option value="corporate">Corporate</option>
                    <option value="leisure">Leisure</option>
                    <option value="group">Group</option>
                </select>
            </div>

            <button class="btn btn-primary w-100 mt-3 btn-lg" id="sim-run-btn">
                <i class="bi bi-play-fill"></i> Run Simulation
            </button>
        `;
    },

    sliderField(id, label, min, max, def, unit, step) {
        step = step || 1;
        return `<div class="mb-2">
            <div class="d-flex justify-content-between">
                <label class="form-label form-label-sm mb-0">${label}</label>
                <span class="badge bg-light text-dark" id="${id}-val">${def}${unit}</span>
            </div>
            <input type="range" class="form-range form-range-sm" id="${id}" min="${min}" max="${max}" value="${def}" step="${step}">
        </div>`;
    },

    numberField(id, label, min, max, def) {
        return `<div class="mb-2">
            <label class="form-label form-label-sm mb-0">${label}</label>
            <input type="number" class="form-control form-control-sm" id="${id}" min="${min}" max="${max}" value="${def}" step="1">
        </div>`;
    },

    emptyState() {
        return `<div class="text-center text-muted py-5">
            <i class="bi bi-lightbulb" style="font-size:3rem; opacity:0.5"></i>
            <p class="mt-3">Adjust the market signals on the left and click<br><strong>"Run Simulation"</strong> to see the model's response.</p>
            <p class="small text-muted">This is completely side-effect-free — no decisions are logged.</p>
        </div>`;
    },

    bindEvents() {
        // Slider value displays
        document.querySelectorAll('input[type="range"]').forEach(el => {
            el.addEventListener('input', () => {
                const valEl = document.getElementById(el.id + '-val');
                if (valEl) {
                    const unit = valEl.textContent.replace(/[\d.\-]/g, '').trim();
                    valEl.textContent = el.value + (unit || '');
                }
            });
        });
        document.getElementById('sim-run-btn').addEventListener('click', () => this.run());
        document.getElementById('sim-reset').addEventListener('click', () => this.render(document.getElementById('main-content')));
        document.getElementById('sim-property').addEventListener('change', (e) => this.loadConfig(e.target.value));
    },

    async loadConfig(propertyId) {
        try {
            const config = await API.getPropertyConfig(propertyId);
            document.getElementById('sim-room-type').innerHTML = config.room_types.map(rt => `<option value="${rt}">${rt}</option>`).join('');
            document.getElementById('sim-rate-plan').innerHTML = config.rate_plans.map(rp => {
                const labels = { bar_best_available: 'BAR', government_military: 'Govt/Military', senior: 'Senior', special_offer: 'Special Offer' };
                return `<option value="${rp}">${labels[rp] || rp}</option>`;
            }).join('');
        } catch(e) {}
    },

    async run() {
        const btn = document.getElementById('sim-run-btn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Scoring...';
        try {
            const overrides = {
                occupancy_pct: parseFloat(document.getElementById('sim-occupancy').value),
                adr_trend_pct: parseFloat(document.getElementById('sim-adr-trend').value),
                pace_vs_stly_pct: parseFloat(document.getElementById('sim-pace').value),
                pickup_last_7d: parseFloat(document.getElementById('sim-pickup').value),
                remaining_inventory_pct: parseFloat(document.getElementById('sim-remaining').value),
                comp_set_avg_rate: parseFloat(document.getElementById('sim-compset-rate').value),
                our_rate_vs_compset_index: parseFloat(document.getElementById('sim-compset-index').value),
                compset_rate_trend_pct: parseFloat(document.getElementById('sim-compset-trend').value),
                compset_dispersion: parseFloat(document.getElementById('sim-compset-disp').value),
                event_intensity: parseFloat(document.getElementById('sim-event').value),
                event_flag: parseFloat(document.getElementById('sim-event').value) > 0,
                segment: document.getElementById('sim-segment').value,
            };
            const payload = {
                property_id: document.getElementById('sim-property').value,
                room_type: document.getElementById('sim-room-type').value,
                rate_plan: document.getElementById('sim-rate-plan').value,
                stay_date: document.getElementById('sim-stay-date').value,
                los_nights: parseInt(document.getElementById('sim-los').value),
                dry_run: true,
                context_overrides: overrides,
            };
            const result = await API.simulate(payload);
            this.renderResult(result);
        } catch (e) {
            Utils.showToast('Simulation failed: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-play-fill"></i> Run Simulation';
        }
    },

    renderResult(r) {
        document.getElementById('sim-results').innerHTML = `
            <!-- Hero result card -->
            <div class="card border-0 bg-gradient text-white mb-3" style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);">
                <div class="card-body py-4">
                    <div class="row align-items-center text-center">
                        <div class="col-md-4">
                            <div class="small opacity-75">Recommended Price</div>
                            <div class="display-5 fw-bold">${Utils.currency(r.published_price)}</div>
                            <div class="mt-1">${Utils.armLabel(r.chosen_arm_label, r.chosen_arm_offset_pct)}
                                <span class="ms-1 opacity-75">(${(r.chosen_arm_offset_pct>=0?'+':'')}${(r.chosen_arm_offset_pct*100).toFixed(1)}%)</span>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="small opacity-75">Reference Rate</div>
                            <div class="fs-4">${Utils.currency(r.reference_rate)}</div>
                        </div>
                        <div class="col-md-3">
                            <div class="small opacity-75">Confidence</div>
                            <div class="fs-4 mt-1">${Utils.confidenceBadge(r.confidence_score, r.confidence_label)}</div>
                        </div>
                        <div class="col-md-2">
                            <div class="small opacity-75">Approval?</div>
                            <div class="mt-1">${r.requires_approval ? '<span class="badge bg-warning text-dark">Required</span>' : '<span class="badge bg-success">Auto-publish</span>'}</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row g-3">
                <!-- Arm probability chart -->
                <div class="col-md-7">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-light"><strong>Arm Probability Distribution</strong></div>
                        <div class="card-body"><div class="chart-container"><canvas id="sim-arm-chart"></canvas></div></div>
                    </div>
                </div>
                <!-- Confidence breakdown -->
                <div class="col-md-5">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-light"><strong>Confidence Breakdown</strong></div>
                        <div class="card-body">${this.confidenceHTML(r.confidence_breakdown)}</div>
                    </div>
                </div>
            </div>

            ${r.excluded_arms && r.excluded_arms.length ? `
            <div class="card shadow-sm mt-3 border-warning">
                <div class="card-header bg-warning bg-opacity-10">
                    <strong><i class="bi bi-shield-exclamation me-1"></i>Guardrails: Excluded Arms</strong>
                </div>
                <div class="card-body py-2">
                    ${r.excluded_arms.map(e => `<div class="small py-1"><strong>${e.arm.label}</strong> (${(e.arm.offset_pct*100).toFixed(1)}%): <span class="text-muted">${e.reason}</span></div>`).join('')}
                </div>
            </div>` : ''}
        `;
        this.renderArmChart(r.all_arms);
    },

    renderArmChart(arms) {
        if (this.chart) this.chart.destroy();
        const ctx = document.getElementById('sim-arm-chart').getContext('2d');
        const colors = arms.map(a => a.offset_pct < -0.01 ? '#0d6efd' : a.offset_pct > 0.2 ? '#dc3545' : a.offset_pct > 0.01 ? '#198754' : '#6c757d');
        this.chart = new Chart(ctx, {
            type: 'bar',
            data: { labels: arms.map(a => a.label), datasets: [{ label: 'Probability %', data: arms.map(a => (a.probability*100).toFixed(1)), backgroundColor: colors, borderRadius: 6 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: '%' } }, x: { ticks: { maxRotation: 45 } } } },
        });
    },

    confidenceHTML(bd) {
        if (!bd) return '<p class="text-muted">N/A</p>';
        let html = '';
        for (const [k, v] of Object.entries(bd)) {
            const label = k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            if (typeof v === 'number' && v >= 0 && v <= 1) {
                const pct = (v * 100).toFixed(0);
                const color = v > 0.7 ? 'success' : v > 0.4 ? 'warning' : 'danger';
                html += `<div class="mb-2"><div class="d-flex justify-content-between small"><span>${label}</span><strong>${pct}%</strong></div><div class="progress" style="height:6px"><div class="progress-bar bg-${color}" style="width:${pct}%"></div></div></div>`;
            } else {
                html += `<div class="d-flex justify-content-between small py-1 border-bottom"><span>${label}</span><strong>${v}</strong></div>`;
            }
        }
        return html;
    },
};
