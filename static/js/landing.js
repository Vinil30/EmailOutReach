// Landing page interactions. Content stays readable without JS; motion respects reduced-motion settings.
(() => {
    const $ = id => document.getElementById(id);
    const esc = OutreachApi.escapeHtml;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

    // ---------- Nav, progress, reveal ----------
    if (OutreachApi.getToken()) {
        $("navActions").innerHTML = '<button type="button" class="theme-toggle" data-theme-toggle></button><a class="btn primary" href="/dashboard">Open dashboard</a>';
    }
    OutreachApi.bindThemeToggles();

    const nav = $("nav");
    const progress = $("scrollProgress");
    function onScroll() {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        progress.style.transform = `scaleX(${max > 0 ? window.scrollY / max : 0})`;
        nav.classList.toggle("scrolled", window.scrollY > 8);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    const navLinks = [...document.querySelectorAll(".lp-links a")];
    const sectionObserver = new IntersectionObserver(entries => entries.forEach(entry => {
        if (entry.isIntersecting) {
            navLinks.forEach(link => link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`));
        }
    }), { rootMargin: "-45% 0px -50% 0px" });
    navLinks.forEach(link => {
        const target = document.querySelector(link.getAttribute("href"));
        if (target) sectionObserver.observe(target);
    });

    const revealObserver = new IntersectionObserver(entries => entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("visible");
        entry.target.querySelectorAll("[data-count]").forEach(countUp);
        revealObserver.unobserve(entry.target);
    }), { threshold: 0.1 });
    document.querySelectorAll(".reveal").forEach(node => revealObserver.observe(node));

    function countUp(node) {
        const target = Number(node.dataset.count);
        const suffix = node.dataset.suffix || "";
        if (reduced || target === 0) { node.textContent = `${target}${suffix}`; return; }
        const start = performance.now();
        const step = now => {
            const t = Math.min(1, (now - start) / 1100);
            node.textContent = `${Math.round(target * (1 - Math.pow(1 - t, 3)))}${suffix}`;
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    // ---------- Hero: emails passing through the guard ----------
    const EMAILS = [
        { to: "Alex Rivera", org: "Hugging Face", subject: "Internship idea: self-healing ML pipelines", score: 0.4 },
        { to: "Priya Kapoor", org: "Brightloop", subject: "URGENT: FREE growth audit for Brightloop!!!", score: 7.6,
          flags: ["ALL CAPS", "Pressure words", "!!!"], fixed: "A quick idea for Brightloop's ad spend", after: 0.6 },
        { to: "Keller Rinaudo", org: "Zipline", subject: "Real-time vision work for your drone fleet", score: 0.7 },
        { to: "Daniel Okafor", org: "Northwind", subject: "RE: Hi [Name], act now — limited offer", score: 6.4,
          flags: ["Fake RE:", "Placeholder left in", "“Act now”"], fixed: "Daniel, a two-week audit for Northwind", after: 0.5 },
        { to: "Mei Lin", org: "Harbor Analytics", subject: "Cutting warehouse walk time at Harbor", score: 0.3 }
    ];
    const stage = $("stage");
    const guard = stage.querySelector(".lp-guard");
    const slot = $("guardSlot");
    const drafts = $("laneDrafts");
    const inbox = $("laneInbox");
    const stats = { checked: 0, fixed: 0, sent: 0 };
    let paused = false;
    stage.addEventListener("pointerenter", () => { paused = true; });
    stage.addEventListener("pointerleave", () => { paused = false; });

    async function sleep(ms) {
        let left = ms;
        while (left > 0 || paused || document.hidden) {
            await wait(60);
            if (!paused && !document.hidden) left -= 60;
        }
    }

    function mini(email, extra = "", note = "") {
        return `<div class="lp-mini ${extra}"><b>${esc(email.to)}</b><span>${esc(email.org)}${note ? ` · <span class="note">${note}</span>` : ""}</span></div>`;
    }

    function renderDrafts(index) {
        drafts.innerHTML = [1, 2, 3].map(offset => mini(EMAILS[(index + offset) % EMAILS.length])).join("");
    }

    async function countTo(node, from, to, ms) {
        const steps = Math.max(1, Math.round(ms / 40));
        for (let i = 1; i <= steps; i++) {
            node.textContent = (from + (to - from) * (i / steps)).toFixed(1);
            await sleep(40);
        }
    }

    function bumpStat(key) {
        stats[key] += 1;
        $(`stat${key[0].toUpperCase()}${key.slice(1)}`).textContent = stats[key];
    }

    async function runStage() {
        for (let index = 0; ; index = (index + 1) % EMAILS.length) {
            const email = EMAILS[index];
            drafts.querySelector(".lp-mini")?.classList.add("leaving");
            await sleep(300);
            renderDrafts(index);

            slot.querySelector(".lp-card")?.remove();
            slot.insertAdjacentHTML("beforeend", `
                <div class="lp-card">
                    <div class="lp-card-top">
                        <div class="lp-avatar">${esc(email.to[0])}</div>
                        <div class="lp-card-who"><b>${esc(email.to)}</b><span>${esc(email.org)}</span></div>
                        <div class="lp-score-pill">–</div>
                    </div>
                    <div class="lp-card-subject">${esc(email.subject)}</div>
                    <div class="lp-lines"><i></i><i></i><i></i></div>
                    <div class="lp-flags"></div>
                    <div class="lp-card-status">Scanning 14 checks…</div>
                </div>`);
            const card = slot.querySelector(".lp-card");
            const pill = card.querySelector(".lp-score-pill");
            const flags = card.querySelector(".lp-flags");
            const status = card.querySelector(".lp-card-status");
            const subject = card.querySelector(".lp-card-subject");

            await sleep(400);
            guard.classList.add("scanning");
            await countTo(pill, 0, email.score, 900);
            guard.classList.remove("scanning");
            bumpStat("checked");

            if (email.flags) {
                card.classList.add("flagged");
                pill.classList.add("bad");
                status.textContent = `Held — score ${email.score.toFixed(1)} is over 4`;
                for (const flag of email.flags) {
                    flags.insertAdjacentHTML("beforeend", `<span class="badge bad">${esc(flag)}</span>`);
                    await sleep(260);
                }
                await sleep(700);
                status.textContent = "Rewriting with AI…";
                subject.classList.add("swap");
                await sleep(500);
                subject.textContent = email.fixed;
                subject.classList.remove("swap");
                flags.innerHTML = `<span class="badge ok">${email.flags.length} issues fixed</span>`;
                guard.classList.add("scanning");
                status.textContent = "Re-checking…";
                await countTo(pill, email.score, email.after, 800);
                guard.classList.remove("scanning");
                pill.classList.remove("bad");
                card.classList.remove("flagged");
                bumpStat("fixed");
            }

            card.classList.add("clean");
            pill.classList.add("ok");
            status.textContent = "Passed · sending from your Gmail";
            await sleep(1100);

            card.classList.add("out");
            await sleep(420);
            card.remove();
            inbox.insertAdjacentHTML("afterbegin", mini(email, "delivered", email.flags ? "rewritten" : ""));
            [...inbox.children].slice(4).forEach(node => node.remove());
            bumpStat("sent");
            await sleep(500);
        }
    }
    renderDrafts(-1);
    runStage();

    // ---------- Lab: try to get past the guard ----------
    const CLEAN = {
        subject: "Your warehouse-routing post and a small idea",
        body: "Hi Priya,\n\nI read your team's write-up on cutting pick times at the Pune warehouse. The batching approach was clever, especially how you handled late orders.\n\nI'm a final-year CS student and built a routing simulator that tests batching rules against real order logs. On a public dataset it reduced walking distance by about 18%. You can try it here: https://github.com/aarav/route-sim\n\nWould you be open to a 15-minute chat in the next couple of weeks?\n\nThanks,\nAarav Mehta"
    };
    const subjectInput = $("subjectInput");
    const bodyInput = $("bodyInput");
    const backdrop = $("bodyBackdrop");
    const habitInputs = [...document.querySelectorAll("[data-habit]")];
    let base = { ...CLEAN };
    let campaignType = "outreach";
    let lastRisk = null;
    let shownScore = 0;

    // Each habit is a reversible transform applied on top of the base draft.
    function applyHabits(draft, on) {
        let subject = draft.subject;
        const paras = draft.body.split(/\n\s*\n/);
        const insertBeforeAsk = text => paras.splice(Math.max(1, paras.length - 2), 0, text);
        if (on.placeholder) {
            paras[0] = "Hi [Name],";
            const sign = paras[paras.length - 1].split("\n");
            sign[sign.length - 1] = "[Your Name]";
            paras[paras.length - 1] = sign.join("\n");
        }
        if (on.caps) {
            subject = subject.toUpperCase();
            if (paras.length > 2) paras[1] = paras[1].toUpperCase();
        }
        if (on.short) {
            let replaced = false;
            for (let i = 0; i < paras.length; i++) {
                paras[i] = paras[i].replace(/https?:\/\/\S+/g, () => { replaced = true; return "https://bit.ly/3xYz9"; });
            }
            if (!replaced) insertBeforeAsk("Details here: https://bit.ly/3xYz9");
        }
        if (on.bang) {
            subject = `${subject}!!!`;
            const ask = Math.max(0, paras.length - 2);
            paras[ask] = paras[ask].replace(/[.?!]*$/, "!!!");
        }
        if (on.urgency) insertBeforeAsk("Act now: this is a limited time special offer, and results are guaranteed.");
        if (on.money) insertBeforeAsk("Save $500 today: 50% off, just $99 for your first month.");
        if (on.fake) subject = `RE: ${subject}`;
        return { subject, body: paras.join("\n\n") };
    }

    function habitState() {
        return Object.fromEntries(habitInputs.map(input => [input.dataset.habit, input.checked]));
    }

    function rebuild() {
        const draft = applyHabits(base, habitState());
        subjectInput.value = draft.subject;
        bodyInput.value = draft.body;
        scheduleCheck(0);
    }

    function toHtml(text) {
        return text.split(/\n\s*\n/).map(chunk => chunk.trim()).filter(Boolean)
            .map(chunk => `<p>${esc(chunk).replace(/\n/g, "<br>")}</p>`).join("");
    }

    function patterns(risk) {
        const list = [
            /\b[A-Z]{4,}\b/g,
            /[!?]{2,}/g,
            /https?:\/\/(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|is\.gd|buff\.ly|\d{1,3}(?:\.\d{1,3}){3})\S*/gi,
            /\[[^\]\n]*(?:name|company|title|role|link|email)[^\]\n]*\]|\{\{[^}]*\}\}/gi,
            /[$€£₹]\s?\d+|\b\d+\s?%\s?off\b/gi,
            /\b(?:urgent|immediately|asap|limited|exclusive|guaranteed|free|now)\b/gi
        ];
        for (const phrase of risk?.signals?.promotional_phrase_hits || []) {
            list.push(new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"));
        }
        return list;
    }

    function paintHighlights() {
        const text = bodyInput.value;
        const ranges = [];
        for (const pattern of patterns(lastRisk)) {
            for (const match of text.matchAll(pattern)) ranges.push([match.index, match.index + match[0].length]);
        }
        ranges.sort((a, b) => a[0] - b[0]);
        let html = "";
        let cursor = 0;
        for (const [start, end] of ranges) {
            if (end <= cursor) continue;
            const from = Math.max(start, cursor);
            html += `${esc(text.slice(cursor, from))}<mark class="hl">${esc(text.slice(from, end))}</mark>`;
            cursor = end;
        }
        backdrop.innerHTML = `${html}${esc(text.slice(cursor))}\n`;
        backdrop.scrollTop = bodyInput.scrollTop;
    }

    function animateScore(target) {
        const from = shownScore;
        const start = performance.now();
        const step = now => {
            const t = reduced ? 1 : Math.min(1, (now - start) / 600);
            shownScore = from + (target - from) * (1 - Math.pow(1 - t, 3));
            $("scoreValue").textContent = shownScore.toFixed(1);
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    const VERDICTS = {
        low: ["Clear to send", "In auto mode this goes straight out from your Gmail."],
        medium: ["Held for review", "One AI rewrite targets these issues. If it's still risky, it waits for you."],
        high: ["Almost certainly spam", "This would be held, rewritten, and kept out of your recipients' inboxes."]
    };

    function paintResult(risk) {
        lastRisk = risk;
        const score = Number(risk.score);
        const level = (risk.level || "LOW").toLowerCase();
        $("ring").className = `lp-ring ${level}`;
        $("ringFill").style.strokeDashoffset = `${326.7 * (1 - score / 10)}`;
        animateScore(score);
        document.querySelector(".lp-verdict-panel").className = `lp-verdict-panel ${level}`;
        $("verdictTitle").textContent = VERDICTS[level][0];
        $("verdictSub").textContent = VERDICTS[level][1];
        $("barMarker").style.left = `${Math.min(100, score * 10)}%`;
        $("barFill").style.width = `${Math.min(100, score * 10)}%`;

        const checks = risk.checks || [];
        const failing = checks.filter(check => !check.passed).sort((a, b) => b.weight - a.weight);
        const tips = Object.fromEntries((risk.reasons || []).map((reason, i) => [reason, (risk.suggestions || [])[i]]));
        $("passCount").textContent = `${checks.length - failing.length} of ${checks.length} passing`;
        $("issues").innerHTML = failing.length
            ? failing.map(check => `
                <div class="lp-issue">
                    <b>${esc(check.label)}</b><span class="pts">+${check.weight}</span>
                    <p>${esc(tips[check.key] || check.detail)}</p>
                </div>`).join("")
            : `<div class="lp-allclear">✓ Every check passes. Try switching on a habit above.</div>`;
        paintHighlights();
    }

    let checkTimer = null;
    let checkSeq = 0;
    function scheduleCheck(delay = 250) {
        paintHighlights();
        clearTimeout(checkTimer);
        checkTimer = setTimeout(async () => {
            const mine = ++checkSeq;
            try {
                const risk = await RiskView.check(subjectInput.value, toHtml(bodyInput.value), campaignType);
                if (mine === checkSeq) paintResult(risk);
            } catch {
                $("verdictTitle").textContent = "Checker offline";
                $("verdictSub").textContent = "Start the app server to score drafts live.";
            }
        }, delay);
    }

    // Typing makes the edited text the new base, so habits stay reversible on top of it.
    function captureEdit() {
        habitInputs.forEach(input => { input.checked = false; });
        base = { subject: subjectInput.value, body: bodyInput.value };
        scheduleCheck();
    }
    subjectInput.addEventListener("input", captureEdit);
    bodyInput.addEventListener("input", captureEdit);
    bodyInput.addEventListener("scroll", () => { backdrop.scrollTop = bodyInput.scrollTop; });
    habitInputs.forEach(input => input.addEventListener("change", rebuild));
    $("labReset").addEventListener("click", () => {
        base = { ...CLEAN };
        habitInputs.forEach(input => { input.checked = false; });
        rebuild();
    });
    $("typeToggle").addEventListener("click", event => {
        const button = event.target.closest("button[data-type]");
        if (!button) return;
        campaignType = button.dataset.type;
        $("typeToggle").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        scheduleCheck(0);
    });
    rebuild();

    // ---------- Modes ----------
    const modeButtons = [...document.querySelectorAll("#modeSwitch button")];
    modeButtons.forEach(button => button.addEventListener("click", () => {
        modeButtons.forEach(node => node.classList.toggle("active", node === button));
        document.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== button.dataset.mode; });
    }));

    function replay(node) {
        node.style.animation = "none";
        void node.offsetWidth;
        node.style.animation = "";
    }

    const COMPANIES = [
        { picks: ["Self-Healing DAG", "InterviewBot"], line: (a, b) => `Hi Alex, your team's work on open models is exactly where I want to grow. I built <span class="tok-proj">${a}</span>, a LoRA DistilBERT pipeline that reroutes around failing nodes, and <span class="tok-proj">${b}</span>, an LLM interviewer that scores answers live…` },
        { picks: ["InfSec", "SmartFarming.AI"], line: (a, b) => `Hi Keller, reliable perception is what makes last-mile drops safe. My project <span class="tok-proj">${a}</span> runs YOLO and pose estimation in real time, and <span class="tok-proj">${b}</span> coordinates field agents by voice…` },
        { picks: ["CostIQ", "BidMind"], line: (a, b) => `Hi Shashank, payments at Razorpay's scale depend on catching anomalies early. I built <span class="tok-proj">${a}</span>, a five-agent system that flags cost outliers, and <span class="tok-proj">${b}</span>, which matches pitches with FAISS search…` }
    ];
    const projectCards = [...document.querySelectorAll(".lp-project")];
    function pickCompany(index) {
        const company = COMPANIES[index];
        document.querySelectorAll("#companyList button").forEach(button => button.classList.toggle("active", Number(button.dataset.company) === index));
        projectCards.forEach(card => {
            const picked = company.picks.includes(card.querySelector("b").textContent);
            card.classList.toggle("picked", picked);
            card.classList.toggle("dim", !picked);
        });
        $("studentSnippet").innerHTML = company.line(...company.picks);
        replay($("studentSnippet"));
    }
    $("companyList").addEventListener("click", event => {
        const button = event.target.closest("button[data-company]");
        if (button) pickCompany(Number(button.dataset.company));
    });
    pickCompany(0);

    const ROWS = [
        { first: "Priya", company: "Brightloop", city: "Bengaluru" },
        { first: "Daniel", company: "Northwind", city: "Lagos" },
        { first: "", company: "Harbor", city: "" }
    ];
    function pickRow(index) {
        const row = ROWS[index];
        document.querySelectorAll("#contactList button").forEach(button => button.classList.toggle("active", Number(button.dataset.row) === index));
        const field = (value, fallback) => value ? `<span class="tok-merge">${esc(value)}</span>` : `<span class="tok-fallback">${esc(fallback)}</span>`;
        $("campaignSnippet").innerHTML = `Hi ${field(row.first, "there")}, saw ${field(row.company, "your team")} is growing in ${field(row.city, "your region")}. We help teams like yours find wasted ad spend in a two-week audit. Would a 15-minute call next week be useful?<span class="foot">Brightloop Analytics · 12 MG Road, Bengaluru<br>Not interested? Reply “unsubscribe” and we won't email you again.</span>`;
        replay($("campaignSnippet"));
    }
    $("contactList").addEventListener("click", event => {
        const button = event.target.closest("button[data-row]");
        if (button) pickRow(Number(button.dataset.row));
    });
    pickRow(0);
})();
