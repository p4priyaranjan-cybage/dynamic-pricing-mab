/**
 * OTA Storefront - professional mock of what a guest sees on a booking site.
 * Auto-refreshes to show price updates immediately after approval.
 */
const OTAStorefrontPage = {
    refreshTimer: null,
    lastPrices: {},

    async render(container) {
        container.innerHTML = `
        <div class="page-content">
            <!-- OTA Header Bar -->
            <div class="card border-0 mb-3" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                <div class="card-body py-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="text-white">
                            <h4 class="mb-0 fw-bold"><i class="bi bi-building me-2"></i>StayBook.com</h4>
                            <small class="opacity-75">Mock OTA — Live channel prices (refreshes every 3s)</small>
                        </div>
                        <div class="d-flex align-items-center gap-3">
                            <span class="badge bg-light text-dark"><i class="bi bi-broadcast-pin text-success"></i> Live</span>
                            <select class="form-select form-select-sm bg-white" id="ota-property-select" style="width:280px">
                                <option value="">Select a hotel...</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>
            <div id="ota-content">${this.emptyState()}</div>
        </div>`;

        const sel = document.getElementById('ota-property-select');
        App.properties.forEach(p => { sel.innerHTML += `<option value="${p.property_id}">${p.name} - ${p.region}</option>`; });
        if (App.selectedProperty) sel.value = App.selectedProperty;
        sel.addEventListener('change', () => { this.lastPrices = {}; this.load(sel.value); });
        if (sel.value) this.load(sel.value);
        this.refreshTimer = setInterval(() => {
            const v = document.getElementById('ota-property-select')?.value;
            if (v) this.load(v);
        }, 3000);
    },

    emptyState() {
        return `<div class="text-center py-5 text-muted">
            <i class="bi bi-search" style="font-size:3rem; opacity:0.4"></i>
            <p class="mt-3">Select a hotel above to see its live pricing.</p>
        </div>`;
    },

    async load(propertyId) {
        if (!propertyId) return;
        try {
            const data = await API.getStorefront(propertyId);
            this.renderHotel(data, propertyId);
        } catch(e) {}
    },

    renderHotel(data, propertyId) {
        const content = document.getElementById('ota-content');
        const prop = App.properties.find(p => p.property_id === propertyId);
        if (!data.length) {
            content.innerHTML = `
                <div class="card shadow-sm">
                    <div class="card-body text-center py-5">
                        <i class="bi bi-calendar-x" style="font-size:2.5rem; opacity:0.4"></i>
                        <p class="mt-2 text-muted">No live rates available for this property.<br>
                        <small>Approve recommendations in the Approval Queue to publish rates here.</small></p>
                    </div>
                </div>`;
            return;
        }

        // Group by room type
        const byRoom = {};
        data.forEach(r => { if (!byRoom[r.room_type]) byRoom[r.room_type] = []; byRoom[r.room_type].push(r); });

        const stars = prop?.market_tier === 'luxury' ? '&#9733;&#9733;&#9733;&#9733;&#9733;' : '&#9733;&#9733;&#9733;&#9733;';
        const tierBadge = prop?.market_tier === 'luxury' ? '<span class="badge bg-warning text-dark">Luxury</span>' : '<span class="badge bg-info">Midscale</span>';

        content.innerHTML = `
            <!-- Hotel card header -->
            <div class="card shadow-sm mb-3">
                <div class="card-body">
                    <div class="row align-items-center">
                        <div class="col-md-1 text-center">
                            <div style="width:60px;height:60px;border-radius:12px;background:linear-gradient(135deg,#f093fb,#f5576c);display:flex;align-items:center;justify-content:center">
                                <i class="bi bi-building text-white" style="font-size:1.5rem"></i>
                            </div>
                        </div>
                        <div class="col-md-7">
                            <h5 class="mb-0 fw-bold">${prop?.name || propertyId}</h5>
                            <div class="text-muted small">
                                <span class="text-warning">${stars}</span>
                                <span class="ms-2">${prop?.chain || ''}</span>
                                <span class="mx-1">|</span>
                                <i class="bi bi-geo-alt"></i> ${prop?.region || ''}
                                <span class="ms-2">${tierBadge}</span>
                            </div>
                        </div>
                        <div class="col-md-4 text-end">
                            <div class="text-muted small">Prices from</div>
                            <div class="fs-3 fw-bold text-success">${Utils.currency(Math.min(...data.map(r => r.published_price)), 0)}</div>
                            <div class="text-muted small">per night</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Room sections -->
            ${Object.entries(byRoom).map(([room, rows]) => this.roomSection(room, rows)).join('')}

            <div class="text-center text-muted small mt-3">
                <i class="bi bi-shield-check me-1"></i>Prices update automatically when approved by Revenue Management
            </div>
        `;
    },

    roomSection(roomType, rows) {
        rows.sort((a, b) => a.stay_date.localeCompare(b.stay_date));
        const display = rows.slice(0, 21); // 3 weeks max
        const roomNames = { standard: 'Standard Room', deluxe: 'Deluxe Room', suite: 'Executive Suite' };
        const roomIcons = { standard: 'bi-door-closed', deluxe: 'bi-door-open', suite: 'bi-star' };

        return `
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-white border-bottom">
                    <div class="d-flex justify-content-between align-items-center">
                        <h6 class="mb-0"><i class="bi ${roomIcons[roomType] || 'bi-door-open'} me-2"></i>${roomNames[roomType] || roomType}</h6>
                        <small class="text-muted">${display.length} dates available</small>
                    </div>
                </div>
                <div class="card-body">
                    <div class="row g-2">
                        ${display.map(r => this.dateCard(r)).join('')}
                    </div>
                </div>
            </div>`;
    },

    dateCard(row) {
        const key = row.decision_id;
        const oldPrice = this.lastPrices[key];
        const changed = oldPrice !== undefined && oldPrice !== row.published_price;
        this.lastPrices[key] = row.published_price;

        const d = new Date(row.stay_date);
        const dayName = d.toLocaleDateString('en-US', { weekday: 'short' });
        const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const isWeekend = d.getDay() === 5 || d.getDay() === 6;

        // Derive a "was" price for visual effect (reference rate as the "rack rate")
        const rackPrice = row.reference_rate * 1.15;
        const discount = row.published_price < rackPrice;

        return `
            <div class="col-6 col-md-4 col-lg-3 col-xl-2">
                <div class="card h-100 border ${changed ? 'border-success' : ''} ${changed ? 'ota-price-card price-updated' : 'ota-price-card'}" style="border-radius:10px">
                    <div class="card-body text-center p-2">
                        <div class="small text-muted">${dayName}</div>
                        <div class="fw-bold small ${isWeekend ? 'text-info' : ''}">${dateStr}</div>
                        ${discount ? `<div class="ota-strikethrough small">${Utils.currency(rackPrice, 0)}</div>` : '<div style="height:1.2rem"></div>'}
                        <div class="fs-4 fw-bold ${changed ? 'text-success' : 'text-dark'}">${Utils.currency(row.published_price, 0)}</div>
                        <div class="small text-muted">${row.rate_plan.replace(/_/g, ' ')}</div>
                        ${changed ? '<div class="badge bg-success mt-1" style="font-size:0.65rem"><i class="bi bi-check"></i> Updated</div>' : ''}
                        ${isWeekend ? '<div class="badge bg-info bg-opacity-25 text-info mt-1" style="font-size:0.6rem">Weekend</div>' : ''}
                    </div>
                </div>
            </div>`;
    },

    destroy() {
        if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    },
};
