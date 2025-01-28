import affinidi_tdk_wallets_client.api_client
from flask import Flask, Response, render_template, jsonify, request, send_file
from affinidi_tdk_wallets_client.models.sign_credential_input_dto_unsigned_credential_params import (
    SignCredentialInputDtoUnsignedCredentialParams,
)
from cryptography.hazmat.primitives.hashes import Hash, SHA256
from . import app
import affinidi_tdk_auth_provider
import affinidi_tdk_credential_issuance_client
import logging
from pypdf import PdfWriter, PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.lib import colors
from reportlab.lib.units import inch  # Import inch
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import uuid
import json
from io import BytesIO
import base64
import affinidi_tdk_credential_verification_client
import requests
import os
import hashlib
import qrcode
import datetime

api_gateway_url = os.environ.get("API_GATEWAY_URL")
token_endpoint = os.environ.get("TOKEN_ENDPOINT")
project_id = os.environ.get("PROJECT_ID")
private_key = os.environ.get("PRIVATE_KEY").replace("\\n", "\n")
token_id = os.environ.get("TOKEN_ID")
passphrase = os.environ.get("PASSPHRASE")
key_id = os.environ.get("KEY_ID")
vault_url = os.environ.get("VAULT_URL")
course_credential_type_id = os.environ.get("COURSE_CREDENTIAL_TYPE_ID")
personal_information_credential_type_id = os.environ.get(
    "PERSONAL_INFORMATION_CREDENTIAL_TYPE_ID"
)
employment_credential_type_id = os.environ.get("EMPLOYMENT_CREDENTIAL_TYPE_ID")
education_credential_type_id = os.environ.get("EDUCATION_CREDENTIAL_TYPE_ID")
address_credential_type_id = os.environ.get("ADDRESS_CREDENTIAL_TYPE_ID")
background_check_credential_type_id = os.environ.get(
    "BACKGROUND_CHECK_CREDENTIAL_TYPE_ID"
)
wallet_id = os.environ.get("WALLET_ID")
holder_did = os.environ.get("HOLDER_DID")
pdf_signature_json_context = os.environ.get("PDF_SIGNATURE_JSON")
pdf_signature_jsonld_context = os.environ.get("PDF_SIGNATURE_JSONLD")
pdf_signature_type_id = os.environ.get("PDF_SIGNATURE_TYPE_ID")

DATA_FILE = "orders/order.json"
CHECKS_DATA_DIR = "orders"


@app.route("/create-case")
def case():
    return render_template("case.html")


@app.route("/checks")
def checks():
    return render_template("checks.html")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/save-order", methods=["POST"])
def save_order():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    order_id = data.get("orderId")
    if not order_id:
        return jsonify({"success": False, "error": "orderId is required"}), 400

    checks_config = data.get("checks", {})
    payload_for_checks_api = {}

    try:
        if not os.path.exists(CHECKS_DATA_DIR):
            os.makedirs(CHECKS_DATA_DIR)

        for check_type, should_run in checks_config.items():
            if should_run:
                check_file = os.path.join(CHECKS_DATA_DIR, f"{check_type}.json")
                if os.path.exists(check_file):
                    with open(check_file, "r") as f:
                        try:
                            check_data = json.load(f)
                            payload_for_checks_api[check_type] = check_data
                        except json.JSONDecodeError:
                            logging.error(f"{check_file} is corrupted.")
                            return (
                                jsonify(
                                    {
                                        "success": False,
                                        "error": f"Error reading {check_type} data.",
                                    }
                                ),
                                500,
                            )
                else:
                    logging.warning(f"Check data file not found: {check_file}")
                    return (
                        jsonify(
                            {"success": False, "error": f"{check_type} data not found."}
                        ),
                        400,
                    )

        # Now, payload_for_checks_api contains the data for the checks that should run.
        # Here you would typically make a request to the other API:
        # response = requests.post("other_api_url", json=payload_for_checks_api)
        # For this example, we'll just log the payload.

        # print(f"Payload for checks API: {payload_for_checks_api}")
        credentials_request = [
            {
                "credentialTypeId": background_check_credential_type_id,
                "credentialData": payload_for_checks_api,
            }
        ]
        # print("credentials_request", credentials_request)

        # Pass the projectScopedToken generated from AuthProvider package
        configuration = affinidi_tdk_credential_issuance_client.Configuration()
        configuration.api_key["ProjectTokenAuth"] = pst()

        with affinidi_tdk_credential_issuance_client.ApiClient(
            configuration
        ) as api_client:
            api_instance = affinidi_tdk_credential_issuance_client.IssuanceApi(
                api_client
            )

            projectId = project_id
            request_json = {"data": credentials_request, "claimMode": "TX_CODE"}
            # print("request_json", request_json)

            start_issuance_input = (
                affinidi_tdk_credential_issuance_client.StartIssuanceInput.from_dict(
                    request_json
                )
            )
            api_response = api_instance.start_issuance(
                projectId, start_issuance_input=start_issuance_input
            )

            # print("api_response", api_response)
            response = api_response.to_dict()
            response["vaultLink"] = (
                vault_url
                + f"/claim?credential_offer_uri={response['credentialOfferUri']}"
            )
            print("response", response)

    except Exception as e:
        logging.error(f"Error processing checks: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    # Call /api/issuance/status with the given payload
    status_payload = {
        "issuanceId": response.get("issuanceId"),
        "projectId": project_id,
    }
    status_response = requests.post(
        "http://127.0.0.1:5000/api/issuance/status", json=status_payload
    )
    # print("Status response:", status_response.json())

    if not os.path.exists(CHECKS_DATA_DIR):
        os.makedirs(CHECKS_DATA_DIR)

    orders_file = os.path.join(CHECKS_DATA_DIR, "order.json")

    try:
        # Read existing orders
        if os.path.exists(orders_file) and os.path.getsize(orders_file) > 0:
            with open(orders_file, "r") as f:
                orders = json.load(f)
                if not isinstance(orders, list):
                    orders = []  # Reset to empty list if not a list
        else:
            orders = []

        # Add backgroundCheckDetails to the order data
        data["backgroundCheckDetails"] = payload_for_checks_api
        data["issuanceResponse"] = response
        data["issuanceState"] = status_response.json()
        orders.append(data)

        # Write updated orders back to the file
        with open(orders_file, "w") as f:
            json.dump(orders, f, indent=4)

        response["success"] = True
        return response, 200
    except Exception as e:
        logging.error(f"Error saving order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/orders", methods=["GET"])
def orders_page():
    return render_template("orders.html")


@app.route("/get_orders", methods=["GET"])
def get_orders():
    try:
        with open(DATA_FILE, "r") as f:
            orders = json.load(f)
            # Convert checks dictionary to a list if it's a dictionary
            check_mapping = {
                "personalInfo": "Personal Information Verification",
                "address": "Address Verification",
                "education": "Education Verification",
                "employment": "Employment Details Verification with HR",
                "criminal": "Civil Litigation Check",
            }

            for order in orders:
                if isinstance(order.get("checks"), dict):
                    order["checks"] = [
                        check for check, value in order["checks"].items() if value
                    ]
                    order["checks"] = [
                        check_mapping.get(check, check) for check in order["checks"]
                    ]
            # print(orders)
        return jsonify(orders)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify([]), 200


@app.route("/generate_pdf/<order_id>")
def generate_pdf(order_id):
    try:
        with open(DATA_FILE, "r") as f:
            orders = json.load(f)
    except FileNotFoundError:
        return "Orders file not found.", 404
    except json.JSONDecodeError:
        return "Invalid JSON in orders file.", 500

    order = next((o for o in orders if o["orderId"] == order_id), None)
    if not order:
        return "Order not found", 404

    # call generae_pdf_report function
    print("Calling generae_pdf_report function ")
    pdf_buffer = generate_pdf_report(order)

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        download_name=f"order_{order_id}.pdf",
        as_attachment=True,
    )


@app.route("/generate_secure_pdf/<order_id>")
def generate_secure_pdf(order_id):
    try:
        with open(DATA_FILE, "r") as f:
            orders = json.load(f)
    except FileNotFoundError:
        return "Orders file not found.", 404
    except json.JSONDecodeError:
        return "Invalid JSON in orders file.", 500

    order = next((o for o in orders if o["orderId"] == order_id), None)
    if not order:
        return "Order not found", 404

    # call generae_pdf_report function
    # Generate initial PDF report (same as before)
    pdf_secure_buffer = generate_pdf_report(order)

    pdf_writer = PdfWriter()
    pdf_reader = PdfReader(pdf_secure_buffer)  # Use the buffer as input
    pdf_writer.append_pages_from_reader(pdf_reader)

    # --- Calculate hash of the INITIAL PDF CONTENT (WITHOUT QR, ATTACHMENTS) ---
    pdf_hash_excluding_attachments = hash_pdf_content_excluding_attachments(pdf_reader)
    print("pdf_hash_excluding_attachments (initial)", pdf_hash_excluding_attachments)

    # --- NOW add the QR code page ---
    url = "http://127.0.0.1:5000/verify"
    qr_buffer = generate_qr_code(url)  # url same as before

    qr_reader = ImageReader(qr_buffer)
    qr_page_buffer = BytesIO()
    c = canvas.Canvas(qr_page_buffer, pagesize=A4)
    c.drawString(100, 750, f"Click here ({url}) for Verification")
    c.linkURL(url, (100, 740, 300, 760), relative=0)
    c.drawImage(qr_reader, 100, 600, width=100, height=100)
    c.showPage()

    c.save()
    qr_page_buffer.seek(0)

    pdf_reader_qr = PdfReader(qr_page_buffer)
    pdf_writer.append_pages_from_reader(pdf_reader_qr)

    # --- Calculate hash of the PDF (including QR code, excluding attachments) ---
    # Create a new PdfReader from the current state of the pdf_writer:
    current_pdf_buffer = BytesIO()
    pdf_writer.write(current_pdf_buffer)
    current_pdf_buffer.seek(0)
    pdf_reader_with_qr = PdfReader(current_pdf_buffer)  # Reader with QR

    pdf_hash_with_qr = hash_pdf_content_excluding_attachments(pdf_reader_with_qr)
    print("pdf_hash_with_qr", pdf_hash_with_qr)  # Hash including QR code

    # --- Add the attachments (including the signature which we will generate NOW) ---
    issued_credentials = order.get("issuedCredentials")
    # print("=====issued_credentials=======", issued_credentials)
    if issued_credentials:
        json_buffer = get_file_content_buffer(issued_credentials)
        pdf_writer.add_attachment("issuedCredentials.json", json_buffer.getbuffer())

    pdf_signature = pdf_signature_vc(pdf_hash_with_qr)  # Sign the initial hash
    print("pdf_signature", pdf_signature)
    if pdf_signature:
        json_buffer = get_file_content_buffer(pdf_signature)
        pdf_writer.add_attachment("PDFSignature.json", json_buffer.getbuffer())

    # --- Write the final PDF (now with QR and attachments) ---
    final_pdf_buffer = BytesIO()
    pdf_writer.write(final_pdf_buffer)
    final_pdf_buffer.seek(0)

    return send_file(
        final_pdf_buffer,
        mimetype="application/pdf",
        download_name=f"secure_pdf_{order_id}.pdf",
        as_attachment=True,
    )


@app.route("/api/issuance/status", methods=["POST"])
def issuance_status():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    issuance_id = data.get("issuanceId")
    if not issuance_id:
        return jsonify({"error": "issuanceId is required"}), 400

    try:
        # Pass the projectScopedToken generated from AuthProvider package
        configuration = affinidi_tdk_credential_issuance_client.Configuration()
        configuration.api_key["ProjectTokenAuth"] = pst()

        with affinidi_tdk_credential_issuance_client.ApiClient(
            configuration
        ) as api_client:
            api_instance = affinidi_tdk_credential_issuance_client.IssuanceApi(
                api_client
            )

            projectId = project_id
            issuanceId = issuance_id

            api_response = api_instance.issuance_state(issuanceId, projectId)

            response = api_response.to_dict()
            return jsonify(response)
    except Exception as e:
        logging.error(f"Error getting issuance status: {e}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/accept-credential-status", methods=["POST"])
def accept_credential_status():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    issuance_id = data.get("issuanceId")
    if not issuance_id:
        return jsonify({"error": "issuanceId is required"}), 400

    try:
        with open(DATA_FILE, "r") as f:
            try:
                orders = json.load(f)
            except json.JSONDecodeError:
                logging.error("Error decoding order.json. File might be corrupted.")
                return jsonify({"error": "Invalid order data"}), 500

        updated = False
        for order in orders:
            if order["issuanceResponse"]["issuanceId"] == issuance_id:
                if "issuanceState" in order:
                    order["issuanceState"].update(data)
                else:
                    order["issuanceState"] = data
                updated = True

                if data.get("status") == "VC_CLAIMED":
                    issued_credentials_response = issued_credentials()
                    if (
                        issued_credentials_response
                        and issued_credentials_response[1] == 200
                    ):
                        issued_credentials_data = issued_credentials_response[0]
                        order["issuedCredentials"] = (
                            issued_credentials_data  # Update IN PLACE
                        )
                break

        if not updated:
            return jsonify({"error": "No order with issuanceId exists"}), 404

        with open(DATA_FILE, "w") as f:
            json.dump(orders, f, indent=4)  # Write ONCE after ALL updates

        return jsonify({"success": True, "message": "Order updated successfully"}), 200

    except Exception as e:
        logging.error(f"Error updating order: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/issued-credentials", methods=["POST"])
def issued_credentials():
    try:
        with open(os.path.join(CHECKS_DATA_DIR, "issuedCredentials.json"), "r") as f:
            issued_credentials = json.load(f)
        # print("issued_credentials", issued_credentials)
        return issued_credentials, 200
    except FileNotFoundError:
        return jsonify({"error": "issuedCredentials.json file not found"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON in issuedCredentials.json file"}), 500


def get_file_content_buffer(credential):
    json_buffer = BytesIO()
    json_buffer.write(json.dumps(credential).encode("utf-8"))
    json_buffer.seek(0)
    return json_buffer


def generate_qr_code(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url)
    qr.make(fit=True)

    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    return qr_buffer


@app.route("/verify")
def verify():
    return render_template("verify.html")


@app.route("/api/verify_pdf", methods=["POST"])
def verify_pdf():

    try:
        if "report_pdf" not in request.files:
            return jsonify({"error": "No PDF file uploaded"}), 400

        pdf_file = request.files["report_pdf"]
        pdf_buffer = BytesIO(pdf_file.read())

        pdf_reader = PdfReader(pdf_buffer)

        # 1. Extract the Signature and Hash:
        signature_data = None
        signature_verified = False  # Flag to track if any signature is verified
        for filename, data in pdf_reader.attachments.items():
            if filename == "PDFSignature.json":
                try:
                    signature_data = json.loads(
                        "".join([item.decode("utf-8") for item in data])
                    )
                    signature_data_vc = signature_data.get("signedCredential")
                    # print("signature_data_vc", signature_data_vc)
                    verification_results = verification(signature_data_vc)
                    print("verification_results", verification_results)
                    if verification_results.get("isValid") == "True":
                        signature_verified = True
                        break  # Exit loop once signature is found and verified
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return jsonify({"error": "Invalid signature format"}), 400
        for filename, data in pdf_reader.attachments.items():
            if filename == "issuedCredentials.json":
                try:
                    issued_credentials = json.loads(
                        "".join([item.decode("utf-8") for item in data])
                    )
                    issued_credentials_vc = issued_credentials.get("signedCredential")
                    # print("issued_credentials", issued_credentials)
                    verification_results = verification(issued_credentials_vc)
                    print("verification_results", verification_results)
                    if verification_results.get("isValid") == "True":
                        signature_verified = True
                        break  # Exit loop once signature is found and verified
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return jsonify({"error": "Invalid issuedCredentials format"}), 400

        # if not signature_verified:  # Check AFTER the loop
        #     return (
        #         jsonify({"error": "No valid signature found. VC Verification failed"}),
        #         400,
        #     )
        if not signature_data:
            return jsonify({"error": "Signature not found"}), 400

        expected_hash = signature_data_vc["credentialSubject"].get(
            "hashWithoutAttachments"
        )  # Get the hash from signature
        if not expected_hash:
            return jsonify({"error": "Hash not found in signature"}), 400

        # 2. Calculate the Hash of the PDF (excluding attachments)
        calculated_hash = hash_pdf_content_excluding_attachments(pdf_reader)
        print("calculated_hash", calculated_hash)
        print("expected_hash", expected_hash)

        # 3. Verify the Signature (Compare Hashes)
        if calculated_hash == expected_hash:
            return (
                jsonify(
                    {
                        "PDF Signature Validation": "Valid PDF",
                        "Calculated Hash": calculated_hash,
                        "Expected Hash": expected_hash,
                        "Issued Credentials": issued_credentials,
                        "PDF Signature": signature_data,
                    }
                ),
                200,
            )  # Successful verification
        else:
            return (
                jsonify(
                    {
                        "PDF Signature Validation": "Invalid PDF",
                        "Calculated Hash": calculated_hash,
                        "Expected Hash": expected_hash,
                        "Issued Credentials": issued_credentials,
                        "PDF Signature": signature_data,
                    }
                ),
                400,
            )  # Hash mismatch

    except Exception as e:
        logging.exception("Error verifying PDF:")
        return jsonify({"error": str(e)}), 500


def pst():
    stats = {
        "apiGatewayUrl": api_gateway_url,
        "tokenEndpoint": token_endpoint,
        "projectId": project_id,
        "privateKey": private_key,
        "tokenId": token_id,
        "vaultUrl": vault_url,
    }
    # print("stats", stats)
    authProvider = affinidi_tdk_auth_provider.AuthProvider(stats)
    projectScopedToken = authProvider.fetch_project_scoped_token()
    print("projectScopedToken", projectScopedToken)
    return projectScopedToken


def verification(request):
    verification_results = {}  # Store results for each file
    # for filename, content in request.items():
    #     if not filename.endswith(".json"):
    #         continue

    print("verification input:", request)
    verifiable_credentials = request

    url = api_gateway_url + f"/ver/v1/verifier/verify-vcs"
    headers = {
        "Authorization": f"Bearer {
        pst()}",
        "Content-Type": "application/json",
    }

    body = {"verifiableCredentials": [verifiable_credentials]}

    response = requests.post(url, headers=headers, json=body)
    api_response = response.json()
    print("api_response", api_response)
    return api_response


def hash_pdf_content(pdf_buffer):
    # Get the PDF content
    pdf_buffer.seek(0)
    pdf_content = pdf_buffer.getvalue()

    # Hash the content
    pdf_hash = hashlib.sha256(pdf_content).hexdigest()
    return pdf_hash


def hash_pdf_content_excluding_attachments(pdf_reader):
    try:
        extracted_text = ""
        for page in pdf_reader.pages:
            extracted_text += page.extract_text()  # Extract text from each page

        pdf_hash = hashlib.sha256(
            extracted_text.encode("utf-8")
        ).hexdigest()  # Hash the TEXT
        return pdf_hash
    except Exception as e:
        raise RuntimeError(f"Error processing PDF: {e}")


def generate_pdf_report(order):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    styleN = styles["Normal"]
    styleH = styles["Heading2"]  # Use a heading style for check titles

    # Header Table Data
    header_data = [
        [
            "Candidate/Employee Full Name",
            "GRAJESH CHANDRA",
            "Order ID",
            order.get("orderId", "-"),
        ],
        ["Company Name", "TEST COMPANY", "Branch Name", ""],
        ["Date of Report", "02-02-2024", "Cost Centre", "-"],
        ["Package Code/Level (if any)", "", "Case Reference No.", "AV0202240DA1OTA"],
        ["Result", "Processing", "", ""],
    ]

    # Apply word wrap to the header data
    for row in header_data:
        for i in range(len(row)):
            row[i] = Paragraph(row[i], styleN)

    # Checks Table Data
    checks_data = [
        [
            "Selected Checks",
            "Years Of Coverage",
            "Country Name",
            "Verified Status",
            "Remarks",
        ]
    ]
    check_mapping = {
        "personalInfo": "Personal Information Verification",
        "address": "Address Verification",
        "education": "Education Verification",
        "employment": "Employment Details Verification with HR",
        "criminal": "Civil Litigation Check",
    }

    for check_name, check_value in order.get("checks", {}).items():
        if check_value:
            check_name = check_mapping.get(check_name, check_name)
            checks_data.append([check_name, "-", "Worldwide", "In Progress", ""])

    # Apply word wrap to the header data
    for row in checks_data:
        for i in range(len(row)):
            row[i] = Paragraph(row[i], styleN)

    # Table Styles
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.orange),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]
    )

    # Calculate available width (accounting for margins)
    available_width = letter[0] - 2 * inch  # 1-inch margins on left and right

    # Create Tables with adjusted colWidths and wrapOn
    header_table = Table(header_data, colWidths=[available_width / 4.0] * 4)
    header_table.setStyle(table_style)
    w1, h1 = header_table.wrapOn(p, available_width, letter[1])
    header_table.drawOn(p, inch, 7.5 * inch)

    p.drawCentredString(
        letter[0] / 2, 7.5 * inch - h1 - 0.2 * inch, "Background Verification Summary"
    )
    p.line(
        inch,
        7.5 * inch - h1 - 0.3 * inch,
        letter[0] - inch,
        7.5 * inch - h1 - 0.3 * inch,
    )
    Spacer(1, 0.2 * inch).wrapOn(p, available_width, letter[1])

    checks_table = Table(checks_data, colWidths=[available_width / 5.0] * 5)
    checks_table.setStyle(table_style)
    checks_table.wrapOn(p, available_width, letter[1])
    checks_table.drawOn(p, inch, 7.5 * inch - h1 - 0.5 * inch - checks_table._height)

    p.showPage()
    # Add a new page for each check
    for check_name, check_value in order.get("checks", {}).items():
        if check_value:
            check_display_name = check_mapping.get(check_name, check_name)

            p.setFont("Helvetica-Bold", 16)
            p.drawCentredString(letter[0] / 2, 10.5 * inch, check_display_name)
            p.setFont("Helvetica", 12)

            check_details = [
                ["Field Name", "Personal Details", "Verified Value"],
            ]
            # Example Data. Replace with your actual data retrieval logic
            if check_name == "personalInfo":
                personal_info = order.get(
                    "personalInfoDetails", {}
                )  # Access the personalInfoDetails
                check_details.extend(
                    [
                        [
                            "First Name",
                            personal_info.get("firstName", "Grajesh"),
                            personal_info.get("firstName", "-"),
                        ],
                        [
                            "Last Name",
                            personal_info.get("lastName", "Chandra"),
                            personal_info.get("lastName", "-"),
                        ],
                        [
                            "Birthdate",
                            personal_info.get("birthdate", "-"),
                            personal_info.get("birthdate", "-"),
                        ],
                        [
                            "Country of Birth",
                            personal_info.get("birthCountry", "-"),
                            personal_info.get("birthCountry", "-"),
                        ],
                        [
                            "Email Address",
                            personal_info.get("email", "-"),
                            personal_info.get("email", "-"),
                        ],
                        [
                            "Gender",
                            personal_info.get("gender", "-"),
                            personal_info.get("gender", "-"),
                        ],
                    ]
                )
            # Add similar blocks for other check types (address, education, etc.)
            elif check_name == "address":
                addressInfo = order.get("addressInfoDetails", {})
                check_details.extend(
                    [
                        [
                            "Address",
                            addressInfo.get("addressLine1", "-"),
                            addressInfo.get("addressLine1", "-"),
                        ],
                        [
                            "City",
                            addressInfo.get("city", "-"),
                            addressInfo.get("city", "-"),
                        ],
                        [
                            "State",
                            addressInfo.get("state", "-"),
                            addressInfo.get("state", "-"),
                        ],
                        [
                            "Postal Code",
                            addressInfo.get("postalCode", "-"),
                            addressInfo.get("postalCode", "-"),
                        ],
                    ]
                )

            # Style the Check details table
            check_table_style = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.orange),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
            # Create and draw the table
            check_table = Table(check_details, colWidths=[available_width / 3.0] * 3)
            check_table.setStyle(check_table_style)
            check_table.wrapOn(p, available_width, letter[1])
            check_table.drawOn(p, inch, 8 * inch)
            p.showPage()

    p.save()
    buffer.seek(0)
    return buffer


# @app.route("/api/generate_pdf_signature_vc", methods=["POST"])
def pdf_signature_vc(pdf_hash) -> dict:  # Type hinting for clarity
    """Generates a signed verifiable credential (VC) for a given PDF hash.

    Args:
        pdf_hash: The hash of the PDF document to be signed.

    Returns:
        A dictionary containing the JSON response from the signing API, or
        None if an error occurs (consider raising an exception instead).

    Raises:
        requests.exceptions.RequestException: If there's an issue with the API request.
        # Or a custom exception if you prefer:
        # SigningError: If the signing process fails.
    """

    url = f"{api_gateway_url}/cwe/v1/wallets/{wallet_id}/sign-credential"

    headers = {
        "Authorization": f"Bearer {pst()}",  # More descriptive function name
        "Content-Type": "application/json",
    }

    expires_at = datetime.datetime.now() + datetime.timedelta(days=5 * 365)
    expires_at_str = expires_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    body = {
        "unsignedCredentialParams": {
            "jsonLdContextUrl": pdf_signature_jsonld_context,
            "jsonSchemaUrl": pdf_signature_json_context,
            "typeName": pdf_signature_type_id,
            "holderDid": holder_did,
            "credentialSubject": {
                "@type": ["VerifiableCredential", pdf_signature_type_id],
                "hashWithoutAttachments": pdf_hash,
            },
            "expiresAt": expires_at_str,
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error signing credential: {e}")  # Log the error
        # Consider raising the exception or returning None
        raise  # Re-raise the exception for handling higher up
        # return None  # Or return None if you want to handle the error differently
