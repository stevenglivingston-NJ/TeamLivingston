Shared JSON envelope emitted by every template in this directory.
Parser: intranet/scripts/ingest_sm_notes.py

{
  "source":       "appointment" | "contact" | "proposal",
  "brand":        "KTU" | "BTU",
  "contact_id":     int | null,
  "appointment_id": int | null,
  "proposal_id":    int | null,
  "subject_label":  string   (human context, e.g. customer name + service)
  "cancel_reason_id":   int | null,
  "cancel_reason":      string | null,   -- the LABEL; Liquid-only
  "cancelled_at":       string | null,
  "notes": [ { "id", "title", "body", "private", "created_at", "created_by" } ]
}

Only `source`, `brand` and `notes` are required. Everything else may be null;
the ingest fills what it can and never fails a row for a missing optional.
