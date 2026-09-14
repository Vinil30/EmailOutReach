function renderEmailCard(email, sent = false, onSend = null, onReject = null) {
    const details = email.written_email_details || {};
    const risk = email.deliverability_risk || {};
    const attempts = email.send_attempts || [];
    const lastAttempt = attempts.length ? attempts[attempts.length - 1] : null;
    const maxAttempts = email.email_response?.max_attempts || lastAttempt?.max_attempts || attempts.length;
    const riskText = risk.score !== undefined
        ? `Spam Risk: ${OutreachApi.escapeHtml(risk.score)} - ${OutreachApi.escapeHtml(risk.level || "UNKNOWN")}`
        : "Spam Risk: not analyzed";
    const reasons = (risk.reasons || []).join(", ");
    const status = email.outreach_status || (sent ? "SENT" : "REVIEW_REQUIRED");
    const card = document.createElement("article");
    card.className = "mail-card";
    card.innerHTML = `
        <div class="mail-head">
            <div>
                <h4>${OutreachApi.escapeHtml(email.company_name || "Unknown company")}</h4>
                <p>${OutreachApi.escapeHtml(email.recipient_name || "")} ${OutreachApi.escapeHtml(email.recipient_email || "")}</p>
            </div>
            <span class="pill">${OutreachApi.escapeHtml(status)}</span>
        </div>
        <div class="risk-box">
            <strong>${riskText}</strong>
            <span>Action: ${OutreachApi.escapeHtml(risk.action || status)}</span>
            ${reasons ? `<span>Reasons: ${OutreachApi.escapeHtml(reasons)}</span>` : ""}
            ${email.failure_reason ? `<span>Reason: ${OutreachApi.escapeHtml(email.failure_reason)}</span>` : ""}
            ${lastAttempt ? `<span>Attempt: ${OutreachApi.escapeHtml(lastAttempt.attempt || attempts.length)}/${OutreachApi.escapeHtml(maxAttempts)}</span>` : ""}
        </div>
        <label>
            Subject
            <input ${sent ? "readonly" : ""} value="${OutreachApi.escapeAttr(details.email_subject || "")}">
        </label>
        <label>
            HTML Body
            <textarea ${sent ? "readonly" : ""}>${OutreachApi.escapeHtml(details.email_body || "")}</textarea>
        </label>
        <div class="meta">Projects: ${OutreachApi.escapeHtml((email.relevant_projects || []).join(", ") || "None selected")}</div>
    `;

    if (!sent && onSend) {
        const actions = document.createElement("div");
        actions.className = "actions";
        const sendButton = document.createElement("button");
        sendButton.className = "btn";
        sendButton.type = "button";
        sendButton.textContent = "Send Approved";
        sendButton.addEventListener("click", () => onSend(email.id, card, sendButton));
        actions.appendChild(sendButton);
        if (onReject) {
            const rejectButton = document.createElement("button");
            rejectButton.className = "btn danger";
            rejectButton.type = "button";
            rejectButton.textContent = "Reject";
            rejectButton.addEventListener("click", () => onReject(email.id, card, rejectButton));
            actions.appendChild(rejectButton);
        }
        card.appendChild(actions);
    }

    return card;
}
