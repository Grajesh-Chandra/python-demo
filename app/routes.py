from flask import Flask, Response, render_template, jsonify, request, send_file

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

        print(f"Payload for checks API: {payload_for_checks_api}")
        credentials_request = [
            {
                "credentialTypeId": background_check_credential_type_id,
                "credentialData": payload_for_checks_api,
            }
        ]
        print("credentials_request", credentials_request)

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

            print("api_response", api_response)
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
    print("Status response:", status_response.json())

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
            print(orders)
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

    return send_file(
        buffer,
        mimetype="application/pdf",
        download_name=f"order_{order_id}.pdf",
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
            if os.path.getsize(DATA_FILE) == 0:
                return jsonify({"error": "No order with issuanceId exists"}), 404
    except Exception as e:
        logging.error(f"Error reading order file: {e}")
        return jsonify({"error": str(e)}), 500
    try:
        # update the order.json file with the issuance_state payload
        with open(DATA_FILE, "r") as f:
            orders = json.load(f)
            for order in orders:
                if order["issuanceResponse"]["issuanceId"] == issuance_id:
                    if "issuanceState" in order:
                        order["issuanceState"].update(data)
                    else:
                        order["issuanceState"] = data
                    break
        with open(DATA_FILE, "w") as f:
            json.dump(orders, f, indent=4)

        if data.get("status") == "VC_CLAIMED":
            issued_credentials_response = issued_credentials()
            print("issued_credentials_response", issued_credentials_response)
        if issued_credentials_response[1] == 200:
            issued_credentials_data = issued_credentials_response[0]
            for order in orders:
                if order["issuanceResponse"]["issuanceId"] == issuance_id:
                    order["issuedCredentials"] = issued_credentials_data
                break
            with open(DATA_FILE, "w") as f:
                json.dump(orders, f, indent=4)
        return jsonify({"success": True, "message": "Order updated successfully"}), 200

    except Exception as e:
        logging.error(f"Error updating order: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/issued-credentials", methods=["POST"])
def issued_credentials():
    try:
        with open(os.path.join(CHECKS_DATA_DIR, "issuedCredentials.json"), "r") as f:
            issued_credentials = json.load(f)
        print("issued_credentials", issued_credentials)
        return issued_credentials, 200
    except FileNotFoundError:
        return jsonify({"error": "issuedCredentials.json file not found"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON in issuedCredentials.json file"}), 500


# try:
#     # Pass the projectScopedToken generated from AuthProvider package
#     configuration = affinidi_tdk_credential_issuance_client.Configuration()
#     configuration.api_key["ProjectTokenAuth"] = pst()

#     with affinidi_tdk_credential_issuance_client.ApiClient(
#         configuration
#     ) as api_client:
#         api_instance = affinidi_tdk_credential_issuance_client.IssuanceApi(
#             api_client
#         )

#         projectId = project_id

#         api_response = api_instance.issued_credentials(projectId)

#         response = api_response.to_dict()
#         return jsonify(response)
# except Exception as e:
#     logging.error(f"Error getting issued credentials: {e}")
#     return jsonify({"error": "An error occurred"}), 500


@app.route("/cis")
def cis():
    return render_template("cis.html")


@app.route("/iota")
def iota():
    return render_template("iota.html")


@app.route("/report")
def report():
    return render_template("report.html")


@app.route("/verify")
def verify():
    return render_template("verify.html")


@app.route("/api/issue-credential", methods=["POST"])
def issue_credentials():
    # Placeholder for issuing credentials
    # response = {"credentialOfferUri":"https://97dde52f-e99c-420e-885a-3cc3032e73d9.apse1.issuance.affinidi.io/offers/461349d1-4e6b-4588-b346-c7a9f71b9c30","txCode":"631279","issuanceId":"461349d1-4e6b-4588-b346-c7a9f71b9c30","expiresIn":600,"vaultLink":"https://vault.affinidi.com/claim?credential_offer_uri=https://97dde52f-e99c-420e-885a-3cc3032e73d9.apse1.issuance.affinidi.io/offers/461349d1-4e6b-4588-b346-c7a9f71b9c30"}

    try:
        type_id = request.json.get("credentialType")
        if not type_id:
            return jsonify({"error": "typeId is required"}), 400

        credentials_request = []
        print("credentialType", type_id)

        if type_id == "personalInformation":
            credentials_request = [
                {
                    "credentialTypeId": personal_information_credential_type_id,
                    "credentialData": {
                        "name": {
                            "givenName": "Grajesh",
                            "familyName": "Chandra",
                            "nickname": "Grajesh Testing",
                        },
                        "birthdate": "01-01-1990",
                        "birthCountry": "India",
                        "citizenship": "Indian",
                        "phoneNumber": "7666009585",
                        "nationalIdentification": {
                            "idNumber1": "pan",
                            "idType1": "askjd13212432d",
                        },
                        "email": "grajesh.c@affinidi.com",
                        "gender": "male",
                        "maritalStatus": "married",
                        "verificationStatus": "Completed",
                        "verificationEvidence": {
                            "evidenceName1": "letter",
                            "evidenceURL1": "http://localhost",
                        },
                        "verificationRemarks": "Done",
                    },
                }
            ]
        elif type_id == "address":
            credentials_request = [
                {
                    "credentialTypeId": address_credential_type_id,
                    "credentialData": {
                        "address": {
                            "addressLine1": "Varthur, Gunjur",
                            "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                            "postalCode": "560087",
                            "addressRegion": "Karnataka",
                            "addressCountry": "India",
                        },
                        "ownerDetails": {
                            "ownerName": "TestOwner",
                            "ownerContactDetails1": "+912325435634",
                        },
                        "neighbourDetails": {
                            "neighbourName": "Test Neighbour",
                            "neighbourContactDetails1": "+912325435634",
                        },
                        "stayDetails": {
                            "fromDate": "01-01-2000",
                            "toDate": "01-01-2020",
                        },
                        "verificationStatus": "Completed",
                        "verificationEvidence": {
                            "evidenceName1": "Letter",
                            "evidenceURL1": "http://localhost",
                        },
                        "verificationRemarks": "done",
                    },
                }
            ]
        elif type_id == "education":
            credentials_request = [
                {
                    "credentialTypeId": education_credential_type_id,
                    "credentialData": {
                        "candidateDetails": {
                            "name": "Grajesh Chandra",
                            "phoneNumber": "7666009585",
                            "email": "grajesh.c@affinidi.com",
                            "gender": "male",
                        },
                        "institutionDetails": {
                            "institutionName": "Affinidi",
                            "institutionAddress": {
                                "addressLine1": "Varthur, Gunjur",
                                "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                                "postalCode": "560087",
                                "addressRegion": "Karnataka",
                                "addressCountry": "India",
                            },
                            "institutionContact1": "+91 1234567890",
                            "institutionContact2": "+91 1234567890",
                            "institutionEmail": "test@affinidi.com",
                            "institutionWebsiteURL": "affinidi.com",
                        },
                        "educationDetails": {
                            "qualification": "Graduation",
                            "course": "MBA",
                            "graduationDate": "12-08-2013",
                            "dateAttendedFrom": "12-08-2011",
                            "dateAttendedTo": "12-07-2013",
                            "educationRegistrationID": "admins1223454356",
                        },
                        "verificationStatus": "Verified",
                        "verificationEvidence": {
                            "evidenceName1": "Degree",
                            "evidenceURL1": "http://localhost",
                        },
                        "verificationRemarks": "completed",
                    },
                }
            ]
        elif type_id == "employment":
            credentials_request = [
                {
                    "credentialTypeId": employment_credential_type_id,
                    "credentialData": {
                        "candidateDetails": {
                            "name": "Grajesh Chandra",
                            "phoneNumber": "7666009585",
                            "email": "grajesh.c@affinidi.com",
                            "gender": "male",
                        },
                        "employerDetails": {
                            "companyName": "Affinidi",
                            "companyAddress": {
                                "addressLine1": "Varthur, Gunjur",
                                "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                                "postalCode": "560087",
                                "addressRegion": "Karnataka",
                                "addressCountry": "India",
                            },
                            "hRDetails": {
                                "hRfirstName": "Testing",
                                "hRLastName": "HR",
                                "hREmail": "hr@affinidi.com",
                                "hRDesignation": "Lead HR",
                                "hRContactNumber1": "+911234567789",
                                "whenToContact": "9:00-6:00 PM",
                            },
                        },
                        "employmentDetails": {
                            "designation": "Testing",
                            "employmentStatus": "Fulltime",
                            "annualisedSalary": "10000",
                            "currency": "INR",
                            "tenure": {"fromDate": "05-2022", "toDate": "06-2050"},
                            "reasonForLeaving": "Resignation",
                            "eligibleForRehire": "Yes",
                        },
                        "verificationStatus": "Completed",
                        "verificationEvidence": {
                            "evidenceName1": "letter",
                            "evidenceURL1": "http://localhost",
                        },
                        "verificationRemarks": "Done",
                    },
                }
            ]
        else:
            return jsonify({"error": "Invalid typeId"}), 400

        print("credentials_request", credentials_request)

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

            print("api_response", api_response)
            response = api_response.to_dict()
            response["vaultLink"] = (
                vault_url
                + f"/claim?credential_offer_uri={response['credentialOfferUri']}"
            )
            print("response", response)
        return jsonify(response)

    except Exception as e:
        logging.error(f"Error in credential_request: {e}")
        return jsonify({"error": "An error occurred"}), 500


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


def create_table(
    canvas,
):
    data = [
        ["Candidate/Employee Full Name", "Grajesh Chandra", "Order ID", "241004.1021"],
        ["Company Name", "Affinidi", "Branch Name", ""],
        ["Date of Report", "14-01-2025", "Cost Centre", "-"],
        ["Package Code/Level (if any)", "", "Case Reference No.", "AV041024MTIxNDU0"],
        ["Result", "Completed", "Result", "GREEN"],
    ]
    table = Table(data, colWidths=[150, 100, 150, 150])

    # (attribute, (start_column, start_row), (end_column, end_row), value)
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (0, -1), colors.yellow),  # First column
            ("BACKGROUND", (2, 0), (2, -1), colors.yellow),  # 3rd column
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.black,
            ),  # Text color for the header row
            ("GRID", (0, 0), (-1, -1), 1, colors.black),  # Add grid lines
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),  # Center-align all text
        ]
    )
    table.setStyle(style)

    # Calculate table position (x, y coordinates on the page)
    table_width, table_height = table.wrap(0, 0)  # Get table dimensions
    page_width, page_height = A4

    # Set margins (e.g., 50 points on left and right)
    margin = 30

    x = (page_width - table_width + margin) / 2  # Center the table horizontally
    y = page_height - 200  # Position the table below the header text

    # Draw the table on the canvas
    table.drawOn(canvas, x, y)


@app.route("/api/generate-report", methods=["POST"])
def generate_report():
    try:
        report_type = request.json.get("reportType")
        if not report_type:
            return jsonify({"error": "reportType is required"}), 400

        # Generate initial PDF content using reportlab
        pdf_buffer = BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)

        # Add content to the first page
        c.drawString(100, 750, f"Report Type: {report_type}")

        # Create table
        create_table(c)

        c.showPage()  # End the first page

        url = "http://127.0.0.1:5000/verify"

        c.drawString(100, 750, f"Click here ({url}) for Verification")

        # Add clickable URL link
        c.linkURL(url, (100, 740, 300, 760), relative=0)

        # Generate the QR code
        qr_buffer = generate_qr_code(url)
        qr_reader = ImageReader(qr_buffer)
        c.drawImage(qr_reader, 100, 600, width=100, height=100)

        # Finalize the PDF
        c.save()

        # Create a PdfReader to read the reportlab output
        pdf_buffer.seek(0)
        pdf_reader = PdfReader(pdf_buffer)

        # Write the new PDF
        pdf_writer = PdfWriter()
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)

        # Create JSON data
        AddressVerification_credentials = {
            "credentialSchema": {
                "type": "TAddressVerificationV1R0",
                "id": "https://schema.affinidi.io/TAddressVerificationV1R0.json",
            },
            "credentialSubject": {
                "address": {
                    "addressCountry": "India",
                    "addressLine1": "Varthur, Gunjur",
                    "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                    "addressRegion": "Karnataka",
                    "postalCode": "560087",
                },
                "ownerDetails": {
                    "ownerName": "TestOwner",
                    "ownerContactDetails1": "+912325435634",
                },
                "verificationStatus": "Completed",
                "verificationEvidence": {
                    "evidenceName1": "Letter",
                    "evidenceURL1": "http://localhost",
                },
                "stayDetails": {"fromDate": "01-01-2000", "toDate": "01-01-2020"},
                "verificationRemarks": "done",
                "neighbourDetails": {
                    "neighbourName": "Test Neighbour",
                    "neighbourContactDetails1": "+912325435634",
                },
            },
            "issuanceDate": "2024-12-02T16:53:40.405Z",
            "holder": {
                "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
            },
            "id": "claimId:97c5117320016ec0",
            "type": ["VerifiableCredential", "TAddressVerificationV1R0"],
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://schema.affinidi.io/TAddressVerificationV1R0.jsonld",
            ],
            "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
            "proof": {
                "type": "EcdsaSecp256k1Signature2019",
                "created": "2024-12-02T16:53:50Z",
                "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proofPurpose": "assertionMethod",
                "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..Jiq6yE6BTq9wXI2QT8-174_BAA-W2fdEF1d5DaUXEC1gMr62zSw2pGL_fl_eIBUPwKsOgc6TA0E1_rMmD8BOKA",
            },
        }

        json_buffer = get_file_content_buffer(AddressVerification_credentials)

        # Attach JSON to PDF
        pdf_writer.add_attachment("AddressVerification.json", json_buffer.getbuffer())

        # Create JSON data
        PersonalInformationVerification_credentials = {
            "credentialSchema": {
                "type": "TAddressVerificationV1R0",
                "id": "https://schema.affinidi.io/TAddressVerificationV1R0.json",
            },
            "credentialSubject": {
                "address": {
                    "addressCountry": "India",
                    "addressLine1": "Varthur, Gunjur",
                    "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                    "addressRegion": "Karnataka",
                    "postalCode": "560087",
                },
                "ownerDetails": {
                    "ownerName": "TestOwner",
                    "ownerContactDetails1": "+912325435634",
                },
                "verificationStatus": "Completed",
                "verificationEvidence": {
                    "evidenceName1": "Letter",
                    "evidenceURL1": "http://localhost",
                },
                "stayDetails": {"fromDate": "01-01-2000", "toDate": "01-01-2020"},
                "verificationRemarks": "done",
                "neighbourDetails": {
                    "neighbourName": "Test Neighbour",
                    "neighbourContactDetails1": "+912325435634",
                },
            },
            "issuanceDate": "2024-12-02T16:53:40.405Z",
            "holder": {
                "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
            },
            "id": "claimId:97c5117320016ec0",
            "type": ["VerifiableCredential", "TAddressVerificationV1R0"],
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://schema.affinidi.io/TAddressVerificationV1R0.jsonld",
            ],
            "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
            "proof": {
                "type": "EcdsaSecp256k1Signature2019",
                "created": "2024-12-02T16:53:50Z",
                "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proofPurpose": "assertionMethod",
                "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..Jiq6yE6BTq9wXI2QT8-174_BAA-W2fdEF1d5DaUXEC1gMr62zSw2pGL_fl_eIBUPwKsOgc6TA0E1_rMmD8BOKA",
            },
        }

        json_buffer = get_file_content_buffer(
            PersonalInformationVerification_credentials
        )

        # Attach JSON to PDF
        pdf_writer.add_attachment(
            "PersonalInformationVerification.json", json_buffer.getbuffer()
        )

        # Create JSON data
        EducationVerification_credentials = (
            {
                "credentialSchema": {
                    "type": "TEducationVerificationV1R0",
                    "id": "https://schema.affinidi.io/TEducationVerificationV1R0.json",
                },
                "credentialSubject": {
                    "educationDetails": {
                        "educationRegistrationID": "admins1223454356",
                        "qualification": "Graduation",
                        "course": "MBA",
                        "graduationDate": "12-08-2013",
                        "dateAttendedFrom": "12-08-2011",
                        "dateAttendedTo": "12-07-2013",
                    },
                    "verificationRemarks": "completed",
                    "verificationStatus": "Verified",
                    "institutionDetails": {
                        "institutionEmail": "test@affinidi.com",
                        "institutionContact1": "+91 1234567890",
                        "institutionContact2": "+91 1234567890",
                        "institutionName": "Affinidi",
                        "institutionAddress": {
                            "addressCountry": "India",
                            "addressLine1": "Varthur, Gunjur",
                            "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                            "addressRegion": "Karnataka",
                            "postalCode": "560087",
                        },
                        "institutionWebsiteURL": "affinidi.com",
                    },
                    "candidateDetails": {
                        "name": "Grajesh Chandra",
                        "phoneNumber": "7666009585",
                        "gender": "male",
                        "email": "grajesh.c@affinidi.com",
                    },
                    "verificationEvidence": {
                        "evidenceName1": "Degree",
                        "evidenceURL1": "http://localhost",
                    },
                },
                "issuanceDate": "2024-12-02T16:53:59.689Z",
                "holder": {
                    "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
                },
                "id": "claimId:b92044d269deaafb",
                "type": ["VerifiableCredential", "TEducationVerificationV1R0"],
                "@context": [
                    "https://www.w3.org/2018/credentials/v1",
                    "https://schema.affinidi.io/TEducationVerificationV1R0.jsonld",
                ],
                "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proof": {
                    "type": "EcdsaSecp256k1Signature2019",
                    "created": "2024-12-02T16:54:07Z",
                    "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                    "proofPurpose": "assertionMethod",
                    "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..MTr4jleSgTx5WuDHd6QQz6VqeNs-LI1bAgvvADE30DkXYXHk1xUF4fgLgKkcyPprMsQNJ6Rd3gSoKfXVAyUxow",
                },
            },
        )

        json_buffer = get_file_content_buffer(EducationVerification_credentials)

        # Attach JSON to PDF
        pdf_writer.add_attachment("EducationVerification.json", json_buffer.getbuffer())

        # Create JSON data
        EmploymentVerification_credentials = {
            "credentialSchema": {
                "type": "TEmploymentVerificationV1R1",
                "id": "https://schema.affinidi.io/TEmploymentVerificationV1R1.json",
            },
            "credentialSubject": {
                "verificationRemarks": "Done",
                "employerDetails": {
                    "companyName": "Affinidi",
                    "companyAddress": {
                        "addressCountry": "India",
                        "addressLine1": "Varthur, Gunjur",
                        "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                        "addressRegion": "Karnataka",
                        "postalCode": "560087",
                    },
                    "hRDetails": {
                        "hRfirstName": "Testing",
                        "hRContactNumber1": "+911234567789",
                        "whenToContact": "9:00-6:00 PM",
                        "hRDesignation": "Lead HR",
                        "hREmail": "hr@affinidi.com",
                        "hRLastName": "HR",
                    },
                },
                "verificationStatus": "Completed",
                "candidateDetails": {
                    "name": "Grajesh Chandra",
                    "phoneNumber": "7666009585",
                    "gender": "male",
                    "email": "grajesh.c@affinidi.com",
                },
                "employmentDetails": {
                    "eligibleForRehire": "Yes",
                    "reasonForLeaving": "Resignation",
                    "annualisedSalary": "10000",
                    "currency": "INR",
                    "designation": "Testing",
                    "employmentStatus": "Fulltime",
                    "tenure": {"fromDate": "05-2022", "toDate": "06-2050"},
                },
                "verificationEvidence": {
                    "evidenceName1": "letter",
                    "evidenceURL1": "http://localhost",
                },
            },
            "issuanceDate": "2024-12-02T16:54:12.767Z",
            "holder": {
                "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
            },
            "id": "claimId:8076e3f05e734b4a",
            "type": ["VerifiableCredential", "TEmploymentVerificationV1R1"],
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://schema.affinidi.io/TEmploymentVerificationV1R1.jsonld",
            ],
            "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
            "proof": {
                "type": "EcdsaSecp256k1Signature2019",
                "created": "2024-12-02T16:54:21Z",
                "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proofPurpose": "assertionMethod",
                "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..wsOTPlB_E21Av4JORHBBF-RL5XK6CSvQR9KNvFi8yDBzfRY8JgFsSLRmd9kiiHkk6rYsJeHhWBmL-iY-LG5nlQ",
            },
        }
        json_buffer = get_file_content_buffer(EmploymentVerification_credentials)

        # Attach JSON to PDF
        pdf_writer.add_attachment(
            "EmploymentVerification.json", json_buffer.getbuffer()
        )

        # Create Signature
        pdf_hash_excluding_attachments = hash_pdf_content_excluding_attachments(
            pdf_reader
        )
        print("pdf_hash_excluding_attachments", pdf_hash_excluding_attachments)

        pdf_signature = {
            "credentialSchema": {
                "type": "TEmploymentVerificationV1R1",
                "id": "https://schema.affinidi.io/TEmploymentVerificationV1R1.json",
            },
            "credentialSubject": {
                "hash_without_attachments": pdf_hash_excluding_attachments
            },
            "issuanceDate": "2024-12-02T16:54:12.767Z",
            "holder": {
                "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
            },
            "id": "claimId:8076e3f05e734b4a",
            "type": ["VerifiableCredential", "TEmploymentVerificationV1R1"],
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://schema.affinidi.io/TEmploymentVerificationV1R1.jsonld",
            ],
            "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
            "proof": {
                "type": "EcdsaSecp256k1Signature2019",
                "created": "2024-12-02T16:54:21Z",
                "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proofPurpose": "assertionMethod",
                "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..wsOTPlB_E21Av4JORHBBF-RL5XK6CSvQR9KNvFi8yDBzfRY8JgFsSLRmd9kiiHkk6rYsJeHhWBmL-iY-LG5nlQ",
            },
        }

        json_buffer = get_file_content_buffer(pdf_signature)
        # Attach Signature JSON to PDF
        pdf_writer.add_attachment("PDFSignature.json", json_buffer.getbuffer())

        # Write the final PDF to a buffer
        final_pdf_buffer = BytesIO()
        pdf_writer.write(final_pdf_buffer)
        final_pdf_buffer.seek(0)

        return send_file(
            final_pdf_buffer,
            as_attachment=True,
            download_name="report.pdf",
            mimetype="application/pdf",
        )
    except Exception as e:
        logging.exception("Error generating report:")  # Improved logging
        return jsonify({"error": str(e)}), 500


@app.route("/api/verify_pdf", methods=["POST"])
def verify_pdf():

    try:
        if "report_pdf" not in request.files:
            return jsonify({"error": "No PDF file uploaded"}), 400

        pdf_file = request.files["report_pdf"]
        pdf_buffer = BytesIO(pdf_file.read())

        pdf_reader = PdfReader(pdf_buffer)

        # Hash the PDF content
        pdf_hash_excluding_attachments = hash_pdf_content_excluding_attachments(
            pdf_reader
        )

        attachments = {}

        attachments["PDF Full Hash"] = hash_pdf_content(pdf_buffer)

        attachments["PDF Hash(Without attachments)"] = pdf_hash_excluding_attachments

        for filename, data in pdf_reader.attachments.items():
            if isinstance(data, list):  # Check if data is a list

                # join bytes in list to single bytes object
                data = b"".join(data)

            try:
                if filename != "PDFSignature.json":
                    continue

                # Attempt to decode as JSON
                json_data = json.loads(data.decode("utf-8"))
                attachments[filename] = json_data

                # verification_results = verification(json_data)
                # print('verification_results', verification_results)
                # verification_results['verificationResult'] = json_data
                # print('new_json_data', json_data)
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):  # added UnicodeDecodeError
                # If not JSON or Unicode, store as base64
                attachments[filename] = base64.b64encode(data).decode("utf-8")

        return jsonify(attachments), 200

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
    print("stats", stats)
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

    # configuration = affinidi_tdk_credential_issuance_client.Configuration()
    # configuration.api_key['ProjectTokenAuth'] = pst()

    # with affinidi_tdk_credential_verification_client.ApiClient(configuration) as api_client:
    #     api_instance = affinidi_tdk_credential_verification_client.DefaultApi(api_client)

    url = api_gateway_url + f"/ver/v1/verifier/verify-vcs"
    headers = {
        "Authorization": f"Bearer {
        pst()}",
        "Content-Type": "application/json",
    }

    body = {
        "verifiableCredentials": [
            {
                "credentialSchema": {
                    "type": "TEmploymentVerificationV1R1",
                    "id": "https://schema.affinidi.io/TEmploymentVerificationV1R1.json",
                },
                "credentialSubject": {
                    "verificationRemarks": "Done",
                    "employerDetails": {
                        "companyName": "Affinidi",
                        "companyAddress": {
                            "addressCountry": "India",
                            "addressLine1": "Varthur, Gunjur",
                            "addressLine2": "B305, Candeur Landmark, Tower Eiffel",
                            "addressRegion": "Karnataka",
                            "postalCode": "560087",
                        },
                        "hRDetails": {
                            "hRfirstName": "Testing",
                            "hRContactNumber1": "+911234567789",
                            "whenToContact": "9:00-6:00 PM",
                            "hRDesignation": "Lead HR",
                            "hREmail": "hr@affinidi.com",
                            "hRLastName": "HR",
                        },
                    },
                    "verificationStatus": "Completed",
                    "candidateDetails": {
                        "name": "Grajesh Chandra",
                        "phoneNumber": "7666009585",
                        "gender": "male",
                        "email": "grajesh.c@affinidi.com",
                    },
                    "employmentDetails": {
                        "eligibleForRehire": "Yes",
                        "reasonForLeaving": "Resignation",
                        "annualisedSalary": "10000",
                        "currency": "INR",
                        "designation": "Testing",
                        "employmentStatus": "Fulltime",
                        "tenure": {"fromDate": "05-2022", "toDate": "06-2050"},
                    },
                    "verificationEvidence": {
                        "evidenceName1": "letter",
                        "evidenceURL1": "http://localhost",
                    },
                },
                "issuanceDate": "2024-12-02T16:54:12.767Z",
                "holder": {
                    "id": "did:key:zQ3shs2AM1EMpfDthXaZJmBnjvGbuzMPB94uFAeUkvGe5sM15"
                },
                "id": "claimId:8076e3f05e734b4a",
                "type": ["VerifiableCredential", "TEmploymentVerificationV1R1"],
                "@context": [
                    "https://www.w3.org/2018/credentials/v1",
                    "https://schema.affinidi.io/TEmploymentVerificationV1R1.jsonld",
                ],
                "issuer": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                "proof": {
                    "type": "EcdsaSecp256k1Signature2019",
                    "created": "2024-12-02T16:54:21Z",
                    "verificationMethod": "did:key:zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf#zQ3shNyLdzYDbwZibk5hinAm5ChzxMinywBJz98fbFcQbn6Xf",
                    "proofPurpose": "assertionMethod",
                    "jws": "eyJhbGciOiJFUzI1NksiLCJiNjQiOmZhbHNlLCJjcml0IjpbImI2NCJdfQ..wsOTPlB_E21Av4JORHBBF-RL5XK6CSvQR9KNvFi8yDBzfRY8JgFsSLRmd9kiiHkk6rYsJeHhWBmL-iY-LG5nlQ",
                },
            }
        ]
    }

    response = requests.post(url, headers=headers, json=body)
    api_response = response.json()
    print("api_response", api_response)
    # verify_credentials_input = affinidi_tdk_credential_verification_client.VerifyCredentialInput.from_dict(request_json)
    # print('verify_credentials_input', verify_credentials_input)
    # api_response = api_instance.verify_credentials(verify_credentials_input=verify_credentials_input)
    # print('api_response', api_response)
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

        # Create a new PdfWriter to store only the pages
        pdf_writer = PdfWriter()

        # Add pages from the original PDF, excluding attachments
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)

        # Write the new PDF (without attachments) to a temporary buffer
        temp_buffer = BytesIO()
        pdf_writer.write(temp_buffer)
        temp_buffer.seek(0)

        # Hash the content of the new PDF
        pdf_hash = hashlib.sha256(temp_buffer.getvalue()).hexdigest()

        return pdf_hash
    except Exception as e:
        raise RuntimeError(f"Error processing PDF: {e}")
