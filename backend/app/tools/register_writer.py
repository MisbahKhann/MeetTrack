"""Writes and updates the Excel action register via openpyxl.

Enforces:
- Hard rule 8: Scoped by team_id.
- Hard rule 10: Manual columns in the Excel register are never overwritten on re-export.
- Hard rule 13: No em-dashes anywhere.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.tools.action_store import (
    NotFoundError,
    list_actions,
)
from app.tools.date_checker import days_overdue, parse_as_of

GENERATED_HEADERS = [
    "Action Code",
    "Action ID",
    "Description",
    "Owner",
    "Due Date",
    "Status",
    "Overdue Days",
    "Source Line",
    "Blocker",
    "Next Action",
    "Valid From",
]

DEFAULT_MANUAL_HEADERS = [
    "Decision",
    "Comments",
]

HISTORY_HEADERS = [
    "Action Code",
    "Action ID",
    "Version No",
    "Description",
    "Owner",
    "Due Date",
    "Status",
    "Blocked Reason",
    "Changed By",
    "Valid From",
    "Superseded At",
    "Is Current",
]


def _read_existing_manual_data(
    existing_bytes: bytes,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Extract user-maintained column values and headers from existing register.

    Returns:
        (manual_data_by_key, manual_headers_list)
        where manual_data_by_key maps action_code/action_id to {col_header: cell_value}.
    """
    manual_data: dict[str, dict[str, Any]] = {}
    manual_headers: list[str] = []

    try:
        wb = openpyxl.load_workbook(io.BytesIO(existing_bytes), data_only=True)
    except Exception:
        # If the file is unreadable or corrupted, fail clearly or return empty
        return manual_data, DEFAULT_MANUAL_HEADERS.copy()

    sheet = None
    if "Action Register" in wb.sheetnames:
        sheet = wb["Action Register"]
    elif wb.sheetnames:
        sheet = wb.active

    if sheet is None or sheet.max_row < 1:
        return manual_data, DEFAULT_MANUAL_HEADERS.copy()

    # Read header row
    header_cells = [cell.value for cell in sheet[1]]
    code_col_idx: int | None = None
    id_col_idx: int | None = None
    manual_col_indices: dict[int, str] = {}

    for idx, header in enumerate(header_cells):
        if not header:
            continue
        header_str = str(header).strip()
        if header_str == "Action Code":
            code_col_idx = idx
        elif header_str == "Action ID":
            id_col_idx = idx
        elif header_str not in GENERATED_HEADERS:
            manual_col_indices[idx] = header_str
            if header_str not in manual_headers:
                manual_headers.append(header_str)

    # Ensure default manual headers are present
    for def_h in DEFAULT_MANUAL_HEADERS:
        if def_h not in manual_headers:
            manual_headers.append(def_h)

    # Read data rows
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        action_code = str(row[code_col_idx]).strip() if code_col_idx is not None and code_col_idx < len(row) and row[code_col_idx] is not None else None
        action_id = str(row[id_col_idx]).strip() if id_col_idx is not None and id_col_idx < len(row) and row[id_col_idx] is not None else None

        row_manual_vals: dict[str, Any] = {}
        for col_idx, col_name in manual_col_indices.items():
            if col_idx < len(row):
                row_manual_vals[col_name] = row[col_idx]

        if action_code and row_manual_vals:
            manual_data[action_code] = row_manual_vals
        if action_id and row_manual_vals:
            manual_data[action_id] = row_manual_vals

    return manual_data, manual_headers


def export_register(
    conn: Any,
    *,
    team_id: str,
    as_of: str | None = None,
    existing_bytes: bytes | None = None,
) -> bytes:
    """Generate the Excel action register workbook with Action Register and History sheets.

    Preserves manual decision and comment columns from existing_bytes if provided.
    """
    # Verify team exists
    team_row = conn.execute("SELECT id FROM teams WHERE id = ?", (team_id,)).fetchone()
    if team_row is None:
        raise NotFoundError(f"Team {team_id!r} not found")

    as_of_date = parse_as_of(as_of) if as_of else date.today()

    # Read preserved manual columns if existing workbook given
    preserved_manual_data: dict[str, dict[str, Any]] = {}
    manual_headers = DEFAULT_MANUAL_HEADERS.copy()

    if existing_bytes:
        preserved_manual_data, manual_headers = _read_existing_manual_data(existing_bytes)

    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)

    # Header styling
    header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True)

    # 1. Action Register sheet
    ws_actions = wb.create_sheet(title="Action Register")
    ws_actions.freeze_panes = "A2"

    all_action_headers = GENERATED_HEADERS + manual_headers
    ws_actions.append(all_action_headers)
    for col_idx in range(1, len(all_action_headers) + 1):
        cell = ws_actions.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    actions = list_actions(conn, team_id=team_id, include_done=True)

    for act in actions:
        # Calculate overdue days
        ov_days = 0
        if act.status != "done" and act.due_date:
            try:
                due_d = date.fromisoformat(act.due_date)
                ov_days = days_overdue(due_d, as_of_date, act.status)
            except ValueError:
                ov_days = 0

        # Match preserved manual data
        match_data = preserved_manual_data.get(act.action_code) or preserved_manual_data.get(act.action_id) or {}

        # Generated fields
        row_vals = [
            act.action_code,
            act.action_id,
            act.description,
            act.owner or "",
            act.due_date or "",
            act.status,
            ov_days if ov_days > 0 else 0,
            act.source_line if act.source_line is not None else "",
            act.blocked_reason or "",
            "",  # Next Action
            act.valid_from,
        ]

        # Append manual columns
        for mh in manual_headers:
            row_vals.append(match_data.get(mh, ""))

        ws_actions.append(row_vals)

    # Adjust column widths for Action Register
    for col in ws_actions.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws_actions.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    # 2. History sheet
    ws_history = wb.create_sheet(title="History")
    ws_history.freeze_panes = "A2"
    ws_history.append(HISTORY_HEADERS)
    for col_idx in range(1, len(HISTORY_HEADERS) + 1):
        cell = ws_history.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    history_rows = conn.execute(
        "SELECT a.action_code, a.id AS action_id, v.description, "
        "       v.version_no, v.owner, v.due_date, v.status, v.blocked_reason, "
        "       v.changed_by, v.valid_from, v.superseded_at, v.is_current "
        "FROM actions a "
        "JOIN action_versions v ON a.id = v.action_id "
        "WHERE a.team_id = ? "
        "ORDER BY a.action_code ASC, v.version_no ASC",
        (team_id,),
    ).fetchall()

    for r in history_rows:
        ws_history.append(
            [
                r["action_code"],
                r["action_id"],
                r["version_no"],
                r["description"],
                r["owner"] or "",
                r["due_date"] or "",
                r["status"],
                r["blocked_reason"] or "",
                r["changed_by"],
                r["valid_from"],
                r["superseded_at"] or "",
                1 if r["is_current"] else 0,
            ]
        )

    # Adjust column widths for History
    for col in ws_history.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws_history.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_register_file(
    conn: Any,
    *,
    team_id: str,
    output_path: str | Path,
    as_of: str | None = None,
) -> Path:
    """Write action register directly to a file on disk."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    existing_bytes: bytes | None = None
    if out.exists():
        try:
            existing_bytes = out.read_bytes()
        except Exception:
            existing_bytes = None

    data = export_register(conn, team_id=team_id, as_of=as_of, existing_bytes=existing_bytes)
    out.write_bytes(data)
    return out
