#!/usr/bin/env python
# api.py
# FastAPI implementation for PDF parser

import os
import json
import tempfile
import shutil
import sys
import zipfile
import io
import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
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
os.makedirs(TEMP_DIR, exist_ok=True)

# Create a directory for storing extracted tables
OUTPUT_DIR = Path("./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Create a directory for storing ZIP archives
ZIP_DIR = Path("./zip")
os.makedirs(ZIP_DIR, exist_ok=True)

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
    output_folder: str  # Path to the output folder containing all files

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

    # Create a safe filename (remove special characters)
    safe_filename = "".join([c for c in file.filename if c.isalnum() or c in "._- "]).strip()
    if not safe_filename:
        safe_filename = "uploaded_file.pdf"

    # Ensure temp directory exists
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Save the uploaded file with a safe filename
    temp_file_path = TEMP_DIR / safe_filename

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving uploaded file: {str(e)}")

    try:
        # Extract metadata
        metadata = format_metadata_for_api(temp_file_path)

        # Create a safe folder name for output
        safe_foldername = "".join([c for c in Path(safe_filename).stem if c.isalnum() or c in "._- "]).strip()
        if not safe_foldername:
            safe_foldername = f"output_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Create output directory for this file
        file_output_dir = OUTPUT_DIR / safe_foldername
        os.makedirs(file_output_dir, exist_ok=True)

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
                try:
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(all_markdown)
                except Exception as e:
                    print(f"Error saving full text: {str(e)}")
                    # Try an alternative location if there's an issue
                    text_file = file_output_dir / "text.txt"
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(all_markdown)
            except Exception as e:
                # If OCR processing fails, log the error but continue with metadata
                print(f"Error during OCR processing: {str(e)}")
                all_markdown = f"OCR processing failed: {str(e)}"
                text_file = file_output_dir / "error_log.txt"
                try:
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(all_markdown)
                except Exception as write_error:
                    print(f"Error saving error log: {str(write_error)}")
                    # Try an alternative location
                    text_file = file_output_dir / "error.txt"
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(all_markdown)
        else:
            # Mistral not available
            all_markdown = "OCR processing not available. Install mistralai package to enable this feature."
            text_file = file_output_dir / "info.txt"
            try:
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(all_markdown)
            except Exception as write_error:
                print(f"Error saving info file: {str(write_error)}")
                # Try an alternative location
                text_file = file_output_dir / "info_note.txt"
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
            full_text_path=str(text_file),
            output_folder=str(file_output_dir)
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

@app.get("/download-output/{output_folder:path}")
async def download_output_folder(output_folder: str, background_tasks: BackgroundTasks):
    """
    Download the entire output folder as a ZIP file

    Args:
        output_folder: Path to the output folder

    Returns:
        ZIP file containing all files in the output folder
    """
    full_path = Path(output_folder)

    if not full_path.exists() or not full_path.is_dir():
        raise HTTPException(status_code=404, detail="Output folder not found")

    # Get the folder name for the ZIP file
    folder_name = full_path.name

    # Create a unique filename for the ZIP
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_folder_name = "".join([c for c in folder_name if c.isalnum() or c in "._- "]).strip()
    if not safe_folder_name:
        safe_folder_name = "output"

    zip_filename = f"{safe_folder_name}_{timestamp}.zip"

    # Ensure ZIP directory exists
    os.makedirs(ZIP_DIR, exist_ok=True)
    zip_path = ZIP_DIR / zip_filename

    try:
        # Create the ZIP file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in full_path.rglob('*'):
                if file_path.is_file():
                    try:
                        # Add the file to the ZIP with a relative path
                        arcname = file_path.relative_to(full_path)
                        zip_file.write(file_path, arcname=arcname)
                    except Exception as e:
                        print(f"Error adding file {file_path} to ZIP: {str(e)}")
                        # Continue with other files
                        continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP file: {str(e)}")

    # Schedule cleanup of the ZIP file after it's been downloaded
    background_tasks.add_task(lambda: os.remove(zip_path) if os.path.exists(zip_path) else None)

    return FileResponse(
        path=zip_path,
        filename=zip_filename,
        media_type="application/zip"
    )

class FilesRequest(BaseModel):
    files: List[str]

@app.post("/download-zip/")
async def download_zip(background_tasks: BackgroundTasks, files_request: FilesRequest):
    """
    Create and download a ZIP file containing multiple files

    Args:
        files_request: Request body containing list of file paths to include in the ZIP

    Returns:
        StreamingResponse with the ZIP file
    """
    files = files_request.files
    # Create a unique filename for the ZIP
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_filename = f"pdf_parser_results_{timestamp}.zip"

    # Ensure ZIP directory exists
    os.makedirs(ZIP_DIR, exist_ok=True)
    zip_path = ZIP_DIR / zip_filename

    try:
        # Create the ZIP file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in files:
                try:
                    full_path = Path(file_path)
                    if full_path.exists():
                        # Add the file to the ZIP with a relative path
                        arcname = full_path.name
                        zip_file.write(full_path, arcname=arcname)
                except Exception as e:
                    print(f"Error adding file {file_path} to ZIP: {str(e)}")
                    # Continue with other files
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP file: {str(e)}")

    # Schedule cleanup of the ZIP file after it's been downloaded
    background_tasks.add_task(lambda: os.remove(zip_path) if os.path.exists(zip_path) else None)

    return FileResponse(
        path=zip_path,
        filename=zip_filename,
        media_type="application/zip"
    )

@app.post("/download-folder-zip/{folder_name}")
async def download_folder_as_zip(folder_name: str, background_tasks: BackgroundTasks):
    """
    Create and download a ZIP file containing all files in a specific output folder

    Args:
        folder_name: Name of the folder to zip (relative to OUTPUT_DIR)

    Returns:
        StreamingResponse with the ZIP file
    """
    folder_path = OUTPUT_DIR / folder_name

    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    # Create a unique filename for the ZIP
    zip_filename = f"{folder_name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = ZIP_DIR / zip_filename

    # Create the ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in folder_path.rglob('*'):
            if file_path.is_file():
                # Add the file to the ZIP with a relative path
                arcname = file_path.relative_to(folder_path)
                zip_file.write(file_path, arcname=arcname)

    # Save the ZIP file
    zip_buffer.seek(0)
    with open(zip_path, 'wb') as f:
        f.write(zip_buffer.getvalue())

    # Schedule cleanup of the ZIP file after it's been downloaded
    background_tasks.add_task(lambda: os.remove(zip_path) if os.path.exists(zip_path) else None)

    return FileResponse(
        path=zip_path,
        filename=zip_filename,
        media_type="application/zip"
    )

# Run the server if executed as a script
if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
