if (!OutreachApi.requireAuth()) {
    throw new Error("Authentication required");
}
OutreachApi.bindLogout();

const uploadStatus = document.getElementById("uploadStatus");
const automateBtn = document.getElementById("automateBtn");
const reviewBtn = document.getElementById("reviewBtn");
const connectGmailBtn = document.getElementById("connectGmailBtn");

async function loadGmailStatus() {
    try {
        const data = await OutreachApi.request("/gmail/status");
        connectGmailBtn.textContent = data.connected ? "Gmail Connected" : "Connect Gmail";
        connectGmailBtn.className = data.connected ? "btn secondary" : "btn";
    } catch (error) {
        OutreachApi.setStatus(uploadStatus, error.message, "error");
    }
}

async function connectGmail() {
    connectGmailBtn.disabled = true;
    try {
        const data = await OutreachApi.request("/gmail/connect");
        window.location.href = data.authorization_url;
    } catch (error) {
        OutreachApi.setStatus(uploadStatus, error.message, "error");
        connectGmailBtn.disabled = false;
    }
}

async function upload(mode) {
    const file = document.getElementById("fileInput").files[0];
    const emailFrom = document.getElementById("fromInput").value;
    if (!file || !emailFrom) {
        OutreachApi.setStatus(uploadStatus, "Choose a file and sender email first.", "error");
        return;
    }

    const form = new FormData();
    form.append("file", file);
    form.append("email_from", emailFrom);

    const isAutomated = mode === "automated";
    OutreachApi.setStatus(
        uploadStatus,
        isAutomated
            ? "Running automation one contact at a time. Emails are sent at least 1 minute apart."
            : "Generating drafts one contact at a time. Each process starts at least 30 seconds apart."
    );
    automateBtn.disabled = true;
    reviewBtn.disabled = true;

    try {
        const data = await OutreachApi.request(isAutomated ? "/automated/run" : "/human/generate", {
            method: "POST",
            body: form
        });
        const message = isAutomated
            ? `Processed ${data.processed} contacts with a ${data.delay_seconds}-second email delay and ${data.process_start_delay_seconds}-second process start spacing.`
            : `Processed ${data.processed} contacts with ${data.process_start_delay_seconds}-second process start spacing.`;
        OutreachApi.setStatus(uploadStatus, message, "ok");
        if (isAutomated) {
            window.location.href = "/sent-mails";
        } else {
            window.location.href = "/waiting-mails";
        }
    } catch (error) {
        OutreachApi.setStatus(uploadStatus, error.message, "error");
    } finally {
        automateBtn.disabled = false;
        reviewBtn.disabled = false;
    }
}

automateBtn.addEventListener("click", () => upload("automated"));
reviewBtn.addEventListener("click", () => upload("review"));
connectGmailBtn.addEventListener("click", connectGmail);
loadGmailStatus();
