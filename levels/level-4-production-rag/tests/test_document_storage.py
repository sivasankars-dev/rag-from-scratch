from uuid import UUID

from services.document_storage import generate_storage_key


def test_generate_storage_key():
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    document_id = UUID("22222222-2222-2222-2222-222222222222")
    version_id = UUID("33333333-3333-3333-3333-333333333333")

    result = generate_storage_key(tenant_id=tenant_id, document_id=document_id, version_id=version_id)

    print("ressssss", result)
    expected = (
        f"tenants/{tenant_id}/"
        f"documents/{document_id}/"
        f"versions/{version_id}/source.pdf"
    )

    assert result == expected
