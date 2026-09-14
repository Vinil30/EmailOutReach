if (!OutreachApi.requireAuth()) {
    throw new Error("Authentication required");
}
OutreachApi.bindLogout();

const reviewStatus = document.getElementById("reviewStatus");
const reviewList = document.getElementById("reviewList");
const refreshReviewBtn = document.getElementById("refreshReviewBtn");
const downloadRejectedBtn = document.getElementById("downloadRejectedBtn");

async function loadReview() {
    OutreachApi.setStatus(reviewStatus, "Loading drafts...");
    try {
        const data = await OutreachApi.request("/human/waiting-emails");
        reviewList.innerHTML = "";
        if (!data.emails.length) {
            reviewList.innerHTML = `<div class="empty">No drafts waiting for review.</div>`;
        } else {
            data.emails.forEach(email => reviewList.appendChild(renderEmailCard(email, false, sendDraft, rejectDraft)));
        }
        OutreachApi.setStatus(reviewStatus, `${data.emails.length} drafts waiting.`, "ok");
    } catch (error) {
        OutreachApi.setStatus(reviewStatus, error.message, "error");
    }
}

async function sendDraft(mailId, card, button) {
    const inputs = card.querySelectorAll("input, textarea");
    button.disabled = true;
    button.textContent = "Sending...";
    try {
        const data = await OutreachApi.request("/human/send-mail", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                mail_id: mailId,
                email_subject: inputs[0].value,
                email_body: inputs[1].value
            })
        });
        if (data.blocked) {
            const replacement = renderEmailCard(data.email, false, sendDraft, rejectDraft);
            card.replaceWith(replacement);
            const reasons = (data.deliverability_risk?.reasons || []).join(", ") || "Rspamd risk threshold exceeded";
            OutreachApi.setStatus(reviewStatus, `Send blocked for spam/deliverability risk: ${reasons}`, "error");
            return;
        }
        if (data.failed) {
            const replacement = renderEmailCard(data.email, false, sendDraft, rejectDraft);
            card.replaceWith(replacement);
            OutreachApi.setStatus(reviewStatus, data.email?.failure_reason || "Gmail send failed.", "error");
            return;
        }
        card.remove();
        OutreachApi.setStatus(reviewStatus, "Email sent and moved to sent collection.", "ok");
        if (!reviewList.children.length) {
            reviewList.innerHTML = `<div class="empty">No drafts waiting for review.</div>`;
        }
    } catch (error) {
        OutreachApi.setStatus(reviewStatus, error.message, "error");
        button.disabled = false;
        button.textContent = "Send Approved";
    }
}

async function rejectDraft(mailId, card, button) {
    const inputs = card.querySelectorAll("input, textarea");
    button.disabled = true;
    button.textContent = "Rejecting...";
    try {
        await OutreachApi.request("/human/reject-mail", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                mail_id: mailId,
                email_subject: inputs[0].value,
                email_body: inputs[1].value
            })
        });
        card.remove();
        OutreachApi.setStatus(reviewStatus, "Draft rejected, removed from review, and saved to the rejected CSV.", "ok");
        if (!reviewList.children.length) {
            reviewList.innerHTML = `<div class="empty">No drafts waiting for review.</div>`;
        }
    } catch (error) {
        OutreachApi.setStatus(reviewStatus, error.message, "error");
        button.disabled = false;
        button.textContent = "Reject";
    }
}

async function downloadRejectedCsv() {
    OutreachApi.setStatus(reviewStatus, "Preparing rejected CSV...");
    try {
        const response = await fetch("/human/rejected-csv", {
            headers: { Authorization: `Bearer ${OutreachApi.getToken()}` }
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Could not download rejected CSV");
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "rejected_by_human.csv";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        OutreachApi.setStatus(reviewStatus, "Rejected CSV downloaded.", "ok");
    } catch (error) {
        OutreachApi.setStatus(reviewStatus, error.message, "error");
    }
}

refreshReviewBtn.addEventListener("click", loadReview);
downloadRejectedBtn.addEventListener("click", downloadRejectedCsv);
loadReview();
