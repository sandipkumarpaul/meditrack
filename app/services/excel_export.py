import io
from datetime import timezone
from zoneinfo import ZoneInfo
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from app.utils.timeutil import utcnow_naive

def generate_dose_history_excel(logs, username, user_email, timezone_name='UTC'):
    """
    Generates a professionally formatted Excel (.xlsx) workbook for medication dose history.
    Date/Time columns are shown in `timezone_name` (the household's local timezone);
    the full timestamp column keeps the original UTC value for precise auditing.
    """
    tz = ZoneInfo(timezone_name)

    def to_local(dt):
        return dt.replace(tzinfo=timezone.utc).astimezone(tz)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dose History"

    # Ensure grid lines are visible
    ws.views.sheetView[0].showGridLines = True

    # Color definitions
    HEADER_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid") # Dark Navy Blue
    ZEBRA_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")  # Soft Slate 50
    HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name="Calibri", size=15, bold=True, color="1E3A8A")
    SUBTITLE_FONT = Font(name="Calibri", size=10, italic=True, color="475569")
    REGULAR_FONT = Font(name="Calibri", size=10)
    
    THIN_BORDER = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    # Title & Metadata
    ws['A1'] = "MediTrack — Household Medication & Dose Adherence History"
    ws['A1'].font = TITLE_FONT
    ws.row_dimensions[1].height = 24

    ws['A2'] = f"Account: {username} ({user_email})  |  Generated: {utcnow_naive().strftime('%Y-%m-%d %I:%M %p')} UTC"
    ws['A2'].font = SUBTITLE_FONT
    ws.row_dimensions[2].height = 18

    # Blank row
    ws.row_dimensions[3].height = 10

    # Column Headers
    headers = [
        "Date",
        "Time",
        "Family Member",
        "Relationship",
        "Medication",
        "Category",
        "Action",
        "Change",
        "Scheduled Times",
        "Notes",
        "Full Timestamp (UTC)"
    ]

    header_row = 4
    ws.row_dimensions[header_row].height = 26

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Data Rows
    current_row = 5
    for log in logs:
        med = log.medication_ref
        person = med.person if med else None

        action_label = "Dose Taken" if log.action == 'increment' else (
            "Dose Undone" if log.action == 'decrement' else "Inventory Refill"
        )
        sign = "+" if log.action in ['increment', 'refill'] else "-"
        qty_str = f"{sign}{log.pills_changed} pill" if log.pills_changed == 1 else f"{sign}{log.pills_changed} pills"

        local_ts = to_local(log.timestamp)
        row_values = [
            local_ts.strftime('%Y-%m-%d'),
            local_ts.strftime('%I:%M %p'),
            person.name if person else "Unknown",
            person.relationship if person else "Family",
            med.name if med else "Unknown",
            med.genre if med else "General",
            action_label,
            qty_str,
            med.time_slot if med else "Morning",
            log.notes or "",
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        ]

        ws.row_dimensions[current_row].height = 20
        is_even = (current_row % 2 == 0)

        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = THIN_BORDER

            if is_even:
                cell.fill = ZEBRA_FILL

            # Alignment
            if col_idx in [1, 2, 7, 8]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            # Color styling for action
            if col_idx == 7: # Action column
                if log.action == 'increment':
                    cell.font = Font(name="Calibri", size=10, bold=True, color="15803D") # Green
                elif log.action == 'decrement':
                    cell.font = Font(name="Calibri", size=10, bold=True, color="B45309") # Amber
                elif log.action == 'refill':
                    cell.font = Font(name="Calibri", size=10, bold=True, color="0369A1") # Sky Blue

        current_row += 1

    # Auto-adjust column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            # Skip title row from calculation
            if cell.row in [1, 2, 3]:
                continue
            val_str = str(cell.value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
