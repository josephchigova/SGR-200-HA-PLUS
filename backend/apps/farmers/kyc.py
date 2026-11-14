"""KYC documents and the registration approval workflow.

The three mandatory documents are the ones the registration screen asks for. The
optional ones come from the SGR 200HA+ KYC and supporting documents checklist.
"""

import re

from django.utils import timezone

from .models import Farmer, FarmerDocument, FarmerReviewEvent

NATIONAL_ID_PATTERN = re.compile(r"^[0-9]{2}-[0-9]{7}[A-Z][0-9]{2}$")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_SIGNATURES = (b"%PDF", b"\xff\xd8\xff", b"\x89PNG")

DOCUMENT_TYPES = [
    {"code": "NATIONAL_ID", "label": "National ID copy", "required": True, "hint": "National ID of the applicant, or passport for an entity director."},
    {"code": "PROOF_OF_LAND", "label": "Proof of land", "required": True, "hint": "Offer letter, lease agreement, title deed or approved joint venture agreement showing the land."},
    {"code": "MEMBERSHIP_FORM", "label": "Signed membership form", "required": True, "hint": "The completed and signed SGR membership application form."},
    {"code": "PLEDGE_FORM", "label": "Membership pledge form", "required": False, "hint": "Only when the farmer applies under the post-harvest pledge arrangement."},
    {"code": "JV_ASSESSMENT_FORM", "label": "Joint venture assessment form", "required": False, "hint": "The completed SGR joint venture programme assessment form."},
    {"code": "ZESA_BILL", "label": "ZESA bill", "required": False, "hint": "Dated within the past 30 days."},
    {"code": "ZINWA_BILL", "label": "ZINWA bill", "required": False, "hint": "Dated within the past 30 days."},
    {"code": "REFERENCE_LETTER", "label": "Reference letter", "required": False, "hint": "From a current paid-up SGR member."},
    {"code": "DAEO_LETTER", "label": "DAEO letter", "required": False, "hint": "New farmers: letter from the District Agriculture Extension Officer."},
    {"code": "GUARANTEE_AGREEMENT", "label": "Signed guarantee agreement", "required": False, "hint": "New farmers only."},
]
DOCUMENT_CODES = {item["code"] for item in DOCUMENT_TYPES}
REQUIRED_CODES = [item["code"] for item in DOCUMENT_TYPES if item["required"]]
DOCUMENT_LABELS = {item["code"]: item["label"] for item in DOCUMENT_TYPES}

# A registration can be changed by the person who captured it only in these states.
EDITABLE_BY_REGISTRAR = {Farmer.STATUS_DRAFT, Farmer.STATUS_CORRECTIONS, Farmer.STATUS_REJECTED}
AWAITING_REVIEW = {Farmer.STATUS_SUBMITTED, Farmer.STATUS_UNDER_REVIEW, Farmer.STATUS_PENDING}
APPROVED_STATES = {Farmer.STATUS_VERIFIED, Farmer.STATUS_APPROVED}


def missing_required_documents(farmer):
    present = set(farmer.documents.values_list("document_type", flat=True))
    return [DOCUMENT_LABELS[code] for code in REQUIRED_CODES if code not in present]


def unverified_documents(farmer):
    return [
        DOCUMENT_LABELS.get(document.document_type, document.document_type)
        for document in farmer.documents.exclude(review_status=FarmerDocument.REVIEW_VERIFIED)
    ]


def record_event(farmer, action, user=None, remarks=""):
    name = ""
    if user is not None and getattr(user, "pk", None):
        name = f"{user.first_name} {user.last_name}".strip() or user.email
    return FarmerReviewEvent.objects.create(farmer=farmer, action=action, remarks=remarks or "", actor=user if getattr(user, "pk", None) else None, actor_name=name)


def submit_registration(farmer, user):
    """Send a draft, corrected or rejected registration to the approval queue."""
    resubmission = farmer.verification_status in {Farmer.STATUS_CORRECTIONS, Farmer.STATUS_REJECTED}
    farmer.verification_status = Farmer.STATUS_SUBMITTED
    farmer.submitted_at = timezone.now()
    farmer.rejection_reason = ""
    farmer.save(update_fields=["verification_status", "submitted_at", "rejection_reason", "updated_at"])
    # Documents replaced after a rejection go back to the reviewer.
    farmer.documents.filter(review_status=FarmerDocument.REVIEW_REJECTED).update(review_status=FarmerDocument.REVIEW_PENDING)
    record_event(farmer, FarmerReviewEvent.RESUBMITTED if resubmission else FarmerReviewEvent.SUBMITTED, user)
    return farmer


def validate_upload(upload):
    name = (getattr(upload, "name", "") or "").lower()
    extension = name[name.rfind("."):] if "." in name else ""
    if extension not in ALLOWED_EXTENSIONS:
        return "Upload a PDF, JPG or PNG file."
    if upload.size > MAX_UPLOAD_BYTES:
        return "The file is larger than 10 MB."
    if upload.size == 0:
        return "The file is empty."
    head = upload.read(8)
    upload.seek(0)
    if not head.startswith(ALLOWED_SIGNATURES):
        return "The file is not a valid PDF, JPG or PNG."
    return ""
