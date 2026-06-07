from tavily import TavilyClient
import os
from dotenv import load_dotenv

class WebSearchAgent:
    def __init__(self, query):
        self.search_api_key = os.environ.get("search_api_key")
        self.client = TavilyClient(api_key=self.search_api_key)
        self.query = query
 
    def search_agent(self):
        response = self.client.search(
            query=self.query,
            max_results=1,
            search_depth="advanced",
            include_raw_content=True,  
            include_answer=True,       
            include_images=False,
            include_domains=[],        
            exclude_domains=["youtube.com", "pinterest.com"]  
        )  
        output = []
        for result in response["results"]:
            output.append({
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "raw_content": result.get("raw_content", ""),  
                "url": result.get("url", "")
            })
        
        return output