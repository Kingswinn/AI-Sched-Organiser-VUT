# AI Sched Organiser - VUT

**Vaal University of Technology - Artificial Intelligence Applications**
**Student:** [Yvonne Motloung + 216155614]
**Date:** 20 October 2026

Intelligent Academic Schedule Management System that extracts deadlines from PDFs and answers questions using local AI (Ollama).

### Problem Statement
VUT students receive assessment schedules as unstructured PDFs. Manual entry into calendars is time-consuming and error-prone. This system automates PDF -> Calendar.

### Features
- Upload PDF assessment schedule (TUT/VUT format)
- Auto extracts: Task name, Date, Time Left (Overdue/Today/Upcoming)
- Filter by: All | Today | Overdue | Upcoming
- Ask AI questions like "are there any upcoming assessments?"
- 100% offline & private - uses Ollama Llama 3.2:3b (2GB) on localhost:11434

### System Architecture
- Frontend: HTML5, CSS3, JS (Port 8000)
- Backend: FastAPI + Uvicorn
- PDF Engine: PyPDF2 / PyMuPDF
- AI Engine: Ollama API - `POST http://localhost:11434/api/generate`

### How to Run Locally (For Lecturer)

1. **Clone the repo**
   ```bash
   git clone https://github.com/kingswinn/AI-Sched-Organiser-VUT.git
   cd AI-Sched-Organiser-VUT
