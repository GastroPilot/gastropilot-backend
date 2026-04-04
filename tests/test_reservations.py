"""
Tests for reservation endpoints.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


class TestReservationCRUD:
    """Tests for reservation CRUD operations."""

    async def test_create_reservation(
        self, client: AsyncClient, test_restaurant, test_table, test_guest, admin_auth_headers
    ):
        """Test creating a new reservation."""
        start_time = datetime.now(UTC) + timedelta(days=1)
        end_time = start_time + timedelta(hours=2)

        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/reservations",
            headers=admin_auth_headers,
            json={
                "table_id": test_table.id,
                "guest_id": test_guest.id,
                "start_at": start_time.isoformat(),
                "end_at": end_time.isoformat(),
                "party_size": 4,
                "status": "pending",
                "channel": "manual",
                "guest_name": "Max Mustermann",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["party_size"] == 4
        assert data["status"] == "pending"
        assert data["guest_name"] == "Max Mustermann"

    async def test_list_reservations(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test listing reservations."""
        from app.database.models import Reservation

        # Create some reservations
        start_time = datetime.now(UTC) + timedelta(days=1)
        for i in range(3):
            reservation = Reservation(
                restaurant_id=test_restaurant.id,
                table_id=test_table.id,
                start_at=start_time + timedelta(hours=i * 3),
                end_at=start_time + timedelta(hours=i * 3 + 2),
                party_size=2 + i,
                status="pending",
                channel="manual",
                guest_name=f"Gast {i+1}",
            )
            db_session.add(reservation)
        await db_session.commit()

        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/reservations", headers=admin_auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    async def test_get_reservation(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test getting a single reservation."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
            guest_name="Test Gast",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["guest_name"] == "Test Gast"
        assert data["party_size"] == 4

    async def test_update_reservation(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test updating a reservation."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
            guest_name="Original Name",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
            json={
                "guest_name": "Updated Name",
                "party_size": 6,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["guest_name"] == "Updated Name"
        assert data["party_size"] == 6

    async def test_delete_reservation(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test deleting a reservation."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
            guest_name="To Delete",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.delete(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["message"] == "deleted"

    async def test_table_move_syncs_active_order_tables(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Moving a reservation updates active linked orders, but not paid ones."""
        from app.database.models import Order, Reservation, Table

        second_table = Table(
            restaurant_id=test_restaurant.id,
            number="T2",
            capacity=4,
            shape="rectangle",
            position_x=220.0,
            position_y=100.0,
            width=120.0,
            height=80.0,
            is_active=True,
        )
        db_session.add(second_table)
        await db_session.commit()
        await db_session.refresh(second_table)

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="confirmed",
            channel="manual",
            guest_name="Sync Test Guest",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        open_order = Order(
            restaurant_id=test_restaurant.id,
            reservation_id=reservation.id,
            table_id=test_table.id,
            status="open",
            party_size=4,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
        )
        paid_order = Order(
            restaurant_id=test_restaurant.id,
            reservation_id=reservation.id,
            table_id=test_table.id,
            status="paid",
            party_size=4,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
            payment_status="paid",
        )
        db_session.add_all([open_order, paid_order])
        await db_session.commit()
        await db_session.refresh(open_order)
        await db_session.refresh(paid_order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
            json={"table_id": second_table.id},
        )

        assert response.status_code == 200
        assert response.json()["table_id"] == second_table.id

        await db_session.refresh(open_order)
        await db_session.refresh(paid_order)
        assert open_order.table_id == second_table.id
        assert paid_order.table_id == test_table.id


class TestReservationStatus:
    """Tests for reservation status changes."""

    async def test_confirm_reservation(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test confirming a reservation."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
            json={"status": "confirmed"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "confirmed"

    async def test_cancel_reservation(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test canceling a reservation."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(days=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/reservations/{reservation.id}",
            headers=admin_auth_headers,
            json={"status": "canceled", "canceled_reason": "Gast hat abgesagt"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "canceled"


class TestReservationFilters:
    """Tests for reservation filtering."""

    async def test_filter_by_date(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test filtering reservations by date."""
        from app.database.models import Reservation

        # Create reservations for different dates
        today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        # Today's reservation
        res_today = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=today,
            end_at=today + timedelta(hours=2),
            party_size=2,
            status="pending",
            channel="manual",
            guest_name="Today",
        )

        # Tomorrow's reservation
        res_tomorrow = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=tomorrow,
            end_at=tomorrow + timedelta(hours=2),
            party_size=4,
            status="pending",
            channel="manual",
            guest_name="Tomorrow",
        )

        db_session.add_all([res_today, res_tomorrow])
        await db_session.commit()

        # Filter for tomorrow
        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/reservations",
            headers=admin_auth_headers,
            params={"date": tomorrow.date().isoformat()},
        )

        assert response.status_code == 200
        data = response.json()
        # Should contain tomorrow's reservation
        guest_names = [r["guest_name"] for r in data]
        assert "Tomorrow" in guest_names
