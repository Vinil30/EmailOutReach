import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel

load_dotenv()


class OutputStructure(BaseModel):
    summarised_info: str


class Summarizer:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")

    def summarize(self, company_info):
        messages = [
            SystemMessage(
                content=(
                    "You are an expert summarizer. You will be given company information scraped "
                    "from the web. Summarize it into useful context for writing a personalized "
                    "outreach email and matching relevant candidate projects."
                )
            ),
            HumanMessage(content=f"Web scraped information: {company_info}"),
        ]
        llm = ChatGroq(
            model="openai/gpt-oss-120b",
            api_key=self.api_key,
        )
        structured_llm = llm.with_structured_output(OutputStructure)
        response = structured_llm.invoke(messages)
        return response.summarised_info
