import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Guest,
    Order,
    Reservation,
    ReservationTable,
    Restaurant,
    Table,
    User,
)
from app.dependencies import (
    get_current_user,
    get_session,
    normalize_datetime_to_utc,
    require_mitarbeiter_role,
    require_reservations_module,
    require_restaurantinhaber_role,
    require_schichtleiter_role,
)
from app.schemas import ReservationCreate, ReservationRead, ReservationUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/restaurants/{restaurant_id}/reservations", tags=["reservations"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_reservation_or_404(
    reservation_id: int, restaurant_id: int, session: AsyncSession
) -> Reservation:
    reservation = await session.get(Reservation, reservation_id)
    if not reservation or reservation.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return reservation


@router.post(
    "/",
    response_model=ReservationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_reservations_module)],
)
async def create_reservation(
    restaurant_id: int,
    reservation_data: ReservationCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Erstellt eine neue Reservierung (Mitarbeiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)

    if reservation_data.table_id:
        table = await session.get(Table, reservation_data.table_id)
        if not table or table.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
        if not table.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Table is not active"
            )

    if reservation_data.guest_id:
        guest = await session.get(Guest, reservation_data.guest_id)
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    start_at = normalize_datetime_to_utc(reservation_data.start_at)
    end_at = normalize_datetime_to_utc(reservation_data.end_at)

    if start_at >= end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be after start time"
        )

    reservation = Reservation(
        restaurant_id=restaurant_id,
        table_id=reservation_data.table_id,
        guest_id=reservation_data.guest_id,
        start_at=start_at,
        end_at=end_at,
        party_size=reservation_data.party_size,
        status=reservation_data.status,
        channel=reservation_data.channel,
        guest_name=reservation_data.guest_name,
        guest_email=reservation_data.guest_email,
        guest_phone=reservation_data.guest_phone,
        confirmation_code=reservation_data.confirmation_code,
        special_requests=reservation_data.special_requests,
        notes=reservation_data.notes,
        tags=reservation_data.tags,
    )

    try:
        session.add(reservation)
        await session.flush()

        if reservation_data.table_id:
            table = await session.get(Table, reservation_data.table_id)
            if table and table.join_group_id is not None:
                result = await session.execute(
                    select(Table).where(
                        Table.restaurant_id == restaurant_id,
                        Table.join_group_id == table.join_group_id,
                    )
                )
                group_tables = result.scalars().all()

                for tbl in group_tables:
                    rt = ReservationTable(
                        reservation_id=reservation.id,
                        table_id=tbl.id,
                        start_at=start_at,
                        end_at=end_at,
                    )
                    session.add(rt)
            else:
                rt = ReservationTable(
                    reservation_id=reservation.id,
                    table_id=reservation_data.table_id,
                    start_at=start_at,
                    end_at=end_at,
                )
                session.add(rt)

        await session.commit()
        await session.refresh(reservation)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reservation conflict")

    return reservation


@router.get(
    "/", response_model=list[ReservationRead], dependencies=[Depends(require_reservations_module)]
)
async def list_reservations(
    restaurant_id: int,
    date: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    status: str | None = None,
    table_id: int | None = None,
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(get_current_user),
):
    """Listet Reservierungen eines Restaurants mit optionalen Filtern.

    Filter:
    - date: Einzelnes Datum (YYYY-MM-DD) - filtert auf diesen Tag
    - from_date/to_date: Datumsbereich für start_at
    - status: Filtert nach Status (z.B. "confirmed", "pending")
    - table_id: Filtert nach Tisch
    - limit: Maximale Anzahl Ergebnisse
    """
    from datetime import timedelta

    from sqlalchemy import and_

    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Reservation).where(Reservation.restaurant_id == restaurant_id)

    # Datumsfilter
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
            day_end = day + timedelta(days=1)
            query = query.where(and_(Reservation.start_at >= day, Reservation.start_at < day_end))
        except ValueError:
            pass  # Ignoriere ungültiges Datum
    elif from_date or to_date:
        if from_date:
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
                query = query.where(Reservation.start_at >= from_dt)
            except ValueError:
                pass
        if to_date:
            try:
                to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(
                    days=1
                )
                query = query.where(Reservation.start_at < to_dt)
            except ValueError:
                pass

    # Statusfilter
    if status:
        query = query.where(Reservation.status == status)

    # Tischfilter
    if table_id:
        query = query.where(Reservation.table_id == table_id)

    # Sortierung
    query = query.order_by(Reservation.start_at)

    # Limit
    if limit and limit > 0:
        query = query.limit(limit)

    result = await session.execute(query)
    reservations = result.scalars().all()

    return list(reservations)


@router.get("/{reservation_id}", response_model=ReservationRead)
async def get_reservation(
    restaurant_id: int,
    reservation_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(get_current_user),
):
    """Holt eine einzelne Reservierung."""
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationRead)
async def update_reservation(
    restaurant_id: int,
    reservation_id: int,
    reservation_data: ReservationUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(get_current_user),
):
    """
    Aktualisiert eine Reservierung.
    - Vollständige Bearbeitung (inkl. Stornieren): Schichtleiter oder höher
    - Status-Änderungen (annehmen, zuweisen, platzieren, abschließen, no_show): Mitarbeiter oder höher
    """
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)

    update_data = reservation_data.model_dump(exclude_unset=True)

    # Prüfe ob Status auf "canceled" gesetzt wird (nur Schichtleiter)
    if "status" in update_data and update_data["status"] == "canceled":
        if current_user.role not in ["servecta", "restaurantinhaber", "schichtleiter"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Schichtleiter or higher can cancel reservations",
            )

    # Prüfe ob andere Felder als Status geändert werden (nur Schichtleiter)
    allowed_status_changes = ["pending", "confirmed", "seated", "completed", "no_show"]
    if "status" in update_data and update_data["status"] in allowed_status_changes:
        pass  # Statusänderung ok für Mitarbeiter
    else:
        non_status_fields = set(update_data.keys()) - {"status"}
        if non_status_fields:
            if current_user.role not in ["servecta", "restaurantinhaber", "schichtleiter"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only Schichtleiter or higher can edit reservation details",
                )

    if "table_id" in update_data and update_data["table_id"]:
        table = await session.get(Table, update_data["table_id"])
        if not table or table.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    if "start_at" in update_data:
        update_data["start_at"] = normalize_datetime_to_utc(update_data["start_at"])
    if "end_at" in update_data:
        update_data["end_at"] = normalize_datetime_to_utc(update_data["end_at"])
    if "canceled_at" in update_data and update_data["canceled_at"]:
        update_data["canceled_at"] = normalize_datetime_to_utc(update_data["canceled_at"])
    if "no_show_at" in update_data and update_data["no_show_at"]:
        update_data["no_show_at"] = normalize_datetime_to_utc(update_data["no_show_at"])

    if "start_at" in update_data and "end_at" in update_data:
        if update_data["start_at"] >= update_data["end_at"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End time must be after start time",
            )

    if "guest_id" in update_data:
        guest_id = update_data["guest_id"]
        if guest_id:
            guest = await session.get(Guest, guest_id)
            if not guest or guest.restaurant_id != restaurant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    old_table_id = reservation.table_id
    new_table_id = update_data.get("table_id", old_table_id)

    for field, value in update_data.items():
        setattr(reservation, field, value)

    if "table_id" in update_data and new_table_id != old_table_id:
        if old_table_id:
            old_table = await session.get(Table, old_table_id)
            if old_table and old_table.join_group_id is not None:
                result = await session.execute(
                    select(Table).where(
                        Table.restaurant_id == restaurant_id,
                        Table.join_group_id == old_table.join_group_id,
                    )
                )
                old_group_tables = result.scalars().all()
                for tbl in old_group_tables:
                    rt = await session.get(ReservationTable, (reservation.id, tbl.id))
                    if rt:
                        await session.delete(rt)
            else:
                rt = await session.get(ReservationTable, (reservation.id, old_table_id))
                if rt:
                    await session.delete(rt)

        if new_table_id:
            new_table = await session.get(Table, new_table_id)
            start_at = (
                update_data.get("start_at") if "start_at" in update_data else reservation.start_at
            )
            end_at = update_data.get("end_at") if "end_at" in update_data else reservation.end_at

            if new_table and new_table.join_group_id is not None:
                result = await session.execute(
                    select(Table).where(
                        Table.restaurant_id == restaurant_id,
                        Table.join_group_id == new_table.join_group_id,
                    )
                )
                new_group_tables = result.scalars().all()
                for tbl in new_group_tables:
                    existing_rt = await session.get(ReservationTable, (reservation.id, tbl.id))
                    if not existing_rt:
                        rt = ReservationTable(
                            reservation_id=reservation.id,
                            table_id=tbl.id,
                            start_at=start_at,
                            end_at=end_at,
                        )
                        session.add(rt)
            else:
                existing_rt = await session.get(ReservationTable, (reservation.id, new_table_id))
                if not existing_rt:
                    rt = ReservationTable(
                        reservation_id=reservation.id,
                        table_id=new_table_id,
                        start_at=start_at,
                        end_at=end_at,
                    )
                    session.add(rt)

        await session.execute(
            update(Order)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.reservation_id == reservation.id,
                Order.status.notin_(["paid", "canceled"]),
            )
            .values(table_id=new_table_id)
        )

    try:
        await session.commit()
        await session.refresh(reservation)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reservation conflict")

    return reservation


@router.post("/{reservation_id}/cancel", response_model=ReservationRead)
async def cancel_reservation(
    restaurant_id: int,
    reservation_id: int,
    canceled_reason: str | None = Body(None, embed=True),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Storniert eine Reservierung (Schichtleiter oder höher) und sendet E-Mail-Benachrichtigung."""

    from app.services.notification_service import ReservationNotification, notification_service
    from app.settings import RESERVATION_WIDGET_URL

    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)
    restaurant = await session.get(Restaurant, restaurant_id)

    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    # Prüfe ob bereits storniert
    if reservation.status == "canceled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reservierung ist bereits storniert"
        )

    # Aktualisiere Reservierung
    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    if canceled_reason:
        reservation.canceled_reason = canceled_reason

    try:
        await session.commit()
        await session.refresh(reservation)
    except Exception:
        await session.rollback()
        raise

    # Sende Stornierungs-Benachrichtigung per E-Mail
    if reservation.guest_email:
        try:
            # Formatiere Datum und Zeit
            start_dt = reservation.start_at
            date_str = start_dt.strftime("%d.%m.%Y")
            time_str = start_dt.strftime("%H:%M")

            manage_url = (
                f"{RESERVATION_WIDGET_URL}/{restaurant.slug}/manage/{reservation.confirmation_code}"
                if reservation.confirmation_code and restaurant.slug
                else None
            )

            notification = ReservationNotification(
                guest_name=reservation.guest_name or "Gast",
                guest_email=reservation.guest_email,
                guest_phone=reservation.guest_phone or "",
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_address=restaurant.address,
                restaurant_phone=restaurant.phone,
                date=date_str,
                time=time_str,
                party_size=reservation.party_size,
                table_number=None,  # Nicht relevant für Stornierung
                confirmation_code=reservation.confirmation_code or "",
                special_requests=None,
                manage_url=manage_url,
            )

            # Sende Stornierungs-Benachrichtigung
            results = await notification_service.send_reservation_cancellation(
                notification=notification,
                channels=["email"],  # Nur E-Mail für Stornierung
            )

            # Logge Ergebnisse
            for result in results:
                if result.success:
                    logger.info(
                        f"Stornierungs-E-Mail gesendet via {result.channel}: {result.message}"
                    )
                else:
                    logger.warning(
                        f"Stornierungs-E-Mail fehlgeschlagen via {result.channel}: {result.error}"
                    )
        except Exception as notify_error:
            # Benachrichtigungsfehler sollten die Stornierung nicht abbrechen
            logger.error(f"Failed to send cancellation notification: {notify_error}")

    return reservation


@router.delete("/{reservation_id}", status_code=status.HTTP_200_OK)
async def delete_reservation(
    restaurant_id: int,
    reservation_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_restaurantinhaber_role),
):
    """Löscht eine Reservierung komplett (Restaurantinhaber oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)

    try:
        await session.delete(reservation)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise

    return {"message": "deleted"}
