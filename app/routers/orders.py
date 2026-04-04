from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Guest,
    MenuItem,
    Order,
    OrderItem,
    Reservation,
    Restaurant,
    Table,
    User,
)
from app.dependencies import (
    get_current_user,
    get_session,
    normalize_datetime_to_utc,
    require_mitarbeiter_role,
    require_orders_module,
    require_schichtleiter_role,
)
from app.schemas import (
    OrderCreate,
    OrderItemCreate,
    OrderItemRead,
    OrderItemUpdate,
    OrderRead,
    OrderUpdate,
    OrderWithItems,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/orders", tags=["orders"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_order_or_404(order_id: int, restaurant_id: int, session: AsyncSession) -> Order:
    order = await session.get(Order, order_id)
    if not order or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def _generate_order_number(restaurant_id: int, session: AsyncSession) -> str:
    """Generiert eine eindeutige Bestellnummer."""
    from datetime import date

    today = date.today()
    prefix = f"ORD-{today.strftime('%Y%m%d')}-"

    result = await session.execute(
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.order_number.like(f"{prefix}%"))
        .order_by(Order.order_number.desc())
        .limit(1)
    )
    last_order = result.scalar_one_or_none()

    if last_order and last_order.order_number:
        try:
            last_num = int(last_order.order_number.split("-")[-1])
            new_num = last_num + 1
        except (ValueError, IndexError):
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


def _calculate_totals(
    items: list[OrderItem],
    discount_amount: float = 0.0,
    discount_percentage: float | None = None,
    tip_amount: float = 0.0,
) -> dict[str, float]:
    """Berechnet die Summen einer Bestellung. Preise sind inkl. MwSt."""
    subtotal = sum(item.total_price for item in items)

    # Rabatt berechnen (entweder Fixbetrag oder Prozent)
    if discount_percentage is not None and discount_percentage > 0:
        calculated_discount = subtotal * (discount_percentage / 100)
    else:
        calculated_discount = discount_amount

    subtotal_after_discount = subtotal - calculated_discount

    # MwSt. aus inkl. Preisen extrahieren (getrennt nach Steuersätzen)
    # Formel: MwSt. = Preis_inkl * (Steuersatz / (1 + Steuersatz))
    tax_amount_7 = 0.0
    tax_amount_19 = 0.0

    for item in items:
        # MwSt. für dieses Item berechnen
        # Da Preise inkl. MwSt. sind: MwSt. = Preis * (tax_rate / (1 + tax_rate))
        item_tax = item.total_price * (item.tax_rate / (1 + item.tax_rate))

        # Rabatt proportional auf MwSt. anwenden
        if subtotal > 0:
            discount_factor = calculated_discount / subtotal
            item_tax_after_discount = item_tax * (1 - discount_factor)
        else:
            item_tax_after_discount = item_tax

        # Nach Steuersatz aufteilen
        if abs(item.tax_rate - 0.07) < 0.001:  # 7% Steuersatz
            tax_amount_7 += item_tax_after_discount
        elif abs(item.tax_rate - 0.19) < 0.001:  # 19% Steuersatz
            tax_amount_19 += item_tax_after_discount
        else:
            # Fallback: Standardmäßig zu 19% zuordnen
            tax_amount_19 += item_tax_after_discount

    tax_amount = tax_amount_7 + tax_amount_19
    total = subtotal_after_discount + tip_amount  # MwSt. ist bereits im Preis enthalten

    return {
        "subtotal": round(subtotal, 2),
        "tax_amount_7": round(tax_amount_7, 2),
        "tax_amount_19": round(tax_amount_19, 2),
        "tax_amount": round(tax_amount, 2),
        "discount_amount": round(calculated_discount, 2),
        "tip_amount": round(tip_amount, 2),
        "total": round(total, 2),
    }


def _serialize_split_payments(data):
    """Ensure split_payments are plain dicts for JSON columns."""
    if not data:
        return data
    return [sp.model_dump() if hasattr(sp, "model_dump") else dict(sp) for sp in data]


@router.post(
    "/",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_orders_module)],
)
async def create_order(
    restaurant_id: int,
    order_data: OrderCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Erstellt eine neue Bestellung (Mitarbeiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)

    if not order_data.reservation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservation is required for every order",
        )

    reservation = await session.get(Reservation, order_data.reservation_id)
    if not reservation or reservation.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    resolved_table_id = reservation.table_id
    if order_data.table_id and resolved_table_id and order_data.table_id != resolved_table_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Table does not match reservation assignment",
        )

    if resolved_table_id:
        table = await session.get(Table, resolved_table_id)
        if not table or table.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    if order_data.guest_id:
        guest = await session.get(Guest, order_data.guest_id)
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    order_number = await _generate_order_number(restaurant_id, session)

    order = Order(
        restaurant_id=restaurant_id,
        table_id=resolved_table_id,
        guest_id=order_data.guest_id,
        reservation_id=reservation.id,
        order_number=order_number,
        party_size=order_data.party_size,
        notes=order_data.notes,
        special_requests=order_data.special_requests,
        split_payments=_serialize_split_payments(order_data.split_payments),
        created_by_user_id=current_user.id,
        status="open",
        payment_status="unpaid",
    )

    try:
        session.add(order)
        await session.flush()

        if order_data.items:
            sort_order = 0
            for item_data in order_data.items:
                total_price = item_data.quantity * item_data.unit_price
                # Versuche menu_item_id zu finden falls item_name übereinstimmt
                menu_item_id = None
                tax_rate = (
                    item_data.tax_rate if item_data.tax_rate is not None else 0.19
                )  # Default 19%
                if item_data.item_name:
                    result = await session.execute(
                        select(MenuItem)
                        .where(
                            MenuItem.restaurant_id == restaurant_id,
                            MenuItem.name == item_data.item_name,
                        )
                        .limit(1)
                    )
                    menu_item = result.scalar_one_or_none()
                    if menu_item:
                        menu_item_id = menu_item.id
                        tax_rate = menu_item.tax_rate  # Verwende tax_rate vom MenuItem

                order_item = OrderItem(
                    order_id=order.id,
                    menu_item_id=menu_item_id,
                    item_name=item_data.item_name,
                    item_description=item_data.item_description,
                    category=item_data.category,
                    quantity=item_data.quantity,
                    unit_price=item_data.unit_price,
                    total_price=total_price,
                    tax_rate=tax_rate,
                    notes=item_data.notes,
                    sort_order=sort_order,
                    status="pending",
                )
                session.add(order_item)
                sort_order += 1

            await session.flush()

            # Lade Items neu und berechne Totals
            result = await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
            items = result.scalars().all()
            totals = _calculate_totals(
                items,
                discount_amount=order.discount_amount,
                discount_percentage=order.discount_percentage,
                tip_amount=order.tip_amount,
            )

            order.subtotal = totals["subtotal"]
            order.tax_amount_7 = totals["tax_amount_7"]
            order.tax_amount_19 = totals["tax_amount_19"]
            order.tax_amount = totals["tax_amount"]
            order.discount_amount = totals["discount_amount"]
            order.tip_amount = totals["tip_amount"]
            order.total = totals["total"]

        await session.commit()
        await session.refresh(order)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order conflict")

    return order


@router.get("/", response_model=list[OrderRead])
async def list_orders(
    restaurant_id: int,
    status_filter: str | None = Query(None),
    table_id: int | None = Query(None),
    guest_id: int | None = Query(None),
    reservation_id: int | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Listet Bestellungen eines Restaurants mit optionalen Filtern."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Order).where(Order.restaurant_id == restaurant_id)

    if status_filter:
        query = query.where(Order.status == status_filter)
    if table_id:
        query = query.where(Order.table_id == table_id)
    if guest_id:
        query = query.where(Order.guest_id == guest_id)
    if reservation_id:
        query = query.where(Order.reservation_id == reservation_id)
    if start_date:
        query = query.where(Order.opened_at >= start_date)
    if end_date:
        query = query.where(Order.opened_at <= end_date)

    query = query.order_by(Order.opened_at.desc())

    result = await session.execute(query)
    return result.scalars().all()


@router.get("/{order_id}", response_model=OrderWithItems)
async def get_order(
    restaurant_id: int,
    order_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Holt eine einzelne Bestellung mit allen Positionen."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    result = await session.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.sort_order, OrderItem.id)
    )
    items = result.scalars().all()

    order_dict = {
        **order.__dict__,
        "items": items,
    }
    return OrderWithItems(**order_dict)


@router.patch("/{order_id}", response_model=OrderRead)
async def update_order(
    restaurant_id: int,
    order_id: int,
    order_data: OrderUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Aktualisiert eine Bestellung (Mitarbeiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    update_data = order_data.model_dump(exclude_unset=True)

    if "reservation_id" in update_data:
        reservation_id = update_data["reservation_id"]
        if not reservation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reservation is required for every order",
            )
        reservation = await session.get(Reservation, reservation_id)
        if not reservation or reservation.restaurant_id != restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
            )
        if "table_id" in update_data and update_data["table_id"] not in (None, reservation.table_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Table does not match reservation assignment",
            )
        update_data["table_id"] = reservation.table_id

    if "table_id" in update_data and update_data["table_id"] and "reservation_id" not in update_data:
        if order.reservation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Table assignment is derived from reservation. Update reservation instead.",
            )
        table = await session.get(Table, update_data["table_id"])
        if not table or table.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    if "guest_id" in update_data and update_data["guest_id"]:
        guest = await session.get(Guest, update_data["guest_id"])
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    if "split_payments" in update_data:
        update_data["split_payments"] = _serialize_split_payments(update_data["split_payments"])

    if "closed_at" in update_data and update_data["closed_at"]:
        update_data["closed_at"] = normalize_datetime_to_utc(update_data["closed_at"])
    if "paid_at" in update_data and update_data["paid_at"]:
        update_data["paid_at"] = normalize_datetime_to_utc(update_data["paid_at"])

    # Berechne Totals neu wenn relevante Felder geändert wurden
    recalculate_totals = any(
        key in update_data for key in ["discount_amount", "discount_percentage", "tip_amount"]
    )

    for field, value in update_data.items():
        setattr(order, field, value)

    # Totals neu berechnen wenn nötig
    if recalculate_totals:
        result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        totals = _calculate_totals(
            items,
            discount_amount=order.discount_amount,
            discount_percentage=order.discount_percentage,
            tip_amount=order.tip_amount,
        )
        order.subtotal = totals["subtotal"]
        order.tax_amount = totals["tax_amount"]
        order.discount_amount = totals["discount_amount"]
        order.tip_amount = totals["tip_amount"]
        order.total = totals["total"]

    try:
        await session.commit()
        await session.refresh(order)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order conflict")

    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    restaurant_id: int,
    order_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht eine Bestellung (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    try:
        await session.delete(order)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise


# OrderItem Endpoints


@router.post("/{order_id}/items", response_model=OrderItemRead, status_code=status.HTTP_201_CREATED)
async def create_order_item(
    restaurant_id: int,
    order_id: int,
    item_data: OrderItemCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Fügt eine Position zu einer Bestellung hinzu."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    if order.status in ["paid", "canceled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add items to paid or canceled orders",
        )

    total_price = item_data.quantity * item_data.unit_price

    # Versuche menu_item_id zu finden falls item_name übereinstimmt
    menu_item_id = None
    tax_rate = item_data.tax_rate if item_data.tax_rate is not None else 0.19  # Default 19%
    if item_data.item_name:
        result_menu = await session.execute(
            select(MenuItem)
            .where(MenuItem.restaurant_id == restaurant_id, MenuItem.name == item_data.item_name)
            .limit(1)
        )
        menu_item = result_menu.scalar_one_or_none()
        if menu_item:
            menu_item_id = menu_item.id
            tax_rate = menu_item.tax_rate  # Verwende tax_rate vom MenuItem

    # Bestimme nächsten sort_order
    result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    existing_items = result.scalars().all()
    max_sort = max([item.sort_order or 0 for item in existing_items], default=-1)
    sort_order = item_data.sort_order if item_data.sort_order is not None else (max_sort + 1)

    order_item = OrderItem(
        order_id=order_id,
        menu_item_id=menu_item_id,
        item_name=item_data.item_name,
        item_description=item_data.item_description,
        category=item_data.category,
        quantity=item_data.quantity,
        unit_price=item_data.unit_price,
        total_price=total_price,
        tax_rate=tax_rate,
        notes=item_data.notes,
        sort_order=sort_order,
        status="pending",
    )

    try:
        session.add(order_item)
        await session.flush()

        # Aktualisiere Totals der Bestellung
        result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        totals = _calculate_totals(
            items,
            discount_amount=order.discount_amount,
            discount_percentage=order.discount_percentage,
            tip_amount=order.tip_amount,
        )

        order.subtotal = totals["subtotal"]
        order.tax_amount = totals["tax_amount"]
        order.discount_amount = totals["discount_amount"]
        order.tip_amount = totals["tip_amount"]
        order.total = totals["total"]

        await session.commit()
        await session.refresh(order_item)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order item conflict")

    return order_item


@router.patch("/{order_id}/items/{item_id}", response_model=OrderItemRead)
async def update_order_item(
    restaurant_id: int,
    order_id: int,
    item_id: int,
    item_data: OrderItemUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Aktualisiert eine Bestellposition."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    result = await session.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    order_item = result.scalar_one_or_none()
    if not order_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")

    if order.status in ["paid", "canceled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update items in paid or canceled orders",
        )

    update_data = item_data.model_dump(exclude_unset=True)

    # Berechne neue total_price wenn quantity oder unit_price geändert wird
    quantity = update_data.get("quantity", order_item.quantity)
    unit_price = update_data.get("unit_price", order_item.unit_price)
    update_data["total_price"] = quantity * unit_price

    # Wenn tax_rate nicht angegeben ist, behalte den bestehenden Wert
    if "tax_rate" not in update_data:
        update_data["tax_rate"] = order_item.tax_rate

    for field, value in update_data.items():
        setattr(order_item, field, value)

    try:
        await session.flush()

        # Aktualisiere Totals der Bestellung
        result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        totals = _calculate_totals(
            items,
            discount_amount=order.discount_amount,
            discount_percentage=order.discount_percentage,
            tip_amount=order.tip_amount,
        )

        order.subtotal = totals["subtotal"]
        order.tax_amount = totals["tax_amount"]
        order.discount_amount = totals["discount_amount"]
        order.tip_amount = totals["tip_amount"]
        order.total = totals["total"]

        await session.commit()
        await session.refresh(order_item)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order item conflict")

    return order_item


@router.delete("/{order_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_item(
    restaurant_id: int,
    order_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Löscht eine Bestellposition."""
    await _get_restaurant_or_404(restaurant_id, session)
    order = await _get_order_or_404(order_id, restaurant_id, session)

    result = await session.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    order_item = result.scalar_one_or_none()
    if not order_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")

    if order.status in ["paid", "canceled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete items from paid or canceled orders",
        )

    try:
        await session.delete(order_item)
        await session.flush()

        # Aktualisiere Totals der Bestellung
        result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        items = result.scalars().all()
        totals = _calculate_totals(
            items,
            discount_amount=order.discount_amount,
            discount_percentage=order.discount_percentage,
            tip_amount=order.tip_amount,
        )

        order.subtotal = totals["subtotal"]
        order.tax_amount = totals["tax_amount"]
        order.discount_amount = totals["discount_amount"]
        order.tip_amount = totals["tip_amount"]
        order.total = totals["total"]

        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
