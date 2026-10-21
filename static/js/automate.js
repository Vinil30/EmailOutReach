(async () => {
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
        quota: ["Weekly limit reached", "warn"],
        blocked: ["Needs attention", "bad"],
        error: ["Stopped with an error", "bad"]
    };

    function locked(plan) {
        content.innerHTML = `
            <div class="card locked-card">
                <div class="card-body">
                    <span class="eyebrow">${plan?.premium_expired ? "Your Premium has ended" : "Premium feature"}</span>
                    <h2 class="locked-title">Let us find the companies and send for you.</h2>
                    <ul class="locked-list">
                        <li><b>100 emails every week</b>, sent automatically from your Gmail</li>
                        <li>Contacts from our curated recruiter and company database</li>
                        <li>See every company you've reached; stop and resume any time</li>
                        <li>30 days of access per purchase</li>
                    </ul>
                    <div class="actions">
                        <a class="btn primary lg" href="${esc(plan?.premium_url || "#")}" target="_blank" rel="noopener">${plan?.premium_expired ? "Renew Premium" : "Buy Premium"}</a>
                        <a class="btn secondary lg" href="/campaigns/new">Send to my own list instead</a>
                    </div>
                    <p class="small muted">After you buy, we activate Premium on <b>${esc(user.email)}</b>, usually within a day. Make sure you buy with this email.</p>
                </div>
            </div>`;
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
                                : `<button class="btn primary lg" id="startBtn" ${problems.length || !quota.remaining ? "disabled" : ""}>${state.status === "idle" ? "Start" : "Start again"}</button>`}
                        </div>
                    </div>
                    ${problems.length ? `<ul class="auto-problems">${problems.map(problem => `<li>${esc(problem)} ${problem.includes("Gmail") ? '<button class="btn ghost sm" data-gmail>Connect</button>' : problem.includes("Profile") ? '<a class="btn ghost sm" href="/profile">Open profile</a>' : ""}</li>`).join("")}</ul>` : ""}
                </div>
            </div>

            <section class="stats">
                <div class="stat"><div class="label">This week</div><div class="value">${quota.used}<small class="muted" style="font-size:16px;"> / ${quota.limit}</small></div><div class="plan-meter-lg" style="margin-top:10px;"><span style="width:${pct}%"></span></div></div>
                <div class="stat"><div class="label">Companies reached</div><div class="value">${counts.sent || 0}</div><div class="hint">from the database</div></div>
                <div class="stat"><div class="label">Contacts left for you</div><div class="value">${remaining_contacts ?? "–"}</div><div class="hint">not emailed yet</div></div>
                <div class="stat"><div class="label">Template</div><div class="value" style="font-size:20px;margin-top:12px;">${esc(template)}</div><div class="hint"><a href="/templates">Change template</a></div></div>
            </section>

            <div class="card">
                <div class="card-head"><div><h2>Companies you've reached</h2><p>Full emails are in your Gmail Sent folder.</p></div><span class="small muted">Premium until ${esc(OutreachApi.formatDate(quota.premium_until))}</span></div>
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
            data = await OutreachApi.request("/api/automation");
        } catch (error) {
            content.innerHTML = `<div class="status error">${esc(error.message)}</div>`;
            return;
        }
        if (data.quota.plan !== "premium") {
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
