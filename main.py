from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os
import shutil
import traceback
from extractor import extract_text_from_file
from analyzer import analyze_reports

app = FastAPI(title="ForestGuard Pro Validation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# ----- API ROUTES (must be defined BEFORE the static mount) -----

@app.post("/api/analyze")
async def analyze_files(files: List[UploadFile] = File(...)):
    extracted_texts = []
    try:
        for file in files:
            safe_name = os.path.basename(file.filename)
            temp_path = os.path.join("temp", safe_name)
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            text = extract_text_from_file(temp_path)
            extracted_texts.append({"filename": safe_name, "text": text})

        analysis_result = analyze_reports(extracted_texts)

        # Cleanup temp dir
        for f in os.listdir("temp"):
            try:
                os.remove(os.path.join("temp", f))
            except Exception:
                pass

        return JSONResponse(content=analysis_result)

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": traceback.format_exc()}
        )

# ----- STATIC FILES (last, after API routes) -----

app.mount("/", StaticFiles(directory="static", html=True), name="static")
