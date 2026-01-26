"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient


class TestLogin:
    """Tests for the login endpoint."""
    
    async def test_login_success(self, client: AsyncClient, test_user):
        """Test successful login with valid credentials."""
        response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "1234",
                "pin": "123456"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
    
    async def test_login_invalid_operator_number(self, client: AsyncClient):
        """Test login with invalid operator number."""
        response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "9999",
                "pin": "123456"
            }
        )
        
        assert response.status_code == 401
        assert "Invalid operator number or PIN" in response.json()["detail"]
    
    async def test_login_invalid_pin(self, client: AsyncClient, test_user):
        """Test login with invalid PIN."""
        response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "1234",
                "pin": "wrongpin"
            }
        )
        
        assert response.status_code == 401
        assert "Invalid operator number or PIN" in response.json()["detail"]
    
    async def test_login_inactive_user(self, client: AsyncClient, db_session, test_user):
        """Test login with inactive user."""
        test_user.is_active = False
        await db_session.commit()
        
        response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "1234",
                "pin": "123456"
            }
        )
        
        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()


class TestNFCLogin:
    """Tests for the NFC login endpoint."""
    
    async def test_nfc_login_success(self, client: AsyncClient, db_session, test_user):
        """Test successful NFC login."""
        # Add NFC tag to user
        test_user.nfc_tag_id = "NFC123456"
        await db_session.commit()
        
        response = await client.post(
            "/v1/auth/login-nfc",
            json={"nfc_tag_id": "NFC123456"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    async def test_nfc_login_invalid_tag(self, client: AsyncClient):
        """Test NFC login with invalid tag."""
        response = await client.post(
            "/v1/auth/login-nfc",
            json={"nfc_tag_id": "INVALID_TAG"}
        )
        
        assert response.status_code == 401
        assert "Invalid NFC tag ID" in response.json()["detail"]


class TestGetCurrentUser:
    """Tests for the /me endpoint."""
    
    async def test_get_current_user_authenticated(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Test getting current user info when authenticated."""
        response = await client.get("/v1/auth/me", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["operator_number"] == "1234"
        assert data["first_name"] == "Test"
        assert data["last_name"] == "User"
        assert data["role"] == "mitarbeiter"
    
    async def test_get_current_user_unauthenticated(self, client: AsyncClient):
        """Test getting current user info without authentication."""
        response = await client.get("/v1/auth/me")
        
        assert response.status_code == 401


class TestRefreshToken:
    """Tests for the token refresh endpoint."""
    
    async def test_refresh_token_success(self, client: AsyncClient, test_user):
        """Test successful token refresh."""
        # First login to get tokens
        login_response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "1234",
                "pin": "123456"
            }
        )
        tokens = login_response.json()
        
        # Then refresh
        response = await client.post(
            "/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New refresh token should be different (rotation)
        assert data["refresh_token"] != tokens["refresh_token"]
    
    async def test_refresh_token_invalid(self, client: AsyncClient):
        """Test refresh with invalid token."""
        response = await client.post(
            "/v1/auth/refresh",
            json={"refresh_token": "invalid_token"}
        )
        
        assert response.status_code == 401
    
    async def test_refresh_token_reuse_prevention(self, client: AsyncClient, test_user):
        """Test that old refresh tokens cannot be reused after rotation."""
        # Login
        login_response = await client.post(
            "/v1/auth/login",
            json={
                "operator_number": "1234",
                "pin": "123456"
            }
        )
        original_tokens = login_response.json()
        
        # First refresh
        refresh_response = await client.post(
            "/v1/auth/refresh",
            json={"refresh_token": original_tokens["refresh_token"]}
        )
        assert refresh_response.status_code == 200
        
        # Try to reuse old refresh token
        reuse_response = await client.post(
            "/v1/auth/refresh",
            json={"refresh_token": original_tokens["refresh_token"]}
        )
        
        # Should fail because token was revoked after rotation
        assert reuse_response.status_code == 401


class TestOperatorManagement:
    """Tests for operator management endpoints."""
    
    async def test_list_operators(
        self, client: AsyncClient, test_admin_user, admin_auth_headers
    ):
        """Test listing operators as admin."""
        response = await client.get("/v1/auth/operators", headers=admin_auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    async def test_list_operators_unauthorized(self, client: AsyncClient, auth_headers):
        """Test listing operators as regular user."""
        response = await client.get("/v1/auth/operators", headers=auth_headers)
        
        # Should fail because regular user doesn't have restaurantinhaber role
        assert response.status_code == 403
    
    async def test_create_operator(
        self, client: AsyncClient, test_admin_user, admin_auth_headers
    ):
        """Test creating a new operator."""
        response = await client.post(
            "/v1/auth/create-operator",
            headers=admin_auth_headers,
            json={
                "operator_number": "5678",
                "pin": "654321",
                "first_name": "New",
                "last_name": "Operator",
                "role": "mitarbeiter"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["operator_number"] == "5678"
        assert data["first_name"] == "New"
        assert data["role"] == "mitarbeiter"
    
    async def test_create_operator_duplicate_number(
        self, client: AsyncClient, test_user, test_admin_user, admin_auth_headers
    ):
        """Test creating operator with duplicate number."""
        response = await client.post(
            "/v1/auth/create-operator",
            headers=admin_auth_headers,
            json={
                "operator_number": "1234",  # Same as test_user
                "pin": "654321",
                "first_name": "Duplicate",
                "last_name": "Operator",
                "role": "mitarbeiter"
            }
        )
        
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]
    
    async def test_create_operator_reserved_number(
        self, client: AsyncClient, test_admin_user, admin_auth_headers
    ):
        """Test creating operator with reserved Servecta number."""
        response = await client.post(
            "/v1/auth/create-operator",
            headers=admin_auth_headers,
            json={
                "operator_number": "0000",  # Reserved for Servecta
                "pin": "654321",
                "first_name": "Reserved",
                "last_name": "Operator",
                "role": "mitarbeiter"
            }
        )
        
        assert response.status_code == 400
        assert "reserved" in response.json()["detail"].lower()
    
    async def test_update_operator(
        self, client: AsyncClient, test_user, test_admin_user, admin_auth_headers
    ):
        """Test updating an operator."""
        response = await client.patch(
            f"/v1/auth/operators/{test_user.id}",
            headers=admin_auth_headers,
            json={
                "first_name": "Updated",
                "last_name": "Name"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "Name"
    
    async def test_delete_operator(
        self, client: AsyncClient, db_session, test_admin_user, admin_auth_headers
    ):
        """Test deleting an operator."""
        from app.database.models import User
        from app.auth import hash_password
        
        # Create a user to delete
        user_to_delete = User(
            operator_number="7777",
            pin_hash=hash_password("123456"),
            first_name="To",
            last_name="Delete",
            role="mitarbeiter",
            is_active=True,
        )
        db_session.add(user_to_delete)
        await db_session.commit()
        await db_session.refresh(user_to_delete)
        
        response = await client.delete(
            f"/v1/auth/operators/{user_to_delete.id}",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 204
    
    async def test_restaurantinhaber_cannot_create_servecta_user(
        self, client: AsyncClient, test_admin_user, admin_auth_headers
    ):
        """Test that restaurantinhaber cannot create servecta users."""
        response = await client.post(
            "/v1/auth/create-operator",
            headers=admin_auth_headers,
            json={
                "operator_number": "8888",
                "pin": "654321",
                "first_name": "Fake",
                "last_name": "Servecta",
                "role": "servecta"
            }
        )
        
        assert response.status_code == 403
