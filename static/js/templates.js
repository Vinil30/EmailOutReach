(async () => {
    await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    let data = null;
    let viewing = null;
    let writing = null;
    let plan = null;

    function scoreBadge(risk) {
        if (!risk) return "";
        const tone = risk.level === "LOW" ? "ok" : risk.level === "MEDIUM" ? "warn" : "bad";
        return `<span class="badge ${tone}">Spam score ${Number(risk.score).toFixed(1)}</span>`;
    }

    // ---- Template vs AI ----
    function renderWriting() {
        const inUse = data.selected === "ai" ? "ai" : "template";
        $("writingChoice").querySelectorAll(".choice").forEach(node => {
            node.classList.toggle("active", node.dataset.writing === writing);
            node.querySelector(".in-use")?.remove();
            if (node.dataset.writing === inUse) node.querySelector("strong").insertAdjacentHTML("beforeend", ' <span class="badge ok in-use">In use</span>');
        });
        $("templatePane").hidden = writing !== "template";
        $("aiPane").hidden = writing !== "ai";
        if (writing === "ai") renderAi();
    }

    function renderAi() {
        const inUse = data.selected === "ai";
        $("aiPane").innerHTML = data.ai_allowed ? `
            <div class="card ai-pane"><div class="card-body">
                <p>For every company, Mailzen reads what they do, picks the project of yours that fits best, and drafts a unique email with your resume link. Each draft still passes the spam check before it's sent.</p>
                <div class="actions"><button class="btn primary" type="button" id="useAiBtn" ${inUse ? "disabled" : ""}>${inUse ? "AI-personalized is in use" : "Use AI-personalized"}</button></div>
            </div></div>` : `
            <div class="card ai-pane"><div class="card-body">
                <span class="eyebrow">Premium feature</span>
                <p>AI research and writing are included with Premium, along with 100 emails a week and our recruiter database. On the General plan, templates are free to use.</p>
                <div class="actions">
                    <a class="btn primary" href="${esc(plan?.premium_url || "#")}" target="_blank" rel="noopener">Buy Premium</a>
                    <button class="btn secondary" type="button" data-writing-switch="template">Use a template</button>
                </div>
            </div></div>`;
        $("useAiBtn")?.addEventListener("click", async () => {
            try {
                await saveSelection("ai");
                await load();
            } catch (error) {
                OutreachApi.toast(error.message, "error");
            }
        });
        $("aiPane").querySelector("[data-writing-switch]")?.addEventListener("click", () => { writing = "template"; renderWriting(); });
    }

    function renderFeatured() {
        const select = $("featuredSelect");
        select.innerHTML = data.projects.length
            ? data.projects.map(name => `<option value="${esc(name)}" ${name === data.featured_project ? "selected" : ""}>${esc(name)}</option>`).join("")
            : `<option value="">No projects yet. Add one on your profile.</option>`;
        select.disabled = !data.projects.length;
    }

    function renderList() {
        $("templateList").innerHTML = data.templates.filter(template => !template.ai).map(template => `
            <button type="button" class="tpl-item ${template.id === viewing ? "viewing" : ""}" data-id="${template.id}">
                <span class="tpl-item-top"><b>${esc(template.name)}</b>${template.id === data.selected ? '<span class="badge ok">In use</span>' : ""}</span>
                <span>${esc(template.description)}</span>
            </button>`).join("");
    }

    function renderPreview() {
        const template = data.templates.find(item => item.id === viewing);
        $("previewName").textContent = template.name;
        $("previewDesc").textContent = template.description;
        $("useBtn").textContent = template.id === data.selected ? "In use" : "Use this template";
        $("useBtn").disabled = template.id === data.selected && !template.custom;
        const body = $("previewBody");

        const fields = Object.entries(data.fields).map(([field, help]) => `<button type="button" data-field="${field}" title="${esc(help)}">{{${field}}}</button>`).join("");
        body.innerHTML = `
            ${template.custom ? `
                <label class="field"><span>Subject</span><input id="customSubject" value="${OutreachApi.escapeAttr(template.subject_template || "")}" placeholder="Interested in roles at {{company}}"></label>
                <label class="field"><span>Body</span><textarea id="customBody" rows="10" placeholder="Hi {{first_name|there}},&#10;&#10;{{my_intro}} …">${esc(template.body_template || "")}</textarea>
                    <small>Lines whose field is empty are left out, so optional lines like your portfolio vanish when blank.</small></label>
                <div><div class="field-label" style="margin-bottom:6px;">Insert a field</div><div class="chips" id="fieldChips">${fields}</div></div>
                <div class="divider"></div>` : ""}
            <div class="tpl-meta"><span class="small muted">To ${esc(data.sample_contact.name)}, ${esc(data.sample_contact.company)}</span><span id="riskBadge">${scoreBadge(template.risk)}</span></div>
            <div class="tpl-subject" id="previewSubject">${esc(template.preview_subject || "")}</div>
            <div class="mail-preview" id="previewFrame"></div>
            ${template.custom ? "" : `<details class="tpl-source"><summary class="small muted">Show template source</summary><pre>${esc(template.subject_template)}\n\n${esc(template.body_template)}</pre></details>`}`;
        OutreachApi.renderEmailPreview($("previewFrame"), template.preview_body || '<p style="color:#9a9ea6">Write a body to see the preview.</p>');

        if (template.custom) {
            const update = () => livePreview(template);
            $("customSubject").addEventListener("input", update);
            $("customBody").addEventListener("input", update);
            $("fieldChips").addEventListener("mousedown", event => event.preventDefault());
            $("fieldChips").addEventListener("click", event => {
                const button = event.target.closest("button[data-field]");
                if (!button) return;
                const target = document.activeElement === $("customSubject") ? $("customSubject") : $("customBody");
                const token = `{{${button.dataset.field}}}`;
                const start = target.selectionStart ?? target.value.length;
                target.value = target.value.slice(0, start) + token + target.value.slice(target.selectionEnd ?? start);
                target.focus();
                target.selectionStart = target.selectionEnd = start + token.length;
                update();
            });
        }
    }

    // Rendered by the server with the same rules automation uses; nothing is saved until "Use this template".
    let previewTimer;
    function livePreview(template) {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(async () => {
            template.subject_template = $("customSubject").value;
            template.body_template = $("customBody").value;
            try {
                const preview = await OutreachApi.request("/api/templates/preview", {
                    method: "POST",
                    json: { subject: template.subject_template, body: template.body_template }
                });
                Object.assign(template, preview);
                $("previewSubject").textContent = preview.preview_subject;
                $("riskBadge").innerHTML = scoreBadge(preview.risk);
                OutreachApi.renderEmailPreview($("previewFrame"), preview.preview_body);
                $("useBtn").disabled = false;
                $("useBtn").textContent = "Save & use this template";
            } catch (error) {
                OutreachApi.toast(error.message, "error");
            }
        }, 450);
    }

    async function saveSelection(id) {
        const profile = { template_id: id };
        if (id === "custom" && $("customSubject")) {
            profile.custom_subject = $("customSubject").value;
            profile.custom_body = $("customBody").value;
        }
        await OutreachApi.request("/api/profile", { method: "PUT", json: { profile } });
        OutreachApi.toast(id === "ai" ? "AI-personalized emails are on." : "Template saved.", "ok");
    }

    async function load() {
        [data, plan] = await Promise.all([OutreachApi.request("/api/templates"), plan || OutreachApi.request("/api/plan")]);
        if (!viewing) viewing = data.selected === "ai" ? "short" : data.selected;
        if (!writing) writing = data.selected === "ai" ? "ai" : "template";
        renderWriting();
        renderFeatured();
        renderList();
        renderPreview();
    }

    $("writingChoice").addEventListener("click", event => {
        const choice = event.target.closest(".choice[data-writing]");
        if (!choice) return;
        writing = choice.dataset.writing;
        renderWriting();
    });

    $("featuredSelect").addEventListener("change", async event => {
        try {
            await OutreachApi.request("/api/profile", { method: "PUT", json: { profile: { featured_project: event.target.value } } });
            OutreachApi.toast("Featured project saved.", "ok");
            await load();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    $("templateList").addEventListener("click", event => {
        const button = event.target.closest("button[data-id]");
        if (!button) return;
        viewing = button.dataset.id;
        renderList();
        renderPreview();
    });

    $("useBtn").addEventListener("click", async () => {
        try {
            await saveSelection(viewing);
            await load();
        } catch (error) {
            OutreachApi.toast(error.message, "error");
        }
    });

    load().catch(error => OutreachApi.toast(error.message, "error"));
})();
