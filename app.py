# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import re
from section_parser import get_relevant_sections_smart

# Load environment variables
load_dotenv()

app = FastAPI(title="Intergas Support API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load the manual content
MANUAL_PATH = Path(__file__).parent / "data" / "processed" / "intergas_full_agent.md"

def load_manual():
    """Load the Intergas manual content"""
    try:
        with open(MANUAL_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Manual file not found")

# Cache the manual content
MANUAL_CONTENT = load_manual()

# Request/Response models
class ChatRequest(BaseModel):
    question: str
    model: str  # HRE 24/18 A, HRE 28/24 A, etc.
    conversation_history: Optional[List[dict]] = []

class ChatResponse(BaseModel):
    answer: str
    source: str
    confidence: float

def extract_relevant_sections(question: str, manual_content: str, max_context_length: int = 8000) -> str:
    """Extract relevant sections from the manual based on the question"""
    
    # Keywords to search for based on the question
    keywords = []
    q_lower = question.lower()
    
    # Extract keywords based on common topics
    if 'storing' in q_lower or 'error' in q_lower or 'code' in q_lower:
        keywords.extend(['storing', 'storingscode', '## 8', 'sensorfout', 'vlamsignaal'])
    if 'druk' in q_lower or 'bar' in q_lower or 'pressure' in q_lower:
        keywords.extend(['waterdruk', 'bar', 'vullen', 'druksensor', 'druk'])
    if 'tapcomfort' in q_lower or 'warm water' in q_lower:
        keywords.extend(['tapcomfort', 'tapwater', 'warmwater', 'eco', 'comfort'])
    if 'temperatuur' in q_lower or 'temp' in q_lower:
        keywords.extend(['temperatuur', 'graden', '�C', 'thermostat'])
    if 'vul' in q_lower or 'ontlucht' in q_lower:
        keywords.extend(['vullen', 'ontluchten', 'bijvullen', '## 6.1'])
    if 'parameter' in q_lower or 'instel' in q_lower:
        keywords.extend(['parameter', 'instellen', 'servicecode', '## 7'])
    if 'onderhoud' in q_lower:
        keywords.extend(['onderhoud', '## 9'])
    
    # If no specific keywords, add general terms from the question
    if not keywords:
        # Extract potential keywords from the question (words > 4 chars)
        keywords = [word for word in q_lower.split() if len(word) > 4]
    
    # Find relevant sections
    lines = manual_content.split('\n')
    relevant_sections = []
    context_lines = 1000  # Lines of context around matches
    print(f"Searching for keywords: {keywords}")
    print(f"context_lines: {context_lines}")
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in keywords):
            # Get context around the match
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            section = '\n'.join(lines[start:end])
            
            # Add page reference if available
            page_match = re.search(r'<!-- PAGE_REF: (\d+) -->', section)
            if page_match:
                section = f"[Pagina {page_match.group(1)}]\n{section}"
            
            relevant_sections.append(section)
    
    # Combine sections and limit to max length
    combined = '\n\n---\n\n'.join(relevant_sections)
    if len(combined) > max_context_length:
        combined = combined[:max_context_length]
    
    return combined if combined else manual_content[:max_context_length]

def create_system_prompt(model: str) -> str:
    """Create the system prompt for the LLM"""
    return f"""Je bent een technische expert voor Intergas CV-ketels, specifiek voor het model {model}.

Je taak is om nauwkeurige, praktische antwoorden te geven op technische vragen van installateurs en monteurs.

BELANGRIJKE INSTRUCTIES:
1. Geef ALTIJD de paginanummers waar de informatie vandaan komt (bijv. "Zie pagina 42")
2. Wees specifiek en praktisch in je antwoorden
3. Gebruik stap-voor-stap instructies waar relevant
4. Vermeld belangrijke waarschuwingen met �
5. Als informatie niet in de handleiding staat, geef dat eerlijk aan
6. Gebruik Nederlandse technische terminologie
7. Verwijs naar specifieke secties (bijv. "Sectie 7.2: Parameters")
8. Noem relevante storingscodes als die van toepassing zijn

Formaat je antwoord als:
- Duidelijke stappen of uitleg
- Relevante waarschuwingen
- Bronvermelding: [Sectie/Hoofdstuk] - Pagina X

Antwoord altijd in het Nederlands."""

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Intergas Support API"}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Handle chat requests about Intergas boilers"""
    
    try:
        # Extract relevant sections from the manual
        relevant_context = extract_relevant_sections(request.question, MANUAL_CONTENT)
        
        # Create the messages for OpenAI
        messages = [
            {"role": "system", "content": create_system_prompt(request.model)},
            {"role": "system", "content": f"Relevante informatie uit de handleiding:\n\n{relevant_context}"}
        ]
        
        # Add conversation history if provided
        for msg in request.conversation_history[-5:]:  # Keep last 5 messages for context
            messages.append(msg)
        
        # Add the current question
        messages.append({
            "role": "user",
            "content": f"Model: {request.model}\nVraag: {request.question}"
        })
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4",  # or "gpt-3.5-turbo" for faster/cheaper responses
            messages=messages,
            temperature=0.3,  # Lower temperature for more consistent technical answers
            max_tokens=1000
        )
        
        answer = response.choices[0].message.content
        
        # Extract source information from the answer
        source_match = re.search(r'(Pagina|Sectie|Hoofdstuk).*?\d+', answer)
        source = source_match.group(0) if source_match else f"Intergas {request.model} Handleiding"
        
        # Calculate confidence based on context relevance
        confidence = 0.9 if relevant_context and len(relevant_context) > 500 else 0.7
        
        return ChatResponse(
            answer=answer,
            source=source,
            confidence=confidence
        )
        
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/api/models")
async def get_models():
    """Get available boiler models"""
    return {
        "models": [
            {"id": "HRE 24/18 A", "name": "HRE 24/18 A", "cw_class": 3},
            {"id": "HRE 28/24 A", "name": "HRE 28/24 A", "cw_class": 4},
            {"id": "HRE 36/30 A", "name": "HRE 36/30 A", "cw_class": 5},
            {"id": "HRE 36/48 A", "name": "HRE 36/48 A", "cw_class": 5}
        ]
    }

@app.get("/api/manual/search")
async def search_manual(query: str, model: Optional[str] = None):
    """Search the manual for specific terms"""
    
    try:
        results = []
        lines = MANUAL_CONTENT.split('\n')
        
        for i, line in enumerate(lines):
            if query.lower() in line.lower():
                # Get context
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = '\n'.join(lines[start:end])
                
                # Find page reference
                page = None
                for j in range(max(0, i - 50), min(len(lines), i + 50)):
                    page_match = re.search(r'<!-- PAGE_REF: (\d+) -->', lines[j])
                    if page_match:
                        page = int(page_match.group(1))
                        break
                
                results.append({
                    "line_number": i + 1,
                    "text": line,
                    "context": context,
                    "page": page
                })
        
        return {
            "query": query,
            "model": model,
            "results": results[:20]  # Limit to 20 results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)