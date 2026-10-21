// Shared by the Spam Lab page and the landing-page demo (which has no sidebar).
(async () => {
    if (document.getElementById("sidebar")) {
        await Layout.init();
    }
    const $ = id => document.getElementById(id);
    let campaignType = "outreach";

    const EXAMPLES = {
        spammy: {
            subject: "RE: URGENT - Your FREE offer expires TODAY!!!",
            body: "Dear Friend,\n\nCongratulations!!! You have been selected for an EXCLUSIVE deal. Act now — this is a limited time special offer with guaranteed results.\n\nClick here: https://bit.ly/xyz\nSign up: https://1.2.3.4/login\nBook a call today. Reach out now!\n\n[Your Name]"
        },
        clean: {
            subject: "Your warehouse-routing post and an idea",
            body: "<p>Hi Priya,</p><p>I read your team's write-up on cutting pick times at the Pune warehouse — the batching approach was clever, especially how you handled late orders.</p><p>I'm a final-year CS student and built a small routing simulator that tests batching rules against real order logs. On a public dataset it reduced walking distance by about 18%. I'd be glad to share it if it's useful for your next iteration.</p><p>Would you be open to a 15-minute chat in the next couple of weeks about internship openings on the operations engineering team?</p><p>Thanks for reading,<br>Aarav Mehta<br>github.com/aarav</p>"
        }
    };

    function toHtml(body) {
        if (/<(p|div|br|ul|table)\b/i.test(body)) return body;
        return body.split(/\n\s*\n/).map(chunk => chunk.trim()).filter(Boolean)
            .map(chunk => `<p>${OutreachApi.escapeHtml(chunk).replace(/\n/g, "<br>")}</p>`).join("");
    }

    const run = RiskView.live([$("subjectInput"), $("bodyInput")], () => {
        const body = toHtml($("bodyInput").value);
        OutreachApi.renderEmailPreview($("preview"), body || '<p style="color:#9a9ea6">Your email preview appears here.</p>', 140);
        return { subject: $("subjectInput").value, body, campaignType };
    }, risk => {
        $("result").innerHTML = RiskView.render(risk);
    }, 300);

    $("typeToggle").addEventListener("click", event => {
        const button = event.target.closest("button[data-type]");
        if (!button) return;
        campaignType = button.dataset.type;
        $("typeToggle").querySelectorAll("button").forEach(node => node.classList.toggle("active", node === button));
        run();
    });

    document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click", () => {
        const example = EXAMPLES[button.dataset.example];
        $("subjectInput").value = example.subject;
        $("bodyInput").value = example.body;
        run();
    }));

    if (document.body.dataset.autodemo) {
        $("subjectInput").value = EXAMPLES.spammy.subject;
        $("bodyInput").value = EXAMPLES.spammy.body;
    }
    run();
})();
