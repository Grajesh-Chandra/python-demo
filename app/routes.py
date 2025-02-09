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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
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
import jwt  # PyJWT library for JWT handling
import time

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
TOKEN_FILE_PATH = "orders/pst_response.jwt"


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

    except Exception as e:
        logging.error(f"Error processing checks: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

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
        order_data = {
            "orderId": order_id,
            "checks": checks_config,
            "consent": data.get("consent", False),
            "backgroundCheckDetails": payload_for_checks_api,
            "issuanceResponse": {},
            "issuanceState": {},
            "caseStatus": "Pending",
        }
        orders.append(order_data)

        # Write updated orders back to the file
        with open(orders_file, "w") as f:
            json.dump(orders, f, indent=4)

        response = {"success": True, "message": "Order saved successfully"}
        return jsonify(response), 200
    except Exception as e:
        logging.error(f"Error saving order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/orders", methods=["GET"])
def orders_page():
    return render_template("orders.html")


@app.route("/get_orders", methods=["GET"])
def get_orders():
    try:
        status_filter = request.args.get("status", "all").lower()

        with open(DATA_FILE, "r") as f:
            orders = json.load(f)

            filtered_orders = []
            for order in orders:
                # Determine order status (keep this logic)
                order_status = (
                    "completed"
                    if order.get("caseStatus", {}) == "Completed"
                    else "pending"
                )

                # Apply filter (keep this logic)
                if status_filter == "all" or order_status == status_filter:
                    filtered_orders.append(order)

            return jsonify(
                filtered_orders
            )  # Return the filtered orders, checks will remain as dictionaries

    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify([]), 200  # Return empty list for file not found or JSON error
    except Exception as e:
        logging.error(f"Error fetching orders: {e}")  # Use logging for errors
        return jsonify({"error": "Internal server error"}), 500


@app.route("/order_details/<order_id>")
def order_details(order_id):
    orders_file = os.path.join(CHECKS_DATA_DIR, "order.json")
    order_detail = None
    try:
        if os.path.exists(orders_file) and os.path.getsize(orders_file) > 0:
            with open(orders_file, "r") as f:
                orders = json.load(f)
                for order in orders:
                    if order["orderId"] == order_id:
                        order_detail = order
                        break
    except Exception as e:
        logging.error(f"Error reading order file: {e}")
        return jsonify({"success": False, "error": "Error fetching order details"}), 500

    if order_detail:
        return render_template("order_details.html", order=order_detail)
    else:
        return jsonify({"success": False, "error": "Order not found"}), 404


@app.route("/update_order/<order_id>", methods=["POST"])
def update_order_details(order_id):
    orders_file = os.path.join(CHECKS_DATA_DIR, "order.json")
    try:
        if not os.path.exists(orders_file) or os.path.getsize(orders_file) == 0:
            return (
                jsonify({"success": False, "error": "Order file not found or empty."}),
                404,
            )

        with open(orders_file, "r") as f:
            orders = json.load(f)

        order_found_index = -1
        for index, order in enumerate(orders):
            if order["orderId"] == order_id:
                order_found_index = index
                break

        if order_found_index == -1:
            return jsonify({"success": False, "error": "Order not found"}), 404

        if request.json.get("backgroundCheckDetails"):
            edited_data = request.json.get("backgroundCheckDetails")
            orders[order_found_index]["backgroundCheckVerifiedDetails"] = edited_data
        elif request.json.get("caseStatus"):
            edited_data = request.json.get("caseStatus")
            orders[order_found_index]["caseStatus"] = edited_data
            if edited_data == "Completed":
                orders[order_found_index][
                    "completedAt"
                ] = datetime.datetime.now().isoformat()

                background_check_verified_details = orders[order_found_index].get(
                    "backgroundCheckVerifiedDetails", {}
                )

                issuance_response_data = (
                    {}
                )  # Initialize to store responses for each check
                for (
                    check_type,
                    check_details,
                ) in background_check_verified_details.items():
                    issuance_payload = {
                        check_type: check_details
                    }  # Payload for each check type
                    response = startIssuance(
                        issuance_payload
                    )  # Call startIssuance for each check
                    print(
                        f"Issuance Response for {check_type}:", response
                    )  # Print individual responses
                    issuance_response_data[check_type] = (
                        response  # Store response against check type
                    )

                orders[order_found_index][
                    "issuanceResponse"
                ] = issuance_response_data  # Store all responses

            else:
                orders[order_found_index]["completedAt"] = None
                raise ValueError("Invalid case status")

        else:
            return (
                jsonify(
                    {"success": False, "error": "No valid data provided for update."}
                ),
                400,
            )

        with open(orders_file, "w") as f:
            json.dump(orders, f, indent=4)  # Write updated orders back to file

        return (
            jsonify(
                {"success": True, "message": "Order details updated successfully."}
            ),
            200,
        )

    except Exception as e:
        logging.error(f"Error updating order {order_id}: {e}")
        return (
            jsonify({"success": False, "error": "Error updating order details."}),
            500,
        )


# @app.route("/test")
# def test():
#     return render_template("test.html")


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
    results = [
        {
            "key": "PDF File Upload",
            "value": "No PDF file uploaded",
            "result": "Invalid",
        },
        {
            "key": "PDFSignature VC Verification",
            "value": "Not Verified",
            "result": "Invalid",
        },
        {
            "key": "PDFSignature Attachment",
            "value": "Not Verified",
            "result": "Invalid",
        },
        {
            "key": "IssuedCredentials VC Verification",
            "value": "Not Verified",
            "result": "Invalid",
        },
        {
            "key": "IssuedCredentials Attachment",
            "value": "Not Verified",
            "result": "Invalid",
        },
        {"key": "PDF Hash", "value": "Not Verified", "result": "Invalid"},
    ]

    pdf_signature_valid = False
    issued_credentials_valid = False
    hash_match = False
    signature_data = None
    issued_credentials = None
    calculated_hash = None
    expected_hash = None

    try:
        if "report_pdf" not in request.files:
            return jsonify(results), 400

        pdf_file = request.files["report_pdf"]
        results[0]["value"] = pdf_file.filename
        results[0]["result"] = "Valid"

        pdf_buffer = BytesIO(pdf_file.read())
        pdf_reader = PdfReader(pdf_buffer)

        # 1. Extract and Verify Signature and Issued Credentials
        for filename, data in pdf_reader.attachments.items():
            if filename == "PDFSignature.json":
                try:
                    signature_data = json.loads(
                        "".join([item.decode("utf-8") for item in data])
                    )
                    results[2]["value"] = "PDFSignature.json attached"
                    results[2]["result"] = "Valid"

                    signature_data_vc = signature_data.get("signedCredential")
                    verification_results = verification(signature_data_vc)
                    if verification_results.get("isValid") == True:
                        pdf_signature_valid = True
                        results[1]["value"] = signature_data_vc
                        results[1]["result"] = "Valid"
                    else:
                        results[1]["value"] = signature_data_vc
                        results[1]["result"] = "Invalid"

                except (json.JSONDecodeError, UnicodeDecodeError):
                    results[2]["value"] = "Invalid PDFSignature.json Exception"
                    results[2]["result"] = "Invalid"
            elif filename == "issuedCredentials.json":
                try:
                    issued_credentials = json.loads(
                        "".join([item.decode("utf-8") for item in data])
                    )
                    results[4]["value"] = "issuedCredentials.json attached"
                    results[4]["result"] = "Valid"

                    issued_credentials_vc = issued_credentials.get("signedCredential")
                    verification_results = verification(issued_credentials_vc)
                    if verification_results.get("isValid") == True:
                        issued_credentials_valid = True
                        results[3]["value"] = issued_credentials_vc
                        results[3]["result"] = "Valid"
                    else:
                        results[3]["value"] = issued_credentials_vc
                        results[3]["result"] = "Invalid"

                except (json.JSONDecodeError, UnicodeDecodeError):
                    results[4]["value"] = "Invalid issuedCredentials.json Exception"
                    results[4]["result"] = "Invalid"

        if not signature_data:
            results[2]["value"] = "Missing PDFSignature.json"
            results[2]["result"] = "Invalid"

        if not issued_credentials:
            results[4]["value"] = "Missing issuedCredentials.json"
            results[4]["result"] = "Invalid"

        if (
            signature_data and pdf_signature_valid
        ):  # only proceed if signature data exists and is valid
            expected_hash = (
                signature_data.get("signedCredential", {})
                .get("credentialSubject", {})
                .get("hashWithoutAttachments")
            )
            if not expected_hash:
                results[5]["value"] = "Hash not found in signature"
                results[5]["result"] = "Invalid"
            else:
                # 2. Calculate the Hash of the PDF (excluding attachments)
                calculated_hash = hash_pdf_content_excluding_attachments(pdf_reader)

                # 3. Verify the Hash
                if calculated_hash == expected_hash:
                    hash_match = True
                    results[5][
                        "value"
                    ] = "No Change in Content of the PDF, Hash Details Match"
                    results[5]["result"] = "Valid"
                else:
                    results[5][
                        "value"
                    ] = "Content of the PDF is tempered with, Hash does not match"
                    results[5]["result"] = "Invalid"

        return jsonify(results), 200

    except Exception as e:
        logging.exception("Error verifying PDF:")
        results.append(
            {"key": "PDF Processing Error", "value": str(e), "result": "Invalid"}
        )
        return jsonify(results), 500


def pst():
    stats = {
        "apiGatewayUrl": api_gateway_url,  # Assuming these are defined elsewhere
        "tokenEndpoint": token_endpoint,
        "projectId": project_id,
        "privateKey": private_key,
        "tokenId": token_id,
        "vaultUrl": vault_url,
    }

    # Check if the token file exists and if it has a valid, unexpired token
    if os.path.exists(TOKEN_FILE_PATH):
        try:
            with open(TOKEN_FILE_PATH, "r") as f:
                stored_token = (
                    f.read().strip()
                )  # Read token from file and remove leading/trailing whitespace

            if stored_token:  # Check if the file is not empty
                decoded_token = jwt.decode(
                    stored_token, options={"verify_signature": False}
                )  # Decode without signature verification for expiry check

                if "exp" in decoded_token and decoded_token["exp"] > time.time():
                    print("Using stored valid token from file.")
                    return stored_token  # Return the stored token if it's valid and not expired
                else:
                    print(
                        "Stored token expired or 'exp' claim missing. Fetching new token."
                    )
        except (
            FileNotFoundError,
            jwt.PyJWTError,
            Exception,
        ) as e:  # Catch file errors, JWT decode errors, and other potential issues
            print(f"Error reading or decoding stored token: {e}. Fetching new token.")
            # In case of any error, proceed to fetch a new token
    else:
        print("Token file not found. Fetching new token.")

    # If no valid stored token is found (or file doesn't exist or errors occurred), fetch a new one
    authProvider = affinidi_tdk_auth_provider.AuthProvider(stats)
    projectScopedToken = authProvider.fetch_project_scoped_token()
    print("projectScopedToken (newly fetched)", projectScopedToken)

    # Store the newly fetched token to the file for future use
    try:
        os.makedirs(
            os.path.dirname(TOKEN_FILE_PATH), exist_ok=True
        )  # Ensure directory exists
        with open(TOKEN_FILE_PATH, "w") as f:
            f.write(projectScopedToken)
        print(f"New token stored in {TOKEN_FILE_PATH}")
    except IOError as e:
        print(f"Error writing token to file {TOKEN_FILE_PATH}: {e}")
        # Consider what to do if saving the token fails. Maybe return the token anyway, or raise an exception.
        # For now, we'll just print an error and return the token

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
            "GRAJESH CHANDRA",  # This is hardcoded, might need to be dynamic if candidate name is in order data
            "Order ID",
            order.get("orderId", "-"),
        ],
        [
            "Company Name",
            "TEST COMPANY",
            "Branch Name",
            "",
        ],  # Company Name is hardcoded
        ["Date of Report", "02-02-2024", "Cost Centre", "-"],  # Date is hardcoded
        [
            "Package Code/Level (if any)",
            "",
            "Case Reference No.",
            "AV0202240DA1OTA",
        ],  # Case ref is hardcoded
        ["Result", "Processing", "", ""],  # Result is hardcoded
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
            verification_status = "In Progress"  # Default status
            if order.get("backgroundCheckDetails") and order[
                "backgroundCheckDetails"
            ].get(check_name.split(" ")[0].lower()):
                verification_status = order["backgroundCheckDetails"][
                    check_name.split(" ")[0].lower()
                ].get("verificationStatus", "In Progress")

            checks_data.append([check_name, "-", "Worldwide", verification_status, ""])

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
            p.drawCentredString(
                letter[0] / 2, 7.5 * inch, check_display_name
            )  # Adjusted position to 7.5 inch
            p.setFont("Helvetica", 12)

            check_details = [
                ["Field Name", "Personal Details", "Verified Value"],
            ]
            # Example Data. Replace with your actual data retrieval logic
            if check_name == "personalInfo":
                personal_info = order.get("backgroundCheckDetails", {}).get(
                    "personalInfo", {}
                )  # Access personalInfo from backgroundCheckDetails
                if personal_info:  # Check if personal_info exists
                    pi_name = personal_info.get("PIname", {})
                    verification_evidence = personal_info.get(
                        "verificationEvidence", {}
                    )

                    check_details.extend(
                        [
                            [
                                "Verification Status",
                                "-",
                                personal_info.get("verificationStatus", "-"),
                            ],
                            ["Given Name", "-", pi_name.get("givenName", "-")],
                            ["Family Name", "-", pi_name.get("familyName", "-")],
                            ["Nickname", "-", pi_name.get("nickname", "-")],
                            ["Birthdate", "-", personal_info.get("birthdate", "-")],
                            [
                                "Birth Country",
                                "-",
                                personal_info.get("birthCountry", "-"),
                            ],
                            ["Citizenship", "-", personal_info.get("citizenship", "-")],
                            [
                                "Phone Number",
                                "-",
                                personal_info.get("phoneNumber", "-"),
                            ],
                            ["Email Address", "-", personal_info.get("email", "-")],
                            ["Gender", "-", personal_info.get("gender", "-")],
                            [
                                "Marital Status",
                                "-",
                                personal_info.get("maritalStatus", "-"),
                            ],
                            [
                                "Verification Evidence Name",
                                "-",
                                verification_evidence.get("evidenceName1", "-"),
                            ],
                            [
                                "Verification Evidence URL",
                                "-",
                                verification_evidence.get("evidenceURL1", "-"),
                            ],
                            [
                                "Verification Remarks",
                                "-",
                                personal_info.get("verificationRemarks", "-"),
                            ],
                        ]
                    )
            elif check_name == "address":
                address_info = order.get("backgroundCheckDetails", {}).get(
                    "address", {}
                )  # Access address from backgroundCheckDetails
                if address_info:  # Check if address_info exists
                    address_data = address_info.get("address", {})
                    owner_details = address_info.get("ownerDetails", {})
                    neighbour_details = address_info.get("neighbourDetails", {})
                    stay_details = address_info.get("stayDetails", {})
                    verification_evidence = address_info.get("verificationEvidence", {})

                    check_details.extend(
                        [
                            [
                                "Verification Status",
                                "-",
                                address_info.get("verificationStatus", "-"),
                            ],
                            [
                                "Address Line 1",
                                "-",
                                address_data.get("addressLine1", "-"),
                            ],
                            [
                                "Address Line 2",
                                "-",
                                address_data.get("addressLine2", "-"),
                            ],
                            ["Postal Code", "-", address_data.get("postalCode", "-")],
                            [
                                "Address Region",
                                "-",
                                address_data.get("addressRegion", "-"),
                            ],
                            [
                                "Address Country",
                                "-",
                                address_data.get("addressCountry", "-"),
                            ],
                            ["Owner Name", "-", owner_details.get("ownerName", "-")],
                            [
                                "Neighbour Name",
                                "-",
                                neighbour_details.get("neighbourName", "-"),
                            ],
                            ["Stay From Date", "-", stay_details.get("fromDate", "-")],
                            ["Stay To Date", "-", stay_details.get("toDate", "-")],
                            [
                                "Verification Evidence Name",
                                "-",
                                verification_evidence.get("evidenceName1", "-"),
                            ],
                            [
                                "Verification Evidence URL",
                                "-",
                                verification_evidence.get("evidenceURL1", "-"),
                            ],
                            [
                                "Verification Remarks",
                                "-",
                                address_info.get("verificationRemarks", "-"),
                            ],
                        ]
                    )

            elif check_name == "education":
                education_info = order.get("backgroundCheckDetails", {}).get(
                    "education", {}
                )  # Access education from backgroundCheckDetails
                if education_info:  # Check if education_info exists
                    candidate_details = education_info.get("candidateDetails", {})
                    institution_details_data = education_info.get(
                        "institutionDetails", {}
                    )  # Renamed to avoid conflict
                    institution_address = education_info.get("institutionAddress", {})
                    education_details_data = education_info.get(
                        "educationDetails", {}
                    )  # Renamed to avoid conflict
                    verification_evidence = education_info.get(
                        "verificationEvidence", {}
                    )

                    check_details.extend(
                        [
                            [
                                "Verification Status",
                                "-",
                                education_info.get("verificationStatus", "-"),
                            ],
                            [
                                "Candidate Name",
                                "-",
                                candidate_details.get("studentName", "-"),
                            ],
                            [
                                "Institution Details",
                                "-",
                                institution_details_data,
                            ],  # Showing institutionDetails as is
                            [
                                "Institution Address Line 1",
                                "-",
                                institution_address.get("addressLine1", "-"),
                            ],
                            [
                                "Institution Address Country",
                                "-",
                                institution_address.get("addressCountry", "-"),
                            ],
                            [
                                "Qualification",
                                "-",
                                education_details_data.get("qualification", "-"),
                            ],
                            ["Course", "-", education_details_data.get("course", "-")],
                            [
                                "Graduation Date",
                                "-",
                                education_details_data.get("graduationDate", "-"),
                            ],
                            [
                                "Verification Evidence Name",
                                "-",
                                verification_evidence.get("evidenceName1", "-"),
                            ],
                            [
                                "Verification Evidence URL",
                                "-",
                                verification_evidence.get("evidenceURL1", "-"),
                            ],
                            [
                                "Verification Remarks",
                                "-",
                                education_info.get("verificationRemarks", "-"),
                            ],
                        ]
                    )
            elif check_name == "employment":
                employment_info = order.get("backgroundCheckDetails", {}).get(
                    "employment", {}
                )  # Access employment from backgroundCheckDetails
                if employment_info:  # Check if employment_info exists
                    candidate_details = employment_info.get("candidateDetails", {})
                    employer_details_data = employment_info.get(
                        "employerDetails", {}
                    )  # Renamed to avoid conflict
                    company_address = employer_details_data.get("companyAddress", {})
                    hr_details = employer_details_data.get("hRDetails", {})
                    employment_details_data = employer_details_data.get(
                        "employmentDetails", {}
                    )  # Renamed to avoid conflict
                    verification_evidence = employer_details_data.get(
                        "verificationEvidence", {}
                    )

                    check_details.extend(
                        [
                            [
                                "Verification Status",
                                "-",
                                employer_details_data.get("verificationStatus", "-"),
                            ],
                            [
                                "Employee Name",
                                "-",
                                candidate_details.get("employeeName", "-"),
                            ],
                            [
                                "Company Name",
                                "-",
                                employer_details_data.get("companyName", "-"),
                            ],
                            [
                                "Company Address Line 1",
                                "-",
                                company_address.get("addressLine1", "-"),
                            ],
                            [
                                "Company Address Country",
                                "-",
                                company_address.get("addressCountry", "-"),
                            ],
                            [
                                "Designation",
                                "-",
                                employment_details_data.get("designation", "-"),
                            ],
                            [
                                "Employment Status",
                                "-",
                                employment_details_data.get("employmentStatus", "-"),
                            ],
                            [
                                "Annualised Salary",
                                "-",
                                employment_details_data.get("annualisedSalary", "-"),
                            ],
                            [
                                "Currency",
                                "-",
                                employment_details_data.get("currency", "-"),
                            ],
                            [
                                "Tenure From Date",
                                "-",
                                employment_details_data.get("tenure", {}).get(
                                    "fromDate", "-"
                                ),
                            ],  # Access nested 'fromDate'
                            [
                                "Tenure To Date",
                                "-",
                                employment_details_data.get("tenure", {}).get(
                                    "toDate", "-"
                                ),
                            ],  # Access nested 'toDate'
                            [
                                "Verification Evidence Name 1",
                                "-",
                                verification_evidence.get("evidenceName1", "-"),
                            ],
                            [
                                "Verification Evidence URL 1",
                                "-",
                                verification_evidence.get("evidenceURL1", "-"),
                            ],
                            [
                                "Verification Evidence Name 2",
                                "-",
                                verification_evidence.get("evidenceName2", "-"),
                            ],
                            [
                                "Verification Evidence URL 2",
                                "-",
                                verification_evidence.get("evidenceURL2", "-"),
                            ],
                            [
                                "Verification Remarks",
                                "-",
                                employer_details_data.get("verificationRemarks", "-"),
                            ],
                        ]
                    )
            elif check_name == "criminal":
                criminal_info = order.get("backgroundCheckDetails", {}).get(
                    "criminal", {}
                )  # Access criminal from backgroundCheckDetails
                if criminal_info:  # Check if criminal_info exists
                    check_details.extend(
                        [
                            ["Case ID", "-", criminal_info.get("caseId", "-")],
                            ["Crime Type", "-", criminal_info.get("crimeType", "-")],
                            [
                                "Crime Description",
                                "-",
                                criminal_info.get("crimeDescription", "-"),
                            ],
                            ["Crime Date", "-", criminal_info.get("crimeDate", "-")],
                            [
                                "Crime Location",
                                "-",
                                criminal_info.get("crimeLocation", "-"),
                            ],
                            ["Status", "-", criminal_info.get("status", "-")],
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
            # Apply word wrap to check details table
            for row in check_details:
                for i in range(len(row)):
                    row[i] = Paragraph(row[i], styleN)
            # Create and draw the table
            check_table = Table(check_details, colWidths=[available_width / 3.0] * 3)
            check_table.setStyle(check_table_style)
            check_table.wrapOn(p, available_width, letter[1])
            check_table.drawOn(
                p, inch, 6.5 * inch - check_table._height
            )  # Adjusted Y position dynamically based on table height
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


def startIssuance(payload_for_issuance_api):
    try:
        credentials_request = [
            {
                "credentialTypeId": background_check_credential_type_id,
                "credentialData": payload_for_issuance_api,
            }
        ]
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
            print("request_json", request_json)

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
        return response
    except Exception as e:
        logging.error(f"Error processing checks: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
