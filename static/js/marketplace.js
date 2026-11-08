(async () => {
    // Start this page's data request alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet("/api/marketplace");
    const user = await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    let data = null;
    let tags = [];
    let pollTimer = null;
    let availableTimer = null;

    const STATUS = {
        running: ["Running", "ok live"], completed: ["Done", "ok"], partial: ["Partly filled", "warn"],
        failed: ["Nothing found", "plain"], interrupted: ["Interrupted", "warn"]
    };

    function money(value) {
        const amount = Number(value);
        return `${data.currency}${Number.isInteger(amount) ? amount : amount.toFixed(2)}`;
    }

    function render() {
        const prices = data.contact_credits;
        $("balance").textContent = data.credits.toLocaleString();
        // Keep the sidebar's credit count in step after a purchase or a finished search.
        document.querySelectorAll(".plan-chip-credits b").forEach(node => { node.textContent = data.credits.toLocaleString(); });
        $("priceNote").textContent = `A database contact costs ${prices.database} credits; a contact found on the web costs ${prices.web}.`;
        $("packs").innerHTML = data.packs.filter(pack => pack.credits > 0 && pack.price > 0).map(pack => `
            <button type="button" class="mk-pack" data-pack="${esc(pack.id)}" ${data.payments_enabled ? "" : "disabled"}>
                <strong>${pack.credits.toLocaleString()} credits</strong>
                <span>${esc(money(pack.price))}</span>
            </button>`).join("");
        $("paymentsNotice").hidden = data.payments_enabled;
        $("paymentsNotice").textContent = "Buying credits will open soon. Payments are being set up.";
        $("upgradeNotice").hidden = data.can_buy_contacts;
        $("ownedLink").textContent = `${data.owned.available} contacts ready to email →`;
        $("dbCount").max = data.limits.database;
        $("webCount").max = data.limits.web;
        if (!data.search_enabled) {
            $("webStartBtn").disabled = true;
            $("webQuote").innerHTML = `<span class="muted">Web search is being set up and will open soon. Database contacts are available now.</span>`;
        }
        ["dbBuyBtn", "webStartBtn"].forEach(id => { if (!data.can_buy_contacts) $(id).disabled = true; });
        renderTags();
        renderJobs();
        quoteDatabase();
        quoteWeb();
    }

    // ---- Quotes ----
    function count(id, max) {
        const value = Math.floor(Number($(id).value));
        return Number.isFinite(value) ? Math.min(Math.max(value, 1), max) : 1;
    }

    function quoteDatabase() {
        const n = count("dbCount", data.limits.database);
        $("dbQuote").innerHTML = `<b>${(n * data.contact_credits.database).toLocaleString()} credits</b> for ${n} contacts · <span id="dbAvailable" class="muted">checking availability…</span>`;
        clearTimeout(availableTimer);
        availableTimer = setTimeout(async () => {
            try {
                const result = await OutreachApi.request(`/api/marketplace/available?keywords=${encodeURIComponent($("dbKeywords").value)}`, { background: true });
                const node = $("dbAvailable");
                if (node) node.textContent = `${result.available.toLocaleString()} new contacts match right now${result.available < n ? " (you're charged only for what's delivered)" : ""}`;
            } catch {
                /* the quote still works without the count */
            }
        }, 300);
    }

    function quoteWeb() {
        if (!data.search_enabled) return;
        const n = count("webCount", data.limits.web);
        const most = n * data.contact_credits.web;
        $("webQuote").innerHTML = `Up to <b>${most.toLocaleString()} credits</b> for ${n} contacts. Matches already in our database cost ${data.contact_credits.database}; anything not found is refunded.`;
    }

    // ---- Tags ----
    function renderTags() {
        $("tagList").innerHTML = tags.length
            ? tags.map((tag, i) => `<span class="mk-tag">${esc(tag)}<button type="button" data-remove="${i}" aria-label="Remove ${esc(tag)}">×</button></span>`).join("")
            : `<span class="small muted">Add at least one tag, e.g. the role you want and where.</span>`;
    }

    function addTag() {
        const value = $("tagInput").value.trim().replace(/\s+/g, " ").slice(0, 60);
        if (value.length < 2 || tags.length >= 10 || tags.some(tag => tag.toLowerCase() === value.toLowerCase())) return;
        tags.push(value);
        $("tagInput").value = "";
        renderTags();
        saveTags();
    }

    let saveTimer;
    function saveTags() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => OutreachApi.request("/api/marketplace/tags", { method: "PUT", json: { tags }, background: true }).catch(() => {}), 500);
    }

    $("tagAddBtn").addEventListener("click", addTag);
    $("tagInput").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); addTag(); } });
    $("tagList").addEventListener("click", event => {
        const button = event.target.closest("[data-remove]");
        if (!button) return;
        tags.splice(Number(button.dataset.remove), 1);
        renderTags();
        saveTags();
    });

    // ---- Purchases ----
    function renderJobs() {
        const jobs = data.jobs || [];
        $("jobs").innerHTML = jobs.length ? `<div class="table-wrap"><table>
            <thead><tr><th>Purchase</th><th>Status</th><th class="right">Contacts</th><th class="right">Charged</th><th class="right">Refunded</th><th class="right">When</th></tr></thead>
            <tbody>${jobs.map(job => {
                const [label, tone] = STATUS[job.status] || [job.status, "plain"];
                const what = job.type === "web" ? `Web search${job.tags?.length ? `: ${esc(job.tags.slice(0, 3).join(", "))}${job.tags.length > 3 ? "…" : ""}` : ""}` : `Database${job.tags?.length ? `: ${esc(job.tags.join(", "))}` : ""}`;
                return `<tr>
                    <td><div class="cell-main">${what}</div>${job.message ? `<div class="cell-sub">${esc(job.message)}</div>` : ""}</td>
                    <td><span class="badge ${tone}">${label}</span></td>
                    <td class="right">${job.delivered} / ${job.target}${job.type === "web" && job.delivered ? `<div class="cell-sub">${job.from_database} database · ${job.from_web} web</div>` : ""}</td>
                    <td class="right">${job.status === "running" ? `<span class="muted">${job.reserved} held</span>` : job.spent}</td>
                    <td class="right">${job.refunded || "—"}</td>
                    <td class="right cell-sub nowrap">${OutreachApi.timeAgo(job.created_at)}</td>
                </tr>`;
            }).join("")}</tbody></table></div>`
            : `<div class="empty" style="border:0;"><strong>No purchases yet</strong><span>Buy credits above, then get contacts from the database or the web.</span></div>`;
        clearTimeout(pollTimer);
        if (jobs.some(job => job.status === "running")) pollTimer = setTimeout(() => load({ quiet: true }), 4000);
    }

    async function loadLedger() {
        try {
            const result = await OutreachApi.request("/api/credits/ledger", { background: true });
            $("ledger").innerHTML = result.entries.length ? `<dl class="kv">${result.entries.map(entry => `
                <dt>${OutreachApi.timeAgo(entry.created_at)}</dt>
                <dd><b class="${entry.delta > 0 ? "mk-plus" : "mk-minus"}">${entry.delta > 0 ? "+" : ""}${entry.delta}</b> · ${esc(entry.note || entry.kind)}${entry.balance_after !== undefined ? ` <span class="muted">→ ${entry.balance_after}</span>` : ""}</dd>`).join("")}</dl>`
                : `<p class="small muted">No credit activity yet.</p>`;
        } catch (error) {
            $("ledger").innerHTML = `<div class="status error">${esc(error.message)}</div>`;
        }
    }
    $("ledgerBox").addEventListener("toggle", () => { if ($("ledgerBox").open) loadLedger(); });

    async function load({ quiet = false } = {}) {
        try {
            data = await OutreachApi.cachedGet("/api/marketplace", { fresh: Boolean(data), background: quiet });
            if (!tags.length) tags = [...(data.tags || [])];
            render();
            if (quiet) Layout.refreshPlan();
        } catch (error) {
            $("packs").innerHTML = `<div class="status error">${esc(error.message)}</div>`;
        }
    }

    // ---- Buying ----
    $("dbKeywords").addEventListener("input", quoteDatabase);
    $("dbCount").addEventListener("input", quoteDatabase);
    $("webCount").addEventListener("input", quoteWeb);

    $("dbForm").addEventListener("submit", async event => {
        event.preventDefault();
        const n = count("dbCount", data.limits.database);
        const cost = n * data.contact_credits.database;
        if (cost > data.credits) return OutreachApi.toast(`That needs ${cost} credits; you have ${data.credits}. Buy a credit pack first.`, "error");
        if (!confirm(`Get up to ${n} contacts for up to ${cost} credits? You're only charged for contacts delivered.`)) return;
        try {
            const keywords = $("dbKeywords").value.split(",").map(word => word.trim()).filter(Boolean);
            const result = await OutreachApi.request("/api/marketplace/database", { method: "POST", json: { count: n, keywords } });
            OutreachApi.toast(result.message, result.added ? "ok" : "error");
            await load();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
            if (/Upgrade/.test(error.message)) OutreachApi.openUpgrade();
        }
    });

    $("webForm").addEventListener("submit", async event => {
        event.preventDefault();
        if (!tags.length) return OutreachApi.toast("Add at least one search tag.", "error");
        const n = count("webCount", data.limits.web);
        const most = n * data.contact_credits.web;
        if (most > data.credits) return OutreachApi.toast(`A search for ${n} contacts holds up to ${most} credits; you have ${data.credits}. Buy a credit pack or ask for fewer.`, "error");
        if (!confirm(`Search the web for ${n} contacts? Up to ${most} credits are held now and anything not used comes back when the search ends.`)) return;
        try {
            await OutreachApi.request("/api/marketplace/search", { method: "POST", json: { tags, count: n } });
            OutreachApi.toast("Searching. You can leave this page; results appear under Your purchases.", "ok");
            await load();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
            if (/Upgrade/.test(error.message)) OutreachApi.openUpgrade();
        }
    });

    // Razorpay Checkout loads only when someone actually buys.
    function loadCheckout() {
        if (window.Razorpay) return Promise.resolve();
        return new Promise((resolve, reject) => {
            const script = Object.assign(document.createElement("script"), { src: "https://checkout.razorpay.com/v1/checkout.js", onload: resolve, onerror: () => reject(new Error("Couldn't load the payment window. Check your connection.")) });
            document.head.appendChild(script);
        });
    }

    $("packs").addEventListener("click", async event => {
        const button = event.target.closest("[data-pack]");
        if (!button || button.disabled) return;
        try {
            const [order] = await Promise.all([
                OutreachApi.request("/api/credits/orders", { method: "POST", json: { pack_id: button.dataset.pack } }),
                loadCheckout()
            ]);
            const checkout = new window.Razorpay({
                key: order.key_id,
                order_id: order.order_id,
                amount: order.amount,
                currency: order.currency,
                name: "Mailzen",
                description: `${order.credits} credits`,
                prefill: { email: order.email, name: order.name },
                theme: { color: "#141414" },
                handler: async response => {
                    try {
                        const result = await OutreachApi.request("/api/credits/verify", { method: "POST", json: response });
                        OutreachApi.toast(`Payment received. You now have ${result.credits} credits.`, "ok");
                    } catch (error) {
                        // The webhook still adds the credits if this check couldn't finish.
                        OutreachApi.toast(`${error.message} If you were charged, your credits will appear shortly.`, "error");
                    }
                    load();
                }
            });
            checkout.on("payment.failed", response => OutreachApi.toast(response.error?.description || "Payment failed. You weren't charged.", "error"));
            checkout.open();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    load();
})();
