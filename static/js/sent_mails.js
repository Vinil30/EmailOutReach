(async () => {
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet("/automated/sent-emails");
    OutreachApi.cachedGet("/api/campaigns");
    let fresh = false;
    await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    const view = { campaign: new URLSearchParams(window.location.search).get("campaign") || "", query: "" };
    let emails = [];

    function visible() {
        return emails.filter(email => {
            if (view.campaign && email.campaign_id !== view.campaign) return false;
            const haystack = [email.recipient_name, email.recipient_email, email.company_name, email.written_email_details?.email_subject].join(" ").toLowerCase();
            return !view.query || haystack.includes(view.query);
        });
    }

    function scoreBadge(risk) {
        if (risk?.score === undefined) return `<span class="badge plain">n/a</span>`;
        const tone = risk.level === "HIGH" ? "bad" : risk.level === "MEDIUM" ? "warn" : "ok";
        return `<span class="badge ${tone}">${Number(risk.score).toFixed(1)}</span>`;
    }

    function render() {
        const rows = visible();
        $("sentList").innerHTML = rows.length ? rows.map((email, index) => `
            <tr class="clickable" data-index="${emails.indexOf(email)}">
                <td><div class="cell-main">${esc(email.recipient_name || email.recipient_email)}</div><div class="cell-sub">${esc(email.recipient_email || (email.from_database ? "Mailzen recruiter database" : ""))}${email.company_name ? ` · ${esc(email.company_name)}` : ""}</div></td>
                <td style="max-width:320px;"><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(email.written_email_details?.email_subject || "")}</div></td>
                <td class="cell-sub">${esc(email.campaign_name || "—")}</td>
                <td>${scoreBadge(email.deliverability_risk)}</td>
                <td class="cell-sub">${email.email_response?.attempt || 1}</td>
                <td class="right cell-sub nowrap" title="${esc(email.updated_at || "")}">${OutreachApi.timeAgo(email.updated_at || email.created_at)}</td>
            </tr>`).join("") : `<tr><td colspan="6"><div class="empty" style="border:0;"><strong>No sent emails${emails.length ? " match" : " yet"}</strong><span>Approved drafts and auto-sent emails are logged here.</span></div></td></tr>`;
        OutreachApi.setStatus($("sentStatus"), `${rows.length} email${rows.length === 1 ? "" : "s"}`);
    }

    async function load() {
        OutreachApi.setStatus($("sentStatus"), "Loading…");
        try {
            const [data, campaigns] = await Promise.all([
                OutreachApi.cachedGet("/automated/sent-emails", { fresh }),
                OutreachApi.cachedGet("/api/campaigns", { fresh }).catch(() => ({ campaigns: [] }))
            ]);
            fresh = true;
            emails = data.emails;
            $("campaignFilter").innerHTML = `<option value="">All campaigns</option>` + campaigns.campaigns
                .filter(campaign => campaign.counts?.sent)
                .map(campaign => `<option value="${campaign.id}">${esc(campaign.name)} (${campaign.counts.sent})</option>`).join("");
            $("campaignFilter").value = view.campaign;
            render();
        } catch (error) {
            OutreachApi.setStatus($("sentStatus"), error.message, "error");
        }
    }

    $("sentList").addEventListener("click", event => {
        const row = event.target.closest("tr[data-index]");
        if (!row) return;
        const email = emails[Number(row.dataset.index)];
        const risk = email.deliverability_risk;
        const sentAt = OutreachApi.parseDate(email.sent_at || email.updated_at);
        const attempts = email.email_response?.attempt || 1;
        $("modalTitle").textContent = email.written_email_details?.email_subject || "(no subject)";
        $("modalMeta").innerHTML = `
            <div><dt>To</dt><dd><b>${esc(email.recipient_name || email.recipient_email)}</b>${email.from_database ? "<span>From our recruiter database (address kept private)</span>" : email.recipient_name ? `<span>${esc(email.recipient_email)}</span>` : ""}</dd></div>
            <div><dt>Company</dt><dd>${esc(email.company_name || "—")}</dd></div>
            <div><dt>From</dt><dd>${esc(email.email_from || "—")}</dd></div>
            <div><dt>Sent</dt><dd>${sentAt ? esc(sentAt.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })) : "—"}</dd></div>
            <div><dt>List</dt><dd>${esc(email.campaign_name || "—")}</dd></div>
            <div><dt>Delivery</dt><dd>${attempts === 1 ? "First attempt" : `${attempts} attempts`}</dd></div>`;
        $("mailModal").hidden = false;
        document.body.style.overflow = "hidden";
        OutreachApi.renderEmailPreview($("modalPreview"), email.written_email_details?.email_body || "", 360);
        // A 0.0 score is a real result: it means every check passed when the email went out.
        $("modalRisk").innerHTML = risk?.checks
            ? RiskView.render(risk)
            : `${RiskView.render(risk)}<p class="small muted" style="margin-top:12px;">This email was sent before detailed check results were recorded, so only its score is available.</p>`;
    });
    const close = () => { $("mailModal").hidden = true; document.body.style.overflow = ""; };
    $("closeModal").addEventListener("click", close);
    $("mailModal").addEventListener("click", event => { if (event.target.id === "mailModal") close(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });

    $("campaignFilter").addEventListener("change", event => { view.campaign = event.target.value; render(); });
    $("searchInput").addEventListener("input", event => { view.query = event.target.value.trim().toLowerCase(); render(); });
    $("refreshSentBtn").addEventListener("click", load);
    $("exportBtn").addEventListener("click", () => {
        const quote = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
        const lines = [["sent_at", "recipient_name", "recipient_email", "company", "subject", "campaign", "spam_score"].join(",")]
            .concat(visible().map(email => [email.updated_at, email.recipient_name, email.recipient_email, email.company_name, email.written_email_details?.email_subject, email.campaign_name, email.deliverability_risk?.score].map(quote).join(",")));
        const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
        const link = Object.assign(document.createElement("a"), { href: url, download: "sent_emails.csv" });
        link.click();
        URL.revokeObjectURL(url);
    });

    load();
})();
