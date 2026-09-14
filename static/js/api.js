const OutreachApi = (() => {
    function getToken() {
        return localStorage.getItem("outreachToken") || "";
    }

    function getUser() {
        return JSON.parse(localStorage.getItem("outreachUser") || "null");
    }

    function saveSession(data) {
        localStorage.setItem("outreachToken", data.access_token);
        localStorage.setItem("outreachUser", JSON.stringify(data.user));
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
        const user = getUser();
        const userEmail = document.getElementById("userEmail");
        if (userEmail) {
            userEmail.textContent = user?.email || "";
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
        node.textContent = message;
        node.className = `status ${type}`.trim();
    }

    async function request(path, options = {}) {
        const headers = options.headers || {};
        const token = getToken();
        if (token) {
            headers.Authorization = `Bearer ${token}`;
        }
        const response = await fetch(path, { ...options, headers });
        const text = await response.text();
        const data = text ? JSON.parse(text) : {};
        if (!response.ok) {
            if (response.status === 401) {
                clearSession();
                const next = `${window.location.pathname}${window.location.search}`;
                window.location.replace(`/login?next=${encodeURIComponent(next)}`);
            }
            throw new Error(data.detail || "Request failed");
        }
        return data;
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function escapeAttr(value) {
        return escapeHtml(value).replaceAll("\n", " ");
    }

    return {
        bindLogout,
        escapeAttr,
        escapeHtml,
        getToken,
        getUser,
        logout,
        redirectIfLoggedIn,
        requireAuth,
        request,
        saveSession,
        setStatus
    };
})();
