// Renders spam-guard results and runs debounced live checks against /spam/check.
const RiskView = (() => {
    const VERDICT = {
        LOW: ["Low risk", "Clear to send.", "low"],
        MEDIUM: ["Medium risk", "Will be held — fix the flagged items before sending.", "medium"],
        HIGH: ["High risk", "Very likely to be filtered as spam.", "high"]
    };

    function render(risk, { compact = false } = {}) {
        if (!risk || risk.score === undefined) {
            return `<div class="risk"><div class="muted small">Not analyzed yet.</div></div>`;
        }
        const [title, sub, tone] = VERDICT[risk.level] || VERDICT.LOW;
        const pct = Math.min(100, (Number(risk.score) / 10) * 100);
        const tips = Object.fromEntries((risk.reasons || []).map((reason, index) => [reason, (risk.suggestions || [])[index]]));
        const checks = [...(risk.checks || [])].sort((a, b) => Number(a.passed) - Number(b.passed)).map(check => `
            <li class="${check.passed ? "pass" : "fail"}">
                <span class="ico">${check.passed ? "✓" : "!"}</span>
                <span class="what">
                    <span>${OutreachApi.escapeHtml(check.label)}</span>
                    ${check.detail ? `<span class="detail">${OutreachApi.escapeHtml(check.detail)}</span>` : ""}
                    ${!check.passed && tips[check.key] ? `<span class="tip">${OutreachApi.escapeHtml(tips[check.key])}</span>` : ""}
                </span>
                <span class="pts">${check.passed ? "" : `+${check.weight}`}</span>
            </li>`).join("");
        const legacyReasons = !risk.checks && (risk.reasons || []).length
            ? `<div class="small muted">${OutreachApi.escapeHtml(risk.reasons.join(", "))}</div>`
            : "";
        const failing = (risk.checks || []).filter(check => !check.passed).length;
        return `
            <div class="risk ${tone}">
                <div class="risk-top">
                    <div class="risk-dial" style="--pct:${pct}"><b>${Number(risk.score).toFixed(1)}<small>/10</small></b></div>
                    <div class="risk-verdict">
                        <strong>${title}</strong>
                        <span>${sub}</span>
                        ${risk.checks ? `<span class="small">${failing ? `${failing} of ${risk.checks.length} checks flagged` : `All ${risk.checks.length} checks passed`}</span>` : ""}
                    </div>
                </div>
                ${checks ? `<ul class="checks ${compact ? "compact" : ""}">${checks}</ul>` : legacyReasons}
            </div>`;
    }

    async function check(subject, body, campaignType = "outreach") {
        return OutreachApi.request("/spam/check", {
            method: "POST",
            json: { email_subject: subject, email_body: body, campaign_type: campaignType }
        });
    }

    // Calls onResult with a fresh risk whenever the inputs settle.
    function live(inputs, getValues, onResult, delay = 450) {
        let timer = null;
        let seq = 0;
        const run = () => {
            const values = getValues();
            const mine = ++seq;
            check(values.subject, values.body, values.campaignType)
                .then(risk => { if (mine === seq) onResult(risk); })
                .catch(() => {});
        };
        inputs.forEach(input => input.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(run, delay);
        }));
        return run;
    }

    return { check, live, render };
})();
