# PDF Parser API

A FastAPI-based API for extracting tables and metadata from PDF files using Mistral AI's OCR capabilities.

## Features

- **PDF Metadata Extraction**: Analyze PDF metadata for fraud detection and document integrity
- **Table Extraction**: Extract tables from PDFs using Mistral AI's OCR
- **File Conversion**: Convert extracted tables to CSV and Excel formats
- **API Access**: Access all functionality through a RESTful API

## Requirements

- Python 3.12 or higher
- FastAPI
- Uvicorn
- Mistral AI API key
- PyPDF2
- Pandas
- OpenPyXL

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/pdf-parser-api.git
   cd pdf-parser-api
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Optional: Install Mistral AI for OCR capabilities:
   ```bash
   pip install mistralai>=1.5.1
   ```
   Note: The API will work without Mistral AI, but OCR and table extraction features will be disabled.

4. Set your Mistral AI API key (if you installed Mistral AI):
   - Open `api.py` and replace the `MISTRAL_API_KEY` value with your actual API key
   - For production, use environment variables instead

## Usage

### Starting the API Server

Run the following command to start the API server:

```bash
python api.py
```

This will start the server at `http://localhost:8000`.

Alternatively, you can use Uvicorn directly:

```bash
uvicorn api:app --reload
```

### API Endpoints

#### 1. Upload and Process a PDF

**Endpoint**: `POST /upload/`

**Request**:
- Form data with a file field named `file` containing the PDF file

**Response**:
```json
{
  "metadata": {
    "document_info": {
      "title": "Example Document",
      "author": "John Doe",
      "subject": "Example",
      "keywords": "pdf, example",
      "creator": "PDF Creator",
      "producer": "PDF Producer",
      "creation_date": "2023-01-01 12:00:00",
      "modification_date": "2023-01-02 14:30:00"
    },
    "security_info": {
      "is_encrypted": false,
      "encryption_method": null,
      "permissions": null
    },
    "forensic_indicators": [
      "Creation date differs from modification date"
    ],
    "risk_assessment": {
      "risk_indicators": [
        "Creation and modification dates differ"
      ],
      "risk_level": "Medium",
      "recommendation": "Perform additional verification"
    }
  },
  "tables": {
    "total_tables": 2,
    "tables": [
      {
        "table_id": 1,
        "csv_path": "output/example/table_1.csv",
        "excel_path": "output/example/table_1.xlsx",
        "preview": [
          ["Header1", "Header2", "Header3"],
          ["Value1", "Value2", "Value3"],
          ["Value4", "Value5", "Value6"]
        ]
      },
      {
        "table_id": 2,
        "csv_path": "output/example/table_2.csv",
        "excel_path": "output/example/table_2.xlsx",
        "preview": [
          ["Header1", "Header2", "Header3"],
          ["Value1", "Value2", "Value3"],
          ["Value4", "Value5", "Value6"]
        ]
      }
    ]
  },
  "full_text_path": "output/example/full_text.txt"
}
```

Note: If Mistral AI is not installed or OCR processing fails, the response will still include metadata, but the `tables` array will be empty and `full_text_path` will point to an error or information file.

#### 2. Download Extracted Files

**Endpoint**: `GET /download/{file_path}`

**Request**:
- `file_path`: Path to the file to download (obtained from the upload response)

**Response**:
- The file as a download

#### 3. Download Output Folder as ZIP

**Endpoint**: `GET /download-output/{output_folder}`

**Request**:
- `output_folder`: Path to the output folder to download as ZIP (returned in the upload response as `output_folder`)

**Response**:
- ZIP file containing all files in the specified output folder

#### 4. Download Folder as ZIP (Alternative)

**Endpoint**: `POST /download-folder-zip/{folder_name}`

**Request**:
- `folder_name`: Name of the folder to download as ZIP (usually the PDF filename without extension)

**Response**:
- ZIP file containing all files in the specified folder

#### 5. Download Multiple Files as ZIP

**Endpoint**: `POST /download-zip/`

**Request**:
- JSON body with a list of file paths to include in the ZIP:
```json
{
  "files": [
    "output/example/table_1.csv",
    "output/example/table_2.xlsx",
    "output/example/full_text.txt"
  ]
}
```

**Response**:
- ZIP file containing all the specified files

### Interactive API Documentation

FastAPI provides automatic interactive API documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Frontend Integration

To use this API in a frontend application:

### Example with JavaScript/Fetch API

```javascript
// Upload a PDF file
async function uploadPDF(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('http://localhost:8000/upload/', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error('Failed to upload PDF');
  }

  return await response.json();
}

// Download a file
function downloadFile(filePath) {
  window.open(`http://localhost:8000/download/${encodeURIComponent(filePath)}`, '_blank');
}

// Example usage
document.getElementById('uploadButton').addEventListener('click', async () => {
  const fileInput = document.getElementById('pdfFile');
  const file = fileInput.files[0];

  if (file) {
    try {
      const result = await uploadPDF(file);

      // Display metadata
      displayMetadata(result.metadata);

      // Display tables
      displayTables(result.tables);

      // Add download buttons for files
      addDownloadButtons(result);
    } catch (error) {
      console.error('Error:', error);
    }
  }
});
```

## License

[MIT License](LICENSE)

## Credits

This project uses the Mistral AI API for OCR processing.
