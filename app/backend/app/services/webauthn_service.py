import base64
from typing import Optional

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    PublicKeyCredentialDescriptor,
    AuthenticatorTransport,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes


RP_NAME = "NanoCortex"


def get_rp_id(origin: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(origin)
    return parsed.hostname or "localhost"


def create_registration_options(
    user_id: str,
    user_email: str,
    user_name: str,
    existing_credential_ids: list[bytes],
    rp_id: str,
) -> tuple[dict, bytes]:
    exclude_creds = [
        PublicKeyCredentialDescriptor(id=cid)
        for cid in existing_credential_ids
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=user_id.encode(),
        user_name=user_email,
        user_display_name=user_name,
        exclude_credentials=exclude_creds,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    options_json = options_to_json(options)
    challenge = options.challenge

    return options_json, challenge


def verify_registration(
    credential_json: dict,
    expected_challenge: bytes,
    expected_origin: str,
    expected_rp_id: str,
):
    import json

    verification = verify_registration_response(
        credential=json.dumps(credential_json),
        expected_challenge=expected_challenge,
        expected_origin=expected_origin,
        expected_rp_id=expected_rp_id,
    )

    return {
        "credential_id": bytes_to_base64url(verification.credential_id),
        "public_key": bytes_to_base64url(verification.credential_public_key),
        "sign_count": verification.sign_count,
    }


def create_authentication_options(
    credential_ids: list[bytes],
    rp_id: str,
) -> tuple[dict, bytes]:
    allow_creds = [
        PublicKeyCredentialDescriptor(id=cid)
        for cid in credential_ids
    ]

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_creds,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    options_json = options_to_json(options)
    challenge = options.challenge

    return options_json, challenge


def verify_authentication(
    credential_json: dict,
    expected_challenge: bytes,
    expected_origin: str,
    expected_rp_id: str,
    credential_public_key: bytes,
    credential_current_sign_count: int,
):
    import json

    verification = verify_authentication_response(
        credential=json.dumps(credential_json),
        expected_challenge=expected_challenge,
        expected_origin=expected_origin,
        expected_rp_id=expected_rp_id,
        credential_public_key=credential_public_key,
        credential_current_sign_count=credential_current_sign_count,
    )

    return {
        "new_sign_count": verification.new_sign_count,
    }
