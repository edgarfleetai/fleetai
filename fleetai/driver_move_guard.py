"""Stable fingerprint of the assignments reviewed by the owner."""
import hashlib
import json


def assignment_fingerprint(cars):
    records = []
    for car in cars:
        records.append({
            'car_code': str(car.code).strip(),
            'driver': (car.driver or '').strip(),
            'daily_rent': int(car.daily_rent or 0),
            'driver_deposit': int(car.driver_deposit or 0),
        })
    records.sort(key=lambda row: row['car_code'])
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def is_preview_current(cars, fingerprint):
    return isinstance(fingerprint, str) and len(fingerprint) == 64 and assignment_fingerprint(cars) == fingerprint
