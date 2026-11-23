from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, timedelta
from sqlalchemy import extract, func
import csv
import io
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user, require_admin

router = APIRouter(prefix="/api/bills", tags=["Bills"])

@router.get("/")
def list_bills(
    zone_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    q = db.query(models.Bill).join(models.Customer)
    if zone_id:
        q = q.filter(models.Customer.zone_id == zone_id)
    if customer_id:
        q = q.filter(models.Bill.customer_id == customer_id)
    if status:
        q = q.filter(models.Bill.status == status)
    if year:
        q = q.filter(extract("year", models.Bill.bill_date) == year)
    if month:
        q = q.filter(extract("month", models.Bill.bill_date) == month)
    total = q.count()
    bills = q.order_by(models.Bill.bill_date.desc()).offset(skip).limit(limit).all()
    return {"total": total, "data": [schemas.BillOut.model_validate(b) for b in bills]}

@router.get("/monthly-trend")
def monthly_trend(
    zone_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """Monthly aggregated revenue, consumption, NRW for chart."""
    q = (
        db.query(
            func.strftime("%Y-%m", models.Bill.bill_date).label("month"),
            func.sum(models.Bill.amount_billed).label("billed"),
            func.sum(models.Bill.amount_paid).label("collected"),
            func.sum(models.Bill.units_consumed).label("consumption"),
            func.sum(models.Bill.nrw_loss).label("nrw"),
            func.count(models.Bill.id).label("bill_count"),
        )
        .join(models.Customer)
    )
    if zone_id:
        q = q.filter(models.Customer.zone_id == zone_id)
    rows = q.group_by(func.strftime("%Y-%m", models.Bill.bill_date)).order_by("month").all()
    return [
        {
            "month": r.month if r.month else None,
            "billed": round(r.billed or 0, 2),
            "collected": round(r.collected or 0, 2),
            "collection_rate": round((r.collected / r.billed * 100) if r.billed else 0, 1),
            "consumption": round(r.consumption or 0, 2),
            "nrw": round(r.nrw or 0, 2),
            "bill_count": r.bill_count,
        }
        for r in rows
    ]

@router.get("/zone-comparison")
def zone_comparison(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """Compare all zones for a given period."""
    if year and month:
        yr, mn = year, month
    else:
        latest_bill = db.query(models.Bill).order_by(models.Bill.bill_date.desc()).first()
        if latest_bill:
            yr = latest_bill.bill_date.year
            mn = latest_bill.bill_date.month
        else:
            now = date.today()
            yr, mn = now.year, now.month
    zones = db.query(models.Zone).all()
    result = []
    for zone in zones:
        bills = (
            db.query(models.Bill)
            .join(models.Customer)
            .filter(
                models.Customer.zone_id == zone.id,
                extract("year", models.Bill.bill_date) == yr,
                extract("month", models.Bill.bill_date) == mn,
            )
            .all()
        )
        billed = sum(b.amount_billed for b in bills)
        collected = sum(b.amount_paid for b in bills)
        nrw = sum(b.nrw_loss for b in bills)
        result.append({
            "zone_id": zone.id,
            "zone_name": zone.name,
            "billed": round(billed, 2),
            "collected": round(collected, 2),
            "nrw": round(nrw, 2),
            "collection_rate": round((collected / billed * 100) if billed else 0, 1),
            "target": zone.target_monthly_revenue,
            "target_pct": round((collected / zone.target_monthly_revenue * 100) if zone.target_monthly_revenue else 0, 1),
            "bill_count": len(bills),
        })
    return sorted(result, key=lambda x: x["collected"], reverse=True)

@router.post("/", response_model=schemas.BillOut)
def create_bill(payload: schemas.BillCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    bill = models.Bill(**payload.model_dump())
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill

@router.patch("/{bill_id}/pay")
def record_payment(
    bill_id: int,
    amount: float,
    payment_date: Optional[date] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    bill.amount_paid = min(bill.amount_billed, bill.amount_paid + amount)
    bill.payment_date = payment_date or date.today()
    if bill.amount_paid >= bill.amount_billed:
        bill.status = "paid"
    elif bill.amount_paid > 0:
        bill.status = "partial"
    db.commit()
    return {"message": "Payment recorded", "bill_id": bill_id, "amount_paid": bill.amount_paid, "status": bill.status}

@router.post("/import")
async def import_bills(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """Bulk import billing records from CSV."""
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
    units_key = next((k for k in ["units_consumed", "units", "consumption", "consumption_m3"] if k in header_map), None)
    billed_key = next((k for k in ["amount_billed", "billed", "amount"] if k in header_map), None)
    paid_key = next((k for k in ["amount_paid", "paid", "collected"] if k in header_map), None)
    date_key = next((k for k in ["bill_date", "date", "month"] if k in header_map), None)

    if not acc_key or not billed_key:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain 'account_number' and 'amount_billed' columns"
        )

    customers = db.query(models.Customer).all()
    cust_by_acc = {c.account_no.strip().upper(): c for c in customers if getattr(c, "account_no", None)}
    cust_by_meter = {c.meter_no.strip().upper(): c for c in customers if getattr(c, "meter_no", None)}
    cust_by_id = {str(c.id): c for c in customers}

    imported_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=2):
        acc_val = (row.get(header_map[acc_key]) or "").strip().upper()
        billed_str = (row.get(header_map[billed_key]) or "").strip()
        units_str = (row.get(header_map[units_key]) or "0").strip() if units_key else "0"
        paid_str = (row.get(header_map[paid_key]) or "0").strip() if paid_key else "0"
        date_str = (row.get(header_map[date_key]) or "").strip() if date_key else None

        if not acc_val or not billed_str:
            continue

        try:
            amt_billed = float(billed_str)
            amt_paid = float(paid_str) if paid_str else 0.0
            units = float(units_str) if units_str else 0.0
        except ValueError:
            errors.append(f"Row {row_idx}: Non-numeric value in amounts/units")
            continue

        customer = cust_by_acc.get(acc_val) or cust_by_meter.get(acc_val) or cust_by_id.get(acc_val)
        if not customer:
            errors.append(f"Row {row_idx}: Account/Meter '{acc_val}' not found")
            continue

        b_date = date.today()
        if date_str:
            try:
                b_date = date.fromisoformat(date_str)
            except ValueError:
                try:
                    from datetime import datetime
                    b_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                except Exception:
                    pass

        status = models.BillStatus.paid if amt_paid >= amt_billed else (
            models.BillStatus.partial if amt_paid > 0 else models.BillStatus.unpaid
        )

        new_bill = models.Bill(
            customer_id=customer.id,
            units_consumed=units,
            amount_billed=amt_billed,
            amount_paid=amt_paid,
            bill_date=b_date,
            due_date=b_date + timedelta(days=21),
            status=status,
            nrw_loss=round(units * 0.22, 2),
        )
        db.add(new_bill)
        imported_count += 1

    if imported_count > 0:
        audit = models.AuditLog(
            user_id=current_user.id,
            action="csv_import",
            resource_type="Bill",
            details=f"Imported {imported_count} billing records from {file.filename}",
        )
        db.add(audit)
        db.commit()

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors[:15],
        "total_errors": len(errors),
    }
