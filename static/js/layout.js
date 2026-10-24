// Shared app chrome: auth guard, role-aware sidebar, Gmail state and review badge.
const Layout = (() => {
    const ICONS = {
        home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
        inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M5 5h14l2 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z"/>',
        send: '<path d="M21 3 10 14"/><path d="M21 3 14 21l-4-7-7-4z"/>',
        shield: '<path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
        folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
        user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
        menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
        bolt: '<path d="M13 3 4 14h7l-1 7 9-11h-7z"/>',
        doc: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
        key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>'
    };

    function icon(name) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
    }

    function navItems(user) {
        const campaigner = OutreachApi.isCampaigner(user);
        const items = [
            { href: "/dashboard", label: "Home", icon: "home" },
            { href: "/automate", label: "Automate", icon: "bolt", tag: user?.is_paid ? "" : "Upgrade" },
            { href: "/campaigns/new", label: "Send to my list", icon: "plus" },
            { href: "/campaigns", label: "My lists", icon: "layers" },
            { href: "/waiting-mails", label: "Review", icon: "inbox", badge: "reviewCount" },
            { href: "/sent-mails", label: "Sent", icon: "send" },
            { section: "Setup" },
            { href: "/profile", label: campaigner ? "Profile & brand" : "Profile & resume", icon: "user" },
            { href: "/templates", label: "Templates", icon: "doc" },
            { href: "/spam-check", label: "Spam check", icon: "shield" }
        ];
        if (user?.is_admin) items.push({ section: "Admin" }, { href: "/admin", label: "Admin panel", icon: "key" });
        return items;
    }

    function planChip(plan) {
        if (!plan) return "";
        const paid = plan.plan !== "free";
        const until = OutreachApi.parseDate(plan.plan_until);
        const daysLeft = until ? Math.max(0, Math.ceil((until - Date.now()) / 86400000)) : 0;
        const pct = Math.min(100, (plan.used / Math.max(1, plan.limit)) * 100);
        const action = !paid ? "Upgrade" : daysLeft <= 5 ? "Renew" : plan.plan === "pro" ? "Upgrade" : "";
        const sub = paid
            ? `${daysLeft} day${daysLeft === 1 ? "" : "s"} left · ${plan.database.remaining}/${plan.database.limit} recruiters`
            : plan.plan_expired ? `${OutreachApi.escapeHtml(plan.expired_plan_name)} expired` : "Free plan · lifetime limit";
        return `
            <div class="plan-chip ${paid ? "premium" : ""}">
                <div class="plan-chip-top"><strong>${plan.plan_name}</strong><span>${plan.used}/${plan.limit}${paid ? " today" : " used"}</span></div>
                <div class="plan-meter"><span style="width:${pct}%"></span></div>
                <div class="plan-chip-sub">${sub}</div>
                ${action ? `<button type="button" class="btn primary sm block" data-upgrade>${action}</button>` : ""}
            </div>`;
    }

    function renderSidebar(user) {
        const sidebar = document.getElementById("sidebar");
        if (!sidebar) return;
        const path = window.location.pathname;
        const campaigner = OutreachApi.isCampaigner(user);
        const links = navItems(user).map(item => {
            if (item.section) return `<div class="nav-label">${item.section}</div>`;
            const active = path === item.href ? "active" : "";
            const badge = item.badge ? `<span class="count" id="${item.badge}" hidden></span>` : "";
            const tag = item.tag ? `<span class="nav-tag">${item.tag}</span>` : "";
            return `<a class="${active}" href="${item.href}">${icon(item.icon)}<span>${item.label}</span>${badge}${tag}</a>`;
        }).join("");

        sidebar.innerHTML = `
            <a class="brand" href="/dashboard">
                <div class="brand-mark" aria-hidden="true"></div>
                <div>
                    <div class="brand-name">Mailzen</div>
                    <div class="brand-sub">Write · Check · Send</div>
                </div>
            </a>
            <nav class="nav">${links}</nav>
            <div id="planChip">${planChip(currentPlan)}</div>
            <div class="sidebar-foot">
                <div class="who" title="${OutreachApi.escapeAttr(user?.email || "")}">${OutreachApi.escapeHtml(user?.profile?.full_name || user?.name || user?.email || "")}<span class="muted small"> · ${campaigner ? "Campaigns" : "Job seeker"}</span></div>
                <div class="gmail ${user?.gmail_connected ? "on" : ""}" id="gmailState"><span class="dot"></span>${user?.gmail_connected ? "Gmail connected" : "Gmail not connected"}</div>
                <button type="button" class="theme-toggle" data-theme-toggle><span data-theme-label></span></button>
                <button type="button" id="logoutBtn">Sign out</button>
                <div class="legal-links"><a href="/terms">Terms</a><a href="/privacy">Privacy</a></div>
            </div>`;
        OutreachApi.bindLogout();
        OutreachApi.bindThemeToggles(sidebar);

        if (!document.querySelector(".mobile-bar")) {
            const bar = document.createElement("div");
            bar.className = "mobile-bar";
            bar.innerHTML = `<div class="brand"><div class="brand-mark" aria-hidden="true"></div><div class="brand-name">Mailzen</div></div><button type="button" aria-label="Open menu">${icon("menu")}</button>`;
            bar.querySelector("button").addEventListener("click", () => document.body.classList.toggle("nav-open"));
            document.body.prepend(bar);
            document.querySelector(".main")?.addEventListener("click", () => document.body.classList.remove("nav-open"));
        }
    }

    let currentPlan = null;

    async function refreshPlan({ fresh = true } = {}) {
        try {
            currentPlan = await OutreachApi.cachedGet("/api/plan", { fresh });
            const node = document.getElementById("planChip");
            if (node) node.innerHTML = planChip(currentPlan);
        } catch {
            currentPlan = null;
        }
        return currentPlan;
    }

    async function refreshUser() {
        try {
            const user = await OutreachApi.cachedGet("/auth/me");
            OutreachApi.setUser(user);
            return user;
        } catch {
            return OutreachApi.getUser();
        }
    }

    async function refreshReviewCount({ fresh = true } = {}) {
        try {
            const stats = await OutreachApi.cachedGet("/api/campaigns/stats", { fresh });
            const node = document.getElementById("reviewCount");
            if (node) {
                node.textContent = stats.waiting;
                node.hidden = !stats.waiting;
            }
            return stats;
        } catch {
            return null;
        }
    }

    // Accounts must sign the current Terms and Privacy Policy for their role; this blocks the app until they do.
    function requireSignature(user) {
        if (!user?.legal || user.legal.signed || document.getElementById("signModal")) return;
        const updated = user.legal.documents.some(doc => doc.signed_at);
        const backdrop = document.createElement("div");
        backdrop.className = "modal-backdrop";
        backdrop.id = "signModal";
        backdrop.innerHTML = `
            <div class="modal card sign-modal" role="dialog" aria-modal="true" aria-labelledby="signTitle">
                <div class="card-head"><div><span class="eyebrow">${updated ? "Updated terms" : "One last step"}</span><h3 id="signTitle">${updated ? "Please review and sign the updated terms" : "Review and sign to continue"}</h3><p>${updated ? "We've changed our terms or your account type. Sign the current versions to keep sending." : "Mailzen sends email from your Gmail account, so every account signs the Terms and Privacy Policy first."}</p></div></div>
                <div class="card-body">
                    <div class="sign-box">${OutreachApi.signatureBlock(user.role, user.profile?.full_name || user.name || "")}</div>
                    <div class="status small" id="signStatus"></div>
                    <div class="actions" style="justify-content:space-between;">
                        <button type="button" class="btn ghost sm" data-sign-out>Sign out</button>
                        <button type="button" class="btn primary" data-sign>Sign and continue</button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(backdrop);
        const signature = OutreachApi.bindSignature(backdrop);
        const status = backdrop.querySelector("#signStatus");
        backdrop.querySelector("[data-sign-out]").addEventListener("click", OutreachApi.logout);
        backdrop.querySelector("[data-sign]").addEventListener("click", async event => {
            const button = event.currentTarget;
            try {
                const value = signature.value();
                button.disabled = true;
                OutreachApi.setStatus(status, "Signing…");
                const data = await OutreachApi.request("/api/legal/sign", { method: "POST", json: { signature: value, agree: true } });
                OutreachApi.setUser(data.user);
                backdrop.remove();
                OutreachApi.toast("Signed. Thanks!", "ok");
            } catch (error) {
                OutreachApi.setStatus(status, error.message, "error");
                button.disabled = false;
            }
        });
    }

    // Resolves with the fresh user so pages can render role-specific content.
    async function init() {
        if (!OutreachApi.requireAuth()) {
            throw new Error("Authentication required");
        }
        renderSidebar(OutreachApi.getUser());
        // Sidebar data starts in parallel with the user check instead of after it.
        refreshReviewCount({ fresh: false });
        refreshPlan({ fresh: false });
        const user = await refreshUser();
        renderSidebar(user);
        requireSignature(user);
        // Re-rendering the sidebar resets the review badge, so re-apply the (already shared) stats.
        OutreachApi.cachedGet("/api/campaigns/stats").then(stats => {
            const badge = document.getElementById("reviewCount");
            if (badge) { badge.textContent = stats.waiting; badge.hidden = !stats.waiting; }
        }).catch(() => {});
        return user;
    }

    async function connectGmail() {
        const data = await OutreachApi.request("/gmail/connect");
        window.location.href = data.authorization_url;
    }

    return { connectGmail, icon, init, refreshPlan, refreshReviewCount, renderSidebar, requireSignature };
})();
