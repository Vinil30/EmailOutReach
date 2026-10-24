(async () => {
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet("/api/automation");
    let fresh = false;
    const user = await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    const content = $("content");
    let data = null;
    let pollTimer = null;

    const STATUS = {
        running: ["Running", "ok live"],
        stopping: ["Stopping…", "warn"],
        stopped: ["Stopped", "plain"],
        idle: ["Not started", "plain"],
        done: ["Finished", "ok"],
        quota: ["Daily limit reached", "warn"],
        allowance: ["Recruiters used up", "warn"],
        blocked: ["Needs attention", "bad"],
        error: ["Stopped with an error", "bad"]
    };

    function locked(plan) {
        const pricing = plan.pricing;
        content.innerHTML = `
            <div class="card locked-card">
                <div class="card-body">
                    <span class="eyebrow">${plan.plan_expired ? `Your ${esc(plan.expired_plan_name)} has ended` : "Pro & Premium"}</span>
                    <h2 class="locked-title">Let us find the companies and send for you.</h2>
                    <ul class="locked-list">
                        <li><b>Unlimited emails</b>, sent automatically from your Gmail (up to ${pricing.daily_cap} a day to keep your account safe)</li>
                        <li><b>${pricing.pro.contacts}</b> (Pro) or <b>${pricing.premium.contacts}</b> (Premium) new recruiters from our database with every purchase</li>
                        <li>Templates on Pro; AI-written emails for every company on Premium</li>
                        <li>See every company you've reached; stop and resume any time</li>
                    </ul>
                    <div class="actions">
                        <button type="button" class="btn primary lg" data-upgrade>${plan.plan_expired ? "Renew" : "Upgrade"}</button>
                        <a class="btn secondary lg" href="/campaigns/new">Send to my own list instead</a>
                    </div>
                    <p class="small muted">After you buy, we activate it on <b>${esc(user.email)}</b>, within 5 hours. Make sure you buy with this email.</p>
                </div>
            </div>`;
    }

    // Why Start is unavailable right now, beyond setup problems.
    function limitNotice(quota) {
        if (!quota.database.remaining) {
            const more = quota.plan === "pro" ? " or upgrade to Premium" : "";
            return `You've emailed all ${quota.database.limit} recruiters included with ${esc(quota.plan_name)} this time. Renew${more} for a new batch of recruiters you haven't emailed. <button type="button" class="btn ghost sm" data-upgrade>${quota.plan === "pro" ? "Upgrade" : "Renew"}</button>`;
        }
        if (!quota.remaining) {
            return `You've sent today's ${quota.limit} emails. ${esc(quota.daily_cap_reason)} Start again after midnight.`;
        }
        return "";
    }

    function countdown(state) {
        if (state.status !== "running") return "";
        if (state.current) return `Writing to ${esc(state.current)}…`;
        if (state.next_send_at) {
            const seconds = state.next_send_at - Date.now() / 1000;
            if (seconds > 0) return `Next email in ${OutreachApi.duration(seconds)}`;
        }
        return "Preparing the next email…";
    }

    function render() {
        const { state, quota, problems, remaining_contacts, counts, history, template } = data;
        const [label, tone] = STATUS[state.status] || STATUS.idle;
        const running = ["running", "stopping"].includes(state.status);
        const pct = Math.min(100, (quota.used / Math.max(1, quota.limit)) * 100);
        // While running, the runner's own message explains pauses (e.g. the daily safety cap).
        const notice = running ? esc(state.message || "") : limitNotice(quota);
        content.innerHTML = `
            <div class="card auto-hero">
                <div class="card-body">
                    <div class="auto-row">
                        <div>
                            <span class="badge ${tone}">${label}</span>
                            <div class="auto-line" id="autoLine">${countdown(state) || esc(state.message || (state.status === "idle" ? "Press Start to begin sending." : ""))}</div>
                        </div>
                        <div class="actions">
                            ${running
                                ? `<button class="btn secondary lg" id="stopBtn" ${state.status === "stopping" ? "disabled" : ""}>Stop</button>`
                                : `<button class="btn primary lg" id="startBtn" ${problems.length || notice ? "disabled" : ""}>${state.status === "idle" ? "Start" : "Start again"}</button>`}
                        </div>
                    </div>
                    ${notice ? `<p class="auto-notice small">${notice}</p>` : ""}
                    ${problems.length ? `<ul class="auto-problems">${problems.map(problem => `<li>${esc(problem)} ${problem.includes("Gmail") ? '<button class="btn ghost sm" data-gmail>Connect</button>' : problem.includes("Profile") ? '<a class="btn ghost sm" href="/profile">Open profile</a>' : ""}</li>`).join("")}</ul>` : ""}
                </div>
            </div>

            <section class="stats">
                <div class="stat"><div class="label">Today</div><div class="value">${quota.used}<small class="muted" style="font-size:16px;"> / ${quota.limit}</small></div><div class="plan-meter-lg" style="margin-top:10px;"><span style="width:${pct}%"></span></div><div class="hint" title="${esc(quota.daily_cap_reason)}">daily safety cap for your Gmail</div></div>
                <div class="stat"><div class="label">Companies reached</div><div class="value">${counts.sent || 0}</div><div class="hint">from the database</div></div>
                <div class="stat"><div class="label">Recruiters left for you</div><div class="value">${remaining_contacts ?? "–"}<small class="muted" style="font-size:16px;"> / ${quota.database.limit}</small></div><div class="hint">new to you, with ${esc(quota.plan_name)}</div></div>
                <div class="stat"><div class="label">Template</div><div class="value" style="font-size:20px;margin-top:12px;">${esc(template)}</div><div class="hint"><a href="/templates">Change template</a></div></div>
            </section>

            <div class="card">
                <div class="card-head"><div><h2>Companies you've reached</h2><p>Full emails are in your Gmail Sent folder.</p></div><span class="small muted">${esc(quota.plan_name)} until ${esc(OutreachApi.formatDate(quota.plan_until))}</span></div>
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Company</th><th>Contact</th><th>Status</th><th class="right">When</th></tr></thead>
                        <tbody>${history.length ? history.map(row => `
                            <tr>
                                <td class="cell-main">${esc(row.company)}</td>
                                <td><div>${esc(row.name || "—")}</div>${row.role ? `<div class="cell-sub">${esc(row.role)}</div>` : ""}</td>
                                <td>${row.status === "sent" ? '<span class="badge ok">Sent</span>' : `<span class="badge bad" title="${esc(row.reason)}">Not delivered</span>`}</td>
                                <td class="right cell-sub nowrap">${OutreachApi.timeAgo(row.at)}</td>
                            </tr>`).join("") : `<tr><td colspan="4"><div class="empty" style="border:0;"><strong>Nothing sent yet</strong><span>Press Start and companies will appear here as emails go out.</span></div></td></tr>`}
                        </tbody>
                    </table>
                </div>
            </div>`;

        $("startBtn")?.addEventListener("click", () => act("start"));
        $("stopBtn")?.addEventListener("click", () => act("stop"));
        content.querySelectorAll("[data-gmail]").forEach(button => button.addEventListener("click", () => Layout.connectGmail().catch(error => OutreachApi.toast(error.message, "error"))));
    }

    async function act(action) {
        const button = $(`${action}Btn`);
        if (button) button.disabled = true;
        try {
            await OutreachApi.request(`/api/automation/${action}`, { method: "POST" });
            OutreachApi.toast(action === "start" ? "Automation started. You can close this page." : "Stopping after the current email.", "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
        load();
    }

    async function load() {
        try {
            data = await OutreachApi.cachedGet("/api/automation", { fresh });
            fresh = true;
        } catch (error) {
            content.innerHTML = `<div class="status error">${esc(error.message)}</div>`;
            return;
        }
        if (data.quota.plan === "free") {
            locked(data.quota);
            return;
        }
        render();
        clearTimeout(pollTimer);
        if (["running", "stopping"].includes(data.state.status)) {
            pollTimer = setTimeout(() => { load(); Layout.refreshPlan(); }, 4000);
        }
    }

    // Live countdown between polls.
    setInterval(() => {
        const line = $("autoLine");
        if (line && data?.state?.status === "running") line.innerHTML = countdown(data.state);
    }, 1000);

    load();
})();
