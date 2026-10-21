OutreachApi.redirectIfLoggedIn();

const authForm = document.getElementById("authForm");
const loginBtn = document.getElementById("loginBtn");
const loginTab = document.getElementById("loginTab");
const signupTab = document.getElementById("signupTab");
const authStatus = document.getElementById("authStatus");
const authTitle = document.getElementById("authTitle");
const authIntro = document.getElementById("authIntro");
const nameLabel = document.getElementById("nameLabel");
const roleField = document.getElementById("roleField");
const roleChoice = document.getElementById("roleChoice");
const params = new URLSearchParams(window.location.search);
let authMode = params.get("mode") === "signup" ? "register" : "login";

if (params.get("role") === "campaigner") {
    roleChoice.querySelector('input[value="campaigner"]').checked = true;
}

function syncRoleCards() {
    roleChoice.querySelectorAll(".choice").forEach(node => node.classList.toggle("active", node.querySelector("input").checked));
}

function renderAuthMode() {
    const isSignup = authMode === "register";
    authTitle.textContent = isSignup ? "Create your account" : "Log in";
    authIntro.textContent = isSignup
        ? "Pick a mode — you can switch later. Connect Gmail from the dashboard when you're ready to send."
        : "Welcome back. Your campaigns and drafts are where you left them.";
    loginBtn.textContent = isSignup ? "Create account" : "Log in";
    nameLabel.hidden = !isSignup;
    roleField.hidden = !isSignup;
    document.getElementById("passwordInput").autocomplete = isSignup ? "new-password" : "current-password";
    loginTab.classList.toggle("active", !isSignup);
    signupTab.classList.toggle("active", isSignup);
    syncRoleCards();
}

async function submitAuth(mode) {
    const payload = {
        email: document.getElementById("emailInput").value,
        password: document.getElementById("passwordInput").value
    };
    if (mode === "register") {
        payload.name = document.getElementById("nameInput").value || null;
        payload.role = roleChoice.querySelector("input:checked").value;
    }

    loginBtn.disabled = true;
    OutreachApi.setStatus(authStatus, mode === "register" ? "Creating account…" : "Signing in…");
    try {
        const data = await OutreachApi.request(`/auth/${mode}`, { method: "POST", json: payload });
        OutreachApi.saveSession(data);
        const fallback = mode === "register" ? "/profile" : "/dashboard";
        const next = params.get("next");
        window.location.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : fallback);
    } catch (error) {
        OutreachApi.setStatus(authStatus, error.message, "error");
        loginBtn.disabled = false;
    }
}

function setMode(mode) {
    authMode = mode;
    OutreachApi.setStatus(authStatus, "");
    renderAuthMode();
}

authForm.addEventListener("submit", event => {
    event.preventDefault();
    submitAuth(authMode);
});
roleChoice.addEventListener("change", syncRoleCards);
loginTab.addEventListener("click", () => setMode("login"));
signupTab.addEventListener("click", () => setMode("register"));

renderAuthMode();
