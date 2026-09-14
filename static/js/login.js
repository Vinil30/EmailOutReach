OutreachApi.redirectIfLoggedIn();

const authForm = document.getElementById("authForm");
const registerBtn = document.getElementById("registerBtn");
const loginBtn = document.getElementById("loginBtn");
const authStatus = document.getElementById("authStatus");
const authTitle = document.getElementById("authTitle");
const authIntro = document.getElementById("authIntro");
const nameLabel = document.getElementById("nameLabel");
let authMode = new URLSearchParams(window.location.search).get("mode") === "signup" ? "register" : "login";

function renderAuthMode() {
    const isSignup = authMode === "register";
    authTitle.textContent = isSignup ? "Create Account" : "Log In";
    authIntro.textContent = isSignup
        ? "Create your workspace, then connect Gmail from the dashboard before sending."
        : "Sign in to run campaigns, review generated drafts, and inspect delivery status.";
    loginBtn.textContent = isSignup ? "Create Account" : "Log In";
    registerBtn.textContent = isSignup ? "Use Existing Account" : "Sign Up";
    nameLabel.style.display = isSignup ? "grid" : "none";
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
        window.location.replace("/dashboard");
    } catch (error) {
        OutreachApi.setStatus(authStatus, error.message, "error");
    }
}

authForm.addEventListener("submit", event => {
    event.preventDefault();
    submitAuth(authMode);
});

registerBtn.addEventListener("click", () => {
    authMode = authMode === "register" ? "login" : "register";
    renderAuthMode();
});

renderAuthMode();
