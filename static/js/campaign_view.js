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
        const writing = campaign.writing_mode === "template" ? "Template" : "AI-written";
        const canResume = ["interrupted", "cancelled", "failed", "quota"].includes(campaign.status) && (campaign.processed || 0) < (campaign.total || 0);
        const errors = (campaign.errors || []).slice(-3);
        return `
            <div class="campaign-row" data-id="${campaign.id}">
                <div class="campaign-row-head">
                    <div style="min-width:0;">
                        <div class="cell-main">${esc(campaign.name)}</div>
                        <div class="cell-sub">${writing} · ${campaign.total} contacts · ${OutreachApi.timeAgo(campaign.created_at)}</div>
                    </div>
                    <div class="actions">
                        <div class="segmented mini" role="group" aria-label="How this list sends">
                            <button type="button" data-mode="review" class="${campaign.mode === "auto" ? "" : "active"}" title="Drafts wait in Review for you to send">Review first</button>
                            <button type="button" data-mode="auto" class="${campaign.mode === "auto" ? "active" : ""}" title="Emails that pass the spam check send automatically">Auto-send</button>
                        </div>
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

        let fresh = false;
        let lists = [];

        async function load() {
            try {
                // The first load can reuse a request the page already started; polling always refetches.
                const data = await OutreachApi.cachedGet("/api/campaigns", { fresh });
                fresh = true;
                const list = data.campaigns.slice(0, limit);
                lists = list;
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

        async function switchMode(button) {
            const row = button.closest(".campaign-row");
            const campaign = lists.find(item => item.id === row.dataset.id);
            const mode = button.dataset.mode;
            if (!campaign || button.classList.contains("active")) return;
            const remaining = Math.max(0, (campaign.total || 0) - (campaign.processed || 0));
            const counts = campaign.counts || {};
            const ready = Math.max(0, (counts.waiting || 0) - (counts.flagged || 0) - (counts.failed || 0));
            const message = mode === "auto"
                ? `Switch “${campaign.name}” to auto-send?

${remaining} contact${remaining === 1 ? "" : "s"} not processed yet and ${ready} ready draft${ready === 1 ? "" : "s"} from this list will be sent automatically, 1–3 minutes apart. Flagged drafts stay in Review for you to fix.`
                : `Switch “${campaign.name}” to review first?

${remaining
                    ? `The ${remaining} remaining contact${remaining === 1 ? "" : "s"} will become drafts in Review instead of being sent.`
                    : "Nothing more will be sent automatically from this list. Its drafts stay in Review for you to send."}`;
            if (!confirm(message)) return;
            row.querySelectorAll("[data-mode]").forEach(node => { node.disabled = true; });
            try {
                const result = await OutreachApi.request(`/api/campaigns/${campaign.id}/mode`, { method: "POST", json: { mode } });
                OutreachApi.toast(mode === "auto"
                    ? (result.started ? "Auto-send is on. Sending now, 1–3 minutes apart." : campaign.status === "cancelled" && (remaining || ready) ? "Auto-send is on. Press Resume to continue." : "Auto-send is on.")
                    : "Review first is on. New drafts will wait in Review.", "ok");
                setTimeout(load, 400);
            } catch (error) {
                OutreachApi.toast(error.message, "error");
                if (/Upgrade/.test(error.message)) OutreachApi.openUpgrade();
                row.querySelectorAll("[data-mode]").forEach(node => { node.disabled = false; });
            }
        }

        container.addEventListener("click", async event => {
            const modeButton = event.target.closest("button[data-mode]");
            if (modeButton) return switchMode(modeButton);
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
