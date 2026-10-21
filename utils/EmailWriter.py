import os
from dotenv import load_dotenv
load_dotenv()
from langchain_groq import ChatGroq
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate


class OutputStructure(BaseModel):
    email_subject : str
    email_body : str


SHARED_RULES = """
                    - Generate a concise, specific email subject (under 60 characters, no ALL CAPS, no fake RE:/FWD:).
                    - Generate the email body as VALID HTML using tags such as <p>, <strong>, <ul>, <li>, <br>.
                    - Personalize using the company/recipient information provided.
                    - Do not invent facts that are not provided.
                    - Never leave placeholders like [Name] or {{{{field}}}} in the output; omit what you don't know.
                    - Avoid spam triggers: no "act now", "free", "guaranteed", "click here", excessive
                      exclamation marks, link shorteners, or more than one link.
                    - Include exactly one clear call to action.
                    - Return ONLY the structured output fields.
"""


def _profile_block(profile, keys):
    lines = [f"{key.replace('_', ' ').title()}: {profile[key]}" for key in keys if profile.get(key)]
    return "\n".join(lines) or "Not provided"


class EmailWriter:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

    def _invoke(self, system_prompt, details):
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured, so AI writing is unavailable. Use a template campaign instead.")
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{details}")])
        llm = ChatGroq(model=self.model, api_key=self.api_key)
        chain = prompt | llm.with_structured_output(OutputStructure)
        return chain.invoke({"details": details})

    def WriteEmail(self, project_content, company_info, recipient_name, recipient_email, profile=None, brief=None):
        profile = profile or {}
        brief = brief or {}
        details = f"""
        Candidate Profile:
        {_profile_block(profile, ("full_name", "headline", "school", "skills", "portfolio_url"))}
        What the candidate is looking for:
        {brief.get("goal") or profile.get("goal") or "Internship or entry-level opportunities"}
        Extra instructions from the candidate:
        {brief.get("instructions") or "None"}
        Candidate Projects:
        {project_content}
        Company Information:
        {company_info}
        Recipient Information:
        Name: {recipient_name}
        Email: {recipient_email}
        Sign-off to use:
        {profile.get("signature") or profile.get("full_name") or "Omit the name if unknown"}
        """

        system_prompt = f"""
                    You are an expert internship and job outreach email writer.

                    Your task is to create highly personalized cold outreach emails
                    for students seeking internships, jobs, collaborations,
                    or networking opportunities.

                    Instructions:
                    - Keep the email between 120 and 180 words.
                    - Mention only the most relevant project(s) and highlight impact, not just technologies.
                    - Explain why the candidate is reaching out to this company specifically.
                    - Avoid generic praise and unnecessary flattery.
                    - Maintain a professional and respectful tone.
                    - End with the provided professional sign-off.
                    {SHARED_RULES}

                    Recommended Structure:
                    1. Personalized introduction.
                    2. Why the company/team is relevant.
                    3. Most relevant project/experience.
                    4. Potential contribution.
                    5. Call to action.
                    6. Professional sign-off.
                    """
        return self._invoke(system_prompt, details)

    def WriteCampaignEmail(self, brief, profile, company_info, recipient_name, recipient_email):
        details = f"""
        Sender:
        {_profile_block(profile, ("full_name", "organization", "website"))}
        What we offer:
        {brief.get("offer") or profile.get("offer") or "Not provided"}
        Target audience:
        {profile.get("audience") or "Not provided"}
        Campaign goal / desired action:
        {brief.get("goal") or "Start a conversation"}
        Tone:
        {brief.get("tone") or profile.get("tone") or "Friendly and professional"}
        Extra instructions:
        {brief.get("instructions") or "None"}
        Recipient:
        Name: {recipient_name}
        Email: {recipient_email}
        Recipient / company context:
        {company_info or "Not provided"}
        Sign-off to use:
        {profile.get("signature") or profile.get("full_name") or profile.get("organization") or "The team"}
        """

        system_prompt = f"""
                    You are a senior email marketer writing permission-friendly, personal
                    campaign emails that land in the inbox, not the promotions or spam folder.

                    Instructions:
                    - Keep the email between 90 and 160 words.
                    - Lead with something relevant to the recipient, then the offer and its concrete benefit.
                    - Sound like one person writing to another, not a newsletter blast.
                    - No pricing hype, countdowns, or pressure tactics.
                    - Do not add an unsubscribe footer; it is appended automatically.
                    - End with the provided sign-off.
                    {SHARED_RULES}
                    """
        return self._invoke(system_prompt, details)

    def RewriteForDeliverability(self, email_subject, email_body, risk_reasons):
        details = f"""
        Current subject:
        {email_subject}

        Current HTML body:
        {email_body}

        Local pre-send spam-risk guard reasons:
        {risk_reasons}
        """

        system_prompt = """
                    You revise outreach and campaign emails after local spam-risk analysis.

                    Rewrite the message to reduce the specific risks provided by the local guard.
                    Preserve the core intent, factual claims, recipient, and professional tone.
                    Do not add tracking links, exaggerated sales language, urgency tricks,
                    misleading claims, or attachments. Remove any unfilled placeholders.
                    Never add a link, URL or website that is not already in the current body;
                    remove suspicious or shortened links instead of replacing them.
                    Keep any existing unsubscribe/footer paragraph unchanged.
                    Return VALID HTML for the body.
                    Return ONLY the structured output fields.
                    """
        return self._invoke(system_prompt, details)
