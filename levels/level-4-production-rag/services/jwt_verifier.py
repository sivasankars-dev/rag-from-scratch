import jwt


def verify_access_token(
    token: str,
    public_key: bytes,
    issuer: str,
    audience: str,
) -> dict:
    claims = jwt.decode(
        jwt=token,
        key=public_key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=audience,
        options={
            "require": ["sub", "iss", "aud", "exp", "iat"],
        },
    )

    return claims
