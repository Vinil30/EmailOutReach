(async () => {
    const user = await Layout.init();
    const campaigner = OutreachApi.isCampaigner(user);
    const esc = OutreachApi.escapeHtml;
    const $ = id => document.getElementById(id);
    const profile = user.profile || {};

    const state = { source: "file", preview: null, writing: "template", mode: "review" };
    const aiAllowed = Boolean(user.is_premium);

    // ---- Role-specific copy ----
    if (campaigner) {
        $("eyebrow").textContent = "New campaign";
        $("title").textContent = "Build an email campaign";
        $("contactsHint").textContent = "Any columns work — they become merge fields. Only an email column is required.";
        $("sampleCsv").href = "/static/demo/campaign_contacts.csv";
        $("contactsText").placeholder = "email,first_name,company\npriya@example.com,Priya,Brightloop";
        $("campaignerAiFields").hidden = false;
        $("studentGoalField").hidden = true;
        $("researchInput").checked = false;
        $("offerInput").value = profile.offer || "";
        if (profile.tone) $("toneInput").value = profile.tone;
        $("subjectTemplate").placeholder = "A quick idea for {{company|your team}}";
        $("bodyTemplate").placeholder = "Hi {{first_name|there}},\n\nI noticed {{company}} ...\n\nWould a 15-minute call next week be useful?\n\n" + (profile.signature || profile.full_name || "");
    } else {
        $("eyebrow").textContent = "New outreach";
        $("title").textContent = "Reach out to companies";
        $("contactsHint").innerHTML = "Columns: <code>company_name</code>, <code>recipient_name</code>, <code>recipient_email</code>, optional <code>details</code>.";
        $("contactsText").placeholder = "company_name,recipient_name,recipient_email,details\nAcme Robotics,Jane Doe,jane@acme.com,Warehouse robotics startup";
        $("studentGoalInput").value = profile.goal || "";
        $("aiChoiceText").textContent = "Researches each company, picks your best-matching project, and drafts a unique email.";
        $("subjectTemplate").placeholder = "Interested in interning at {{company}}";
        $("launchBtn").textContent = "Start outreach";
        OutreachApi.request("/api/profile").then(data => {
            const count = data.projects.length;
            const note = $("projectsNote");
            note.hidden = false;
            note.innerHTML = count
                ? `${count} project${count === 1 ? "" : "s"} in your portfolio — the best matches are picked for each company. <a href="/profile#projects">Manage projects</a>`
                : `You haven't added any projects yet, so emails can only talk about your profile. <a href="/profile#projects">Add projects</a>`;
        });
    }
    $("fromInput").value = localStorage.getItem("outreachFrom") || user.email || "";
    $("gmailWarning").hidden = Boolean(user.gmail_connected);

    // AI research and writing are Premium-only; the server enforces this too.
    if (!aiAllowed) {
        const aiInput = document.querySelector('#writingMode input[value="ai"]');
        aiInput.disabled = true;
        aiInput.closest(".choice").classList.add("locked");
        aiInput.closest(".choice").addEventListener("click", () => OutreachApi.toast("AI writing is a Premium feature. Templates are free to use.", "error"));
    }

    // ---- Choice cards ----
    function bindChoices(containerId, key, onChange) {
        $(containerId).addEventListener("change", event => {
            state[key] = event.target.value;
            $(containerId).querySelectorAll(".choice").forEach(node => node.classList.toggle("active", node.contains(event.target)));
            onChange?.();
            renderSummary();
        });
    }
    bindChoices("writingMode", "writing", () => {
        $("aiFields").hidden = state.writing !== "ai";
        $("templateFields").hidden = state.writing !== "template";
        $("templateRiskCard").hidden = state.writing !== "template";
        runTemplateCheck();
        loadPreview();
    });
    bindChoices("modeChoice", "mode");

    // ---- Contacts source ----
    $("sourceToggle").addEventListener("click", event => {
        const button = event.target.closest("button");
        if (!button) return;
        state.source = button.dataset.source;
        $("sourceToggle").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        $("sourceFile").hidden = state.source !== "file";
        $("sourcePaste").hidden = state.source !== "paste";
        loadPreview();
    });

    const dropzone = $("dropzone");
    ["dragenter", "dragover"].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add("drag"); }));
    ["dragleave", "drop"].forEach(type => dropzone.addEventListener(type, () => dropzone.classList.remove("drag")));
    dropzone.addEventListener("drop", event => {
        event.preventDefault();
        if (event.dataTransfer.files.length) {
            $("fileInput").files = event.dataTransfer.files;
            $("fileInput").dispatchEvent(new Event("change"));
        }
    });
    $("fileInput").addEventListener("change", () => {
        $("fileName").textContent = $("fileInput").files[0]?.name || "";
        loadPreview();
    });
    let pasteTimer;
    $("contactsText").addEventListener("input", () => { clearTimeout(pasteTimer); pasteTimer = setTimeout(loadPreview, 600); });

    function contactsForm() {
        const form = new FormData();
        if (state.source === "file" && $("fileInput").files[0]) {
            form.append("file", $("fileInput").files[0]);
        } else if (state.source === "paste" && $("contactsText").value.trim()) {
            form.append("contacts_text", $("contactsText").value);
        } else {
            return null;
        }
        return form;
    }

    async function loadPreview() {
        const form = contactsForm();
        const node = $("contactPreview");
        if (!form) {
            state.preview = null;
            node.innerHTML = "";
            renderChips();
            renderSummary();
            return;
        }
        form.append("brief_json", JSON.stringify(buildBrief()));
        node.innerHTML = `<div class="skeleton"></div>`;
        try {
            state.preview = await OutreachApi.request("/api/campaigns/preview", { method: "POST", body: form });
            renderContactPreview();
        } catch (error) {
            state.preview = null;
            node.innerHTML = `<div class="status error">${esc(error.message)}</div>`;
        }
        renderChips();
        renderSummary();
        runTemplateCheck();
    }

    function renderContactPreview() {
        const p = state.preview;
        const rows = p.contacts.map(contact => `
            <tr>
                <td><div class="cell-main">${esc(contact.recipient_name || "—")}</div><div class="cell-sub">${esc(contact.recipient_email)}</div></td>
                <td>${esc(contact.company_name || "—")}</td>
                <td class="cell-sub" style="max-width:260px;">${esc(contact.details || "")}</td>
            </tr>`).join("");
        $("contactPreview").innerHTML = `
            <div class="banner ok small" style="margin:0 0 10px;"><strong>${p.total} contact${p.total === 1 ? "" : "s"} ready</strong>${p.skipped.length ? `<span>· ${p.skipped.length} skipped (${esc(p.skipped.slice(0, 3).map(item => `${item.email}: ${item.reason}`).join("; "))}${p.skipped.length > 3 ? "…" : ""})</span>` : ""}</div>
            <div class="table-wrap card" style="box-shadow:none;">
                <table>
                    <thead><tr><th>Recipient</th><th>Company</th><th>Details</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            ${p.total > p.contacts.length ? `<div class="small muted" style="margin-top:6px;">Showing ${p.contacts.length} of ${p.total}</div>` : ""}`;
    }

    // ---- Template merge fields + live spam check ----
    function renderChips() {
        const fields = new Set(["first_name", "name", "company", "email"]);
        (state.preview?.contacts || []).forEach(contact => Object.keys(contact.variables || {}).forEach(key => fields.add(key)));
        $("fieldChips").innerHTML = [...fields].map(field => `<button type="button" data-field="${esc(field)}">{{${esc(field)}}}</button>`).join("");
    }
    $("fieldChips").addEventListener("click", event => {
        const button = event.target.closest("button[data-field]");
        if (!button) return;
        const target = document.activeElement === $("subjectTemplate") ? $("subjectTemplate") : $("bodyTemplate");
        const token = `{{${button.dataset.field}}}`;
        const start = target.selectionStart ?? target.value.length;
        target.value = target.value.slice(0, start) + token + target.value.slice(target.selectionEnd ?? start);
        target.focus();
        target.selectionStart = target.selectionEnd = start + token.length;
        target.dispatchEvent(new Event("input"));
    });
    $("fieldChips").addEventListener("mousedown", event => event.preventDefault());

    // ---- Template gallery ----
    let dropEmptyLines = false;
    OutreachApi.request("/api/templates").then(data => {
        const usable = data.templates.filter(template => template.subject_template);
        $("galleryChips").innerHTML = usable.map(template => `<button type="button" data-template="${template.id}">${esc(template.name)}</button>`).join("");
        $("galleryChips").addEventListener("click", event => {
            const button = event.target.closest("button[data-template]");
            if (button) applyTemplate(usable.find(template => template.id === button.dataset.template));
        });
        // Job seekers start from what they chose on the Templates page.
        const chosen = usable.find(template => template.id === data.selected);
        if (!campaigner && data.selected === "ai" && aiAllowed) {
            document.querySelector('#writingMode input[value="ai"]').click();
        } else if (!campaigner && chosen) {
            applyTemplate(chosen);
        }
    }).catch(() => { $("galleryChips").innerHTML = ""; });

    function applyTemplate(template) {
        $("subjectTemplate").value = template.subject_template;
        $("bodyTemplate").value = template.body_template;
        dropEmptyLines = true;
        $("galleryChips").querySelectorAll("button").forEach(button => button.classList.toggle("active", button.dataset.template === template.id));
        runTemplateCheck();
    }

    // Rendered and scored by the server exactly as a send would be, using the first contact.
    let checkTimer = null;
    let checkSeq = 0;
    function runTemplateCheck() {
        clearTimeout(checkTimer);
        checkTimer = setTimeout(async () => {
            if (state.writing !== "template") return;
            const contact = state.preview?.contacts?.[0];
            const mine = ++checkSeq;
            $("riskFor").textContent = contact ? `Rendered for ${contact.recipient_email}` : "Shown with a sample recruiter until you add recipients";
            try {
                const result = await OutreachApi.request("/api/templates/preview", {
                    method: "POST",
                    json: {
                        subject: $("subjectTemplate").value,
                        body: $("bodyTemplate").value,
                        contact: contact ? contact.variables : null,
                        drop_empty_lines: dropEmptyLines
                    }
                });
                if (mine !== checkSeq) return;
                OutreachApi.renderEmailPreview($("templatePreview"), `<p><strong>${esc(result.preview_subject || "(no subject)")}</strong></p>${result.preview_body || '<p style="color:#9a9ea6">Start writing…</p>'}`, 120);
                $("templateRisk").innerHTML = RiskView.render(result.risk, { compact: true });
            } catch {
                // Preview is best-effort; launching still validates on the server.
            }
        }, 400);
    }
    $("subjectTemplate").addEventListener("input", runTemplateCheck);
    $("bodyTemplate").addEventListener("input", runTemplateCheck);

    // ---- Summary + launch ----
    function buildBrief() {
        const brief = { writing_mode: state.writing };
        if (state.writing === "template") {
            brief.subject_template = $("subjectTemplate").value;
            brief.body_template = $("bodyTemplate").value;
            brief.drop_empty_lines = dropEmptyLines;
        } else {
            brief.research = $("researchInput").checked;
            brief.instructions = $("instructionsInput").value;
            if (campaigner) {
                brief.offer = $("offerInput").value;
                brief.goal = $("goalInput").value;
                brief.tone = $("toneInput").value;
            } else {
                brief.goal = $("studentGoalInput").value;
            }
        }
        return brief;
    }

    function estimateSeconds(total) {
        if (total <= 1) return 0;
        let per = state.writing === "ai" ? 30 : 0;
        if (state.mode === "auto") per = Math.max(per, 120);
        return per * (total - 1);
    }

    function renderSummary() {
        const total = state.preview?.total || 0;
        const seconds = estimateSeconds(total);
        $("summary").innerHTML = `
            <dt>Recipients</dt><dd>${total ? `${total} contacts` : '<span class="muted">none yet</span>'}</dd>
            <dt>Writing</dt><dd>${state.writing === "ai" ? "AI-personalized" : "Template + merge fields"}</dd>
            <dt>Delivery</dt><dd>${state.mode === "auto" ? "Auto-send if score < 4" : "Review every draft"}</dd>
            <dt>Spam guard</dt><dd>${campaigner ? "14 checks incl. unsubscribe line" : "13 outreach checks"}</dd>
            <dt>Est. time</dt><dd>${total ? (seconds ? `~${OutreachApi.duration(seconds)} (1–3 min between sends)` : "about a minute") : "—"}</dd>`;
    }

    $("launchBtn").addEventListener("click", async () => {
        const form = contactsForm();
        const status = $("launchStatus");
        if (!form || !state.preview?.total) {
            OutreachApi.setStatus(status, "Add at least one valid recipient first.", "error");
            return;
        }
        if (!$("fromInput").value) {
            OutreachApi.setStatus(status, "Enter the sender email.", "error");
            return;
        }
        const brief = buildBrief();
        if (state.writing === "template" && (!brief.subject_template.trim() || !brief.body_template.trim())) {
            OutreachApi.setStatus(status, "Write a subject and body for the template.", "error");
            return;
        }
        form.append("name", $("nameInput").value || `${campaigner ? "Campaign" : "Outreach"} · ${new Date().toLocaleDateString()}`);
        form.append("email_from", $("fromInput").value);
        form.append("mode", state.mode);
        form.append("brief_json", JSON.stringify(brief));
        localStorage.setItem("outreachFrom", $("fromInput").value);

        $("launchBtn").disabled = true;
        OutreachApi.setStatus(status, "Launching…");
        try {
            const campaign = await OutreachApi.request("/api/campaigns", { method: "POST", body: form });
            OutreachApi.toast(`“${campaign.name}” is running in the background.`, "ok");
            window.location.href = "/campaigns";
        } catch (error) {
            OutreachApi.setStatus(status, error.message, "error");
            $("launchBtn").disabled = false;
        }
    });

    renderChips();
    renderSummary();
})();
