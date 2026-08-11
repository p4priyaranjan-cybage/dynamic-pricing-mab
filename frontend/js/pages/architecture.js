/**
 * Architecture Overview page - visual explainer with diagrams.
 * Pure HTML/CSS/SVG - no API calls, instant load.
 */
const ArchitecturePage = {
    render(container) {
        container.innerHTML = `
        <div class="page-content arch-page">

            <!-- Hero Header -->
            <div class="arch-hero">
                <div class="arch-hero-content">
                    <h2>How Dynamic Pricing Works</h2>
                    <p>An AI system that learns optimal hotel prices through contextual multi-armed bandits</p>
                </div>
            </div>

            <!-- Section 1: High-Level Flow -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-diagram-3"></i> Scoring Pipeline</h4>
                <p class="arch-section-desc">Every pricing decision flows through this pipeline in ~50ms</p>
                <div class="arch-flow">
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon request"><i class="bi bi-send"></i></div>
                        <div class="arch-flow-label">Request</div>
                        <div class="arch-flow-detail">Property + Room + Date</div>
                    </div>
                    <div class="arch-flow-arrow"><i class="bi bi-chevron-right"></i></div>
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon context"><i class="bi bi-clipboard-data"></i></div>
                        <div class="arch-flow-label">Context</div>
                        <div class="arch-flow-detail">20+ market signals assembled</div>
                    </div>
                    <div class="arch-flow-arrow"><i class="bi bi-chevron-right"></i></div>
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon guardrails"><i class="bi bi-shield-check"></i></div>
                        <div class="arch-flow-label">Guardrails</div>
                        <div class="arch-flow-detail">Filter infeasible arms</div>
                    </div>
                    <div class="arch-flow-arrow"><i class="bi bi-chevron-right"></i></div>
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon ensemble"><i class="bi bi-cpu"></i></div>
                        <div class="arch-flow-label">Ensemble</div>
                        <div class="arch-flow-detail">Backbone + Property blend</div>
                    </div>
                    <div class="arch-flow-arrow"><i class="bi bi-chevron-right"></i></div>
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon decision"><i class="bi bi-lightning-charge"></i></div>
                        <div class="arch-flow-label">Decision</div>
                        <div class="arch-flow-detail">Arm + Confidence score</div>
                    </div>
                    <div class="arch-flow-arrow"><i class="bi bi-chevron-right"></i></div>
                    <div class="arch-flow-step">
                        <div class="arch-flow-icon publish"><i class="bi bi-broadcast"></i></div>
                        <div class="arch-flow-label">Publish</div>
                        <div class="arch-flow-detail">Auto or Approval Queue</div>
                    </div>
                </div>
            </div>

            <!-- Section 2: Two-Tier Model -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-layers"></i> Two-Tier Model Architecture</h4>
                <p class="arch-section-desc">Solves cold-start for new properties while enabling specialization for mature ones</p>
                <div class="arch-two-tier">
                    <div class="arch-model-card backbone">
                        <div class="arch-model-header">
                            <div class="arch-model-icon"><i class="bi bi-people"></i></div>
                            <h5>Cluster Backbone</h5>
                            <span class="arch-model-tag">Shared Wisdom</span>
                        </div>
                        <div class="arch-model-body">
                            <ul>
                                <li><strong>Scope:</strong> 1 per (cluster x tenant)</li>
                                <li><strong>Updates:</strong> Nightly batch retrain only</li>
                                <li><strong>Architecture:</strong> 5-member VW bag ensemble</li>
                                <li><strong>Purpose:</strong> Cold-start fallback + stability</li>
                                <li><strong>Isolation:</strong> Chains never share weights</li>
                            </ul>
                        </div>
                        <div class="arch-model-visual">
                            <div class="arch-bag-members">
                                <div class="arch-bag-dot"></div>
                                <div class="arch-bag-dot"></div>
                                <div class="arch-bag-dot"></div>
                                <div class="arch-bag-dot"></div>
                                <div class="arch-bag-dot"></div>
                            </div>
                            <small>5 independent VW workspaces (online bagging)</small>
                        </div>
                    </div>

                    <div class="arch-blend-visual">
                        <div class="arch-blend-formula">
                            <div class="arch-blend-title">Credibility Blend</div>
                            <div class="arch-blend-eq">
                                <span class="arch-eq-w">w</span> = n / (n + k)
                            </div>
                            <div class="arch-blend-bar">
                                <div class="arch-blend-property" style="width: 35%">Property 35%</div>
                                <div class="arch-blend-backbone" style="width: 65%">Backbone 65%</div>
                            </div>
                            <div class="arch-blend-legend">
                                <small>n=10 observations, k=20</small>
                            </div>
                        </div>
                        <div class="arch-blend-arrow">
                            <svg width="40" height="80"><path d="M20 0 L20 60 L10 50 M20 60 L30 50" stroke="currentColor" fill="none" stroke-width="2"/></svg>
                        </div>
                        <div class="arch-blend-output">
                            <i class="bi bi-bullseye"></i>
                            <span>Final Price Decision</span>
                        </div>
                    </div>

                    <div class="arch-model-card property">
                        <div class="arch-model-header">
                            <div class="arch-model-icon"><i class="bi bi-building"></i></div>
                            <h5>Property Model</h5>
                            <span class="arch-model-tag">Individual Learning</span>
                        </div>
                        <div class="arch-model-body">
                            <ul>
                                <li><strong>Scope:</strong> 1 per property (fully isolated)</li>
                                <li><strong>Updates:</strong> Online after each booking outcome</li>
                                <li><strong>Architecture:</strong> Single VW workspace</li>
                                <li><strong>Purpose:</strong> Property-specific specialization</li>
                                <li><strong>Trust:</strong> Grows with n_observations</li>
                            </ul>
                        </div>
                        <div class="arch-model-visual">
                            <div class="arch-trust-meter">
                                <div class="arch-trust-fill" style="width:35%"></div>
                            </div>
                            <small>Trust grows: 0% (new) &rarr; 100% (mature)</small>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Section 3: Cluster / Tenant -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-grid-3x3-gap"></i> Cluster &amp; Tenant Isolation</h4>
                <p class="arch-section-desc">Properties from competing chains share a market cluster but NEVER share model weights</p>
                <div class="arch-cluster-diagram">
                    <div class="arch-cluster-box">
                        <div class="arch-cluster-title">NYC Midscale Urban</div>
                        <div class="arch-cluster-content">
                            <div class="arch-tenant-col marriott">
                                <div class="arch-tenant-header">
                                    <span class="arch-tenant-dot marriott"></span> Marriott
                                </div>
                                <div class="arch-tenant-model">
                                    <i class="bi bi-cpu"></i> Backbone Weights
                                    <div class="arch-weight-bars">
                                        <div class="arch-wbar"></div><div class="arch-wbar"></div><div class="arch-wbar"></div>
                                    </div>
                                </div>
                                <div class="arch-properties">
                                    <div class="arch-prop-chip">Courtyard NYC #1</div>
                                    <div class="arch-prop-chip">Courtyard NYC #2</div>
                                </div>
                            </div>
                            <div class="arch-isolation-wall">
                                <div class="arch-wall-label"><i class="bi bi-lock"></i> Isolated</div>
                            </div>
                            <div class="arch-tenant-col hyatt">
                                <div class="arch-tenant-header">
                                    <span class="arch-tenant-dot hyatt"></span> Hyatt
                                </div>
                                <div class="arch-tenant-model">
                                    <i class="bi bi-cpu"></i> Backbone Weights
                                    <div class="arch-weight-bars">
                                        <div class="arch-wbar"></div><div class="arch-wbar"></div><div class="arch-wbar"></div>
                                    </div>
                                </div>
                                <div class="arch-properties">
                                    <div class="arch-prop-chip">Hyatt Place NYC #1</div>
                                    <div class="arch-prop-chip">Hyatt Place NYC #2</div>
                                </div>
                            </div>
                        </div>
                        <div class="arch-cluster-shared">
                            <i class="bi bi-share"></i> <strong>Shared:</strong> Arm ladder, context features, market cluster definition
                            &nbsp;|&nbsp; <i class="bi bi-lock"></i> <strong>Separate:</strong> All trained weights, training data, business rules
                        </div>
                    </div>
                </div>
            </div>

            <!-- Section 4: Arm Ladder -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-sliders2-vertical"></i> Price Arm Ladder</h4>
                <p class="arch-section-desc">9 discrete price tiers the bandit chooses from — applied as offsets on the Reference Rate</p>
                <div class="arch-ladder">
                    <div class="arch-arm discount-deep" data-offset="-22.5%">
                        <div class="arch-arm-bar" style="height:20%"></div>
                        <div class="arch-arm-label">Deep<br>Discount</div>
                        <div class="arch-arm-pct">-22.5%</div>
                    </div>
                    <div class="arch-arm discount" data-offset="-15%">
                        <div class="arch-arm-bar" style="height:30%"></div>
                        <div class="arch-arm-label">Discount</div>
                        <div class="arch-arm-pct">-15%</div>
                    </div>
                    <div class="arch-arm discount-slight" data-offset="-6.5%">
                        <div class="arch-arm-bar" style="height:40%"></div>
                        <div class="arch-arm-label">Slight<br>Discount</div>
                        <div class="arch-arm-pct">-6.5%</div>
                    </div>
                    <div class="arch-arm base" data-offset="0%">
                        <div class="arch-arm-bar" style="height:50%"></div>
                        <div class="arch-arm-label">Base<br>Rate</div>
                        <div class="arch-arm-pct">0%</div>
                    </div>
                    <div class="arch-arm premium-slight" data-offset="+6.5%">
                        <div class="arch-arm-bar" style="height:58%"></div>
                        <div class="arch-arm-label">Slight<br>Premium</div>
                        <div class="arch-arm-pct">+6.5%</div>
                    </div>
                    <div class="arch-arm premium" data-offset="+15%">
                        <div class="arch-arm-bar" style="height:66%"></div>
                        <div class="arch-arm-label">Premium</div>
                        <div class="arch-arm-pct">+15%</div>
                    </div>
                    <div class="arch-arm premium-high" data-offset="+27.5%">
                        <div class="arch-arm-bar" style="height:76%"></div>
                        <div class="arch-arm-label">High<br>Premium</div>
                        <div class="arch-arm-pct">+27.5%</div>
                    </div>
                    <div class="arch-arm surge" data-offset="+45%">
                        <div class="arch-arm-bar" style="height:88%"></div>
                        <div class="arch-arm-label">Demand<br>Surge</div>
                        <div class="arch-arm-pct">+45%</div>
                    </div>
                    <div class="arch-arm peak" data-offset="+62.5%">
                        <div class="arch-arm-bar" style="height:100%"></div>
                        <div class="arch-arm-label">Peak<br>Premium</div>
                        <div class="arch-arm-pct">+62.5%</div>
                    </div>
                </div>
                <div class="arch-ladder-formula">
                    <strong>Published Price</strong> = Reference Rate &times; (1 + arm_offset)
                    &nbsp;&nbsp;|&nbsp;&nbsp;
                    <strong>Reference Rate</strong> = BAR &times; Room Multiplier &times; Rate Plan Offset &times; LOS Curve
                </div>
            </div>

            <!-- Section 5: Feedback Loop -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-arrow-repeat"></i> Learning Feedback Loop</h4>
                <p class="arch-section-desc">The system gets smarter with every booking outcome</p>
                <div class="arch-feedback-loop">
                    <div class="arch-loop-step s1">
                        <div class="arch-loop-num">1</div>
                        <div class="arch-loop-icon"><i class="bi bi-cpu"></i></div>
                        <div class="arch-loop-text">
                            <strong>Bandit Scores</strong>
                            <span>Picks an arm based on context</span>
                        </div>
                    </div>
                    <div class="arch-loop-connector"></div>
                    <div class="arch-loop-step s2">
                        <div class="arch-loop-num">2</div>
                        <div class="arch-loop-icon"><i class="bi bi-person-check"></i></div>
                        <div class="arch-loop-text">
                            <strong>RM Reviews</strong>
                            <span>Approve / Reject / Override</span>
                        </div>
                    </div>
                    <div class="arch-loop-connector"></div>
                    <div class="arch-loop-step s3">
                        <div class="arch-loop-num">3</div>
                        <div class="arch-loop-icon"><i class="bi bi-broadcast"></i></div>
                        <div class="arch-loop-text">
                            <strong>Price Published</strong>
                            <span>Guest sees the price</span>
                        </div>
                    </div>
                    <div class="arch-loop-connector"></div>
                    <div class="arch-loop-step s4">
                        <div class="arch-loop-num">4</div>
                        <div class="arch-loop-icon"><i class="bi bi-calendar-check"></i></div>
                        <div class="arch-loop-text">
                            <strong>Stay Occurs</strong>
                            <span>Booked or not? Cancelled?</span>
                        </div>
                    </div>
                    <div class="arch-loop-connector"></div>
                    <div class="arch-loop-step s5">
                        <div class="arch-loop-num">5</div>
                        <div class="arch-loop-icon"><i class="bi bi-graph-up"></i></div>
                        <div class="arch-loop-text">
                            <strong>Model Learns</strong>
                            <span>Weights update from true reward</span>
                        </div>
                    </div>
                    <div class="arch-loop-return">
                        <i class="bi bi-arrow-return-left"></i>
                        <span>Better decisions next time</span>
                    </div>
                </div>
            </div>

            <!-- Section 6: Context Features -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-grid-1x2"></i> Context Signals (20+ Features)</h4>
                <p class="arch-section-desc">What the model sees before every decision</p>
                <div class="arch-features-grid">
                    <div class="arch-feature-group">
                        <div class="arch-fg-title"><i class="bi bi-graph-up text-success"></i> Demand</div>
                        <div class="arch-fg-items">
                            <span>Occupancy %</span>
                            <span>ADR Trend</span>
                            <span>Pace vs STLY</span>
                            <span>Pickup 7d</span>
                            <span>Remaining Inventory</span>
                        </div>
                    </div>
                    <div class="arch-feature-group">
                        <div class="arch-fg-title"><i class="bi bi-people text-primary"></i> Comp-Set</div>
                        <div class="arch-fg-items">
                            <span>Avg Rate</span>
                            <span>Our Index vs Comp</span>
                            <span>Rate Trend</span>
                            <span>Rank</span>
                            <span>Dispersion</span>
                        </div>
                    </div>
                    <div class="arch-feature-group">
                        <div class="arch-fg-title"><i class="bi bi-calendar-event text-danger"></i> Events</div>
                        <div class="arch-fg-items">
                            <span>Event Flag</span>
                            <span>Intensity (0-1)</span>
                        </div>
                    </div>
                    <div class="arch-feature-group">
                        <div class="arch-fg-title"><i class="bi bi-tags text-warning"></i> Segment</div>
                        <div class="arch-fg-items">
                            <span>Guest Segment</span>
                            <span>Room Type</span>
                            <span>Rate Plan</span>
                            <span>LOS Bucket</span>
                        </div>
                    </div>
                    <div class="arch-feature-group">
                        <div class="arch-fg-title"><i class="bi bi-calendar3 text-info"></i> Calendar</div>
                        <div class="arch-fg-items">
                            <span>Day of Week</span>
                            <span>Lead Time</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Section 7: Confidence Score -->
            <div class="arch-section">
                <h4 class="arch-section-title"><i class="bi bi-speedometer2"></i> Confidence Score</h4>
                <p class="arch-section-desc">Three components determine if a decision auto-publishes or needs human review</p>
                <div class="arch-confidence">
                    <div class="arch-conf-component">
                        <div class="arch-conf-ring sample">
                            <span>40%</span>
                        </div>
                        <h6>Sample Size</h6>
                        <p>How much real data does this property have?</p>
                    </div>
                    <div class="arch-conf-plus">+</div>
                    <div class="arch-conf-component">
                        <div class="arch-conf-ring agreement">
                            <span>35%</span>
                        </div>
                        <h6>Bag Agreement</h6>
                        <p>Do the 5 backbone members agree on the best arm?</p>
                    </div>
                    <div class="arch-conf-plus">+</div>
                    <div class="arch-conf-component">
                        <div class="arch-conf-ring margin">
                            <span>25%</span>
                        </div>
                        <h6>Decision Margin</h6>
                        <p>How decisive is the winner vs. second-best?</p>
                    </div>
                    <div class="arch-conf-equals">=</div>
                    <div class="arch-conf-result">
                        <div class="arch-conf-score">Confidence</div>
                        <div class="arch-conf-actions">
                            <div class="arch-conf-action high"><i class="bi bi-check-circle"></i> &gt;0.7: Auto-publish</div>
                            <div class="arch-conf-action med"><i class="bi bi-exclamation-circle"></i> 0.4-0.7: Auto if small delta</div>
                            <div class="arch-conf-action low"><i class="bi bi-hand-index"></i> &lt;0.4: Needs RM approval</div>
                        </div>
                    </div>
                </div>
            </div>

        </div>`;
    }
};
