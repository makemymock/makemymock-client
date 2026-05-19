import secrets

from bson import ObjectId

from modules.authentication.constants import OTP_LENGTH


def generate_otp(length: int = OTP_LENGTH) -> str:
    """Generate a cryptographically secure numeric OTP, zero-padded."""
    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def serialize_mongo_doc(doc: dict | None) -> dict | None:
    """Convert ObjectId/datetime fields into JSON-friendly forms recursively."""
    if doc is None:
        return None
    out: dict = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, dict):
            out[k] = serialize_mongo_doc(v)
        elif isinstance(v, list):
            out[k] = [
                serialize_mongo_doc(i) if isinstance(i, dict)
                else str(i) if isinstance(i, ObjectId)
                else i
                for i in v
            ]
        else:
            out[k] = v
    return out
