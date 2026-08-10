import os
from typing import Any, Dict, List, Optional

import requests


class PMSClient:
    def __init__(self, base_url: Optional[str] = None, timeout: int = 10):
        self.base_url = (base_url or os.getenv("PMS_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        r = requests.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        r = requests.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def find_patients(self, name: Optional[str] = None, dob: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {}
        if name:
            params["name"] = name
        if dob:
            params["dob"] = dob
        return self._get("/patients", params=params)

    def create_patient(self, first_name: str, last_name: str, date_of_birth: str, phone_number: Optional[str] = None) -> Dict[str, Any]:
        return self._post(
            "/patients",
            {
                "first_name": first_name,
                "last_name": last_name,
                "date_of_birth": date_of_birth,
                "phone_number": phone_number,
            },
        )

    def available_slots(self, day: str) -> Dict[str, Any]:
        return self._get("/appointments/available", params={"date": day})

    def book_appointment(
        self,
        patient_id: str,
        appointment_date: str,
        appointment_time: str,
        reason_for_visit: Optional[str] = None,
        provider: Optional[str] = None,
        duration_minutes: int = 30,
        appointment_type: str = "Prophy",
        chair: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider = provider or os.getenv("PMS_PROVIDER", "Dr. Rivera DDS")
        chair = chair or os.getenv("PMS_CHAIR", "Chair 1")
        return self._post(
            "/appointments",
            {
                "patient_id": patient_id,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
                "reason_for_visit": reason_for_visit,
                "provider": provider,
                "duration_minutes": duration_minutes,
                "appointment_type": appointment_type,
                "chair": chair,
                "note": "Created by BrightSmile Dental receptionist sandbox.",
            },
        )

    def create_queue_item(
        self,
        patient_name: str,
        phone_number: Optional[str] = None,
        requested_date: Optional[str] = None,
        requested_time: Optional[str] = None,
        reason_for_visit: Optional[str] = None,
        appointment_type: str = "Prophy",
        risk_level: str = "needs_review",
        patient_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._post(
            "/appointment-queue",
            {
                "patient_id": patient_id,
                "patient_name": patient_name,
                "phone_number": phone_number,
                "requested_date": requested_date,
                "requested_time": requested_time,
                "reason_for_visit": reason_for_visit,
                "appointment_type": appointment_type,
                "risk_level": risk_level,
                "source": "BrightSmile Dental AI receptionist",
                "staff_note": "Receptionist-agent draft. Staff approval required before live PMS use.",
            },
        )
