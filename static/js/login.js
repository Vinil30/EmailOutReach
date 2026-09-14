OutreachApi.redirectIfLoggedIn();

const authForm = document.getElementById("authForm");
const registerBtn = document.getElementById("registerBtn");
const loginBtn = document.getElementById("loginBtn");
const loginTab = document.getElementById("loginTab");
const signupTab = document.getElementById("signupTab");
const authStatus = document.getElementById("authStatus");
const authTitle = document.getElementById("authTitle");
const authIntro = document.getElementById("authIntro");
const nameLabel = document.getElementById("nameLabel");
const params = new URLSearchParams(window.location.search);
let authMode = params.get("mode") === "signup" ? "register" : "login";

function renderAuthMode() {
    const isSignup = authMode === "register";
    authTitle.textContent = isSignup ? "Create account" : "Log in";
    authIntro.textContent = isSignup
        ? "Create your workspace, then connect Gmail from the dashboard before sending."
        : "Sign in to run campaigns, review generated drafts, and inspect delivery status.";
    loginBtn.textContent = isSignup ? "Create account" : "Log in";
    registerBtn.textContent = isSignup ? "Use existing account" : "Create a new account";
    nameLabel.style.display = isSignup ? "grid" : "none";
    document.getElementById("passwordInput").autocomplete = isSignup ? "new-password" : "current-password";
    loginTab.classList.toggle("active", !isSignup);
    signupTab.classList.toggle("active", isSignup);
}

async function submitAuth(mode) {
    const payload = {
        email: document.getElementById("emailInput").value,
        password: document.getElementById("passwordInput").value
    };
    if (mode === "register") {
        payload.name = document.getElementById("nameInput").value || null;
    }

    OutreachApi.setStatus(authStatus, mode === "register" ? "Creating account..." : "Signing in...");
    try {
        const data = await OutreachApi.request(`/auth/${mode}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        OutreachApi.saveSession(data);
        window.location.replace(params.get("next") || "/dashboard");
    } catch (error) {
        OutreachApi.setStatus(authStatus, error.message, "error");
    }
}

function setMode(mode) {
    authMode = mode;
    renderAuthMode();
    OutreachApi.setStatus(authStatus, mode === "register" ? "Create an account to continue." : "Log in to continue.");
}

authForm.addEventListener("submit", event => {
    event.preventDefault();
    submitAuth(authMode);
});

registerBtn.addEventListener("click", () => {
    setMode(authMode === "register" ? "login" : "register");
});

loginTab.addEventListener("click", () => setMode("login"));
signupTab.addEventListener("click", () => setMode("register"));

renderAuthMode();
