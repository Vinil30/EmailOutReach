(async () => {
    // Start this page's data requests alongside the sidebar's user check, not after it.
    OutreachApi.cachedGet("/api/profile");
    let fresh = false;
    let user = await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    const form = $("profileForm");
    let projects = [];
    let editingId = null;

    function applyRole(role) {
        document.querySelectorAll("[data-role]").forEach(node => { node.hidden = node.dataset.role !== role; });
        document.querySelectorAll("#roleChoice .choice").forEach(node => node.classList.toggle("active", node.querySelector("input").value === role));
        document.querySelector(`#roleChoice input[value="${role}"]`).checked = true;
        const campaigner = role === "campaigner";
        $("title").textContent = campaigner ? "Brand & sender" : "Projects & profile";
        $("profileTitle").textContent = campaigner ? "Sender details" : "About you";
        $("profileHint").textContent = campaigner
            ? "Used to write campaign emails and the compliance footer."
            : "Used to introduce you and sign each email.";
    }

    function fillForm() {
        const profile = user.profile || {};
        [...form.elements].forEach(field => {
            if (field.name && profile[field.name] !== undefined) field.value = profile[field.name];
        });
        if (!form.elements.full_name.value) form.elements.full_name.value = user.name || "";
        const badge = $("gmailBadge");
        badge.innerHTML = user.gmail_connected ? `<span class="badge ok">Connected</span>` : `<span class="badge warn">Not connected</span>`;
        $("connectGmailBtn").textContent = user.gmail_connected ? "Reconnect" : "Connect Gmail";
        $("disconnectGmailBtn").hidden = !user.gmail_connected;
    }

    function renderProjects() {
        const grid = $("projectGrid");
        if (!projects.length) {
            grid.innerHTML = `<div class="empty" style="grid-column:1/-1;"><strong>No projects yet</strong><span>Add 3–6 projects you're proud of. Each email features the ones closest to what the company does.</span></div>`;
            return;
        }
        grid.innerHTML = projects.map(project => `
            <article class="project" data-id="${project.id}">
                <h4>${esc(project.name)}</h4>
                <p>${esc(project.summary)}</p>
                ${project.tech ? `<div class="tags">${project.tech.split(",").map(tag => tag.trim()).filter(Boolean).slice(0, 6).map(tag => `<span>${esc(tag)}</span>`).join("")}</div>` : ""}
                ${project.impact ? `<div class="small" style="color:var(--ok)">${esc(project.impact)}</div>` : ""}
                <div class="actions">
                    <button class="btn ghost sm" type="button" data-action="edit">Edit</button>
                    <button class="btn ghost sm" type="button" data-action="delete">Delete</button>
                    ${/^https?:\/\//i.test(project.link || "") ? `<a class="btn ghost sm" href="${esc(project.link)}" target="_blank" rel="noopener">Open ↗</a>` : ""}
                </div>
            </article>`).join("");
    }

    async function load() {
        const data = await OutreachApi.cachedGet("/api/profile", { fresh });
        fresh = true;
        user = data.user;
        projects = data.projects;
        $("suppressionInput").value = (data.suppressed_emails || []).join("\n");
        applyRole(user.role);
        fillForm();
        renderProjects();
        if (location.hash === "#projects") $("projects").scrollIntoView({ behavior: "smooth" });
    }

    async function saveProfile(role) {
        const profile = Object.fromEntries([...form.elements].filter(field => field.name).map(field => [field.name, field.value]));
        const data = await OutreachApi.request("/api/profile", { method: "PUT", json: { role, profile } });
        user = data.user;
        OutreachApi.setUser(user);
        Layout.renderSidebar(user);
        // Switching account type means signing that type's terms.
        Layout.requireSignature(user);
        return user;
    }

    $("roleChoice").addEventListener("change", async event => {
        applyRole(event.target.value);
        try {
            await saveProfile(event.target.value);
            OutreachApi.toast(event.target.value === "campaigner" ? "Switched to campaign mode." : "Switched to student mode.", "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    form.addEventListener("submit", async event => {
        event.preventDefault();
        OutreachApi.setStatus($("profileStatus"), "Saving…");
        try {
            await saveProfile(user.role);
            OutreachApi.setStatus($("profileStatus"), "Saved.", "ok");
        } catch (error) {
            OutreachApi.setStatus($("profileStatus"), error.message, "error");
        }
    });

    // ---- Projects ----
    const projectModal = $("projectModal");
    const projectForm = $("projectForm");
    function openProject(project = null) {
        editingId = project?.id || null;
        $("projectModalTitle").textContent = project ? "Edit project" : "Add project";
        ["name", "summary", "tech", "impact", "link"].forEach(key => { projectForm.elements[key].value = project?.[key] || ""; });
        projectModal.hidden = false;
        projectForm.elements.name.focus();
    }
    document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => { button.closest(".modal-backdrop").hidden = true; }));
    document.querySelectorAll(".modal-backdrop").forEach(backdrop => backdrop.addEventListener("click", event => { if (event.target === backdrop) backdrop.hidden = true; }));
    $("addProjectBtn").addEventListener("click", () => openProject());

    projectForm.addEventListener("submit", async event => {
        event.preventDefault();
        const payload = Object.fromEntries(["name", "summary", "tech", "impact", "link"].map(key => [key, projectForm.elements[key].value]));
        try {
            if (editingId) {
                const updated = await OutreachApi.request(`/api/profile/projects/${editingId}`, { method: "PUT", json: payload });
                projects = projects.map(project => (project.id === editingId ? updated : project));
            } else {
                projects.push(await OutreachApi.request("/api/profile/projects", { method: "POST", json: payload }));
            }
            projectModal.hidden = true;
            renderProjects();
            OutreachApi.toast("Project saved.", "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    $("projectGrid").addEventListener("click", async event => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const id = button.closest(".project").dataset.id;
        const project = projects.find(item => item.id === id);
        if (button.dataset.action === "edit") return openProject(project);
        if (!confirm(`Delete “${project.name}”?`)) return;
        try {
            await OutreachApi.request(`/api/profile/projects/${id}`, { method: "DELETE" });
            projects = projects.filter(item => item.id !== id);
            renderProjects();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    $("importBtn").addEventListener("click", () => { $("importModal").hidden = false; });
    $("loadSampleBtn").addEventListener("click", async () => {
        const sample = await fetch("/static/demo/sample_projects.json").then(response => response.json());
        $("importInput").value = JSON.stringify(sample, null, 2);
    });
    $("importForm").addEventListener("submit", async event => {
        event.preventDefault();
        let payload;
        try {
            payload = JSON.parse($("importInput").value);
            if (!Array.isArray(payload)) throw new Error();
        } catch {
            OutreachApi.toast("Paste a JSON array of projects.", "error");
            return;
        }
        try {
            const data = await OutreachApi.request("/api/profile/projects/import", { method: "POST", json: payload });
            projects = projects.concat(data.projects);
            renderProjects();
            $("importModal").hidden = true;
            OutreachApi.toast(`Imported ${data.projects.length} projects.`, "ok");
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    // ---- Gmail + suppression ----
    $("connectGmailBtn").addEventListener("click", () => Layout.connectGmail().catch(error => OutreachApi.toast(error.message, "error")));
    $("disconnectGmailBtn").addEventListener("click", async () => {
        if (!confirm("Disconnect Gmail? Sends will fail until you reconnect.")) return;
        try {
            await OutreachApi.request("/gmail/disconnect", { method: "POST" });
        } catch (error) {
            OutreachApi.toast(error.message, "error");
            return;
        }
        user.gmail_connected = false;
        OutreachApi.setUser(user);
        Layout.renderSidebar(user);
        fillForm();
    });
    $("saveSuppressionBtn").addEventListener("click", async () => {
        const emails = $("suppressionInput").value.split(/[\s,;]+/).filter(Boolean);
        try {
            const data = await OutreachApi.request("/api/profile/suppression", { method: "PUT", json: { emails } });
            $("suppressionInput").value = data.suppressed_emails.join("\n");
            OutreachApi.setStatus($("suppressionStatus"), `${data.suppressed_emails.length} addresses saved.`, "ok");
        } catch (error) {
            OutreachApi.setStatus($("suppressionStatus"), error.message, "error");
        }
    });

    load().catch(error => OutreachApi.toast(error.message, "error"));
})();
