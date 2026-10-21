// Campaign list rendering + live polling, shared by the overview and campaigns pages.
const CampaignView = (() => {
    const esc = OutreachApi.escapeHtml;

    function segments(campaign) {
        const total = Math.max(1, campaign.total || 0);
        const counts = campaign.counts || {};
        const waitingClean = Math.max(0, (counts.waiting || 0) - (counts.flagged || 0) - (counts.failed || 0));
        const part = (n, cls) => n ? `<span class="${cls}" style="width:${(n / total) * 100}%"></span>` : "";
        return `<div class="progress split">${part(counts.sent, "seg-sent")}${part(waitingClean, "seg-wait")}${part(counts.flagged, "seg-flag")}${part(counts.failed, "seg-fail")}</div>`;
    }

    function eta(campaign) {
        if (campaign.status !== "running") return "";
        if (campaign.next_send_at) {
            const seconds = campaign.next_send_at - Date.now() / 1000;
            if (seconds > 0) return `next contact in ${OutreachApi.duration(seconds)}`;
        }
        return campaign.current_contact ? `writing for ${esc(campaign.current_contact)}` : "starting…";
    }

    function row(campaign, { detailed = false } = {}) {
        const counts = campaign.counts || {};
        const modeLabel = campaign.mode === "auto" ? "Auto-send" : "Review first";
        const writing = campaign.writing_mode === "template" ? "Template" : "AI-written";
        const canResume = ["interrupted", "cancelled", "failed"].includes(campaign.status) && (campaign.processed || 0) < (campaign.total || 0);
        const errors = (campaign.errors || []).slice(-3);
        return `
            <div class="campaign-row" data-id="${campaign.id}">
                <div class="campaign-row-head">
                    <div style="min-width:0;">
                        <div class="cell-main">${esc(campaign.name)}</div>
                        <div class="cell-sub">${modeLabel} · ${writing} · ${campaign.total} contacts · ${OutreachApi.timeAgo(campaign.created_at)}</div>
                    </div>
                    <div class="actions">
                        ${OutreachApi.statusBadge(campaign.status)}
                        ${campaign.status === "running" || campaign.status === "queued" ? `<button class="btn ghost sm" data-action="cancel">Stop</button>` : ""}
                        ${canResume ? `<button class="btn secondary sm" data-action="resume">Resume</button>` : ""}
                    </div>
                </div>
                ${segments(campaign)}
                <div class="campaign-row-head small">
                    <div class="legend">
                        <span><i style="background:var(--ok)"></i>${counts.sent || 0} sent</span>
                        <span><i style="background:var(--brand-2)"></i>${Math.max(0, (counts.waiting || 0) - (counts.flagged || 0) - (counts.failed || 0))} to review</span>
                        <span><i style="background:var(--warn)"></i>${counts.flagged || 0} flagged</span>
                        <span><i style="background:var(--bad)"></i>${counts.failed || 0} failed</span>
                        <span class="muted">${campaign.processed || 0}/${campaign.total} processed ${eta(campaign) ? `· ${eta(campaign)}` : ""}</span>
                    </div>
                    <div class="actions">
                        ${counts.waiting ? `<a class="btn ghost sm" href="/waiting-mails?campaign=${campaign.id}">Review ${counts.waiting}</a>` : ""}
                        ${counts.sent ? `<a class="btn ghost sm" href="/sent-mails?campaign=${campaign.id}">Sent log</a>` : ""}
                    </div>
                </div>
                ${detailed && (campaign.skipped || []).length ? `<div class="small muted">Skipped ${campaign.skipped.length} contacts: ${campaign.skipped.slice(0, 4).map(item => `${esc(item.email)} (${esc(item.reason)})`).join(", ")}${campaign.skipped.length > 4 ? "…" : ""}</div>` : ""}
                ${errors.length ? `<div class="small" style="color:var(--bad)">${errors.map(item => `${esc(item.email || "campaign")}: ${esc(item.reason)}`).join("<br>")}</div>` : ""}
            </div>`;
    }

    function mount(container, { limit = 50, detailed = false, emptyHtml = "" } = {}) {
        let timer = null;

        async function load() {
            try {
                const data = await OutreachApi.request("/api/campaigns");
                const list = data.campaigns.slice(0, limit);
                container.innerHTML = list.length
                    ? list.map(campaign => row(campaign, { detailed })).join("")
                    : emptyHtml;
                const active = list.some(campaign => ["running", "queued"].includes(campaign.status));
                clearTimeout(timer);
                if (active) {
                    timer = setTimeout(() => { load(); Layout.refreshReviewCount(); }, 3000);
                }
            } catch (error) {
                container.innerHTML = `<div class="status error">${esc(error.message)}</div>`;
            }
        }

        container.addEventListener("click", async event => {
            const button = event.target.closest("button[data-action]");
            if (!button) return;
            const id = button.closest(".campaign-row").dataset.id;
            button.disabled = true;
            try {
                await OutreachApi.request(`/api/campaigns/${id}/${button.dataset.action}`, { method: "POST" });
                OutreachApi.toast(button.dataset.action === "cancel" ? "Stopping after the current contact." : "Campaign resumed.", "ok");
                setTimeout(load, 600);
            } catch (error) {
                OutreachApi.toast(error.message, "error");
                button.disabled = false;
            }
        });

        load();
        return { reload: load };
    }

    return { mount, row };
})();
