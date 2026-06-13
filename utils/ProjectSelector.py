from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
import os
from dotenv import load_dotenv
load_dotenv()

class OutputStructure(BaseModel):
    projects : list[str]
class ProjectSelector:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.projects_highlights = {

    "SovenLegal":
        "End-to-end LegalTech AI platform with FAISS-based case retrieval, case solvability "
        "prediction (ML classifier), document validation, deadline tracking, and lawyer strategy "
        "evaluation. Built for Indian legal workflows using LLMs and agentic AI.",

    "CostIQ": 
        "Ecommerce cost optimization agent using LangGraph and Groq. "
        "Analyzes product/order datasets (Olist) to surface cost reduction insights "
        "via multi-agent reasoning.Orchestrated 5 agents for schema unification, business analysis,"
        "anomaly detection, action generation, and validation to identify operational inefficiencies and recommend cost-saving actions.",


    "SelfHealingClassificationDAG":
        "LangGraph-based intelligent DAG workflow using fine-tuned DistilBERT with LoRA adapters. "
        "Detects node-level failures at runtime, dynamically reroutes execution, and improves "
        "classification reliability through self-healing decision paths.",

    "FailureAwareCodeGenerationAgent":
        "Research-oriented agentic coding system (submitted to IEEE) combining Gemini, LangGraph "
        "state machine, unit-test execution, 9-feature ANN risk estimator with Youden's J-optimized "
        "threshold, FAISS retrieval memory, and conformal prediction for failure-aware code generation.",

    "ArenaPulse": 
        "Agentic AI newsroom built with LangGraph that autonomously scrapes web sources, "
        "generates structured news articles, creates AI-powered visuals, and stores content in MongoDB. "
        "Includes automated scheduled execution via GitHub Actions/Cron jobs and an interactive AI news assistant.",

    "AutoBookflow":
        "AI-powered long-form book editing pipeline with LLM-driven rewriting and review agents, "
        "semantic search over manuscript versions, version management, and human-in-the-loop "
        "collaborative editing using vector databases.",

    "Youtube Automation":
        "Multi-agent AI platform for Youtube automation where personality-driven LLMs autonomously generate, schedule, "
        "and publish content across multiple genres in youtube. Supports user-created custom AI personas "
        "with distinct tone, style, and posting behavior. Involves script generation -> Video generation with subtitles using FFMPEG -> Automatically uplaods to youtube using Langgraph automation in one click",
   
    "BidMind":
        "Flask-based AI proposal and pitch management platform for three roles: businesses, entrepreneurs, "
        "and investors. Features FAISS vector search with HuggingFace sentence embeddings for semantic pitch "
        "retrieval, LangGraph-powered investor decision workflows (match/maybe/reject), Groq LLM-generated "
        "feed summaries, MongoDB Atlas for multi-collection data, and role-specific dashboards with analytics, "
        "preference tuning, and shareable proposal links.",

    "InterviewBot":
        "LLM-powered mock interview assistant that conducts role-specific interactive interviews, "
        "evaluates candidate responses in real time, scores answers, and delivers personalized "
        "feedback and improvement suggestions for students.",

    "AIResumeBuilder":
        "Generative AI application that takes user profile and target job description as input, "
        "uses LLM-based content enhancement to rewrite and tailor resume sections, and outputs "
        "an optimized, ATS-friendly professional resume.",

     "LangGraph Cold Email Automation Agent": 
        "Agentic pipeline that scrapes founder/CTO profiles, "
        "personalizes cold outreach emails using LLM reasoning, "
        "and scales LinkedIn/email DM campaigns for job/internship outreach.",

    "SmartFarming.AI":
        "Multilingual voice-first AgriTech assistant using LangGraph hierarchical multi-agent "
        "orchestration with 5 ML models integrated as tools, Whisper ASR for speech-to-text, "
        "and real-time crop advisory. Targets low-literacy Indian farmers via audio-native UX.",

    "Auralytix":
        "LangGraph and RAG-powered content intelligence system that extracts transcripts from YouTube "
        "and Instagram, indexes them into a vector store, and enables cross-platform content comparison "
        "and conversational question answering over indexed media."
        "Audio intelligence platform that extracts audio from YouTube and video URLs via yt-dlp "
        "and FFmpeg, transcribes with Whisper ASR, runs speaker diarization, and enables ",

    "InfSec":
        "Real-time infant safety monitoring system using Flask, MongoDB, YOLO object detection, "
        "and MediaPipe pose estimation. Async background worker queue for low-latency video streaming, "
        "with IoU and std-dev tuned tracker to minimize false positives.",

}
        
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
            model="llama-3.3-70b-versatile",
            api_key = self.api_key
        )
        structured_llm = llm.with_structured_output(OutputStructure)
        response = structured_llm.invoke(messages)
        return response.projects
