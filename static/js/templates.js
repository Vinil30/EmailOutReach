(async () => {
    await Layout.init();
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    let data = null;
    let viewing = null;

    function scoreBadge(risk) {
        if (!risk) return "";
        const tone = risk.level === "LOW" ? "ok" : risk.level === "MEDIUM" ? "warn" : "bad";
        return `<span class="badge ${tone}">Spam score ${Number(risk.score).toFixed(1)}</span>`;
    }

    function renderList() {
        $("templateList").innerHTML = data.templates.map(template => `
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

        if (template.ai) {
            body.innerHTML = `
                <div class="banner info" style="margin:0;">Each email is written fresh for its recipient: the app reads about the company, picks your best-matching projects, and includes your resume link. Every draft still passes the spam check before sending.</div>
                <p class="small muted">Needs an AI key on the server. Slower than templates, and every email is different.</p>`;
            return;
        }

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
        OutreachApi.toast("Template saved.", "ok");
    }

    async function load() {
        data = await OutreachApi.request("/api/templates");
        if (!viewing) viewing = data.selected;
        renderList();
        renderPreview();
    }

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
