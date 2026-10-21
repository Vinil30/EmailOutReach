(async () => {
    // Admins start the first data requests alongside the sidebar's user check, not after it.
    if (OutreachApi.getUser()?.is_admin) {
        OutreachApi.cachedGet("/api/admin/stats");
        OutreachApi.cachedGet("/api/admin/users?q=");
    }
    const firstLoad = { stats: true, users: true };
    const user = await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    if (!user.is_admin) {
        document.querySelector(".main").innerHTML = `<div class="empty"><strong>Admins only</strong><span>This page is for the Mailzen team.</span><a class="btn primary" href="/dashboard">Back home</a></div>`;
        return;
    }

    const PAGE = 50;
    let leadSkip = 0;

    // ---- Tabs ----
    $("tabs").addEventListener("click", event => {
        const button = event.target.closest("button[data-tab]");
        if (!button) return;
        $("tabs").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        document.querySelectorAll("[data-pane]").forEach(pane => { pane.hidden = pane.dataset.pane !== button.dataset.tab; });
        if (button.dataset.tab === "leads") loadLeads();
    });

    async function loadStats() {
        const stats = await OutreachApi.cachedGet("/api/admin/stats", { fresh: !firstLoad.stats });
        firstLoad.stats = false;
        $("stats").innerHTML = [
            ["Users", stats.users],
            ["Premium now", stats.premium_active],
            ["Active contacts", stats.leads_active],
            ["Emails this week", stats.sent_week],
            ["Automations running", stats.automations_running]
        ].map(([label, value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
    }

    // ---- Users ----
    async function loadUsers() {
        const data = await OutreachApi.cachedGet(`/api/admin/users?q=${encodeURIComponent($("userSearch").value.trim())}`, { fresh: !firstLoad.users });
        firstLoad.users = false;
        $("userRows").innerHTML = data.users.length ? data.users.map(row => `
            <tr data-email="${esc(row.email)}">
                <td><div class="cell-main">${esc(row.name || row.email)}</div><div class="cell-sub">${esc(row.email)} · ${row.role === "campaigner" ? "Campaigns" : "Job seeker"}${row.gmail_connected ? "" : " · no Gmail"}</div></td>
                <td>${row.is_premium ? `<span class="badge ok">Premium</span><div class="cell-sub">until ${esc(OutreachApi.formatDate(row.premium_until))}</div>` : row.premium_until ? `<span class="badge plain">Expired</span><div class="cell-sub">${esc(OutreachApi.formatDate(row.premium_until))}</div>` : '<span class="badge plain">General</span>'}</td>
                <td class="right">${row.sent_total}</td>
                <td class="right">${row.sent_week}</td>
                <td class="right">${row.db_sent}</td>
                <td>${row.automation === "idle" ? '<span class="muted">—</span>' : `<span class="badge ${row.automation === "running" ? "ok live" : "plain"}">${esc(row.automation)}</span>`}</td>
                <td class="right nowrap">
                    <button class="btn secondary sm" data-action="extend">+30 days</button>
                    ${row.is_premium ? '<button class="btn ghost sm" data-action="revoke">Revoke</button>' : ""}
                </td>
            </tr>`).join("") : `<tr><td colspan="7"><div class="empty" style="border:0;"><strong>No users found</strong></div></td></tr>`;
        $("grantLog").innerHTML = data.grants.length
            ? `<dl class="kv">${data.grants.map(grant => `<dt>${OutreachApi.timeAgo(grant.created_at)}</dt><dd>${grant.revoked ? "Revoked" : `+${grant.days} days`} · <b>${esc(grant.email)}</b>${grant.pending ? " · waiting for signup" : ""}${grant.note ? ` · ${esc(grant.note)}` : ""} <span class="muted">by ${esc(grant.granted_by || "")}</span></dd>`).join("")}</dl>`
            : `<p class="small muted">No changes yet.</p>`;
    }

    async function grant(email, days, note = "") {
        const result = await OutreachApi.request("/api/admin/premium", { method: "POST", json: { email, days, note } });
        OutreachApi.toast(`${email} is Premium until ${OutreachApi.formatDate(result.premium_until)}${result.account_exists ? "" : " (applies when they sign up)"}.`, "ok");
        await Promise.all([loadUsers(), loadStats()]);
    }

    $("grantForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.target;
        const days = parseInt(form.elements.days.value, 10) || 30;
        try {
            await grant(form.elements.email.value.trim(), days, form.elements.note.value.trim());
            form.reset();
            form.elements.days.value = "30";
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    $("userRows").addEventListener("click", async event => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const email = button.closest("tr").dataset.email;
        button.disabled = true;
        try {
            if (button.dataset.action === "extend") {
                await grant(email, 30);
            } else if (confirm(`Revoke Premium for ${email}? Any running automation stops at its next check.`)) {
                await OutreachApi.request("/api/admin/premium/revoke", { method: "POST", json: { email } });
                OutreachApi.toast(`Premium revoked for ${email}.`, "ok");
                await Promise.all([loadUsers(), loadStats()]);
            }
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
        button.disabled = false;
    });

    let userTimer;
    $("userSearch").addEventListener("input", () => { clearTimeout(userTimer); userTimer = setTimeout(loadUsers, 300); });

    // ---- Contact database ----
    async function loadLeads() {
        const q = encodeURIComponent($("leadSearch").value.trim());
        const data = await OutreachApi.request(`/api/admin/leads?q=${q}&skip=${leadSkip}&limit=${PAGE}`);
        $("leadTotal").textContent = `· ${data.total} total, ${data.active} active`;
        $("leadRows").innerHTML = data.leads.length ? data.leads.map(lead => `
            <tr data-id="${lead.id}">
                <td><div class="cell-main">${esc(lead.name || "—")}</div><div class="cell-sub">${esc(lead.email)}</div></td>
                <td>${esc(lead.company || "—")}</td>
                <td class="cell-sub">${esc(lead.role || "")}</td>
                <td class="right">${lead.times_used} user${lead.times_used === 1 ? "" : "s"}</td>
                <td><label class="toggle"><input type="checkbox" data-action="active" ${lead.active ? "checked" : ""}></label></td>
                <td class="right"><button class="btn ghost sm" data-action="delete">Delete</button></td>
            </tr>`).join("") : `<tr><td colspan="6"><div class="empty" style="border:0;"><strong>No contacts yet</strong><span>Add one above or import a file.</span></div></td></tr>`;
        $("pageInfo").textContent = data.total ? `${leadSkip + 1}–${Math.min(leadSkip + PAGE, data.total)} of ${data.total}` : "";
        $("prevPage").disabled = leadSkip === 0;
        $("nextPage").disabled = leadSkip + PAGE >= data.total;
    }

    $("leadForm").addEventListener("submit", async event => {
        event.preventDefault();
        const form = event.target;
        const payload = Object.fromEntries(["email", "name", "company", "role", "details"].map(key => [key, form.elements[key].value.trim()]));
        try {
            await OutreachApi.request("/api/admin/leads", { method: "POST", json: payload });
            OutreachApi.toast("Contact added.", "ok");
            form.reset();
            await Promise.all([loadLeads(), loadStats()]);
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    $("importFile").addEventListener("change", () => { $("importName").textContent = $("importFile").files[0]?.name || ""; });
    $("importBtn").addEventListener("click", async () => {
        const form = new FormData();
        if ($("importFile").files[0]) form.append("file", $("importFile").files[0]);
        else if ($("importText").value.trim()) form.append("contacts_text", $("importText").value);
        else return OutreachApi.setStatus($("importStatus"), "Choose a file or paste rows.", "error");
        OutreachApi.setStatus($("importStatus"), "Importing…");
        try {
            const result = await OutreachApi.request("/api/admin/leads/import", { method: "POST", body: form });
            OutreachApi.setStatus($("importStatus"), `Added ${result.added}. ${result.duplicates} already existed${result.invalid ? `, ${result.invalid} invalid emails skipped` : ""}.`, "ok");
            $("importText").value = "";
            $("importFile").value = "";
            $("importName").textContent = "";
            await Promise.all([loadLeads(), loadStats()]);
        } catch (error) {
            OutreachApi.setStatus($("importStatus"), error.message, "error");
        }
    });

    $("leadRows").addEventListener("change", async event => {
        const input = event.target.closest('input[data-action="active"]');
        if (!input) return;
        try {
            await OutreachApi.request(`/api/admin/leads/${input.closest("tr").dataset.id}`, { method: "PATCH", json: { active: input.checked } });
            loadStats();
        } catch (error) {
            input.checked = !input.checked;
            OutreachApi.toast(error.message, "error");
        }
    });
    $("leadRows").addEventListener("click", async event => {
        const button = event.target.closest('button[data-action="delete"]');
        if (!button || !confirm("Delete this contact from the database?")) return;
        try {
            await OutreachApi.request(`/api/admin/leads/${button.closest("tr").dataset.id}`, { method: "DELETE" });
            await Promise.all([loadLeads(), loadStats()]);
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    let leadTimer;
    $("leadSearch").addEventListener("input", () => { clearTimeout(leadTimer); leadTimer = setTimeout(() => { leadSkip = 0; loadLeads(); }, 300); });
    $("prevPage").addEventListener("click", () => { leadSkip = Math.max(0, leadSkip - PAGE); loadLeads(); });
    $("nextPage").addEventListener("click", () => { leadSkip += PAGE; loadLeads(); });

    loadStats().catch(error => OutreachApi.toast(error.message, "error"));
    loadUsers().catch(error => OutreachApi.toast(error.message, "error"));
})();
