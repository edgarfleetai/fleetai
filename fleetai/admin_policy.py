"""Owner-only route policy for sensitive dispatcher operations.

Public driver links, bank callbacks and secret-protected cron routes are
deliberately excluded. Keep this allowlist explicit and review new routes.
"""
ADMIN_WRITE_RULES = frozenset({
    "/api/driver-wallet/topup",
    "/api/driver-wallet/fine",
    "/api/driver-debt-from-car",
    "/api/driver-debt-payment",
    "/api/driver-assignment",
    "/api/driver-contract/create",
    "/api/edit-operation/<int:operation_id>",
    "/api/delete-operation/<int:operation_id>",
    "/api/driver-mvp/<code>/test-topup",
    "/api/driver-mvp/<code>/test-debt",
    "/api/driver-mvp/<code>/clear-test-debt",
    "/api/payment-settings",
    "/api/mark-driver-period-partial",
    "/api/mark-driver-period-paid",
    "/api/mark-driver-payment-paid",
    "/api/add-car",
    "/api/delete-car/<code>",
    "/api/reset-car-investor/<code>",
    "/api/reassign-car-investor",
    "/api/driver-telegram/link",
    "/api/driver-telegram/test",
    "/api/wialon/settings/<car_code>",
    "/api/wialon/odometer-baseline/<car_code>",
    "/api/wialon/665/command",
})
ADMIN_READ_RULES = frozenset({
    "/driver-topup",
    "/api/driver-wallet/cars",
    "/driver-debts-admin",
    "/driver-contract-admin",
    "/driver-contracts",
    "/driver-contracts/<contract_id>/pdf",
    "/driver-fines",
    "/driver-telegram",
    "/wialon-settings",
    "/wialon-trackers",
    "/wialon-665",
})
DANGEROUS_WIALON_COMMAND = "/api/wialon/665/command"


def requires_owner(rule, method):
    if method in ("POST", "PUT", "PATCH", "DELETE") and rule in ADMIN_WRITE_RULES:
        return True
    if method == "GET" and rule in ADMIN_READ_RULES:
        return True
    return False
