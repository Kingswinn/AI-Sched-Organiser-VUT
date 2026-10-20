from datetime import date, datetime
import io
import re
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import pdfplumber
import requests

app = FastAPI(title="AI Sched-Organiser")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_DATA = {
    "filename": "",
    "full_text": "",
    "deadlines": [],
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_REGEX = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def parse_date_to_2026(raw_str: str):
    """Parses various date string formats and anchors to 2026."""
    if not raw_str:
        return None
    cleaned = (
        raw_str.replace("’", "'")
        .replace("`", "'")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )

    # 1. DD Month (e.g., '22 Aug', '22 August 2026', '22 Aug \'26')
    m1 = re.search(
        rf"\b(\d{{1,2}})\s*({MONTH_REGEX})(?:\s*['’]?(?:20)?(\d{{2}}))?\b",
        cleaned,
        re.IGNORECASE,
    )
    if m1:
        d = int(m1.group(1))
        m_str = m1.group(2).lower()
        m = MONTH_MAP.get(m_str[:3], 0)
        if 1 <= d <= 31 and 1 <= m <= 12:
            try:
                return date(2026, m, d)
            except ValueError:
                pass

    # 2. Month DD (e.g., 'Aug 22', 'August 22, 2026')
    m2 = re.search(
        rf"\b({MONTH_REGEX})\s*(\d{{1,2}})(?:[,\s]+(?:20)?(\d{{2}}))?\b",
        cleaned,
        re.IGNORECASE,
    )
    if m2:
        m_str = m2.group(1).lower()
        d = int(m2.group(2))
        m = MONTH_MAP.get(m_str[:3], 0)
        if 1 <= d <= 31 and 1 <= m <= 12:
            try:
                return date(2026, m, d)
            except ValueError:
                pass

    # 3. DD/MM, DD-MM, DD.MM
    m3 = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](?:20)?\d{2})?\b", cleaned)
    if m3:
        d = int(m3.group(1))
        m = int(m3.group(2))
        if 1 <= d <= 31 and 1 <= m <= 12:
            try:
                return date(2026, m, d)
            except ValueError:
                pass

    return None


def calculate_time_left(due_date: date):
    """Calculates time difference relative to real today's date."""
    today = date.today()
    diff = (due_date - today).days

    if diff < 0:
        overdue_by = abs(diff)
        return {
            "status": "overdue",
            "badge_class": "badge-overdue",
            "text": f"OVERDUE by {overdue_by} day{'s' if overdue_by != 1 else ''}",
            "days_diff": diff,
        }
    elif diff == 0:
        return {
            "status": "today",
            "badge_class": "badge-today",
            "text": "Due TODAY",
            "days_diff": 0,
        }
    else:
        return {
            "status": "upcoming",
            "badge_class": "badge-upcoming",
            "text": f"{diff} day{'s' if diff != 1 else ''} left",
            "days_diff": diff,
        }


def extract_deadlines_from_pdf(pdf_bytes: bytes):
    deadlines = []
    full_text_pages = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            full_text_pages.append(t)

    full_text = "\n".join(full_text_pages)

    # ---------------------------------------------------------------
    # STRATEGY 1: Weekly Schedule Blocks (for EICNS4A-style files)
    # ---------------------------------------------------------------
    week_pattern = re.compile(
        rf"(?:Week\s+\d+|Recess)\s+\d{{1,2}}\s+{MONTH_REGEX}\s*[-–—]\s*(\d{{1,2}}\s+{MONTH_REGEX})",
        re.IGNORECASE,
    )
    week_matches = list(week_pattern.finditer(full_text))

    if len(week_matches) >= 3:
        for idx, match in enumerate(week_matches):
            end_date_str = match.group(1)
            parsed_date = parse_date_to_2026(end_date_str)
            if not parsed_date:
                continue

            start_pos = match.end()
            end_pos = (
                week_matches[idx + 1].start()
                if idx + 1 < len(week_matches)
                else min(len(full_text), start_pos + 500)
            )
            block_text = full_text[start_pos:end_pos]

            for line in block_text.splitlines():
                clean_line = line.strip()
                if re.search(r"\b(study|debrief|revision|orientation)\b", clean_line, re.IGNORECASE):
                    continue

                task_match = re.search(
                    r"\b(Practical\s+Assignment\s+\d+|Theory\s+Assessment\s+\d+|Practical\s+Competency\s+Assessment(?:\s*\(PCA\))?\s*\d*|Test\s+\d+|Examination|Exam)\b",
                    clean_line,
                    re.IGNORECASE,
                )
                if task_match:
                    task_name = re.sub(r"\s+", " ", task_match.group(0).strip())
                    time_info = calculate_time_left(parsed_date)
                    deadlines.append({
                        "task": task_name,
                        "date": parsed_date.strftime("%d %b %Y"),
                        "raw_date": parsed_date.isoformat(),
                        "time_left": time_info["text"],
                        "status": time_info["status"],
                        "badge_class": time_info["badge_class"],
                        "days_diff": time_info["days_diff"],
                    })

    # ---------------------------------------------------------------
    # STRATEGY 2: Inline Learner Guide / Time Schedule (for AMAEM4A-style files)
    # ---------------------------------------------------------------
    # Look for patterns like:
    # "Test 1 (22 Aug '26)", "Test 2 R-test (23 Oct)", "Re-test (29 Aug)", "Examination 09 Nov 2026"
    ama_pattern = re.compile(
        rf"\b(Test\s*\d+(?:\s*(?:R|R-test|Re-test))?|Re-test|R-test|Examination|Final\s*Exam)\b"
        rf"(?:[^\n\d()]*[\(\[]?\s*(\d{{1,2}}\s*{MONTH_REGEX}(?:[^\n\)]*)?)[\)\]]?)",
        re.IGNORECASE,
    )

    for line in full_text.splitlines():
        line_str = line.strip()
        # Skip pure tutorial headings like "Tut 1", but keep university/subject text
        if re.match(r"^(?:tut\b|tutorial\b)", line_str, re.IGNORECASE):
            continue

        match = ama_pattern.search(line_str)
        if match:
            raw_task = match.group(1).strip()
            raw_date_snippet = match.group(2).strip()

            parsed_date = parse_date_to_2026(raw_date_snippet)
            if parsed_date:
                # Clean up task label
                cleaned_task = re.sub(r"\s+", " ", raw_task)
                time_info = calculate_time_left(parsed_date)
                deadlines.append({
                    "task": cleaned_task,
                    "date": parsed_date.strftime("%d %b %Y"),
                    "raw_date": parsed_date.isoformat(),
                    "time_left": time_info["text"],
                    "status": time_info["status"],
                    "badge_class": time_info["badge_class"],
                    "days_diff": time_info["days_diff"],
                })

    # ---------------------------------------------------------------
    # Deduplicate and Sort
    # ---------------------------------------------------------------
    unique = {}
    for d in deadlines:
        key = (d["task"].lower().replace("-", " ").replace(" ", ""), d["raw_date"])
        if key not in unique:
            unique[key] = d

    sorted_deadlines = sorted(
        unique.values(),
        key=lambda x: (x["raw_date"], x["task"])
    )

    for i, item in enumerate(sorted_deadlines, start=1):
        item["id"] = i

    return sorted_deadlines, full_text


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    try:
        with open("app/static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Index file not found at app/static/index.html</h1>",
            status_code=404,
        )


@app.post("/extract")
async def extract_deadlines(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()
    deadlines, full_text = extract_deadlines_from_pdf(content)

    SESSION_DATA["filename"] = file.filename
    SESSION_DATA["full_text"] = full_text
    SESSION_DATA["deadlines"] = deadlines

    today = date.today()
    return {
        "filename": file.filename,
        "count": len(deadlines),
        "deadlines": deadlines,
        "today": today.strftime("%A, %d %B %Y"),
    }


@app.post("/ask")
async def ask_question(req: dict):
    question = req.get("question", "").strip()
    if not question:
        return {"answer": "Please ask a question."}

    text = SESSION_DATA.get("text", "")
    deadlines = SESSION_DATA.get("deadlines", [])

    if not text and not deadlines:
        return {"answer": "No document loaded. Please upload and extract a PDF first!"}

    # Summary of deadlines
    sched_summary = "\n".join([f"- {d.get('task')}: {d.get('date')}" for d in deadlines[:10]])
    context_snippet = text[:3500]

    prompt = f"""You are a helpful university academic assistant. Answer the student's question concisely using ONLY the provided document details.

ASSESSMENT DEADLINES:
{sched_summary if sched_summary else "None recorded."}

DOCUMENT CONTEXT:
{context_snippet}

QUESTION:
{question}

ANSWER (concise and direct):"""

    payload = {
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 150,
            "num_ctx": 2048,
        },
    }

    try:
        resp = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=60)
        if resp.status_code == 200:
            ollama_json = resp.json()
            ans = ollama_json.get("response", "").strip()
            if not ans:
                ans = "Ollama finished but returned an empty response. Try asking more specifically."
            return {"answer": ans}
        return {"answer": f"Ollama HTTP error {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"answer": "Error: Cannot connect to Ollama. Run 'ollama serve' in PowerShell."}
    except requests.exceptions.Timeout:
        return {"answer": "Error: Ollama timed out. Try asking a shorter question."}
    except Exception as e:
        return {"answer": f"Error: {str(e)}"}

    # Format deadlines table for context
    deadline_context = "\n".join(
        [f"- {d['task']} on {d['date']} ({d['time_left']})" for d in deadlines]
    )

    prompt = f"""You are AI Sched-Organiser assistant.
Use ONLY the following extracted document information and deadline schedule to answer the user's question accurately and concisely.

DEADLINE SCHEDULE:
{deadline_context if deadline_context else "None extracted yet"}

DOCUMENT TEXT:
{full_text[:16000]}

USER QUESTION: {question}

Provide a direct, helpful answer:
- If asking about dates/deadlines, refer to the DEADLINE SCHEDULE.
- If asking about lecturers, coordinators, emails, phone numbers, or contacts, look in the DOCUMENT TEXT.
- If the document does not mention the answer, state that it was not found in the file.
"""

import re

def query_ollama(question: str, doc_text: str, deadlines: list) -> str:
    if not doc_text:
        return "No document text available. Please upload and extract a PDF first."

    # 1. Deadline summary (always available to answer scheduling questions)
    sched_summary = "\n".join([f"- {d.get('task')}: {d.get('date')} ({d.get('time_left', '')})" for d in deadlines[:10]])

    # 2. Extract keywords from the student's question (words longer than 2 letters)
    q_words = [w.lower() for w in re.findall(r"\w+", question) if len(w) > 2]
    # Filter out common stop words so we focus on meaningful terms
    stop_words = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how", "the", "and", "is", "are", "for", "with", "about"}
    keywords = [w for w in q_words if w not in stop_words]

    # 3. Split the entire document into chunks/paragraphs
    chunks = [chunk.strip() for chunk in doc_text.split("\n\n") if len(chunk.strip()) > 30]
    if not chunks:
        # Fallback to single newlines if double-newlines didn't split well
        chunks = [line.strip() for line in doc_text.split("\n") if len(line.strip()) > 30]

    # 4. Score each chunk by how many keywords it contains
    scored_chunks = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(1 for kw in keywords if kw in chunk_lower)
        if score > 0:
            scored_chunks.append((score, chunk))

    # Sort best matching paragraphs first
    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    # Grab the top matching paragraphs (up to ~3500 chars total)
    matched_text = ""
    for _, chunk in scored_chunks[:6]:
        if len(matched_text) + len(chunk) < 3500:
            matched_text += chunk + "\n\n"

    # If no keywords matched, fall back to the first 3000 chars of the guide
    if not matched_text.strip():
        matched_text = doc_text[:3000]

    prompt = f"""You are an accurate university academic assistant. Answer the student's question using ONLY the provided document excerpts and schedule. If the exact answer is not in the text, say what is mentioned or state clearly that it is not specified.

ASSESSMENT DEADLINES:
{sched_summary if sched_summary else "None listed."}

RELEVANT DOCUMENT EXCERPTS:
{matched_text}

STUDENT QUESTION: {question}

CONCISE ANSWER:"""

    payload = {
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 120,
            "num_ctx": 2048
        }
    }

    try:
        resp = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=60)
        if resp.status_code == 200:
            return resp.json().get("response", "No answer generated.").strip()
        return f"Ollama error {resp.status_code}: {resp.text}"
    except requests.exceptions.ConnectionError:
        return "Cannot connect to Ollama. Make sure Ollama is running."
    except requests.exceptions.Timeout:
        return "Ollama took too long to answer. Try a more specific question."
    except Exception as e:
        return f"Error: {str(e)}"


    try:
        # Use explicit 127.0.0.1 with a generous 90-second timeout for CPU
        resp = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response", "No answer generated.").strip()
        return f"Ollama returned status {resp.status_code}: {resp.text}"
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Make sure Ollama is running (check http://127.0.0.1:11434)."
    except requests.exceptions.Timeout:
        return "Error: Ollama timed out. Try asking a shorter or more specific question."
    except Exception as e:
        return f"Error communicating with Ollama: {str(e)}"

