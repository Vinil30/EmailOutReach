import os
from dotenv import load_dotenv
load_dotenv()
from langchain_groq import ChatGroq
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate


class OutputStructure(BaseModel):
    email_subject : str
    email_body : str


class EmailWriter:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")

    def WriteEmail(self, project_content, company_info, recipient_name,recipient_email):
        details = f"""
        Candidate Projects:
        {project_content}
        Company Information:
        {company_info}
        Recipient Information:
        Name: {recipient_name}
        Email: {recipient_email}
        """

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
                    You are an expert internship and job outreach email writer.

                    Your task is to create highly personalized cold outreach emails
                    for students seeking internships, jobs, collaborations,
                    or networking opportunities.

                    Instructions:

                    - Generate a concise and compelling email subject.
                    - Generate the email body as VALID HTML.
                    - Keep the email between 120 and 180 words.
                    - Personalize the email using the company information.
                    - Mention only the most relevant project(s).
                    - Explain why the candidate is reaching out.
                    - Highlight impact, not just technologies.
                    - Avoid generic praise and unnecessary flattery.
                    - Maintain a professional and respectful tone.
                    - Include a clear call to action.
                    - End with a professional sign-off.
                    - Do not invent facts that are not provided.
                    - Return ONLY the structured output fields.

                    The HTML body should use tags such as:
                    <p>, <strong>, <ul>, <li>, <br>

                    Recommended Structure:

                    1. Personalized introduction.
                    2. Why the company/team is relevant.
                    3. Most relevant project/experience.
                    4. Potential contribution.
                    5. Call to action.
                    6. Professional sign-off.

                    Example HTML format:

                    <p>Hello [Name],</p>

                    <p>
                    I recently came across your work at [Company] and was
                    particularly interested in ...
                    </p>

                    <p>
                    One project that aligns closely with your work is ...
                    </p>

                    <ul>
                        <li>Impact/Achievement 1</li>
                        <li>Impact/Achievement 2</li>
                    </ul>

                    <p>
                    I would love the opportunity to contribute and learn from
                    your team.
                    </p>

                    <p>
                    Thank you for your time and consideration.
                    </p>

                    <p>
                    Best Regards,<br>
                    [Candidate Name]
                    </p>
                    """
                ),
                ("human","{details}")
            ]
        )

        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=self.api_key
        )
        structured_llm = llm.with_structured_output(OutputStructure)
        chain = prompt | structured_llm
        response = chain.invoke({
            "details": details
        })

        return response

