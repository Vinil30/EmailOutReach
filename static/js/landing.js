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

    // ---------- Hero: simulated automation console ----------
    // Fictional companies, so the demo never implies a real company received these emails.
    const COMPANIES = [
        ["Northwind Labs", "Talent Partner"],
        ["Orbit Robotics", "Engineering Manager"],
        ["Kestrel Health", "University Recruiter"],
        ["Lumen Pay", "Head of Data"],
        ["Brightloop", "Hiring Manager"],
        ["Harbor Analytics", "Tech Recruiter"],
        ["Tidewater AI", "ML Team Lead"],
        ["Copperline", "Talent Acquisition"]
    ];
    const feed = $("consoleFeed");
    const consoleEl = $("console");
    let running = true;
    let used = 37;
    let companyIndex = 0;
    let countdown = 102;

    function addFeedItem(animate = true) {
        const [company, role] = COMPANIES[companyIndex % COMPANIES.length];
        companyIndex += 1;
        const item = document.createElement("li");
        if (!animate) item.style.animation = "none";
        item.innerHTML = `<span class="av">${esc(company[0])}</span><span><b>${esc(company)}</b><small>${esc(role)}</small></span><span class="when">Sent ✓<br><small>just now</small></span>`;
        feed.prepend(item);
        [...feed.children].slice(4).forEach(node => node.remove());
        [...feed.children].slice(1).forEach((node, i) => {
            const when = node.querySelector(".when small");
            if (when) when.textContent = `${(i + 1) * 2} min ago`;
        });
    }

    function paintConsole() {
        const minutes = Math.floor(countdown / 60);
        const seconds = String(countdown % 60).padStart(2, "0");
        $("consoleNext").textContent = running ? `Next email in ${minutes}:${seconds}` : "Paused. Start resumes at the next company.";
        $("consoleBadge").textContent = running ? "Running" : "Stopped";
        $("consoleBadge").className = `badge ${running ? "ok live" : "plain"}`;
        $("consoleToggle").textContent = running ? "Stop" : "Start";
        $("consoleUsed").textContent = used;
        $("consoleBar").style.width = `${Math.min(100, (used / dailyCap()) * 100)}%`;
        consoleEl.classList.toggle("paused", !running);
    }

    // The demo meter follows the real daily cap, which the admin can change.
    function dailyCap() {
        return Number(consoleEl.querySelector("[data-daily-cap]")?.textContent) || 100;
    }

    for (let i = 0; i < 3; i++) addFeedItem(false);
    paintConsole();
    $("consoleToggle").addEventListener("click", () => { running = !running; paintConsole(); });

    // Time runs ~30x fast: a 1-3 minute gap passes in a few seconds.
    setInterval(() => {
        if (!running || document.hidden) return;
        countdown -= 30;
        if (countdown <= 0) {
            addFeedItem();
            used = used >= dailyCap() ? Math.round(dailyCap() * 0.37) : used + 1;
            countdown = 60 + Math.floor(Math.random() * 120);
        }
        paintConsole();
    }, reduced ? 4000 : 1000);

    // ---------- Template vs AI demo ----------
    const WRITER = [
        { to: "Ayesha Khan, Northwind Labs", first: "Ayesha", company: "Northwind Labs",
          ai: { subject: "Fraud signals at Northwind and a project of mine",
                hook: "Northwind's move into real-time settlement means fraud checks have to run in milliseconds.",
                project: "CostIQ, a multi-agent system that flags payment anomalies in ecommerce data",
                fit: "I'd love to bring that same anomaly-detection work to your risk team." } },
        { to: "Daniel Okafor, Orbit Robotics", first: "Daniel", company: "Orbit Robotics",
          ai: { subject: "Warehouse robots and real-time vision",
                hook: "Orbit's fleet has to see shelves, people and pallets reliably in busy warehouses.",
                project: "InfSec, a real-time YOLO and pose-estimation monitor that halved false alarms",
                fit: "That perception work maps closely to what your robots need on the floor." } },
        { to: "Mei Lin, Kestrel Health", first: "Mei", company: "Kestrel Health",
          ai: { subject: "Reliable ML for clinical triage",
                hook: "Clinical AI at Kestrel can't fail silently; a missed signal matters.",
                project: "Self-Healing DAG, a LoRA DistilBERT pipeline that detects failing steps and reroutes at runtime",
                fit: "Building models that stay reliable is exactly what I want to keep doing." } }
    ];
    let writerMode = "template";
    let writerIndex = 0;

    function renderWriter() {
        const item = WRITER[writerIndex];
        const swap = text => `<span class="chg">${esc(text)}</span>`;
        $("writerTo").textContent = item.to;
        if (writerMode === "template") {
            $("writerSubject").innerHTML = `Internship at ${swap(item.company)}`;
            $("writerBody").innerHTML = `Hi ${swap(item.first)},

I'm Sam, an ML engineer building agentic systems (IIIT Kota).
I'm reaching out because I'd love to contribute to ${swap(item.company)}.

Recently I built InterviewBot: an LLM mock interviewer that scores answers live.

My resume: drive.google.com/…/view

I'm looking for a Summer 2027 ML internship. Would you be open to a quick chat?

Best regards,
Sam`;
            $("writerScore").textContent = "Spam score 0.0";
            $("writerNote").innerHTML = "<b>Template</b> (all plans): the same email for everyone. Only the highlighted name and company change, and your featured project stays the same.";
        } else {
            const ai = text => `<span class="ai">${esc(text)}</span>`;
            $("writerSubject").innerHTML = ai(item.ai.subject);
            $("writerBody").innerHTML = `Hi ${esc(item.first)},

${ai(item.ai.hook)}

I recently built ${ai(item.ai.project)}. ${ai(item.ai.fit)}

I'm Sam, an ML engineer at IIIT Kota, looking for a Summer 2027 internship. My resume: drive.google.com/…/view

Would you be open to a 15-minute chat?

Best,
Sam`;
            $("writerScore").textContent = "Spam score 0.4";
            $("writerNote").innerHTML = "<b>AI-personalized</b> (Premium): researches each company, picks your best-matching project, and writes the highlighted parts fresh for every recipient.";
        }
        const body = $("writerBody");
        body.style.animation = "none";
        void body.offsetWidth;
        body.style.animation = "";
    }

    $("writerMode").addEventListener("click", event => {
        const button = event.target.closest("button[data-mode]");
        if (!button) return;
        writerMode = button.dataset.mode;
        $("writerMode").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        renderWriter();
    });
    $("writerCompanies").addEventListener("click", event => {
        const button = event.target.closest("button[data-company]");
        if (!button) return;
        writerIndex = Number(button.dataset.company);
        $("writerCompanies").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        renderWriter();
    });
    renderWriter();

    // ---------- Time-saved estimate ----------
    function renderSaver() {
        const minutes = Number($("saverInput").value);
        const weekly = Math.round((100 * minutes) / 60);
        $("saverMinutes").textContent = minutes;
        $("saverWeek").textContent = weekly;
        $("saverMonth").textContent = weekly * 4;
    }
    $("saverInput").addEventListener("input", renderSaver);
    renderSaver();

    // ---------- Spam check lab ----------
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
        medium: ["Held for review", "It waits in your queue with the exact fixes. On Premium, AI rewrites it first."],
        high: ["Almost certainly spam", "Mailzen would never send this. It's held until it's fixed."]
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
})();
