from __future__ import annotations

import json

from app.config import SESSIONS_DIR
from app.storage import atomic_write_json, recover_transactions, session_lock
from tests.conftest import activate_session


def test_prepared_transaction_is_recovered(client, auth_headers):
    session_id = activate_session(client, auth_headers, "R")
    root = SESSIONS_DIR / session_id
    txn_dir = root / "transactions" / "pending" / "turn_recovery"
    txn_dir.mkdir(parents=True)
    atomic_write_json(
        txn_dir / "commit_plan.json",
        {
            "transaction_id": "turn_recovery",
            "status": "prepared",
            "writes": {"state/recovered.json": "{\"ok\": true}\n"},
            "receipt": {
                "status": "committed",
                "session_id": session_id,
                "turn_id": "turn_recovery",
            },
        },
    )
    with session_lock(root):
        recovered = recover_transactions(root)
    assert recovered == ["turn_recovery"]
    assert json.loads((root / "state" / "recovered.json").read_text()) == {"ok": True}
    assert (root / "transactions" / "receipts" / "turn_recovery.json").is_file()
