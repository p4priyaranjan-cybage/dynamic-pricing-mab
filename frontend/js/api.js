/**
 * API client - all backend communication goes through here.
 * Base URL is relative (same origin as the static files).
 */
const API = {
    baseUrl: '',

    async get(path, params = {}) {
        const url = new URL(this.baseUrl + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
        });
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
        return resp.json();
    },

    async post(path, body = {}) {
        const resp = await fetch(this.baseUrl + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
        return resp.json();
    },

    // --- Properties ---
    getProperties() { return this.get('/properties'); },
    getPropertyConfig(propertyId) { return this.get(`/properties/${propertyId}/config`); },

    // --- Rate Calendar ---
    getRateCalendar(params) { return this.get('/rate-calendar', params); },

    // --- Approval Queue ---
    getApprovalQueue(propertyId) { return this.get('/approval-queue', { property_id: propertyId }); },
    approve(decisionId, approvedBy) { return this.post(`/approval-queue/${decisionId}/approve`, { approved_by: approvedBy }); },
    reject(decisionId, approvedBy) { return this.post(`/approval-queue/${decisionId}/reject`, { approved_by: approvedBy }); },
    override(decisionId, approvedBy, price) { return this.post(`/approval-queue/${decisionId}/override`, { approved_by: approvedBy, override_price: price }); },

    // --- Scoring ---
    score(payload) { return this.post('/score', payload); },
    simulate(payload) { return this.post('/simulate', payload); },
    getRecommendations(payload) { return this.post('/recommendations', payload); },

    // --- Storefront ---
    getStorefront(propertyId) { return this.get(`/storefront/${propertyId}`); },

    // --- Metrics & Health ---
    getMetrics(params) { return this.get('/metrics', params); },
    getModelHealth() { return this.get('/model/health'); },
    getScoringMode(tenantId) { return this.get(`/scoring-mode/${tenantId}`); },
};
