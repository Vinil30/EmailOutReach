OutreachApi.requireAuth();
OutreachApi.bindLogout();

const sentStatus = document.getElementById("sentStatus");
const sentList = document.getElementById("sentList");
const refreshSentBtn = document.getElementById("refreshSentBtn");

async function loadSent() {
    OutreachApi.setStatus(sentStatus, "Loading sent emails...");
    try {
        const data = await OutreachApi.request("/automated/sent-emails");
        sentList.innerHTML = "";
        if (!data.emails.length) {
            sentList.innerHTML = `<div class="empty">No sent emails yet.</div>`;
        } else {
            data.emails.forEach(email => sentList.appendChild(renderEmailCard(email, true)));
        }
        OutreachApi.setStatus(sentStatus, `${data.emails.length} sent emails found.`, "ok");
    } catch (error) {
        OutreachApi.setStatus(sentStatus, error.message, "error");
    }
}

refreshSentBtn.addEventListener("click", loadSent);
loadSent();
