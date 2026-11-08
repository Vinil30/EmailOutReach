(async () => {
    const PAGE = 50;
    const view = { campaign: new URLSearchParams(window.location.search).get("campaign") || "", query: "" };
    const pageUrl = skip => {
        const params = new URLSearchParams({ skip, limit: PAGE });
        if (view.campaign) params.set("campaign_id", view.campaign);
        if (view.query) params.set("q", view.query);
        return `/automated/sent-emails?${params}`;
    };
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet(pageUrl(0));
    OutreachApi.cachedGet("/api/campaigns");
    await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    let emails = [];
    let total = 0;
    let loading = false;
    let generation = 0;

    function scoreBadge(risk) {
        if (risk?.score === undefined) return `<span class="badge plain">n/a</span>`;
        const tone = risk.level === "HIGH" ? "bad" : risk.level === "MEDIUM" ? "warn" : "ok";
        return `<span class="badge ${tone}">${Number(risk.score).toFixed(1)}</span>`;
    }

    function rowHtml(email, index) {
        return `
            <tr class="clickable" data-index="${index}">
                <td><div class="cell-main">${esc(email.recipient_name || email.recipient_email)}</div><div class="cell-sub">${esc(email.recipient_email || (email.from_database ? "Marketplace contact" : ""))}${email.company_name ? ` · ${esc(email.company_name)}` : ""}${email.bounced ? ' · <span class="badge bad">Bounced</span>' : ""}</div></td>
                <td style="max-width:320px;"><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(email.written_email_details?.email_subject || "")}</div></td>
                <td class="cell-sub">${esc(email.campaign_name || "—")}</td>
                <td>${scoreBadge(email.deliverability_risk)}</td>
                <td class="cell-sub">${email.email_response?.attempt || 1}</td>
                <td class="right cell-sub nowrap" title="${esc(email.updated_at || "")}">${OutreachApi.timeAgo(email.sent_at || email.updated_at || email.created_at)}</td>
            </tr>`;
    }

    function renderStatus() {
        OutreachApi.setStatus($("sentStatus"), total ? `Showing ${emails.length} of ${total}` : "");
        $("sentMore").hidden = emails.length >= total;
    }

    // Loads the next page; reset starts over (after a filter or search change).
    async function loadPage({ reset = false } = {}) {
        if (loading && !reset) return;
        const mine = reset ? ++generation : generation;
        if (reset) {
            emails = [];
            total = 0;
            $("sentList").innerHTML = `<tr><td colspan="6"><div class="skeleton"></div></td></tr>`;
        }
        loading = true;
        $("sentMoreBtn").disabled = true;
        try {
            const data = await OutreachApi.cachedGet(pageUrl(emails.length), { fresh: emails.length > 0 || reset });
            if (mine !== generation) return;
            const start = emails.length;
            emails = emails.concat(data.emails);
            total = data.total;
            if (!start) {
                $("sentList").innerHTML = data.emails.length
                    ? data.emails.map((email, i) => rowHtml(email, i)).join("")
                    : `<tr><td colspan="6"><div class="empty" style="border:0;"><strong>No sent emails${view.query || view.campaign ? " match" : " yet"}</strong><span>Approved drafts and auto-sent emails are logged here.</span></div></td></tr>`;
            } else {
                $("sentList").insertAdjacentHTML("beforeend", data.emails.map((email, i) => rowHtml(email, start + i)).join(""));
            }
            renderStatus();
        } catch (error) {
            OutreachApi.setStatus($("sentStatus"), error.message, "error");
        } finally {
            if (mine === generation) loading = false;
            $("sentMoreBtn").disabled = false;
        }
    }

    async function loadCampaigns() {
        const campaigns = await OutreachApi.cachedGet("/api/campaigns").catch(() => ({ campaigns: [] }));
        $("campaignFilter").innerHTML = `<option value="">All campaigns</option>` + campaigns.campaigns
            .filter(campaign => campaign.counts?.sent)
            .map(campaign => `<option value="${campaign.id}">${esc(campaign.name)} (${campaign.counts.sent})</option>`).join("");
        $("campaignFilter").value = view.campaign;
    }

    // Opening an email shows the row's details at once, then fetches the full message and spam report.
    $("sentList").addEventListener("click", async event => {
        const row = event.target.closest("tr[data-index]");
        if (!row) return;
        const summary = emails[Number(row.dataset.index)];
        renderModal(summary);
        $("modalPreview").innerHTML = `<div class="skeleton"></div>`;
        $("modalRisk").innerHTML = `<div class="skeleton"></div>`;
        $("mailModal").hidden = false;
        document.body.style.overflow = "hidden";
        try {
            const email = await OutreachApi.request(`/automated/sent-emails/${summary.id}`);
            if ($("mailModal").hidden || $("mailModal").dataset.id !== summary.id) return;
            renderModal(email);
            OutreachApi.renderEmailPreview($("modalPreview"), email.written_email_details?.email_body || "", 360);
            const risk = email.deliverability_risk;
            // A 0.0 score is a real result: it means every check passed when the email went out.
            $("modalRisk").innerHTML = risk?.checks
                ? RiskView.render(risk)
                : `${RiskView.render(risk)}<p class="small muted" style="margin-top:12px;">This email was sent before detailed check results were recorded, so only its score is available.</p>`;
        } catch (error) {
            $("modalPreview").innerHTML = `<div class="status error">${esc(error.message)}</div>`;
            $("modalRisk").innerHTML = "";
        }
    });

    function renderModal(email) {
        const sentAt = OutreachApi.parseDate(email.sent_at || email.updated_at);
        const attempts = email.email_response?.attempt || 1;
        $("mailModal").dataset.id = email.id;
        $("modalTitle").textContent = email.written_email_details?.email_subject || "(no subject)";
        $("modalMeta").innerHTML = `
            <div><dt>To</dt><dd><b>${esc(email.recipient_name || email.recipient_email)}</b>${email.from_database ? "<span>Marketplace contact (address kept private)</span>" : email.recipient_name ? `<span>${esc(email.recipient_email)}</span>` : ""}</dd></div>
            <div><dt>Company</dt><dd>${esc(email.company_name || "—")}</dd></div>
            <div><dt>From</dt><dd>${esc(email.email_from || "—")}</dd></div>
            <div><dt>Sent</dt><dd>${sentAt ? esc(sentAt.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })) : "—"}</dd></div>
            <div><dt>List</dt><dd>${esc(email.campaign_name || "—")}</dd></div>
            <div><dt>Delivery</dt><dd>${email.bounced ? '<span class="badge bad">Bounced</span>' : attempts === 1 ? "First attempt" : `${attempts} attempts`}</dd></div>`;
        $("bounceBtn").hidden = Boolean(email.bounced);
    }

    const close = () => { $("mailModal").hidden = true; document.body.style.overflow = ""; };
    $("closeModal").addEventListener("click", close);
    $("mailModal").addEventListener("click", event => { if (event.target.id === "mailModal") close(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });

    // "Mark as bounced": Gmail's "Address not found" reply only reaches the user's inbox, so they tell us.
    $("bounceBtn").addEventListener("click", async () => {
        const id = $("mailModal").dataset.id;
        if (!confirm("Mark this email as bounced (\"Address not found\")?\n\nMailzen won't send to this address again, from any account.")) return;
        try {
            await OutreachApi.request(`/automated/sent-emails/${id}/bounced`, { method: "POST" });
            const email = emails.find(item => item.id === id);
            if (email) email.bounced = true;
            $("bounceBtn").hidden = true;
            OutreachApi.toast("Marked as bounced. This address won't be emailed again.", "ok");
            const row = $("sentList").querySelector(`tr[data-index="${emails.indexOf(email)}"]`);
            if (row && email) row.outerHTML = rowHtml(email, emails.indexOf(email));
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    let searchTimer;
    $("campaignFilter").addEventListener("change", event => { view.campaign = event.target.value; loadPage({ reset: true }); });
    $("searchInput").addEventListener("input", event => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { view.query = event.target.value.trim(); loadPage({ reset: true }); }, 350);
    });
    $("refreshSentBtn").addEventListener("click", () => loadPage({ reset: true }));
    $("sentMoreBtn").addEventListener("click", () => loadPage());
    // The next page loads by itself as the bottom of the list scrolls into view.
    new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting) && !$("sentMore").hidden) loadPage();
    }, { rootMargin: "300px" }).observe($("sentMore"));

    $("exportBtn").addEventListener("click", async () => {
        const params = new URLSearchParams();
        if (view.campaign) params.set("campaign_id", view.campaign);
        if (view.query) params.set("q", view.query);
        try {
            const response = await fetch(`/automated/sent-export.csv?${params}`, { headers: { Authorization: `Bearer ${OutreachApi.getToken()}` } });
            if (!response.ok) throw new Error("Export failed");
            const url = URL.createObjectURL(await response.blob());
            Object.assign(document.createElement("a"), { href: url, download: "sent_emails.csv" }).click();
            URL.revokeObjectURL(url);
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    loadCampaigns();
    loadPage();
})();
