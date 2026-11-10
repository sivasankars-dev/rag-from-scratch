from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import jwt
import base64
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from services.jwt_verifier import verify_access_token


def test_valid_rs256_token_returns_verified_subject():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    user_id = str(uuid4())
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": user_id,
            "iss": "https://auth.example.test",
            "aud": "production-rag-api",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

    claims = verify_access_token(
        token=token,
        public_key=public_key,
        issuer="https://auth.example.test",
        audience="production-rag-api",
    )

    assert claims["sub"] == user_id

def test_modified_payload_rejected():
    # Step 1: Generate RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Step 2: Derive public key
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Step 3: Create original valid JWT
    alice_id = str(uuid4())
    bob_id = str(uuid4())
    now = datetime.now(timezone.utc)

    issuer = "https://auth.example.test"
    audience = "production-rag-api"

    token = jwt.encode(
        {
            "sub": alice_id,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

    # Step 4: Split JWT into 3 parts
    header, payload_encoded, signature = token.split(".")

    # Step 5: Decode payload without verifying signature
    payload_bytes = base64.urlsafe_b64decode(
        payload_encoded + "=" * (-len(payload_encoded) % 4)
    )
    payload = json.loads(payload_bytes)

    # Step 6: Attacker changes Alice's identity to Bob
    payload["sub"] = bob_id

    # Step 7: Base64URL encode modified payload
    modified_payload = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
    ).rstrip(b"=").decode("ascii")

    # Step 8: Keep ORIGINAL signature
    tampered_token = (
        f"{header}.{modified_payload}.{signature}"
    )

    # Step 9: Verify that backend rejects tampered JWT
    with pytest.raises(jwt.InvalidSignatureError):
        verify_access_token(
            token=tampered_token,
            public_key=public_key,
            issuer=issuer,
            audience=audience,
        )

def test_expired_token_rejected():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    now = datetime.now(timezone.utc)

    issuer = "https://auth.example.test"
    audience = "production-rag-api"

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": issuer,
            "aud": audience,
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        verify_access_token(
            token=token,
            public_key=public_key,
            issuer=issuer,
            audience=audience,
        )

def test_wrong_audience_rejected():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    now = datetime.now(timezone.utc)
    issuer = "https://auth.example.test"

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": issuer,
            "aud": "payment-api",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(jwt.InvalidAudienceError):
        verify_access_token(
            token=token,
            public_key=public_key,
            issuer=issuer,
            audience="production-rag-api",
        )

def test_wrong_issuer_rejected():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": "https://untrusted.example.test",
            "aud": "production-rag-api",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(jwt.InvalidIssuerError):
        verify_access_token(
            token=token,
            public_key=public_key,
            issuer="https://auth.example.test",
            audience="production-rag-api",
        )

def test_missing_exp_claim_rejected():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": "https://auth.example.test",
            "aud": "production-rag-api",
            "iat": now,
            # Deliberately missing "exp"
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(jwt.MissingRequiredClaimError) as exc:
        verify_access_token(
            token=token,
            public_key=public_key,
            issuer="https://auth.example.test",
            audience="production-rag-api",
        )

    assert exc.value.claim == "exp"

def test_wrong_public_key_rejected():
    trusted_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    attacker_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    trusted_public_key = trusted_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": "https://auth.example.test",
            "aud": "production-rag-api",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        attacker_private_key,
        algorithm="RS256",
    )

    with pytest.raises(jwt.InvalidSignatureError):
        verify_access_token(
            token=token,
            public_key=trusted_public_key,
            issuer="https://auth.example.test",
            audience="production-rag-api",
        )

def test_hs256_token_rejected_by_rs256_verifier():
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": "https://auth.example.test",
            "aud": "production-rag-api",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        "attacker-controlled-secret",
        algorithm="HS256",
    )

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with pytest.raises(jwt.InvalidAlgorithmError):
        verify_access_token(
            token=token,
            public_key=public_key,
            issuer="https://auth.example.test",
            audience="production-rag-api",
        )