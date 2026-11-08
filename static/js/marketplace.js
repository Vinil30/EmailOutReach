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
        const credits = data.credits;
        $("balanceWorth").textContent = credits
            ? `Enough for ${Math.floor(credits / prices.database).toLocaleString()} database or ${Math.floor(credits / prices.web).toLocaleString()} web contacts`
            : "Top up to start getting contacts";
        $("dbRate").innerHTML = `<b>${prices.database}</b> credits each`;
        $("webRate").innerHTML = `<b>${prices.web}</b> credits each`;
        $("priceNote").textContent = data.payments_enabled
            ? "Secure checkout by Razorpay · UPI, cards and netbanking · credits never expire"
            : "Payments are being set up. Credit packs will open here soon.";
        const packs = data.packs.filter(pack => pack.credits > 0 && pack.price > 0);
        const rate = pack => pack.price / pack.credits;
        const best = packs.length > 1 ? packs.reduce((a, b) => (rate(b) < rate(a) ? b : a)) : null;
        $("packs").innerHTML = packs.map((pack, i) => {
            const tag = best && pack.id === best.id ? "Best value" : packs.length > 2 && i === 1 ? "Popular" : "";
            const saving = rate(pack) < rate(packs[0]) ? Math.round((1 - rate(pack) / rate(packs[0])) * 100) : 0;
            return `<button type="button" class="mk-pack${tag === "Best value" ? " best" : ""}" data-pack="${esc(pack.id)}" ${data.payments_enabled ? "" : "disabled"}>
                ${tag ? `<em>${tag}</em>` : ""}
                <strong>${pack.credits.toLocaleString()}</strong>
                <span class="mk-pack-unit">credits</span>
                <span class="mk-pack-price">${esc(money(pack.price))}</span>
                <span class="mk-pack-note">${saving ? `Save ${saving}%` : `${esc(money(rate(pack).toFixed(2)))} per credit`}</span>
            </button>`;
        }).join("");
        $("paymentsNotice").hidden = data.payments_enabled;
        $("upgradeNotice").hidden = data.can_buy_contacts;
        const ready = data.owned.available || 0;
        $("ownedLink").innerHTML = ready
            ? `<b>${ready.toLocaleString()}</b> contact${ready === 1 ? "" : "s"} ready to email <span aria-hidden="true">→</span>`
            : `<b>0</b> contacts ready to email`;
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
        syncChips("dbCount");
        $("dbQuote").innerHTML = quoteHtml("Total", n * data.contact_credits.database, `<span id="dbAvailable">Checking how many match…</span>`);
        clearTimeout(availableTimer);
        availableTimer = setTimeout(async () => {
            try {
                const result = await OutreachApi.request(`/api/marketplace/available?keywords=${encodeURIComponent($("dbKeywords").value)}`, { background: true });
                const node = $("dbAvailable");
                if (node) node.textContent = result.available >= n
                    ? `${result.available.toLocaleString()} new contacts match right now`
                    : `Only ${result.available.toLocaleString()} match right now; you're charged just for those`;
            } catch {
                /* the quote still works without the count */
            }
        }, 300);
    }

    function quoteWeb() {
        syncChips("webCount");
        if (!data.search_enabled) return;
        const n = count("webCount", data.limits.web);
        $("webQuote").innerHTML = quoteHtml("Up to", n * data.contact_credits.web,
            `Matches already in our database cost ${data.contact_credits.database}; anything not found comes back to you.`);
    }

    function quoteHtml(label, total, note) {
        const short = total > data.credits;
        return `<div class="mk-total"><span>${label}</span><b>${total.toLocaleString()} <small>credits</small></b></div>
            <div class="mk-quote-note">${note}</div>
            ${short ? `<div class="mk-quote-warn">You have ${data.credits.toLocaleString()} credits. Top up or ask for fewer.</div>` : ""}`;
    }

    // Quick-pick counts under each "How many contacts" field.
    function syncChips(id) {
        const value = String(Math.floor(Number($(id).value)));
        document.querySelectorAll(`.mk-chips[data-for="${id}"] button`).forEach(button => button.classList.toggle("active", button.dataset.n === value));
    }
    document.querySelectorAll(".mk-chips").forEach(group => group.addEventListener("click", event => {
        const button = event.target.closest("[data-n]");
        if (!button) return;
        $(group.dataset.for).value = button.dataset.n;
        $(group.dataset.for).dispatchEvent(new Event("input"));
    }));

    // ---- Tags ----
    function renderTags() {
        $("tagList").innerHTML = tags.length
            ? tags.map((tag, i) => `<span class="mk-tag">${esc(tag)}<button type="button" data-remove="${i}" aria-label="Remove ${esc(tag)}">×</button></span>`).join("")
            : `<span class="mk-tags-empty">Add at least one tag, e.g. the role you want and where.</span>`;
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
        $("jobs").innerHTML = jobs.length ? `<div class="mk-jobs">${jobs.map(job => {
                const [label, tone] = STATUS[job.status] || [job.status, "plain"];
                const web = job.type === "web";
                const topic = job.tags?.length ? `${esc(job.tags.slice(0, 3).join(", "))}${job.tags.length > 3 ? "…" : ""}` : web ? "" : "Any role";
                const pct = Math.round((job.delivered / Math.max(1, job.target)) * 100);
                const cost = job.status === "running"
                    ? `<span>${job.reserved} credits held</span>`
                    : `<span>${job.spent} charged</span>${job.refunded ? `<span class="mk-plus">${job.refunded} refunded</span>` : ""}`;
                return `<article class="mk-job">
                    <span class="mk-job-icon ${web ? "web" : ""}" aria-hidden="true">${web ? "W" : "D"}</span>
                    <div class="mk-job-main">
                        <div class="mk-job-top"><b>${web ? "Web search" : "Database"}</b>${topic ? `<span class="mk-job-topic">${topic}</span>` : ""}<span class="badge ${tone}">${label}</span></div>
                        ${job.message ? `<div class="mk-job-msg">${esc(job.message)}</div>` : ""}
                        <div class="mk-progress ${job.status === "running" ? "live" : ""}"><span style="width:${pct}%"></span></div>
                        <div class="mk-job-meta"><span><b>${job.delivered}</b> of ${job.target} contacts${web && job.delivered ? ` · ${job.from_database} database, ${job.from_web} web` : ""}</span>${cost}<span>${OutreachApi.timeAgo(job.created_at)}</span></div>
                    </div>
                </article>`;
            }).join("")}</div>`
            : `<div class="empty mk-empty"><strong>No purchases yet</strong><span>Top up credits, then get contacts from the database or the web.</span></div>`;
        clearTimeout(pollTimer);
        if (jobs.some(job => job.status === "running")) pollTimer = setTimeout(() => load({ quiet: true }), 4000);
    }

    async function loadLedger() {
        try {
            const result = await OutreachApi.request("/api/credits/ledger", { background: true });
            $("ledger").innerHTML = result.entries.length ? `<ul class="mk-ledger-list">${result.entries.map(entry => `
                <li>
                    <span class="mk-amount ${entry.delta > 0 ? "plus" : "minus"}">${entry.delta > 0 ? "+" : "−"}${Math.abs(entry.delta).toLocaleString()}</span>
                    <span class="mk-ledger-note">${esc(entry.note || entry.kind)}</span>
                    <span class="mk-ledger-meta">${entry.balance_after !== undefined ? `Balance ${Number(entry.balance_after).toLocaleString()} · ` : ""}${OutreachApi.timeAgo(entry.created_at)}</span>
                </li>`).join("")}</ul>`
                : `<div class="card-body"><p class="small muted">No credit activity yet.</p></div>`;
        } catch (error) {
            $("ledger").innerHTML = `<div class="card-body"><div class="status error">${esc(error.message)}</div></div>`;
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
