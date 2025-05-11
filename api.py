#!/usr/bin/env python
# api.py
# FastAPI implementation for PDF parser

import os
import json
import tempfile
import shutil
import sys
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from pathlib import Path

# Check for required packages
try:
    # Import functions from pdfparser.py
    from pdfparser import (
        extract_pdf_metadata,
        extract_tables_from_markdown,
        parse_table,
        save_table
    )

    # Import Mistral client
    try:
        from mistralai import Mistral
        MISTRAL_AVAILABLE = True
    except ImportError:
        print("Warning: mistralai package not found. OCR functionality will be disabled.")
        print("To enable OCR, install the mistralai package: pip install mistralai>=1.5.1")
        MISTRAL_AVAILABLE = False
except ImportError as e:
    print(f"Error importing from pdfparser.py: {e}")
    print("Make sure pdfparser.py is in the same directory as api.py")
    sys.exit(1)

# Create FastAPI app
app = FastAPI(
    title="PDF Parser API",
    description="API for extracting tables and metadata from PDF files",
    version="1.0.0"
)

# Add CORS middleware to allow cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Create a temporary directory for storing uploaded files
TEMP_DIR = Path("./temp")
TEMP_DIR.mkdir(exist_ok=True)

# Create a directory for storing extracted tables
OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Mistral API key - should be moved to environment variable in production
MISTRAL_API_KEY = "xinXihKFgx55WQJmuGp749rtwky4PSQU"  # Replace with your actual Mistral API key

# Response models
class MetadataResponse(BaseModel):
    document_info: Dict[str, Any]
    security_info: Dict[str, Any]
    forensic_indicators: List[str]
    risk_assessment: Dict[str, Any]

class TableInfo(BaseModel):
    table_id: int
    csv_path: str
    excel_path: str
    preview: List[List[str]]

class TablesResponse(BaseModel):
    total_tables: int
    tables: List[TableInfo]

class ProcessResponse(BaseModel):
    metadata: MetadataResponse
    tables: TablesResponse
    full_text_path: str

# Helper function to format metadata for API response
def format_metadata_for_api(pdf_path: str) -> MetadataResponse:
    """Extract metadata from PDF and format it for API response"""
    try:
        with open(pdf_path, 'rb') as file:
            import PyPDF2
            pdf = PyPDF2.PdfReader(file)

            # Extract document info dictionary
            info = pdf.metadata or {}

            # Format document info
            document_info = {}
            metadata_fields = [
                ('title', '/Title'),
                ('author', '/Author'),
                ('subject', '/Subject'),
                ('keywords', '/Keywords'),
                ('creator', '/Creator'),
                ('producer', '/Producer'),
                ('creation_date', '/CreationDate'),
                ('modification_date', '/ModDate')
            ]

            for label, key in metadata_fields:
                value = info.get(key, None)
                document_info[label] = str(value) if value else None

            # Security info
            security_info = {
                "is_encrypted": pdf.is_encrypted,
                "encryption_method": str(pdf.encryption_method) if hasattr(pdf, 'encryption_method') else None,
            }

            if pdf.is_encrypted:
                try:
                    security_info["permissions"] = {
                        'print': pdf.can_print,
                        'modify': pdf.can_modify,
                        'copy': pdf.can_copy,
                        'annotate': pdf.can_annotate
                    }
                except:
                    security_info["permissions"] = "Could not retrieve permissions"

            # Forensic indicators
            forensic_indicators = []

            creation_date = info.get('/CreationDate', None)
            mod_date = info.get('/ModDate', None)

            if creation_date and mod_date and creation_date != mod_date:
                forensic_indicators.append("Creation date differs from modification date")

            creator = info.get('/Creator', '')
            producer = info.get('/Producer', '')

            if creator and producer and creator != producer:
                forensic_indicators.append(f"Different creator ({creator}) and producer ({producer})")

            # Check for incremental updates
            try:
                with open(pdf_path, 'rb') as f:
                    content = f.read()
                    updates = content.count(b"%%EOF")
                    if updates > 1:
                        forensic_indicators.append(f"Found {updates} 'EOF' markers - indicates {updates-1} document revisions")
            except:
                pass

            # Risk assessment
            risk_indicators = []

            if pdf.is_encrypted:
                risk_indicators.append("Document is encrypted (could conceal changes)")
            if creation_date and mod_date and creation_date != mod_date:
                risk_indicators.append("Creation and modification dates differ")
            if updates > 1:
                risk_indicators.append(f"Document has been revised {updates-1} times")

            risk_assessment = {
                "risk_indicators": risk_indicators,
                "risk_level": "High" if len(risk_indicators) > 1 else "Medium" if len(risk_indicators) == 1 else "Low",
                "recommendation": "Perform additional verification" if risk_indicators else "No obvious risk indicators detected"
            }

            return MetadataResponse(
                document_info=document_info,
                security_info=security_info,
                forensic_indicators=forensic_indicators,
                risk_assessment=risk_assessment
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error extracting metadata: {str(e)}")

# API endpoints
@app.get("/")
async def root():
    return {"message": "PDF Parser API is running"}

@app.post("/upload/", response_model=ProcessResponse)
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Upload and process a PDF file
    - Extracts metadata
    - Extracts tables (if Mistral OCR is available)
    - Returns paths to extracted files
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save the uploaded file
    temp_file_path = TEMP_DIR / file.filename
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Extract metadata
        metadata = format_metadata_for_api(temp_file_path)

        # Create output directory for this file
        file_output_dir = OUTPUT_DIR / Path(file.filename).stem
        file_output_dir.mkdir(exist_ok=True)

        all_tables = []
        all_markdown = ""
        table_info_list = []

        # Process the PDF with Mistral OCR if available
        if MISTRAL_AVAILABLE:
            try:
                # Initialize Mistral client
                client = Mistral(api_key=MISTRAL_API_KEY)

                # Upload for OCR
                with open(temp_file_path, "rb") as f:
                    content = f.read()

                uploaded = client.files.upload(
                    file={
                        "file_name": os.path.basename(temp_file_path),
                        "content": content
                    },
                    purpose="ocr"
                )

                # Get a signed URL
                signed = client.files.get_signed_url(file_id=uploaded.id)
                signed_url = signed.url

                # Run the OCR model
                ocr_response = client.ocr.process(
                    model="mistral-ocr-latest",
                    include_image_base64=True,
                    document={
                        "type": "document_url",
                        "document_url": signed_url
                    }
                )

                # Process each page
                for i, page in enumerate(ocr_response.pages, start=1):
                    blob = json.loads(page.model_dump_json())
                    markdown = blob.get("markdown", "")
                    all_markdown += markdown + "\n\n"

                    # Extract tables from the markdown
                    tables = extract_tables_from_markdown(markdown)

                    # Add to all tables
                    all_tables.extend(tables)

                # Save tables
                if all_tables:
                    for i, table in enumerate(all_tables):
                        df = parse_table(table)

                        # Skip empty tables or tables with no data rows
                        if df.empty:
                            continue

                        # Create base filename
                        base_filename = file_output_dir / f"table_{i+1}"

                        # Save table without formatting
                        csv_file, excel_file = save_table(df, base_filename)

                        # Add table info to response
                        table_info = TableInfo(
                            table_id=i+1,
                            csv_path=str(csv_file),
                            excel_path=str(excel_file),
                            preview=df.values.tolist()[:5]  # First 5 rows as preview
                        )
                        table_info_list.append(table_info)

                # Save full text
                text_file = file_output_dir / "full_text.txt"
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(all_markdown)
            except Exception as e:
                # If OCR processing fails, log the error but continue with metadata
                print(f"Error during OCR processing: {str(e)}")
                all_markdown = f"OCR processing failed: {str(e)}"
                text_file = file_output_dir / "error_log.txt"
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(all_markdown)
        else:
            # Mistral not available
            all_markdown = "OCR processing not available. Install mistralai package to enable this feature."
            text_file = file_output_dir / "info.txt"
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(all_markdown)

        # Schedule cleanup of temporary file
        background_tasks.add_task(os.remove, temp_file_path)

        return ProcessResponse(
            metadata=metadata,
            tables=TablesResponse(
                total_tables=len(table_info_list),
                tables=table_info_list
            ),
            full_text_path=str(text_file)
        )

    except Exception as e:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download a file by path"""
    full_path = Path(file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_path, filename=full_path.name)

# Run the server if executed as a script
if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
