from pydantic import BaseModel
import os
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

class OutputStructure(BaseModel):
    summarised_info: str

class Summarizer:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")

    def summarize(self, company_info):
        prompt = f"""
                    Web Scrapped Information : {company_info}
                """
        messages = [
            {"role":"system", "content":"You an expert summarizer, you will be given company information scrapped from web, your job is to summarise it and"
            "make information for ai to write an email and match relevant projects specific to the company"},
            {"role":"human","content":prompt}
        ]
        client = OpenAI(
            api_key = os.environ.get("GROQ_API_KEY"),
            base_url = os.environ.get("base_url")
        )
        response = client.beta.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages = messages,
            response_format=OutputStructure
        )
        result = response.choices[0].message.parsed

        return result.summarised_info
