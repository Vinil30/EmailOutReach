(async () => {
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet("/human/waiting-emails");
    OutreachApi.cachedGet("/api/campaigns");
    let fresh = false;
    const user = await Layout.init();
    const $ = id => document.getElementById(id);
    const reviewStatus = $("reviewStatus");
    const reviewList = $("reviewList");
    const params = new URLSearchParams(window.location.search);
    const view = { filter: params.get("filter") || "all", campaign: params.get("campaign") || "", query: "" };
    let emails = [];

    const FILTERS = {
        all: () => true,
        ready: email => email.deliverability_risk?.action === "SEND" && !String(email.outreach_status).startsWith("FAILED"),
        flagged: email => email.outreach_status === "REGENERATE" || email.deliverability_risk?.action === "REGENERATE",
        failed: email => String(email.outreach_status).startsWith("FAILED")
    };

    if (!FILTERS[view.filter]) view.filter = "all";

    function matches(email) {
        if (!FILTERS[view.filter](email)) return false;
        if (view.campaign && email.campaign_id !== view.campaign) return false;
        if (!view.query) return true;
        const haystack = [email.recipient_name, email.recipient_email, email.company_name, email.written_email_details?.email_subject].join(" ").toLowerCase();
        return haystack.includes(view.query);
    }

    function render() {
        document.querySelectorAll("#filterChips button").forEach(button => {
            const count = emails.filter(FILTERS[button.dataset.filter]).length;
            button.classList.toggle("active", button.dataset.filter === view.filter);
            button.innerHTML = `${button.dataset.filter[0].toUpperCase()}${button.dataset.filter.slice(1)}<span class="n">${count}</span>`;
        });
        const visible = emails.filter(matches);
        reviewList.innerHTML = "";
        if (!visible.length) {
            reviewList.innerHTML = emails.length
                ? `<div class="empty"><strong>Nothing matches this filter</strong><span>Try another filter or campaign.</span></div>`
                : `<div class="empty"><strong>Your queue is clear</strong><span>Drafts from “Review first” campaigns, and anything the spam guard holds back, show up here.</span><a class="btn primary" href="/campaigns/new">Start a campaign</a></div>`;
        } else {
            visible.forEach(email => reviewList.appendChild(renderEmailCard(email, { send: sendDraft, reject: rejectDraft, save: saveDraft, ...(user.is_premium ? { rewrite: rewriteDraft } : {}) })));
        }
        OutreachApi.setStatus(reviewStatus, `${visible.length} of ${emails.length} drafts shown.`);
    }

    async function loadReview() {
        OutreachApi.setStatus(reviewStatus, "Loading drafts…");
        try {
            const [data, campaigns] = await Promise.all([
                OutreachApi.cachedGet("/human/waiting-emails", { fresh }),
                OutreachApi.cachedGet("/api/campaigns", { fresh }).catch(() => ({ campaigns: [] }))
            ]);
            fresh = true;
            emails = data.emails;
            const select = $("campaignFilter");
            select.innerHTML = `<option value="">All campaigns</option>` + campaigns.campaigns
                .filter(campaign => campaign.counts?.waiting)
                .map(campaign => `<option value="${campaign.id}">${OutreachApi.escapeHtml(campaign.name)} (${campaign.counts.waiting})</option>`).join("");
            select.value = view.campaign;
            render();
        } catch (error) {
            OutreachApi.setStatus(reviewStatus, error.message, "error");
        }
    }

    function replaceEmail(updated) {
        emails = emails.map(email => (email.id === updated.id ? updated : email));
    }

    function dropEmail(id, card) {
        emails = emails.filter(email => email.id !== id);
        card.style.transition = "opacity .2s, transform .2s";
        card.style.opacity = "0";
        card.style.transform = "translateX(12px)";
        setTimeout(render, 200);
        Layout.refreshReviewCount();
    }

    async function withBusy(button, label, task) {
        const original = button.textContent;
        button.disabled = true;
        button.textContent = label;
        try {
            return await task();
        } finally {
            button.disabled = false;
            button.textContent = original;
        }
    }

    async function sendDraft({ email, card, button, values }) {
        try {
            const data = await withBusy(button, "Sending…", () => OutreachApi.request("/human/send-mail", { method: "POST", json: values }));
            if (data.blocked) {
                replaceEmail(data.email);
                render();
                OutreachApi.toast(`Blocked by the spam guard: ${(data.deliverability_risk?.reasons || []).join(", ")}`, "error");
                return false;
            }
            if (data.failed) {
                replaceEmail(data.email);
                render();
                OutreachApi.toast(data.email?.failure_reason || "Gmail send failed.", "error");
                return false;
            }
            OutreachApi.toast(`Sent to ${email.recipient_email}.`, "ok");
            dropEmail(email.id, card);
            Layout.refreshPlan();
            return true;
        } catch (error) {
            OutreachApi.toast(error.message, "error");
            if (/Upgrade/.test(error.message)) OutreachApi.openUpgrade();
            return false;
        }
    }

    async function rejectDraft({ email, card, button, values }) {
        if (!confirm(`Reject the draft to ${email.recipient_email}? It will be removed from the queue and logged to your rejected CSV.`)) return;
        try {
            await withBusy(button, "Rejecting…", () => OutreachApi.request("/human/reject-mail", { method: "POST", json: values }));
            OutreachApi.toast("Draft rejected and logged.", "ok");
            dropEmail(email.id, card);
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    }

    async function rewriteDraft({ button, values }) {
        try {
            const data = await withBusy(button, "Rewriting…", () => OutreachApi.request("/human/rewrite", { method: "POST", json: values }));
            replaceEmail(data.email);
            render();
            OutreachApi.toast(`Rewritten: spam score ${Number(data.previous_score).toFixed(1)} → ${Number(data.deliverability_risk.score).toFixed(1)}`, "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    }

    async function saveDraft({ button, values }) {
        try {
            const data = await withBusy(button, "Saving…", () => OutreachApi.request("/human/save-draft", { method: "POST", json: values }));
            replaceEmail(data.email);
            render();
            OutreachApi.toast("Draft saved and re-scored.", "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    }

    $("filterChips").addEventListener("click", event => {
        const button = event.target.closest("button[data-filter]");
        if (!button) return;
        view.filter = button.dataset.filter;
        render();
    });
    $("campaignFilter").addEventListener("change", event => { view.campaign = event.target.value; render(); });
    $("searchInput").addEventListener("input", event => { view.query = event.target.value.trim().toLowerCase(); render(); });
    $("refreshReviewBtn").addEventListener("click", loadReview);

    $("downloadRejectedBtn").addEventListener("click", async () => {
        try {
            const response = await fetch("/human/rejected-csv", { headers: { Authorization: `Bearer ${OutreachApi.getToken()}` } });
            if (!response.ok) throw new Error("Could not download the rejected CSV");
            const url = URL.createObjectURL(await response.blob());
            const link = Object.assign(document.createElement("a"), { href: url, download: "rejected_by_human.csv" });
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    loadReview();
})();
