const OutreachApi = (() => {
    function getToken() {
        return localStorage.getItem("outreachToken") || "";
    }

    function getUser() {
        try {
            return JSON.parse(localStorage.getItem("outreachUser") || "null");
        } catch {
            return null;
        }
    }

    function setUser(user) {
        localStorage.setItem("outreachUser", JSON.stringify(user));
    }

    function saveSession(data) {
        localStorage.setItem("outreachToken", data.access_token);
        setUser(data.user);
    }

    function clearSession() {
        localStorage.removeItem("outreachToken");
        localStorage.removeItem("outreachUser");
    }

    function requireAuth() {
        const token = getToken();
        if (!token) {
            const next = `${window.location.pathname}${window.location.search}`;
            window.location.replace(`/login?next=${encodeURIComponent(next)}`);
            return "";
        }
        return token;
    }

    function redirectIfLoggedIn() {
        if (getToken()) {
            window.location.replace("/dashboard");
        }
    }

    function logout() {
        clearSession();
        window.location.replace("/login");
    }

    function bindLogout() {
        const button = document.getElementById("logoutBtn");
        if (button) {
            button.addEventListener("click", logout);
        }
    }

    function setStatus(node, message, type = "") {
        if (!node) return;
        node.textContent = message;
        node.className = `status ${type}`.trim();
    }

    function toast(message, type = "") {
        let host = document.getElementById("toasts");
        if (!host) {
            host = document.createElement("div");
            host.id = "toasts";
            document.body.appendChild(host);
        }
        const node = document.createElement("div");
        node.className = `toast ${type}`.trim();
        node.textContent = message;
        host.appendChild(node);
        setTimeout(() => node.remove(), type === "error" ? 6500 : 4000);
    }

    async function request(path, options = {}) {
        const headers = options.headers || {};
        const token = getToken();
        if (token) {
            headers.Authorization = `Bearer ${token}`;
        }
        let body = options.body;
        if (options.json !== undefined) {
            headers["Content-Type"] = "application/json";
            body = JSON.stringify(options.json);
        }
        const response = await fetch(path, { ...options, body, headers });
        const text = await response.text();
        let data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch {
            data = { detail: text };
        }
        if (!response.ok) {
            if (response.status === 401 && token) {
                clearSession();
                const next = `${window.location.pathname}${window.location.search}`;
                window.location.replace(`/login?next=${encodeURIComponent(next)}`);
            }
            const detail = Array.isArray(data.detail)
                ? data.detail.map(item => item.msg).join("; ")
                : data.detail;
            throw new Error(detail || "Request failed");
        }
        return data;
    }

    // Shares one in-flight GET per path, so a page can start its data requests before the
    // sidebar's user check finishes and duplicate requests (plan, stats) hit the server once.
    const getCache = new Map();
    function cachedGet(path, { fresh = false } = {}) {
        if (fresh || !getCache.has(path)) {
            const pending = request(path);
            getCache.set(path, pending);
            pending.catch(() => { if (getCache.get(path) === pending) getCache.delete(path); });
        }
        return getCache.get(path);
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function escapeAttr(value) {
        return escapeHtml(value).replaceAll("\n", " ");
    }

    // The API returns UTC timestamps, sometimes without an offset.
    function parseDate(value) {
        if (!value) return null;
        return new Date(value.endsWith?.("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
    }

    function formatDate(value) {
        const date = parseDate(value);
        return date ? date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
    }

    function timeAgo(value) {
        if (!value) return "";
        const date = parseDate(value);
        const seconds = Math.round((Date.now() - date.getTime()) / 1000);
        if (seconds < 45) return "just now";
        const units = [["y", 31536000], ["mo", 2592000], ["d", 86400], ["h", 3600], ["m", 60]];
        for (const [label, size] of units) {
            if (seconds >= size) return `${Math.floor(seconds / size)}${label} ago`;
        }
        return "just now";
    }

    function duration(seconds) {
        seconds = Math.max(0, Math.round(seconds || 0));
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ${seconds % 60 ? `${seconds % 60}s` : ""}`.trim();
        return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    }

    // One vocabulary for every outreach_status the backend can store.
    const STATUS = {
        SEND: ["Ready to send", "ok"],
        REVIEW_REQUIRED: ["Needs review", "info"],
        REVIEW_APPROVED: ["Approved", "info"],
        REGENERATE: ["Flagged by spam guard", "warn"],
        SENDING: ["Sending", "info"],
        SENT: ["Sent", "ok"],
        FAILED_PERMANENT: ["Send failed", "bad"],
        FAILED_TRANSIENT: ["Send failed (retryable)", "bad"],
        FAILED: ["Send failed", "bad"],
        DUPLICATE_SUPPRESSED: ["Duplicate suppressed", "warn"],
        QUOTA_REACHED: ["Plan limit reached", "warn"],
        quota: ["Stopped: plan limit", "warn"],
        queued: ["Queued", "info"],
        running: ["Running", "info live"],
        completed: ["Completed", "ok"],
        cancelled: ["Cancelled", "plain"],
        interrupted: ["Interrupted", "warn"],
        failed: ["Failed", "bad"]
    };

    function statusBadge(state) {
        const [label, tone] = STATUS[state] || [state || "Unknown", "plain"];
        return `<span class="badge ${tone}">${escapeHtml(label)}</span>`;
    }

    // Email HTML comes from LLMs and imported lists, so it renders in a script-less sandbox.
    function renderEmailPreview(container, html, minHeight = 160) {
        let frame = container.querySelector("iframe");
        if (!frame) {
            frame = document.createElement("iframe");
            frame.setAttribute("sandbox", "allow-same-origin");
            frame.setAttribute("title", "Email preview");
            frame.style.cssText = `width:100%;border:0;display:block;min-height:${minHeight}px;background:#fff;`;
            container.innerHTML = "";
            container.appendChild(frame);
            frame.addEventListener("load", () => {
                const doc = frame.contentDocument;
                if (doc?.body) frame.style.height = `${Math.max(minHeight, doc.documentElement.scrollHeight)}px`;
            });
        }
        frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><base target="_blank"><style>body{margin:0;font:14px/1.6 -apple-system,Segoe UI,Inter,Arial,sans-serif;color:#1f2328;background:#fff}p{margin:0 0 10px}ul{margin:0 0 10px;padding-left:20px}a{color:#2f5bd9}</style></head><body>${html || ""}</body></html>`;
    }

    const THEME_ICONS = '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

    function currentTheme() {
        return document.documentElement.dataset.theme === "light" ? "light" : "dark";
    }

    function setTheme(theme) {
        if (theme === "light") document.documentElement.dataset.theme = "light";
        else delete document.documentElement.dataset.theme;
        try { localStorage.setItem("odTheme", theme); } catch {}
        document.querySelectorAll("[data-theme-toggle]").forEach(syncToggle);
        window.dispatchEvent(new CustomEvent("themechange", { detail: theme }));
    }

    function syncToggle(button) {
        const label = currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode";
        button.setAttribute("aria-label", label);
        button.title = label;
        const text = button.querySelector("[data-theme-label]");
        if (text) text.textContent = currentTheme() === "dark" ? "Light mode" : "Dark mode";
    }

    // Any element with data-theme-toggle becomes a theme switch.
    function bindThemeToggles(root = document) {
        root.querySelectorAll("[data-theme-toggle]").forEach(button => {
            if (button.dataset.bound) return;
            button.dataset.bound = "1";
            if (!button.innerHTML.trim()) button.innerHTML = THEME_ICONS;
            else button.insertAdjacentHTML("afterbegin", THEME_ICONS);
            syncToggle(button);
            button.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
        });
    }

    function isCampaigner(user = getUser()) {
        return user?.role === "campaigner";
    }

    // Legal documents an account signs, matching utils/legal.py.
    function legalDocuments(role) {
        return [
            { title: "Privacy Policy", url: "/privacy" },
            role === "campaigner"
                ? { title: "Terms for Campaigns & Businesses", url: "/terms/campaigners" }
                : { title: "Terms for Students & Job Seekers", url: "/terms/students" }
        ];
    }

    function loadSignatureFont() {
        if (document.getElementById("signatureFont")) return;
        const link = document.createElement("link");
        link.id = "signatureFont";
        link.rel = "stylesheet";
        link.href = "https://fonts.googleapis.com/css2?family=Caveat:wght@500&display=swap";
        document.head.appendChild(link);
    }

    // Typed-name signature block: document links, a live signature preview and the agreement box.
    function signatureBlock(role, name = "") {
        loadSignatureFont();
        const docs = legalDocuments(role);
        return `
            <div class="sign-docs" data-sign-docs>${docs.map(doc => `<a href="${doc.url}" target="_blank" rel="noopener">${escapeHtml(doc.title)}<span>Read ↗</span></a>`).join("")}</div>
            <label class="field"><span>Type your full name to sign</span><input data-signature type="text" autocomplete="name" maxlength="120" value="${escapeAttr(name)}" placeholder="e.g. Ananya Rao"></label>
            <div class="sign-pad" aria-hidden="true"><output data-signature-preview>${escapeHtml(name)}</output></div>
            <label class="sign-check"><input type="checkbox" data-agree><span>I have read and agree to the ${docs.map(doc => `<a href="${doc.url}" target="_blank" rel="noopener">${escapeHtml(doc.title)}</a>`).join(" and the ")}, and I sign them electronically with the name above.</span></label>`;
    }

    function bindSignature(root) {
        const input = root.querySelector("[data-signature]");
        const preview = root.querySelector("[data-signature-preview]");
        input.addEventListener("input", () => { preview.textContent = input.value; input.dataset.touched = "1"; });
        return {
            setRole(role) {
                const docs = legalDocuments(role);
                root.querySelectorAll("[data-sign-docs] a").forEach((link, i) => { link.href = docs[i].url; link.firstChild.textContent = docs[i].title; });
                root.querySelectorAll(".sign-check a").forEach((link, i) => { link.href = docs[i].url; link.textContent = docs[i].title; });
            },
            // Mirrors another name field until the user edits the signature directly.
            follow(value) {
                if (input.dataset.touched) return;
                input.value = value;
                preview.textContent = value;
            },
            value() {
                const signature = input.value.trim().replace(/\s+/g, " ");
                if (signature.length < 3) throw new Error("Type your full name to sign");
                if (!root.querySelector("[data-agree]").checked) throw new Error("Tick the box to agree to the Terms and Privacy Policy");
                return signature;
            }
        };
    }

    // ---- Plans: live prices/limits (admin-editable) and the upgrade card ----
    const PLAN_NAMES = { free: "Free", pro: "Pro", premium: "Premium" };

    function getPricing() {
        return cachedGet("/api/pricing");
    }

    function forgetPricing() {
        getCache.delete("/api/pricing");
    }

    function formatPrice(pricing, value) {
        const amount = Number(value);
        return `${pricing.currency}${Number.isInteger(amount) ? amount : amount.toFixed(2)}`;
    }

    // Fills [data-price="pro"], [data-contacts="premium"], [data-free-emails], [data-daily-cap] and [data-plan-days].
    async function applyPricing(root = document) {
        if (!root.querySelector("[data-price], [data-contacts], [data-free-emails], [data-daily-cap], [data-plan-days]")) return null;
        const pricing = await getPricing();
        root.querySelectorAll("[data-price]").forEach(node => { node.textContent = formatPrice(pricing, pricing[node.dataset.price].price); });
        root.querySelectorAll("[data-contacts]").forEach(node => { node.textContent = pricing[node.dataset.contacts].contacts; });
        root.querySelectorAll("[data-free-emails]").forEach(node => { node.textContent = pricing.free_emails; });
        root.querySelectorAll("[data-daily-cap]").forEach(node => { node.textContent = pricing.daily_cap; });
        root.querySelectorAll("[data-plan-days]").forEach(node => { node.textContent = pricing.days; });
        return pricing;
    }

    function planFeatures(pricing) {
        const cap = `Unlimited emails, up to ${pricing.daily_cap} a day*`;
        return {
            free: [`${pricing.free_emails} emails in total`, "Send to your own contact lists", "Ready-made templates", "Spam check before every send", "Sends from your own Gmail"],
            pro: [cap, `${pricing.pro.contacts} new recruiters from our database per purchase`, "One-click automation: press Start, it sends", "Ready-made templates with names filled in", "Every company you reach, tracked"],
            premium: [cap, `${pricing.premium.contacts} new recruiters from our database per purchase`, "One-click automation: press Start, it sends", "AI researches each company and writes a unique email", "AI picks your best-matching project", "AI fixes risky drafts before they send"]
        };
    }

    function closeUpgrade() {
        document.getElementById("upgradeCard")?.remove();
        document.removeEventListener("keydown", upgradeEscape);
    }

    function upgradeEscape(event) {
        if (event.key === "Escape") closeUpgrade();
    }

    // The plans card that every "Upgrade" control opens, pinned to the top of the screen.
    async function openUpgrade() {
        if (document.getElementById("upgradeCard")) return;
        let pricing;
        try {
            pricing = await getPricing();
        } catch (error) {
            toast(error.message, "error");
            return;
        }
        const user = getUser();
        const current = user ? (user.plan || "free") : null;
        const features = planFeatures(pricing);
        const tier = id => {
            const paid = id !== "free";
            const isCurrent = current === id;
            const action = !paid
                ? (user ? "" : `<a class="btn secondary block" href="/login?mode=signup">Start free</a>`)
                : `<a class="btn ${id === "premium" ? "primary" : "secondary"} block" href="${escapeAttr(pricing[id].url)}" target="_blank" rel="noopener">${isCurrent ? `Renew ${PLAN_NAMES[id]}` : `Get ${PLAN_NAMES[id]}`}</a>`;
            return `
                <div class="upgrade-tier ${id === "premium" ? "featured" : ""} ${isCurrent ? "current" : ""}">
                    <div class="upgrade-tier-head">
                        <strong>${PLAN_NAMES[id]}</strong>
                        ${isCurrent ? '<span class="badge plain">Your plan</span>' : id === "premium" ? '<span class="badge accent plain">Most complete</span>' : ""}
                    </div>
                    <div class="upgrade-price">${paid ? `${formatPrice(pricing, pricing[id].price)}<small> / ${pricing.days} days</small>` : `${pricing.currency}0<small> forever</small>`}</div>
                    <ul>${features[id].map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
                    ${action}
                </div>`;
        };
        const backdrop = document.createElement("div");
        backdrop.className = "modal-backdrop upgrade-backdrop";
        backdrop.id = "upgradeCard";
        backdrop.innerHTML = `
            <div class="modal card upgrade-card" role="dialog" aria-modal="true" aria-labelledby="upgradeTitle">
                <div class="card-head">
                    <div><span class="eyebrow">Upgrade</span><h3 id="upgradeTitle">Pick the plan that fits your job hunt</h3><p>Any paid plan gives unlimited sending. Plans differ in how many recruiters we provide and whether AI writes your emails.</p></div>
                    <button type="button" class="btn ghost sm" data-upgrade-close aria-label="Close">Close</button>
                </div>
                <div class="card-body">
                    <div class="upgrade-tiers">${tier("free")}${tier("pro")}${tier("premium")}</div>
                    <p class="small muted upgrade-note">*Sending is capped at ${pricing.daily_cap} emails a day because Google may suspend Gmail accounts that send too many emails in a day. It's for your account's safety. Every purchase gives a fresh batch of recruiters you haven't emailed before.</p>
                    <p class="small muted upgrade-note">${user ? `Buy with <b>${escapeHtml(user.email)}</b>, the email on your Mailzen account.` : "Buy with the same email you use for your Mailzen account."} We activate it on that account, within 5 hours.</p>
                </div>
            </div>`;
        backdrop.addEventListener("click", event => {
            if (event.target === backdrop || event.target.closest("[data-upgrade-close]")) closeUpgrade();
        });
        document.addEventListener("keydown", upgradeEscape);
        document.body.appendChild(backdrop);
    }

    return {
        bindLogout,
        bindSignature,
        bindThemeToggles,
        cachedGet,
        applyPricing,
        clearSession,
        closeUpgrade,
        currentTheme,
        duration,
        escapeAttr,
        escapeHtml,
        forgetPricing,
        formatDate,
        formatPrice,
        getPricing,
        getToken,
        getUser,
        isCampaigner,
        legalDocuments,
        logout,
        openUpgrade,
        parseDate,
        redirectIfLoggedIn,
        renderEmailPreview,
        requireAuth,
        request,
        saveSession,
        setStatus,
        setTheme,
        setUser,
        signatureBlock,
        statusBadge,
        timeAgo,
        toast
    };
})();

document.addEventListener("DOMContentLoaded", () => {
    OutreachApi.bindThemeToggles();
    OutreachApi.applyPricing().catch(() => {});
});

// Any element marked data-upgrade opens the plans card instead of navigating.
document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-upgrade]");
    if (!trigger) return;
    event.preventDefault();
    OutreachApi.openUpgrade();
});
