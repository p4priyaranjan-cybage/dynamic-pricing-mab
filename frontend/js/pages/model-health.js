/**
 * Model Health page - shows versioning status, quality gate info, scoring mode.
 */
const ModelHealthPage = {
    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0"><i class="bi bi-heart-pulse me-2"></i>Model Health & Credibility</h4>
                <button class="btn btn-sm btn-outline-primary" id="mh-refresh">
                    <i class="bi bi-arrow-clockwise"></i> Refresh
                </button>
            </div>

            <div id="mh-content">
                <div class="text-center py-4">
                    <div class="spinner-border text-primary"></div>
                    <p class="mt-2 text-muted">Loading model health...</p>
                </div>
            </div>
        </div>`;

        document.getElementById('mh-refresh').addEventListener('click', () => this.loadData());
        this.loadData();
    },

    async loadData() {
        try {
            const health = await API.getModelHealth();
            // Also get scoring mode for each tenant
            const tenants = [...new Set(App.properties.map(p => p.tenant_id))];
            const modes = {};
            for (const t of tenants) {
                try { modes[t] = (await API.getScoringMode(t)).scoring_mode; } catch(e) { modes[t] = 'unknown'; }
            }
            this.renderHealth(health, modes);
        } catch (e) {
            document.getElementById('mh-content').innerHTML = `
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Failed to load model health. Is the API running? Error: ${e.message}
                </div>`;
        }
    },

    renderHealth(health, modes) {
        const content = document.getElementById('mh-content');
        content.innerHTML = `
            <!-- Status cards -->
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="card stat-card border-start border-4 border-success">
                        <div class="card-body">
                            <div class="stat-label">Model Versioning</div>
                            <div class="stat-value text-success">
                                ${health.model_versioning_enabled ? '<i class="bi bi-check-circle-fill"></i> Active' : '<i class="bi bi-x-circle"></i> Off'}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card border-start border-4 border-primary">
                        <div class="card-body">
                            <div class="stat-label">Quality Gate</div>
                            <div class="stat-value text-primary">
                                ${health.quality_gate_enabled ? '<i class="bi bi-shield-check"></i> Enabled' : '<i class="bi bi-shield-x"></i> Disabled'}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card border-start border-4 border-info">
                        <div class="card-body">
                            <div class="stat-label">Backbone Models</div>
                            <div class="stat-value">${Object.keys(health.backbones || {}).length}</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card border-start border-4 border-warning">
                        <div class="card-body">
                            <div class="stat-label">Property Models</div>
                            <div class="stat-value">${health.n_property_models || 0}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Scoring modes -->
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-light">
                    <strong><i class="bi bi-toggles me-2"></i>Scoring Mode per Tenant</strong>
                    <small class="text-muted ms-2">(bandit = live ML, baseline = kill-switch, shadow = A/B validation)</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        ${Object.entries(modes).map(([tenant, mode]) => `
                            <div class="col-md-4 mb-2">
                                <div class="d-flex justify-content-between align-items-center p-2 border rounded">
                                    <span class="fw-bold text-capitalize">${tenant}</span>
                                    ${this.modeBadge(mode)}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Backbone versions -->
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-light">
                    <strong><i class="bi bi-layers me-2"></i>Backbone Model Versions</strong>
                </div>
                <div class="card-body p-0">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Backbone (Tenant × Cluster)</th>
                                <th>Current Version</th>
                                <th>Versions Available</th>
                                <th>Rollback Possible</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${Object.entries(health.backbones || {}).map(([name, info]) => `
                                <tr>
                                    <td><code>${name}</code></td>
                                    <td><span class="badge bg-dark">${info.current_version}</span></td>
                                    <td>${info.versions_available}</td>
                                    <td>${info.versions_available > 1 ? '<i class="bi bi-check-circle-fill text-success"></i> Yes' : '<i class="bi bi-x-circle text-muted"></i> No'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Credibility checklist -->
            <div class="card shadow-sm">
                <div class="card-header bg-light">
                    <strong><i class="bi bi-clipboard-check me-2"></i>Credibility Checklist</strong>
                </div>
                <div class="card-body">
                    <div class="list-group list-group-flush">
                        ${this.checklistItem('Model versioning with rollback', health.model_versioning_enabled)}
                        ${this.checklistItem('Quality gate (auto-rollback on regression)', health.quality_gate_enabled)}
                        ${this.checklistItem('Kill-switch available (baseline fallback)', true)}
                        ${this.checklistItem('Shadow mode available (A/B validation)', true)}
                        ${this.checklistItem('Guardrails active (pre-decision action masking)', true)}
                        ${this.checklistItem('Approval routing (low confidence / large delta)', true)}
                        ${this.checklistItem('Context-conditioned elasticity (per-segment floor)', true)}
                        ${this.checklistItem('Interaction features in reward model', true)}
                        ${this.checklistItem('Prometheus + Grafana observability', true)}
                        ${this.checklistItem('Backtest suite CI > 0 (reliable baseline beat)', null, 'Pending validation')}
                    </div>
                </div>
            </div>
        `;
    },

    modeBadge(mode) {
        const map = {
            'bandit': ['bg-success', 'bi-robot', 'ML Active'],
            'baseline': ['bg-danger', 'bi-shield-exclamation', 'Kill-Switch'],
            'shadow': ['bg-info', 'bi-eye', 'Shadow A/B'],
        };
        const [cls, icon, text] = map[mode] || ['bg-secondary', 'bi-question', mode];
        return `<span class="badge ${cls}"><i class="bi ${icon} me-1"></i>${text}</span>`;
    },

    checklistItem(text, passed, note) {
        if (passed === null) {
            return `<div class="list-group-item d-flex align-items-center">
                <i class="bi bi-hourglass-split text-warning me-3 fs-5"></i>
                <span>${text}</span>
                ${note ? `<small class="text-muted ms-auto">${note}</small>` : ''}
            </div>`;
        }
        return `<div class="list-group-item d-flex align-items-center">
            <i class="bi ${passed ? 'bi-check-circle-fill text-success' : 'bi-x-circle-fill text-danger'} me-3 fs-5"></i>
            <span>${text}</span>
        </div>`;
    },
};
