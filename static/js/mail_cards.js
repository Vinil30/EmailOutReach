// Editable draft card with live spam scoring, used by the review queue.
function renderEmailCard(email, handlers = {}) {
    const esc = OutreachApi.escapeHtml;
    const details = email.written_email_details || {};
    const risk = email.deliverability_risk || {};
    const status = email.outreach_status || "REVIEW_REQUIRED";
    const campaignType = email.campaign_type || "outreach";
    const projects = email.relevant_projects || [];
    const attempts = email.send_attempts || [];
    const lastAttempt = attempts[attempts.length - 1];

    const card = document.createElement("article");
    card.className = "mail-card";
    card.dataset.id = email.id;
    card.innerHTML = `
        <div class="mail-main">
            <div class="mail-head">
                <div style="min-width:0;">
                    <h3>${esc(email.recipient_name || email.recipient_email)}${email.company_name ? ` <span class="muted" style="font-weight:400;">· ${esc(email.company_name)}</span>` : ""}</h3>
                    <div class="to">${esc(email.recipient_email)} · from ${esc(email.email_from || "")}</div>
                </div>
                <div class="mail-meta" data-role="status">${OutreachApi.statusBadge(status)}</div>
            </div>
            <div class="mail-meta">
                ${email.campaign_name ? `<span class="badge plain">${esc(email.campaign_name)}</span>` : ""}
                ${projects.map(name => `<span class="badge accent plain">${esc(name)}</span>`).join("")}
                <span class="badge plain muted">${OutreachApi.timeAgo(email.created_at)}</span>
            </div>
            ${email.failure_reason ? `<div class="failure"><strong>Last send failed:</strong> ${esc(email.failure_reason)}${lastAttempt ? ` (attempt ${esc(lastAttempt.attempt)}/${esc(lastAttempt.max_attempts || attempts.length)})` : ""}</div>` : ""}
            <label class="field"><span>Subject</span><input data-field="subject" value="${OutreachApi.escapeAttr(details.email_subject || "")}"></label>
            <div>
                <div class="mail-tabs">
                    <button type="button" class="active" data-tab="preview">Preview</button>
                    <button type="button" data-tab="html">Edit HTML</button>
                </div>
                <div data-pane="preview" style="padding-top:10px;"><div class="mail-preview"></div></div>
                <div data-pane="html" style="padding-top:10px;" hidden><textarea class="body" data-field="body">${esc(details.email_body || "")}</textarea></div>
            </div>
            <div class="actions">
                <button type="button" class="btn primary" data-action="send">Send</button>
                ${handlers.rewrite ? '<button type="button" class="btn secondary" data-action="rewrite" title="Rewrite with AI to fix flagged checks">✦ Fix with AI</button>' : ""}
                <button type="button" class="btn ghost" data-action="save">Save draft</button>
                <span class="spacer"></span>
                <button type="button" class="btn danger" data-action="reject">Reject</button>
            </div>
        </div>
        <aside class="mail-side">
            <div class="field-label">Spam & deliverability</div>
            <div data-role="risk">${RiskView.render(risk, { compact: true })}</div>
            <button type="button" class="btn ghost sm" data-action="toggle-checks" style="justify-self:start;">Show all checks</button>
        </aside>`;

    const subjectInput = card.querySelector('[data-field="subject"]');
    const bodyInput = card.querySelector('[data-field="body"]');
    const preview = card.querySelector(".mail-preview");
    const riskNode = card.querySelector('[data-role="risk"]');
    let showAll = false;
    let lastRisk = risk;

    function paintPreview() {
        OutreachApi.renderEmailPreview(preview, bodyInput.value);
    }

    function paintRisk(next) {
        lastRisk = next;
        riskNode.innerHTML = RiskView.render(next, { compact: !showAll });
        const sendButton = card.querySelector('[data-action="send"]');
        sendButton.textContent = next.action === "SEND" ? "Send" : "Send (blocked)";
        sendButton.classList.toggle("primary", next.action === "SEND");
        sendButton.classList.toggle("secondary", next.action !== "SEND");
        sendButton.title = next.action === "SEND" ? "" : "Score is 4 or higher — fix the flagged checks first";
    }

    card.querySelectorAll(".mail-tabs button").forEach(button => button.addEventListener("click", () => {
        card.querySelectorAll(".mail-tabs button").forEach(node => node.classList.toggle("active", node === button));
        card.querySelectorAll("[data-pane]").forEach(pane => { pane.hidden = pane.dataset.pane !== button.dataset.tab; });
        paintPreview();
    }));

    card.querySelector('[data-action="toggle-checks"]').addEventListener("click", event => {
        showAll = !showAll;
        event.target.textContent = showAll ? "Show only issues" : "Show all checks";
        paintRisk(lastRisk);
    });

    RiskView.live([subjectInput, bodyInput], () => ({
        subject: subjectInput.value,
        body: bodyInput.value,
        campaignType
    }), paintRisk);

    const values = () => ({ mail_id: email.id, email_subject: subjectInput.value, email_body: bodyInput.value });
    card.querySelectorAll(".actions [data-action]").forEach(button => {
        const handler = handlers[button.dataset.action];
        if (handler) {
            button.addEventListener("click", () => handler({ email, card, button, values: values() }));
        }
    });

    paintPreview();
    if (risk.score !== undefined) paintRisk(risk);
    return card;
}
