import os
import httpx
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional

# Apple Receipt Verification URLs
APPLE_PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"


async def verify_apple_receipt(receipt_data: str, product_id: str) -> Tuple[bool, Optional[str], str]:
    """
    Verifies an Apple App Store receipt against Apple's servers.
    Automatically handles sandbox routing for test receipts.

    Returns:
        Tuple[bool, Optional[str], str]: (is_valid, expiry_iso_string, reason/error_message)
    """
    shared_secret = os.getenv("APPLE_SHARED_SECRET")
    
    # We allow testing without shared secret if strict verification is disabled, but for production it's mandatory
    if not shared_secret:
        print("[APPLE VERIFY] WARNING: APPLE_SHARED_SECRET not set in environment.")
        # For auto-renewable subscriptions, the shared secret is strictly required by Apple.
        return False, None, "Server configuration error: Missing APPLE_SHARED_SECRET"

    payload = {
        "receipt-data": receipt_data,
        "password": shared_secret,
        "exclude-old-transactions": True
    }

    try:
        # Step 1: Always try production first (Apple's recommendation)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(APPLE_PRODUCTION_URL, json=payload)
            data = resp.json()

            # Step 2: If status is 21007, this is a sandbox receipt. Route to Sandbox.
            status = data.get("status")
            if status == 21007:
                print("[APPLE VERIFY] Sandbox receipt detected (21007). Routing to Sandbox endpoint.")
                resp = await client.post(APPLE_SANDBOX_URL, json=payload)
                data = resp.json()
                status = data.get("status")

        if status != 0:
            return False, None, f"Apple Verification Failed. Status Code: {status}"

        # Step 3: Parse the latest_receipt_info to find the active subscription
        latest_receipt_info = data.get("latest_receipt_info", [])
        if not latest_receipt_info:
            return False, None, "No active subscription found in receipt."

        # Find the most recent transaction for the requested product_id
        # Apple returns an array, usually sorted from oldest to newest
        target_transactions = [t for t in latest_receipt_info if t.get("product_id") == product_id]
        
        if not target_transactions:
            return False, None, f"Product {product_id} not found in this receipt."

        # Get the transaction with the furthest expiration date
        latest_transaction = max(
            target_transactions, 
            key=lambda t: int(t.get("expires_date_ms", 0))
        )

        expires_date_ms = int(latest_transaction.get("expires_date_ms", 0))
        current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if expires_date_ms <= current_time_ms:
            return False, None, "Subscription has expired."

        # Calculate expiry ISO
        expiry_dt = datetime.fromtimestamp(expires_date_ms / 1000, tz=timezone.utc)
        expiry_iso = expiry_dt.isoformat()

        print(f"[APPLE VERIFY] Validation success for {product_id}. Expires at {expiry_iso}")
        return True, expiry_iso, "Success"

    except Exception as e:
        print(f"[APPLE VERIFY] Exception during apple verification: {str(e)}")
        return False, None, f"Internal Verification Error: {str(e)}"
