#!/usr/bin/env python
# pdf_table_extractor.py
# requires-python = ">=3.12"
# dependencies = [
#     "mistralai==1.5.1",
#     "pandas==2.0.0",
#     "openpyxl==3.1.2",
#     "PyPDF2==3.0.1"  # Added for metadata extraction
# ]

import os
import json
import re
import pandas as pd
import PyPDF2  # Added for metadata extraction
import datetime  # For formatting dates in metadata

# Try to import Mistral, but don't fail if it's not available
try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False
    print("Warning: mistralai package not found. OCR functionality will be disabled.")
    print("To enable OCR, install the mistralai package: pip install mistralai>=1.5.1")

def clean_number(text):
    """Clean and format numeric values with no column assumptions"""
    if not isinstance(text, str):
        return text

    # Handle LaTeX math expressions
    if '$' in text:
        # Check if this is an actual LaTeX expression (enclosed in $ signs)
        if text.startswith('$') and text.endswith('$'):
            inner_text = text[1:-1].strip()  # Remove outer dollar signs
            return clean_number(inner_text)

        # Check for nested LaTeX expressions
        matches = re.findall(r'\$(.*?)\$', text)
        if matches:
            for match in matches:
                inner_processed = clean_number(match)
                text = text.replace(f"${match}$", str(inner_processed))

    # Special case: if this appears to be a description with a currency value inside parentheses
    # like "Hobby plan included usage v2 ($5.00 off)"
    description_with_currency = re.search(r'^(.*?)(\([\$\\].*?\))(.*?)$', text)
    if description_with_currency:
        prefix = description_with_currency.group(1).strip()
        currency_part = description_with_currency.group(2)
        suffix = description_with_currency.group(3).strip()

        # Replace escaped dollar signs in the currency part
        currency_part = currency_part.replace('\\$', '$')

        # Reconstruct the text with properly formatted currency in parentheses
        return f"{prefix} {currency_part} {suffix}".strip()

    # Replace escaped characters but preserve structure
    text = re.sub(r'\\(.)', r'\1', text)

    # Handle negative amounts properly
    if text.startswith('$') and text.endswith('$') and '-' in text:
        # Special case: negative dollar amounts, retain the negative sign and dollar sign
        clean_text = text[1:-1].strip()  # Remove outer dollar signs
        return f"${clean_text}"

    # Return the cleaned text (handling of positive amounts)
    return text


def extract_tables_from_markdown(markdown):
    """Extract tables from markdown text"""
    tables = []
    current_table = []
    in_table = False

    lines = markdown.split('\n')
    for line in lines:
        line = line.strip()

        # Check if line is part of a table (starts and ends with |)
        if line.startswith('|') and line.endswith('|'):
            if not in_table:
                in_table = True
                current_table = []

            # Add to current table
            current_table.append(line)
        else:
            # If we were in a table but this line is not a table row
            if in_table:
                in_table = False
                if len(current_table) > 1:  # Real table has at least 2 rows
                    tables.append(current_table)
                current_table = []

    # Don't forget the last table if file ends with a table
    if in_table and len(current_table) > 1:
        tables.append(current_table)

    return tables

def parse_table(table_lines):
    """Parse table lines with fully dynamic approach"""
    # Get headers
    header_row = table_lines[0]
    headers = [cell.strip() for cell in header_row.split('|')]
    headers = [h for h in headers if h]  # Remove empty strings

    # Handle separator row
    start_idx = 1
    if len(table_lines) > 1 and re.search(r'[-:|]+', table_lines[1]):
        start_idx = 2

    # Process rows directly with their original structure preserved
    processed_rows = []
    last_item_row_idx = -1

    for i in range(start_idx, len(table_lines)):
        line = table_lines[i]
        raw_cells = line.split('|')

        # Skip line if not enough cells
        if len(raw_cells) <= 2:
            continue

        # Keep original cell structure
        cells = [cell.strip() for cell in raw_cells[1:-1]]

        # Skip completely empty rows
        if all(not c for c in cells):
            continue

        # Date row detection
        date_pattern = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s*-\s*\w+\s+\d{1,2},?\s+\d{4}\b'
        if len(cells) == 1 and re.search(date_pattern, cells[0]) and last_item_row_idx >= 0:
            # Attach to previous item
            processed_rows[last_item_row_idx][0] = f"{processed_rows[last_item_row_idx][0]}\n{cells[0]}"
            continue

        # Clean cells while preserving original structure
        clean_cells = []

        for j, cell in enumerate(cells):
            if j >= len(headers):
                continue

            # Clean all cells of escape characters but preserve content
            clean_cells.append(re.sub(r'\\(.)', r'\1', cell))

        # Pad with empty strings as needed
        while len(clean_cells) < len(headers):
            clean_cells.append("")

        # Add to processed rows
        processed_rows.append(clean_cells)

        # Track last regular item row
        if len(cells) == len(headers) and cells[0]:  # Regular item row has content in first cell
            last_item_row_idx = len(processed_rows) - 1

    # Create DataFrame
    df = pd.DataFrame(processed_rows, columns=headers).fillna("")
    return df

def save_table(df, base_filename):
    """Save the table as both CSV and unformatted Excel"""
    # Save as CSV file
    csv_filename = f"{base_filename}.csv"
    df.to_csv(csv_filename, index=False)

    # Save as Excel file without any formatting
    excel_filename = f"{base_filename}.xlsx"
    df.to_excel(excel_filename, index=False, engine='openpyxl')

    return csv_filename, excel_filename

def extract_pdf_metadata(pdf_path):
    """Extract and return comprehensive metadata from the PDF for fraud detection"""
    print("\n=== PDF METADATA ANALYSIS (FOR FRAUD DETECTION) ===\n")

    try:
        with open(pdf_path, 'rb') as file:
            pdf = PyPDF2.PdfReader(file)

            # Extract document info dictionary
            info = pdf.metadata
            if info:
                print("Document Information Dictionary:")
                print("-" * 50)

                # Standard metadata fields
                metadata_fields = [
                    ('Title', '/Title'),
                    ('Author', '/Author'),
                    ('Subject', '/Subject'),
                    ('Keywords', '/Keywords'),
                    ('Creator', '/Creator'),
                    ('Producer', '/Producer'),
                    ('Creation Date', '/CreationDate'),
                    ('Modification Date', '/ModDate')
                ]

                for label, key in metadata_fields:
                    value = info.get(key, "Not available")

                    # Format dates for better readability
                    if key in ['/CreationDate', '/ModDate'] and value != "Not available":
                        # PDF dates are in format: D:YYYYMMDDHHmmSS±HH'mm'
                        try:
                            # Extract the date components
                            date_str = str(value)
                            if date_str.startswith("D:"):
                                date_str = date_str[2:]

                                year = int(date_str[0:4])
                                month = int(date_str[4:6])
                                day = int(date_str[6:8])

                                # Try to extract time if available
                                time_str = ""
                                if len(date_str) >= 14:
                                    hour = int(date_str[8:10])
                                    minute = int(date_str[10:12])
                                    second = int(date_str[12:14])
                                    time_str = f"{hour:02d}:{minute:02d}:{second:02d}"

                                # Format the date
                                formatted_date = f"{year}-{month:02d}-{day:02d}"
                                if time_str:
                                    formatted_date += f" {time_str}"

                                # Try to extract timezone if available
                                if len(date_str) > 14 and ('+' in date_str or '-' in date_str):
                                    tz_parts = re.search(r'[+-](\d{2})\'?(\d{2})\'?', date_str[14:])
                                    if tz_parts:
                                        tz_hours, tz_minutes = tz_parts.groups()
                                        formatted_date += f" UTC{date_str[14:15]}{tz_hours}:{tz_minutes}"

                                value = formatted_date
                        except:
                            # If date parsing fails, use the original value
                            pass

                    print(f"{label}: {value}")

                # Look for additional metadata that might be present
                print("\nAdditional Metadata:")
                print("-" * 50)

                # Print any other keys in the info dictionary
                additional_found = False
                for key, value in info.items():
                    if key not in [k for _, k in metadata_fields]:
                        print(f"{key}: {value}")
                        additional_found = True

                if not additional_found:
                    print("No additional metadata fields found.")

            # Check for XMP metadata (more detailed and can reveal editing software)
            print("\nXMP Metadata (Advanced):")
            print("-" * 50)
            try:
                xmp_info = pdf.xmp_metadata
                if xmp_info:
                    # XMP data is in XML format, look for interesting elements
                    print("XMP metadata present - may contain detailed editing history")

                    # Look for common Adobe XMP namespaces that might indicate editing
                    xmp_str = str(xmp_info)

                    # Check for specific editing software traces
                    software_patterns = [
                        ('Adobe Photoshop', r'photoshop|Photoshop'),
                        ('Adobe Acrobat', r'acrobat|Acrobat'),
                        ('Microsoft Word', r'microsoft\s+word|Word\s+document'),
                        ('LibreOffice', r'libreoffice|LibreOffice'),
                        ('PDF editing tools', r'pdf\s*editor|PDFsam|Foxit|PDFelement')
                    ]

                    for software, pattern in software_patterns:
                        if re.search(pattern, xmp_str, re.IGNORECASE):
                            print(f"Found evidence of editing with: {software}")

                    # Check for multiple modification dates
                    mod_dates = re.findall(r'modifyDate|ModDate|modified=', xmp_str, re.IGNORECASE)
                    if len(mod_dates) > 1:
                        print(f"WARNING: Found {len(mod_dates)} modification date references - may indicate multiple edits")
                else:
                    print("No XMP metadata found.")
            except Exception as e:
                print(f"Could not extract XMP metadata: {e}")

            # Document encryption and security analysis
            print("\nDocument Security Analysis:")
            print("-" * 50)
            if pdf.is_encrypted:
                print("ALERT: Document is encrypted - this can hide editing history")
                print(f"Encryption method: {pdf.encryption_method}")

                # Check what permissions are enabled
                try:
                    print("Security Permissions:")
                    permissions = {
                        'print': pdf.can_print,
                        'modify': pdf.can_modify,
                        'copy': pdf.can_copy,
                        'annotate': pdf.can_annotate
                    }
                    for perm, val in permissions.items():
                        print(f"  - {perm}: {'Allowed' if val else 'Restricted'}")
                except:
                    print("Could not retrieve detailed permissions")
            else:
                print("Document is not encrypted")

            # Check for potential signs of manipulation
            print("\nForensic Indicators:")
            print("-" * 50)

            # Analyze creation vs modification dates
            creation_date = info.get('/CreationDate', None)
            mod_date = info.get('/ModDate', None)

            if creation_date and mod_date:
                if creation_date != mod_date:
                    print("NOTE: Creation date differs from modification date - document has been modified")
                else:
                    print("Creation date matches modification date - may be first version or dates were synchronized")

            # Check for creator/producer inconsistencies
            creator = info.get('/Creator', '')
            producer = info.get('/Producer', '')

            if creator and producer and creator != producer:
                print(f"Different creator ({creator}) and producer ({producer}) - may indicate conversion between formats")

            # Page count verification
            page_count = len(pdf.pages)
            print(f"Document contains {page_count} pages")

            # Check for incremental updates (sign of editing)
            try:
                with open(pdf_path, 'rb') as f:
                    content = f.read()
                    updates = content.count(b"%%EOF")
                    if updates > 1:
                        print(f"WARNING: Found {updates} 'EOF' markers - indicates {updates-1} document revisions")
                    else:
                        print("No evidence of incremental updates found")
            except:
                print("Could not analyze file for incremental updates")

            # Summary assessment
            print("\nFraud Detection Summary:")
            print("-" * 50)

            risk_indicators = []

            if pdf.is_encrypted:
                risk_indicators.append("Document is encrypted (could conceal changes)")
            if creation_date and mod_date and creation_date != mod_date:
                risk_indicators.append("Creation and modification dates differ")
            if updates > 1:
                risk_indicators.append(f"Document has been revised {updates-1} times")

            if risk_indicators:
                print("Potential Risk Indicators Detected:")
                for indicator in risk_indicators:
                    print(f"- {indicator}")
                print("\nRecommendation: Perform additional verification of document authenticity")
            else:
                print("No obvious risk indicators detected. Document appears consistent.")
                print("Note: Limited metadata doesn't guarantee document hasn't been altered.")

    except Exception as e:
        print(f"Error extracting PDF metadata: {str(e)}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70 + "\n")

def main():
    try:
        # API key
        api_key = "xinXihKFgx55WQJmuGp749rtwky4PSQU"  # Replace with your actual Mistral API key

        # Initialize Mistral client
        client = Mistral(api_key=api_key)

        # PDF path
        pdf_path = r"C:\Users\nihar\Downloads\Receipt-2606-4672.pdf"

        # Check if file exists
        if not os.path.isfile(pdf_path):
            print(f"Error: file not found at {pdf_path}")
            return

        print(f"Processing PDF: {pdf_path}")

        # Extract PDF metadata first for fraud detection
        extract_pdf_metadata(pdf_path)

        # Upload for OCR
        with open(pdf_path, "rb") as f:
            content = f.read()

        print("Uploading file for OCR processing...")
        uploaded = client.files.upload(
            file={
                "file_name": os.path.basename(pdf_path),
                "content": content
            },
            purpose="ocr"
        )

        # Get a signed URL
        print(f"File uploaded with ID: {uploaded.id}")
        print("Getting signed URL...")
        signed = client.files.get_signed_url(file_id=uploaded.id)
        signed_url = signed.url

        # Run the OCR model
        print("Processing document with OCR...")
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            include_image_base64=True,
            document={
                "type": "document_url",
                "document_url": signed_url
            }
        )

        # Process each page
        print(f"\nExtracted {len(ocr_response.pages)} pages from the PDF")

        all_tables = []
        all_markdown = ""

        for i, page in enumerate(ocr_response.pages, start=1):
            blob = json.loads(page.model_dump_json())
            markdown = blob.get("markdown", "")
            all_markdown += markdown + "\n\n"

            print(f"\n\n=== Page {i} ===\n")
            print(markdown)

            # Extract tables from the markdown
            tables = extract_tables_from_markdown(markdown)
            print(f"\nFound {len(tables)} tables on page {i}")

            # Add to all tables
            all_tables.extend(tables)

        # Create output directory
        output_dir = os.path.join(os.path.dirname(pdf_path), "extracted_tables")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Save tables
        if all_tables:
            print(f"\nTotal tables found: {len(all_tables)}")
            csv_files = []
            excel_files = []

            for i, table in enumerate(all_tables):
                df = parse_table(table)

                # Skip empty tables or tables with no data rows
                if df.empty:
                    continue

                # Create base filename
                base_filename = os.path.join(output_dir, f"table_{i+1}")

                # Save table without formatting
                csv_file, excel_file = save_table(df, base_filename)
                csv_files.append(csv_file)
                excel_files.append(excel_file)

                print(f"Saved table {i+1}:")
                print(f"CSV: {csv_file}")
                print(f"Excel (unformatted): {excel_file}")
                print(f"Table preview:")
                print(df)
                print("\n")

            print(f"\nSuccessfully extracted {len(csv_files)} tables:")
            for file in csv_files:
                print(f" - {file}")

            # Open the folder with the exported files
            if csv_files:
                os.startfile(output_dir)
        else:
            print("No tables found in the document.")

        # Save full text
        text_file = os.path.join(output_dir, "full_text.txt")
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(all_markdown)
        print(f"Saved full text to {text_file}")

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()