(async () => {
    const PAGE = 20;
    const params = new URLSearchParams(window.location.search);
    const FILTERS = ["all", "ready", "flagged", "failed"];
    const view = { filter: FILTERS.includes(params.get("filter")) ? params.get("filter") : "all", campaign: params.get("campaign") || "", query: "" };
    const pageUrl = skip => {
        const query = new URLSearchParams({ filter: view.filter, skip, limit: PAGE });
        if (view.campaign) query.set("campaign_id", view.campaign);
        if (view.query) query.set("q", view.query);
        return `/human/waiting-emails?${query}`;
    };
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet(pageUrl(0));
    OutreachApi.cachedGet("/api/campaigns");
    const user = await Layout.init();
    const $ = id => document.getElementById(id);
    const reviewStatus = $("reviewStatus");
    const reviewList = $("reviewList");
    let emails = [];
    let total = 0;
    let counts = { all: 0, ready: 0, flagged: 0, failed: 0 };
    let loading = false;
    let generation = 0;
    let loadedOnce = false;

    const actions = () => ({ send: sendDraft, reject: rejectDraft, save: saveDraft, ...(user.is_premium ? { rewrite: rewriteDraft } : {}) });

    function renderChips() {
        document.querySelectorAll("#filterChips button").forEach(button => {
            button.classList.toggle("active", button.dataset.filter === view.filter);
            button.innerHTML = `${button.dataset.filter[0].toUpperCase()}${button.dataset.filter.slice(1)}<span class="n">${counts[button.dataset.filter] ?? 0}</span>`;
        });
    }

    function renderStatus() {
        OutreachApi.setStatus(reviewStatus, total ? `Showing ${emails.length} of ${total} drafts.` : "");
        $("reviewMore").hidden = emails.length >= total;
    }

    // Re-renders the drafts already loaded (after a save, rewrite or send changes one).
    function render() {
        renderChips();
        reviewList.innerHTML = "";
        if (!emails.length) {
            reviewList.innerHTML = counts.all || view.query || view.campaign
                ? `<div class="empty"><strong>Nothing matches this filter</strong><span>Try another filter or campaign.</span></div>`
                : `<div class="empty"><strong>Your queue is clear</strong><span>Drafts from “Review first” campaigns, and anything the spam guard holds back, show up here.</span><a class="btn primary" href="/campaigns/new">Start a campaign</a></div>`;
        } else {
            emails.forEach(email => reviewList.appendChild(renderEmailCard(email, actions())));
        }
        renderStatus();
    }

    // Loads the next page of drafts; reset starts over after a filter, campaign or search change.
    async function loadPage({ reset = false } = {}) {
        if (loading && !reset) return;
        const mine = reset ? ++generation : generation;
        if (reset) {
            emails = [];
            reviewList.innerHTML = `<div class="card card-pad"><div class="skeleton"></div></div>`;
        }
        loading = true;
        $("reviewMoreBtn").disabled = true;
        try {
            const data = await OutreachApi.cachedGet(pageUrl(emails.length), { fresh: loadedOnce });
            loadedOnce = true;
            if (mine !== generation) return;
            const first = !emails.length;
            emails = emails.concat(data.emails);
            total = data.total;
            counts = data.counts;
            if (first) {
                render();
            } else {
                data.emails.forEach(email => reviewList.appendChild(renderEmailCard(email, actions())));
                renderChips();
                renderStatus();
            }
        } catch (error) {
            OutreachApi.setStatus(reviewStatus, error.message, "error");
        } finally {
            if (mine === generation) loading = false;
            $("reviewMoreBtn").disabled = false;
        }
    }

    async function loadCampaigns() {
        const campaigns = await OutreachApi.cachedGet("/api/campaigns").catch(() => ({ campaigns: [] }));
        const select = $("campaignFilter");
        select.innerHTML = `<option value="">All campaigns</option>` + campaigns.campaigns
            .filter(campaign => campaign.counts?.waiting)
            .map(campaign => `<option value="${campaign.id}">${OutreachApi.escapeHtml(campaign.name)} (${campaign.counts.waiting})</option>`).join("");
        select.value = view.campaign;
    }

    function replaceEmail(updated) {
        emails = emails.map(email => (email.id === updated.id ? updated : email));
    }

    function dropEmail(id, card) {
        emails = emails.filter(email => email.id !== id);
        total = Math.max(0, total - 1);
        counts.all = Math.max(0, counts.all - 1);
        if (view.filter !== "all") counts[view.filter] = Math.max(0, counts[view.filter] - 1);
        card.style.transition = "opacity .2s, transform .2s";
        card.style.opacity = "0";
        card.style.transform = "translateX(12px)";
        setTimeout(() => {
            card.remove();
            renderChips();
            renderStatus();
            if (emails.length) return;
            if (total) loadPage();
            else render();
        }, 200);
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
        if (!button || button.dataset.filter === view.filter) return;
        view.filter = button.dataset.filter;
        renderChips();
        loadPage({ reset: true });
    });
    $("campaignFilter").addEventListener("change", event => { view.campaign = event.target.value; loadPage({ reset: true }); });
    let searchTimer;
    $("searchInput").addEventListener("input", event => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { view.query = event.target.value.trim(); loadPage({ reset: true }); }, 350);
    });
    $("refreshReviewBtn").addEventListener("click", () => loadPage({ reset: true }));
    $("reviewMoreBtn").addEventListener("click", () => loadPage());
    // The next drafts load by themselves as the bottom of the queue scrolls into view.
    new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting) && !$("reviewMore").hidden) loadPage();
    }, { rootMargin: "400px" }).observe($("reviewMore"));

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

    renderChips();
    loadCampaigns();
    loadPage();
})();
