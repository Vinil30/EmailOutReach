(async () => {
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
                <td><div class="cell-main">${esc(email.recipient_name || email.recipient_email)}</div><div class="cell-sub">${esc(email.recipient_email)}${email.company_name ? ` · ${esc(email.company_name)}` : ""}</div></td>
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
                OutreachApi.request("/automated/sent-emails"),
                OutreachApi.request("/api/campaigns").catch(() => ({ campaigns: [] }))
            ]);
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
        $("modalTitle").textContent = email.written_email_details?.email_subject || "(no subject)";
        $("modalSub").textContent = `To ${email.recipient_email} · from ${email.email_from} · ${new Date(`${email.updated_at}Z`).toLocaleString()}`;
        $("mailModal").hidden = false;
        OutreachApi.renderEmailPreview($("modalPreview"), email.written_email_details?.email_body || "");
        $("modalRisk").innerHTML = RiskView.render(email.deliverability_risk);
    });
    const close = () => { $("mailModal").hidden = true; };
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
