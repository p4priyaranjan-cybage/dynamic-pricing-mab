/**
 * OTA Demo Page - Standalone guest-facing hotel booking page with live pricing.
 * Fetches from the same API endpoints as the internal dashboard.
 */
(function () {
    const API_BASE = '';
    let properties = [];
    let refreshTimer = null;
    let lastPrices = {};

    // --- API Helpers ---
    async function apiGet(path, params = {}) {
        const url = new URL(API_BASE + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
        });
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`${resp.status}`);
        return resp.json();
    }

    function currency(val, decimals = 0) {
        return '$' + Number(val).toFixed(decimals);
    }

    function dateOffset(days) {
        const d = new Date();
        d.setDate(d.getDate() + days);
        return d.toISOString().split('T')[0];
    }

    // --- Init ---
    async function init() {
        try {
            properties = await apiGet('/properties');
            populateSelector();
        } catch (e) {
            document.getElementById('ota-empty-state').innerHTML = `
                <i class="bi bi-wifi-off" style="font-size:3rem; opacity:0.3"></i>
                <p class="mt-3 fs-5 text-danger">Unable to connect to pricing API</p>
                <p class="small text-muted">Make sure the API is running at ${window.location.origin}</p>`;
        }

        // Set default dates
        document.getElementById('ota-checkin').value = dateOffset(1);
        document.getElementById('ota-checkout').value = dateOffset(8);

        // Events
        document.getElementById('ota-search-btn').addEventListener('click', search);
        document.getElementById('ota-property-select').addEventListener('change', search);
    }

    function populateSelector() {
        const sel = document.getElementById('ota-property-select');
        properties.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.property_id;
            opt.textContent = `${p.name} — ${p.chain}, ${p.region}`;
            sel.appendChild(opt);
        });
    }

    function search() {
        const propertyId = document.getElementById('ota-property-select').value;
        if (!propertyId) return;

        lastPrices = {};
        loadStorefront(propertyId);

        // Start auto-refresh
        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(() => loadStorefront(propertyId), 5000);
    }

    async function loadStorefront(propertyId) {
        try {
            const data = await apiGet(`/storefront/${propertyId}`);
            renderHotel(propertyId, data);
        } catch (e) {
            // silent retry
        }
    }

    function renderHotel(propertyId, data) {
        const content = document.getElementById('ota-hotel-content');
        const emptyState = document.getElementById('ota-empty-state');
        const prop = properties.find(p => p.property_id === propertyId);

        if (!data || data.length === 0) {
            emptyState.style.display = 'block';
            content.style.display = 'none';
            emptyState.innerHTML = `
                <i class="bi bi-calendar-x" style="font-size:3rem; opacity:0.3"></i>
                <p class="mt-3 fs-5">No live rates available for this property</p>
                <p class="small text-muted">Rates appear here once approved by Revenue Management</p>`;
            return;
        }

        emptyState.style.display = 'none';
        content.style.display = 'block';

        // Group by room type
        const byRoom = {};
        data.forEach(r => {
            if (!byRoom[r.room_type]) byRoom[r.room_type] = [];
            byRoom[r.room_type].push(r);
        });

        const stars = prop?.market_tier === 'luxury' ? 5 : 4;
        const starHtml = Array(stars).fill('<i class="bi bi-star-fill"></i>').join('');
        const tierBadge = prop?.market_tier === 'luxury'
            ? '<span class="badge bg-warning text-dark">Luxury</span>'
            : '<span class="badge bg-primary">Midscale</span>';

        const minPrice = Math.min(...data.map(r => r.published_price));

        content.innerHTML = `
            <!-- Hotel Header -->
            <div class="ota-hotel-card">
                <div class="ota-hotel-header">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h3 class="fw-bold mb-1">${prop?.name || propertyId}</h3>
                            <div class="ota-hotel-stars mb-2">${starHtml}</div>
                            <div class="ota-hotel-meta">
                                <span><i class="bi bi-building me-1"></i>${prop?.chain || ''} — ${prop?.brand || ''}</span>
                                <span><i class="bi bi-geo-alt me-1"></i>${prop?.region || ''}</span>
                                <span>${tierBadge}</span>
                            </div>
                        </div>
                        <div class="text-end">
                            <div class="text-muted small">From</div>
                            <div class="fs-2 fw-bold text-success">${currency(minPrice)}</div>
                            <div class="text-muted small">per night</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Room Sections -->
            ${Object.entries(byRoom).map(([room, rows]) => renderRoomSection(room, rows)).join('')}

            <!-- Footer Note -->
            <div class="text-center text-muted small py-3">
                <i class="bi bi-lightning-charge-fill text-warning me-1"></i>
                Prices are dynamically optimized and may change. Last refresh: ${new Date().toLocaleTimeString()}
            </div>
        `;
    }

    function renderRoomSection(roomType, rows) {
        rows.sort((a, b) => a.stay_date.localeCompare(b.stay_date));
        const display = rows.slice(0, 21);

        const roomNames = { standard: 'Standard Room', deluxe: 'Deluxe Room', suite: 'Executive Suite' };
        const roomDescs = {
            standard: 'Comfortable room with all essential amenities',
            deluxe: 'Spacious room with premium furnishings and city view',
            suite: 'Luxury suite with separate living area and panoramic views'
        };
        const roomIcons = { standard: 'bi-door-closed', deluxe: 'bi-door-open', suite: 'bi-gem' };
        const roomIconClass = { standard: 'standard', deluxe: 'deluxe', suite: 'suite' };

        const minPrice = Math.min(...display.map(r => r.published_price));

        return `
            <div class="ota-room-section">
                <div class="ota-room-header">
                    <div class="d-flex align-items-center gap-3 w-100">
                        <div class="ota-room-icon ${roomIconClass[roomType] || 'standard'}">
                            <i class="bi ${roomIcons[roomType] || 'bi-door-closed'}"></i>
                        </div>
                        <div class="flex-grow-1">
                            <h5>${roomNames[roomType] || roomType}</h5>
                            <p class="text-muted small mb-0">${roomDescs[roomType] || ''}</p>
                        </div>
                        <div class="text-end">
                            <div class="text-muted small">From</div>
                            <div class="fs-5 fw-bold text-success">${currency(minPrice)}</div>
                        </div>
                    </div>
                </div>
                <div class="ota-room-body">
                    <div class="ota-price-grid">
                        ${display.map(r => renderDateCard(r)).join('')}
                    </div>
                </div>
            </div>`;
    }

    function renderDateCard(row) {
        const key = `${row.room_type}_${row.rate_plan}_${row.stay_date}`;
        const oldPrice = lastPrices[key];
        const changed = oldPrice !== undefined && oldPrice !== row.published_price;
        lastPrices[key] = row.published_price;

        const d = new Date(row.stay_date);
        const dayName = d.toLocaleDateString('en-US', { weekday: 'short' });
        const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const isWeekend = d.getDay() === 0 || d.getDay() === 5 || d.getDay() === 6;

        // Show "was" price using reference_rate * 1.1 as a "rack rate" visual
        const rackPrice = row.reference_rate * 1.12;
        const isDiscount = row.published_price < row.reference_rate * 0.98;
        const isPremium = row.published_price > row.reference_rate * 1.10;

        let priceClass = '';
        if (isDiscount) priceClass = 'discount';
        else if (isPremium) priceClass = 'premium';

        return `
            <div class="ota-date-card ${changed ? 'updated' : ''}">
                ${isWeekend ? '<span class="weekend-tag">Weekend</span>' : ''}
                ${changed ? '<span class="update-badge">UPDATED</span>' : ''}
                <div class="day-name">${dayName}</div>
                <div class="date-str">${dateStr}</div>
                ${isDiscount ? `<div class="price-was">${currency(rackPrice)}</div>` : '<div style="height:1rem"></div>'}
                <div class="price-now ${priceClass}">${currency(row.published_price)}</div>
                <div class="rate-plan">${row.rate_plan.replace(/_/g, ' ')}</div>
            </div>`;
    }

    // Boot
    document.addEventListener('DOMContentLoaded', init);
})();
