from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from sqlalchemy import desc
import csv
import io

from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user

router = APIRouter(prefix="/api/meter-readings", tags=["Meter Readings"])

@router.get("/", response_model=List[schemas.MeterReadingOut])
def list_readings(
    customer_id: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """Get recent meter readings, optionally filtered by customer."""
    q = db.query(models.MeterReading)
    if customer_id:
        q = q.filter(models.MeterReading.customer_id == customer_id)
    return q.order_by(desc(models.MeterReading.reading_date)).limit(limit).all()

@router.post("/", response_model=schemas.MeterReadingOut)
def record_reading(
    payload: schemas.MeterReadingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """Field Officers use this to submit a new meter reading."""
    # Find previous reading for this customer to calculate consumption
    last_reading = db.query(models.MeterReading)\
        .filter(models.MeterReading.customer_id == payload.customer_id)\
        .order_by(desc(models.MeterReading.reading_date))\
        .first()

    previous = payload.previous_reading
    if last_reading and previous is None:
        previous = last_reading.current_reading
    
    units = payload.units_consumed
    if units is None and previous is not None:
        units = max(0.0, payload.current_reading - previous)
    
    reading = models.MeterReading(
        customer_id=payload.customer_id,
        reading_date=payload.reading_date,
        current_reading=payload.current_reading,
        previous_reading=previous,
        units_consumed=units,
        recorded_by_id=current_user.id
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading

@router.post("/import")
async def import_meter_readings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """Bulk import meter readings from CSV."""
    if not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file is empty or missing headers")

    header_map = {fn.strip().lower(): fn for fn in reader.fieldnames}
    acc_key = next((k for k in ["account_number", "account_no", "account", "meter_number", "meter_no"] if k in header_map), None)
    reading_key = next((k for k in ["current_reading", "reading", "meter_reading", "value"] if k in header_map), None)
    date_key = next((k for k in ["reading_date", "date"] if k in header_map), None)

    if not acc_key or not reading_key:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain 'account_number' (or 'meter_number') and 'current_reading' columns"
        )

    customers = db.query(models.Customer).all()
    cust_by_acc = {c.account_number.strip().upper(): c for c in customers if c.account_number}
    cust_by_meter = {c.meter_number.strip().upper(): c for c in customers if c.meter_number}

    imported_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=2):
        acc_val = (row.get(header_map[acc_key]) or "").strip().upper()
        reading_str = (row.get(header_map[reading_key]) or "").strip()
        date_str = (row.get(header_map[date_key]) or "").strip() if date_key else None

        if not acc_val or not reading_str:
            continue

        try:
            current_val = float(reading_str)
        except ValueError:
            errors.append(f"Row {row_idx}: Invalid reading number '{reading_str}'")
            continue

        customer = cust_by_acc.get(acc_val) or cust_by_meter.get(acc_val)
        if not customer:
            errors.append(f"Row {row_idx}: Account/Meter '{acc_val}' not found")
            continue

        r_date = date.today()
        if date_str:
            try:
                r_date = date.fromisoformat(date_str)
            except ValueError:
                try:
                    from datetime import datetime
                    r_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                except Exception:
                    pass

        last_reading = (
            db.query(models.MeterReading)
            .filter(models.MeterReading.customer_id == customer.id)
            .order_by(desc(models.MeterReading.reading_date))
            .first()
        )
        prev_val = last_reading.current_reading if last_reading else None
        units = max(0.0, current_val - prev_val) if prev_val is not None else 0.0

        new_reading = models.MeterReading(
            customer_id=customer.id,
            reading_date=r_date,
            current_reading=current_val,
            previous_reading=prev_val,
            units_consumed=units,
            recorded_by_id=current_user.id,
        )
        db.add(new_reading)
        imported_count += 1

    if imported_count > 0:
        audit = models.AuditLog(
            user_id=current_user.id,
            action="csv_import",
            resource_type="MeterReading",
            details=f"Imported {imported_count} meter readings from {file.filename}",
        )
        db.add(audit)
        db.commit()

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors[:15],
        "total_errors": len(errors),
    }
