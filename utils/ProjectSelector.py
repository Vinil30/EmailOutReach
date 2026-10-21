from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
import os
from dotenv import load_dotenv
load_dotenv()

class OutputStructure(BaseModel):
    projects : list[str]
class ProjectSelector:
    def __init__(self, projects_highlights=None):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        # name -> description, supplied from the student's saved projects.
        self.projects_highlights = projects_highlights or {}

    def select_projects(self, company_info):
        details = f"""
                    Company_info: {company_info},
                    projects: {self.projects_highlights}
                    """
        messages = [
            SystemMessage(content="""
                            You are an expert project matching evaluator.

                            Given company information and available projects:
                            - Select the 3 most relevant projects.
                            - Return only project names.
                            - Prefer projects with strong domain alignment.
                        """),
            HumanMessage(content=details)
        ]
        llm = ChatGroq(
            model=self.model,
            api_key = self.api_key
        )
        structured_llm = llm.with_structured_output(OutputStructure)
        response = structured_llm.invoke(messages)
        return response.projects
