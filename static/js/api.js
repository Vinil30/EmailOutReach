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

    return {
        bindLogout,
        bindThemeToggles,
        clearSession,
        currentTheme,
        duration,
        escapeAttr,
        escapeHtml,
        formatDate,
        getToken,
        getUser,
        isCampaigner,
        logout,
        parseDate,
        redirectIfLoggedIn,
        renderEmailPreview,
        requireAuth,
        request,
        saveSession,
        setStatus,
        setTheme,
        setUser,
        statusBadge,
        timeAgo,
        toast
    };
})();

document.addEventListener("DOMContentLoaded", () => OutreachApi.bindThemeToggles());
