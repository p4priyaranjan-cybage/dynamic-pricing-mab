/**
 * Approval Queue page - RM reviews, approves, rejects, or overrides
 * pending recommendations. Supports batch approve and keyboard shortcuts.
 */
const ApprovalQueuePage = {
    queue: [],
    selectedIds: new Set(),

    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0"><i class="bi bi-check2-square me-2"></i>Approval Queue</h4>
                <div class="d-flex gap-2 align-items-center">
                    <span class="text-muted me-2" id="aq-selection-count"></span>
                    <button class="btn btn-sm btn-success" id="aq-batch-approve" disabled>
                        <i class="bi bi-check-all"></i> Approve Selected <kbd class="kbd-hint">A</kbd>
                    </button>
                    <button class="btn btn-sm btn-danger" id="aq-batch-reject" disabled>
                        <i class="bi bi-x-lg"></i> Reject Selected
                    </button>
                    <button class="btn btn-sm btn-outline-primary" id="aq-refresh">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </div>

            <div class="row" id="aq-stats-row">
                <div class="col-md-3">
                    <div class="card stat-card mb-3">
                        <div class="card-body text-center">
                            <div class="stat-value text-warning" id="aq-pending-count">0</div>
                            <div class="stat-label">Pending Review</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card mb-3">
                        <div class="card-body text-center">
                            <div class="stat-value text-danger" id="aq-low-conf-count">0</div>
                            <div class="stat-label">Low Confidence</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card mb-3">
                        <div class="card-body text-center">
                            <div class="stat-value text-primary" id="aq-high-delta-count">0</div>
                            <div class="stat-label">Large Delta (&gt;5%)</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stat-card mb-3">
                        <div class="card-body text-center">
                            <div class="stat-value text-success" id="aq-selected-count">0</div>
                            <div class="stat-label">Selected</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card shadow-sm">
                <div class="card-body p-0">
                    <table class="table table-sm table-hover mb-0" id="aq-table">
                        <thead class="table-light">
                            <tr>
                                <th><input type="checkbox" id="aq-select-all"></th>
                                <th>Stay Date</th>
                                <th>Property</th>
                                <th>Room</th>
                                <th>Price</th>
                                <th>Arm / Offset</th>
                                <th>Confidence</th>
                                <th>Decision Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="aq-tbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- Override modal -->
            <div class="modal fade" id="aq-override-modal" tabindex="-1">
                <div class="modal-dialog modal-sm">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Override Price</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p class="text-muted mb-2">Decision: <code id="aq-override-id"></code></p>
                            <p class="mb-2">Model recommended: <strong id="aq-override-current"></strong></p>
                            <label class="form-label">New price:</label>
                            <div class="input-group">
                                <span class="input-group-text">$</span>
                                <input type="number" class="form-control" id="aq-override-price" step="0.01" min="0">
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
                            <button class="btn btn-warning btn-sm" id="aq-override-submit">Override & Approve</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;

        // Bind events
        document.getElementById('aq-refresh').addEventListener('click', () => this.loadData());
        document.getElementById('aq-batch-approve').addEventListener('click', () => this.batchApprove());
        document.getElementById('aq-batch-reject').addEventListener('click', () => this.batchReject());
        document.getElementById('aq-select-all').addEventListener('change', (e) => this.selectAll(e.target.checked));
        document.getElementById('aq-override-submit').addEventListener('click', () => this.submitOverride());

        // Keyboard shortcut for approve
        this._keyHandler = (e) => {
            if (e.target.tagName === 'INPUT') return;
            if (e.key === 'a' || e.key === 'A') this.batchApprove();
        };
        document.addEventListener('keydown', this._keyHandler);

        this.loadData();
    },

    async loadData() {
        try {
            this.queue = await API.getApprovalQueue(App.selectedProperty);
            this.selectedIds.clear();
            this.renderTable();
            this.updateStats();
        } catch (e) {
            Utils.showToast('Failed to load approval queue: ' + e.message, 'error');
        }
    },

    renderTable() {
        const tbody = document.getElementById('aq-tbody');
        if (!this.queue.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4"><i class="bi bi-inbox me-2"></i>No pending approvals</td></tr>';
            return;
        }
        tbody.innerHTML = this.queue.map(row => `
            <tr class="approval-row ${this.selectedIds.has(row.decision_id) ? 'selected' : ''}" data-id="${row.decision_id}">
                <td><input type="checkbox" class="aq-checkbox" data-id="${row.decision_id}" ${this.selectedIds.has(row.decision_id) ? 'checked' : ''}></td>
                <td>${Utils.formatDate(row.stay_date)}</td>
                <td><small>${row.property_id}</small></td>
                <td>${row.room_type}</td>
                <td><strong>${Utils.currency(row.published_price)}</strong></td>
                <td>${Utils.armLabel(row.arm_label, row.arm_offset_pct)} <small class="text-muted">(${(row.arm_offset_pct*100).toFixed(1)}%)</small></td>
                <td>${Utils.confidenceBadge(row.confidence_score, row.confidence_label)}</td>
                <td>${Utils.formatDateTime(row.decision_ts)}</td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-success aq-approve-btn" data-id="${row.decision_id}" title="Approve">
                            <i class="bi bi-check-lg"></i>
                        </button>
                        <button class="btn btn-outline-warning aq-override-btn" data-id="${row.decision_id}" data-price="${row.published_price}" title="Override">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-outline-danger aq-reject-btn" data-id="${row.decision_id}" title="Reject">
                            <i class="bi bi-x-lg"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

        // Bind row actions
        tbody.querySelectorAll('.aq-approve-btn').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); this.approveOne(btn.dataset.id); });
        });
        tbody.querySelectorAll('.aq-reject-btn').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); this.rejectOne(btn.dataset.id); });
        });
        tbody.querySelectorAll('.aq-override-btn').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); this.showOverrideModal(btn.dataset.id, btn.dataset.price); });
        });
        tbody.querySelectorAll('.aq-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                e.stopPropagation();
                if (e.target.checked) this.selectedIds.add(e.target.dataset.id);
                else this.selectedIds.delete(e.target.dataset.id);
                this.updateSelectionUI();
            });
        });
    },

    updateStats() {
        document.getElementById('aq-pending-count').textContent = this.queue.length;
        document.getElementById('aq-low-conf-count').textContent = this.queue.filter(r => r.confidence_score < 0.4).length;
        document.getElementById('aq-high-delta-count').textContent = this.queue.filter(r => Math.abs(r.arm_offset_pct) > 0.05).length;
        this.updateSelectionUI();
    },

    updateSelectionUI() {
        const count = this.selectedIds.size;
        document.getElementById('aq-selected-count').textContent = count;
        document.getElementById('aq-batch-approve').disabled = count === 0;
        document.getElementById('aq-batch-reject').disabled = count === 0;
        document.getElementById('aq-selection-count').textContent = count > 0 ? `${count} selected` : '';
    },

    selectAll(checked) {
        this.selectedIds.clear();
        if (checked) this.queue.forEach(r => this.selectedIds.add(r.decision_id));
        this.renderTable();
        this.updateSelectionUI();
    },

    async approveOne(id) {
        try {
            await API.approve(id, 'revenue_manager');
            Utils.showToast('Approved! Price published to channels.', 'success');
            this.loadData();
            App.updateApprovalCount();
        } catch (e) {
            Utils.showToast('Approve failed: ' + e.message, 'error');
        }
    },

    async rejectOne(id) {
        try {
            await API.reject(id, 'revenue_manager');
            Utils.showToast('Rejected.', 'info');
            this.loadData();
            App.updateApprovalCount();
        } catch (e) {
            Utils.showToast('Reject failed: ' + e.message, 'error');
        }
    },

    async batchApprove() {
        if (!this.selectedIds.size) return;
        const ids = [...this.selectedIds];
        let success = 0;
        for (const id of ids) {
            try { await API.approve(id, 'revenue_manager'); success++; } catch(e) { /* continue */ }
        }
        Utils.showToast(`Approved ${success}/${ids.length} decisions. Prices published.`, 'success');
        this.loadData();
        App.updateApprovalCount();
    },

    async batchReject() {
        if (!this.selectedIds.size) return;
        const ids = [...this.selectedIds];
        let success = 0;
        for (const id of ids) {
            try { await API.reject(id, 'revenue_manager'); success++; } catch(e) { /* continue */ }
        }
        Utils.showToast(`Rejected ${success}/${ids.length} decisions.`, 'info');
        this.loadData();
        App.updateApprovalCount();
    },

    showOverrideModal(id, currentPrice) {
        document.getElementById('aq-override-id').textContent = id.substring(0, 8) + '...';
        document.getElementById('aq-override-current').textContent = Utils.currency(currentPrice);
        document.getElementById('aq-override-price').value = currentPrice;
        this._overrideId = id;
        new bootstrap.Modal(document.getElementById('aq-override-modal')).show();
    },

    async submitOverride() {
        const price = parseFloat(document.getElementById('aq-override-price').value);
        if (!price || price <= 0) { Utils.showToast('Enter a valid price', 'error'); return; }
        try {
            await API.override(this._overrideId, 'revenue_manager', price);
            Utils.showToast(`Overridden to ${Utils.currency(price)} and published.`, 'success');
            bootstrap.Modal.getInstance(document.getElementById('aq-override-modal')).hide();
            this.loadData();
            App.updateApprovalCount();
        } catch (e) {
            Utils.showToast('Override failed: ' + e.message, 'error');
        }
    },
};
