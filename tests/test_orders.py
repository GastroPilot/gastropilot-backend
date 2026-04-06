"""
Tests for order endpoints.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


class TestOrderCRUD:
    """Tests for order CRUD operations."""

    async def test_create_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test creating a new order."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(hours=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=4,
            status="confirmed",
            channel="manual",
            guest_name="Order Guest",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={
                "reservation_id": reservation.id,
                "party_size": 4,
                "notes": "Test order",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["table_id"] == test_table.id
        assert data["reservation_id"] == reservation.id
        assert data["status"] == "open"
        assert data["party_size"] == 4

    async def test_create_order_rejects_duplicate_active_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """A second active order for the same reservation/table must be rejected."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(hours=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=2,
            status="confirmed",
            channel="manual",
            guest_name="Duplicate Check",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        first_response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={"reservation_id": reservation.id, "party_size": 2},
        )
        assert first_response.status_code == 201

        second_response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={"reservation_id": reservation.id, "party_size": 2},
        )
        assert second_response.status_code == 409
        assert (
            second_response.json()["detail"]
            == "An active order already exists for this reservation or table"
        )

    async def test_create_order_allows_new_order_after_previous_completed(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """After previous order is completed, a new order can be created."""
        from app.database.models import Reservation

        start_time = datetime.now(UTC) + timedelta(hours=1)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=2,
            status="confirmed",
            channel="manual",
            guest_name="Completion Check",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        create_response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={"reservation_id": reservation.id, "party_size": 2},
        )
        assert create_response.status_code == 201
        first_order_id = create_response.json()["id"]

        complete_response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{first_order_id}",
            headers=admin_auth_headers,
            json={"status": "paid", "payment_status": "paid"},
        )
        assert complete_response.status_code == 200

        second_create_response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={"reservation_id": reservation.id, "party_size": 2},
        )
        assert second_create_response.status_code == 201

    async def test_create_order_requires_reservation(
        self, client: AsyncClient, test_restaurant, test_table, admin_auth_headers
    ):
        """Order creation must be rejected when reservation is missing."""
        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders",
            headers=admin_auth_headers,
            json={
                "table_id": test_table.id,
                "party_size": 2,
                "notes": "Missing reservation",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Reservation is required for every order"

    async def test_list_orders(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test listing orders."""
        from app.database.models import Order

        # Create some orders
        for i in range(3):
            order = Order(
                restaurant_id=test_restaurant.id,
                table_id=test_table.id,
                status="open",
                party_size=2 + i,
                subtotal=0.0,
                tax_amount=0.0,
                tax_amount_7=0.0,
                tax_amount_19=0.0,
                total=0.0,
            )
            db_session.add(order)
        await db_session.commit()

        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/orders", headers=admin_auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    async def test_get_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test getting a single order."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="open",
            party_size=4,
            subtotal=50.0,
            tax_amount=8.0,
            tax_amount_7=0.0,
            tax_amount_19=8.0,
            total=50.0,
            notes="Test order",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}", headers=admin_auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["party_size"] == 4
        assert data["notes"] == "Test order"

    async def test_update_order_status(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test updating order status."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="open",
            party_size=4,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=admin_auth_headers,
            json={"status": "sent_to_kitchen"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent_to_kitchen"

    async def test_reject_manual_table_change_for_reservation_bound_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Order table must not be changed directly when reservation-bound."""
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

        start_time = datetime.now(UTC) + timedelta(hours=2)
        reservation = Reservation(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            start_at=start_time,
            end_at=start_time + timedelta(hours=2),
            party_size=2,
            status="confirmed",
            channel="manual",
            guest_name="Bound Guest",
        )
        db_session.add(reservation)
        await db_session.commit()
        await db_session.refresh(reservation)

        order = Order(
            restaurant_id=test_restaurant.id,
            reservation_id=reservation.id,
            table_id=test_table.id,
            status="open",
            party_size=2,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=admin_auth_headers,
            json={"table_id": second_table.id},
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Table assignment is derived from reservation. Update reservation instead."
        )


class TestOrderItems:
    """Tests for order items."""

    async def test_add_order_item(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test adding an item to an order."""
        from app.database.models import MenuCategory, MenuItem, Order

        # Create menu category and item
        category = MenuCategory(
            restaurant_id=test_restaurant.id,
            name="Hauptgerichte",
            sort_order=1,
        )
        db_session.add(category)
        await db_session.commit()
        await db_session.refresh(category)

        menu_item = MenuItem(
            restaurant_id=test_restaurant.id,
            category_id=category.id,
            name="Schnitzel",
            description="Wiener Schnitzel mit Pommes",
            price=15.90,
            tax_rate=0.19,
        )
        db_session.add(menu_item)
        await db_session.commit()
        await db_session.refresh(menu_item)

        # Create order
        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="open",
            party_size=2,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        # Add item to order
        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}/items",
            headers=admin_auth_headers,
            json={
                "item_name": "Schnitzel",
                "quantity": 2,
                "unit_price": 15.90,
                "tax_rate": 0.19,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["item_name"] == "Schnitzel"
        assert data["quantity"] == 2
        assert data["unit_price"] == 15.90

    async def test_add_order_item_reopens_served_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Adding a new item to a served order must reopen it."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="served",
            party_size=2,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}/items",
            headers=admin_auth_headers,
            json={
                "item_name": "Dessert",
                "quantity": 1,
                "unit_price": 6.5,
                "tax_rate": 0.19,
            },
        )

        assert response.status_code == 201
        await db_session.refresh(order)
        assert order.status == "open"

    async def test_add_order_item_reopens_ready_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Adding a pending item to a ready order must move it back to open."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="ready",
            party_size=2,
            subtotal=0.0,
            tax_amount=0.0,
            tax_amount_7=0.0,
            tax_amount_19=0.0,
            total=0.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.post(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}/items",
            headers=admin_auth_headers,
            json={
                "item_name": "Espresso",
                "quantity": 1,
                "unit_price": 2.9,
                "tax_rate": 0.19,
            },
        )

        assert response.status_code == 201
        await db_session.refresh(order)
        assert order.status == "open"

    async def test_order_status_tracks_item_status_progression(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Order status should follow the aggregate item kitchen progress."""
        from app.database.models import Order, OrderItem

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="open",
            party_size=2,
            subtotal=12.0,
            tax_amount=1.92,
            tax_amount_7=0.0,
            tax_amount_19=1.92,
            total=12.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        item = OrderItem(
            order_id=order.id,
            item_name="Pasta",
            quantity=1,
            unit_price=12.0,
            total_price=12.0,
            tax_rate=0.19,
            status="pending",
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        expected_progress = [
            ("sent", "sent_to_kitchen"),
            ("in_preparation", "in_preparation"),
            ("ready", "ready"),
            ("served", "served"),
        ]
        for item_status, expected_order_status in expected_progress:
            response = await client.patch(
                f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}/items/{item.id}",
                headers=admin_auth_headers,
                json={"status": item_status},
            )
            assert response.status_code == 200
            await db_session.refresh(order)
            assert order.status == expected_order_status

    async def test_order_status_remains_open_while_pending_items_exist(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Any pending item must keep the order in open status."""
        from app.database.models import Order, OrderItem

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="ready",
            party_size=2,
            subtotal=18.0,
            tax_amount=2.87,
            tax_amount_7=0.0,
            tax_amount_19=2.87,
            total=18.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        ready_item = OrderItem(
            order_id=order.id,
            item_name="Steak",
            quantity=1,
            unit_price=14.0,
            total_price=14.0,
            tax_rate=0.19,
            status="ready",
        )
        pending_item = OrderItem(
            order_id=order.id,
            item_name="Dessert",
            quantity=1,
            unit_price=4.0,
            total_price=4.0,
            tax_rate=0.19,
            status="pending",
        )
        db_session.add_all([ready_item, pending_item])
        await db_session.commit()
        await db_session.refresh(ready_item)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}/items/{ready_item.id}",
            headers=admin_auth_headers,
            json={"notes": "Bitte sofort servieren"},
        )

        assert response.status_code == 200
        await db_session.refresh(order)
        assert order.status == "open"


class TestOrderPayment:
    """Tests for order payment."""

    async def test_pay_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test paying an order."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="served",
            party_size=2,
            subtotal=50.0,
            tax_amount=8.0,
            tax_amount_7=0.0,
            tax_amount_19=8.0,
            total=50.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=admin_auth_headers,
            json={
                "status": "paid",
                "payment_status": "paid",
                "payment_method": "card",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "paid"
        assert data["payment_status"] == "paid"
        assert data["payment_method"] == "card"

    async def test_split_payment(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test split payment."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="served",
            party_size=2,
            subtotal=100.0,
            tax_amount=16.0,
            tax_amount_7=0.0,
            tax_amount_19=16.0,
            total=100.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=admin_auth_headers,
            json={
                "status": "paid",
                "payment_status": "paid",
                "payment_method": "split",
                "split_payments": [
                    {"method": "cash", "amount": 40.0},
                    {"method": "card", "amount": 60.0},
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["payment_method"] == "split"
        assert len(data["split_payments"]) == 2

    async def test_mitarbeiter_cannot_set_status_paid(
        self, client: AsyncClient, db_session, test_restaurant, test_table, auth_headers
    ):
        """Mitarbeiter darf Bestellung nicht direkt auf paid setzen."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="served",
            party_size=2,
            subtotal=50.0,
            tax_amount=8.0,
            tax_amount_7=0.0,
            tax_amount_19=8.0,
            total=50.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=auth_headers,
            json={"status": "paid"},
        )

        assert response.status_code == 403
        assert "owner or Servecta" in response.json()["detail"]

    async def test_mitarbeiter_cannot_set_status_canceled(
        self, client: AsyncClient, db_session, test_restaurant, test_table, auth_headers
    ):
        """Mitarbeiter darf Bestellung nicht direkt auf canceled setzen."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="open",
            party_size=2,
            subtotal=25.0,
            tax_amount=4.0,
            tax_amount_7=0.0,
            tax_amount_19=4.0,
            total=25.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=auth_headers,
            json={"status": "canceled"},
        )

        assert response.status_code == 403
        assert "owner or Servecta" in response.json()["detail"]

    async def test_mitarbeiter_cannot_set_payment_status_paid(
        self, client: AsyncClient, db_session, test_restaurant, test_table, auth_headers
    ):
        """Mitarbeiter darf payment_status nicht direkt auf paid setzen."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="served",
            party_size=2,
            subtotal=40.0,
            tax_amount=6.4,
            tax_amount_7=0.0,
            tax_amount_19=6.4,
            total=40.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=auth_headers,
            json={"payment_status": "paid"},
        )

        assert response.status_code == 403
        assert "owner or Servecta" in response.json()["detail"]

    async def test_mitarbeiter_cannot_reopen_paid_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, auth_headers
    ):
        """Mitarbeiter darf eine bereits bezahlte Bestellung nicht wieder öffnen."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="paid",
            party_size=2,
            subtotal=40.0,
            tax_amount=6.4,
            tax_amount_7=0.0,
            tax_amount_19=6.4,
            total=40.0,
            payment_status="paid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=auth_headers,
            json={"status": "served"},
        )

        assert response.status_code == 403
        assert "owner or Servecta" in response.json()["detail"]

    async def test_mitarbeiter_cannot_reopen_canceled_order(
        self, client: AsyncClient, db_session, test_restaurant, test_table, auth_headers
    ):
        """Mitarbeiter darf eine stornierte Bestellung nicht wieder öffnen."""
        from app.database.models import Order

        order = Order(
            restaurant_id=test_restaurant.id,
            table_id=test_table.id,
            status="canceled",
            party_size=2,
            subtotal=20.0,
            tax_amount=3.2,
            tax_amount_7=0.0,
            tax_amount_19=3.2,
            total=20.0,
            payment_status="unpaid",
        )
        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        response = await client.patch(
            f"/v1/restaurants/{test_restaurant.id}/orders/{order.id}",
            headers=auth_headers,
            json={"status": "open"},
        )

        assert response.status_code == 403
        assert "owner or Servecta" in response.json()["detail"]


class TestOrderStatistics:
    """Tests for order statistics endpoint."""

    async def test_get_order_statistics(
        self, client: AsyncClient, db_session, test_restaurant, test_table, admin_auth_headers
    ):
        """Test getting order statistics (revenue endpoint)."""
        from datetime import timedelta

        from app.database.models import Order

        # Create some paid orders
        now = datetime.now(UTC)
        for i in range(5):
            order = Order(
                restaurant_id=test_restaurant.id,
                table_id=test_table.id,
                status="paid",
                party_size=2,
                subtotal=50.0 + i * 10,
                tax_amount=8.0,
                tax_amount_7=0.0,
                tax_amount_19=8.0,
                total=50.0 + i * 10,
                payment_status="paid",
                opened_at=now - timedelta(hours=i),
                paid_at=now - timedelta(hours=i) + timedelta(minutes=45),
            )
            db_session.add(order)
        await db_session.commit()

        response = await client.get(
            f"/v1/restaurants/{test_restaurant.id}/order-statistics/revenue",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Statistics should include aggregate data
        assert "total_revenue" in data
        assert "total_orders" in data
        assert data["total_orders"] == 5
