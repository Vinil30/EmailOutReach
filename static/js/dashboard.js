(async () => {
    // Start this page's data requests alongside the sidebar's user check, not after it.
    ["/api/plan", "/api/campaigns/stats", "/api/profile", "/api/campaigns"].forEach(path => OutreachApi.cachedGet(path));
    const user = await Layout.init();
    const campaigner = OutreachApi.isCampaigner(user);
    const esc = OutreachApi.escapeHtml;
    const $ = id => document.getElementById(id);
    const firstName = (user.profile?.full_name || user.name || user.email || "").split(/[\s@]/)[0];
    const hour = new Date().getHours();
    $("greeting").textContent = `${hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"}, ${firstName}`;

    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail") === "connected") {
        OutreachApi.toast("Gmail connected. You can send now.", "ok");
        history.replaceState(null, "", "/dashboard");
    }

    document.querySelectorAll("[data-icon]").forEach(node => { node.innerHTML = Layout.icon(node.dataset.icon); });

    const [plan, stats, profile] = await Promise.all([
        OutreachApi.cachedGet("/api/plan").catch(() => null),
        OutreachApi.cachedGet("/api/campaigns/stats").catch(() => null),
        OutreachApi.cachedGet("/api/profile").catch(() => null)
    ]);

    // ---- Plan ----
    if (plan) {
        const paid = plan.plan !== "free";
        const pct = Math.min(100, (plan.used / Math.max(1, plan.limit)) * 100);
        const until = OutreachApi.formatDate(plan.plan_until);
        const daysLeft = plan.plan_until ? Math.ceil((OutreachApi.parseDate(plan.plan_until) - Date.now()) / 86400000) : 0;
        const upgradeLabel = !paid ? "Upgrade" : daysLeft <= 5 ? "Renew" : plan.plan === "pro" ? "Upgrade" : "";
        const pricing = plan.pricing;
        const db = plan.database;
        $("planCard").innerHTML = `
            <div class="card-body">
                <div class="plan-row">
                    <div>
                        <span class="eyebrow">${esc(plan.plan_name)} plan</span>
                        <div class="plan-title">${paid ? `Unlimited emails · ${plan.remaining} left today` : `${plan.remaining} email${plan.remaining === 1 ? "" : "s"} left`}</div>
                        <p class="small muted" style="margin-top:4px;">
                            ${paid
                                ? `${plan.used} of ${plan.limit} sent today (daily safety cap) · ${db.remaining} of ${db.limit} recruiters left · ${esc(plan.plan_name)} until ${esc(until)}`
                                : `${plan.used} of ${plan.limit} lifetime emails used${plan.plan_expired ? ` · ${esc(plan.expired_plan_name)} ended` : ""}`}
                        </p>
                    </div>
                    <div class="actions">
                        ${paid ? `<a class="btn primary" href="/automate">Open automation</a>` : ""}
                        ${upgradeLabel ? `<button type="button" class="btn ${paid ? "secondary" : "primary"}" data-upgrade>${upgradeLabel}</button>` : ""}
                    </div>
                </div>
                <div class="plan-meter-lg ${plan.remaining ? "" : "full"}"><span style="width:${pct}%"></span></div>
                ${paid
                    ? `<p class="small muted">${esc(plan.daily_cap_reason)}</p>`
                    : `<p class="small muted">Pro and Premium give you unlimited sending (up to ${pricing.daily_cap} a day) and ${pricing.pro.contacts} or ${pricing.premium.contacts} new recruiters from our database, sent automatically. After you buy, we activate it on <b>${esc(user.email)}</b>, usually within a day.</p>`}
            </div>`;
        if (!paid) $("automateGo").textContent = "Pro & Premium →";
    }

    // ---- Banners ----
    const banners = $("banners");
    if (!user.gmail_connected) {
        banners.insertAdjacentHTML("beforeend", `
            <div class="banner warn">
                <strong>Connect Gmail to send.</strong>
                <span>Emails go out from your own account, so you'll see them in your Sent folder.</span>
                <span class="spacer"></span>
                <button class="btn primary sm" id="bannerGmail">Connect Gmail</button>
            </div>`);
        $("bannerGmail").addEventListener("click", () => Layout.connectGmail().catch(error => OutreachApi.toast(error.message, "error")));
    }

    // ---- Setup checklist ----
    const p = user.profile || {};
    const projectsCount = profile?.projects?.length || 0;
    const steps = campaigner
        ? [
            ["Connect Gmail", user.gmail_connected, "#gmail"],
            ["Add your organization and offer", Boolean(p.organization && p.offer), "/profile"],
            ["Add a mailing address for the footer", Boolean(p.physical_address), "/profile"],
            ["Send your first list", Boolean(stats?.campaigns), "/campaigns/new"]
        ]
        : [
            ["Connect Gmail", user.gmail_connected, "#gmail"],
            ["Add your name and headline", Boolean(p.full_name && (p.headline || p.school)), "/profile"],
            ["Add your resume link", Boolean(p.resume_url), "/profile"],
            ["Add at least one project", projectsCount >= 1, "/profile#projects"],
            ["Choose a template", Boolean(p.template_id), "/templates"]
        ];
    const done = steps.filter(step => step[1]).length;
    $("setupProgress").textContent = `${done}/${steps.length} done`;
    $("setupList").innerHTML = steps.map(([label, ok, href]) => `
        <li class="${ok ? "pass" : "fail"}" style="${ok ? "" : "background:transparent"}">
            <span class="ico" style="${ok ? "" : "background:var(--line-strong)"}">${ok ? "✓" : ""}</span>
            <span class="what">${ok ? `<span class="muted">${esc(label)}</span>` : `<a href="${href}" data-href="${href}">${esc(label)}</a>`}</span>
            <span></span>
        </li>`).join("");
    document.querySelectorAll('#setupList a[data-href="#gmail"]').forEach(link => link.addEventListener("click", event => {
        event.preventDefault();
        Layout.connectGmail().catch(error => OutreachApi.toast(error.message, "error"));
    }));

    // ---- Activity ----
    if (stats) {
        $("activity").innerHTML = `
            <dt>Sent in total</dt><dd>${stats.sent}</dd>
            <dt>Waiting for review</dt><dd>${stats.waiting ? `<a href="/waiting-mails">${stats.waiting}</a>` : 0}</dd>
            <dt>Held by spam check</dt><dd>${stats.flagged}</dd>
            <dt>Failed sends</dt><dd>${stats.failed}</dd>`;
    }

    CampaignView.mount($("recentCampaigns"), {
        limit: 4,
        emptyHtml: `<div class="empty"><strong>No lists sent yet</strong><span>Upload contacts and pick a template to get started.</span><a class="btn primary" href="/campaigns/new">Send to my list</a></div>`
    });
})();
