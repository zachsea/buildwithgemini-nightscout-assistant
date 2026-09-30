from typing import Optional, Dict
from google.cloud import firestore
import requests

# Hardcode the project ID to avoid deployment resolution issues with GOOGLE_CLOUD_PROJECT returning the project number
PROJECT_ID = "qwiklabs-gcp-03-c0fc118b7249"

def get_firestore_client() -> firestore.Client:
    return firestore.Client(project=PROJECT_ID)

def _get_profile_internal(user_id: str) -> Optional[Dict]:
    """Internal helper to retrieve the raw Nightscout profile with unmasked token."""
    db = get_firestore_client()
    doc_ref = db.collection("nightscout_profiles").document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None

def get_nightscout_profile(user_id: str) -> Optional[Dict]:
    """
    Fetches the Nightscout profile (URL, target ranges, preferences) for a given user from Firestore.
    The access token is strictly masked to protect user privacy.

    Args:
        user_id: The ID of the user to look up.

    Returns:
        A dictionary containing the profile data with the token masked, or None if the user is not found.
    """
    raw_profile = _get_profile_internal(user_id)
    if not raw_profile:
        return None
    profile = dict(raw_profile)
    if "access_token" in profile and profile["access_token"]:
        profile["access_token"] = "[MASKED - CONFIGURED]"
    return profile

def update_nightscout_profile(user_id: str, updates: Dict) -> str:
    """
    Updates specific fields in a user's Nightscout profile in Firestore.

    Args:
        user_id: The ID of the user to update.
        updates: A dictionary of key-value pairs to update in the profile.

    Returns:
        A success message.
    """
    db = get_firestore_client()
    doc_ref = db.collection("nightscout_profiles").document(user_id)
    doc_ref.set(updates, merge=True)
    return f"Successfully updated profile for {user_id}."

def fetch_current_glucose(user_id: str) -> str:
    """
    Fetches the current sensor glucose (SG) reading from the user's Nightscout instance.

    Args:
        user_id: The ID of the user.

    Returns:
        A string summarizing the current glucose reading, trend, and timestamp, or an error message.
    """
    profile = _get_profile_internal(user_id)
    if not profile:
        return f"Error: No Nightscout profile found for user {user_id}. Please ask the user to provide their Nightscout URL."

    url = profile.get("nightscout_url", "").rstrip("/")
    token = profile.get("access_token", "")
    
    if not url:
        return "Error: Nightscout URL is missing from the user's profile."

    api_url = f"{url}/api/v1/entries.json?count=1"
    if token:
        api_url += f"&token={token}"

    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            return "No recent glucose entries found in Nightscout."
            
        entry = data[0]
        sgv = entry.get("sgv", "Unknown")
        direction = entry.get("direction", "Unknown trend")
        date_str = entry.get("dateString", "Unknown time")
        
        return f"Current Glucose: {sgv} mg/dL, Trend: {direction}, Last updated: {date_str}"
        
    except requests.RequestException:
        return "Failed to fetch glucose data from Nightscout. Please check connection and URL."

def fetch_glucose_trends(user_id: str, count: int = 24) -> str:
    """
    Fetches recent historical sensor glucose readings from Nightscout to analyze trends, trajectory,
    variability, average glucose, min/max range, and time-in-range percentage.

    Args:
        user_id: The ID of the user.
        count: The number of sensor readings to retrieve (default: 24, corresponding to ~2 hours).

    Returns:
        A structured statistical summary of glucose readings, trends, min/max, time-in-range,
        and chronological recent timeline.
    """
    profile = _get_profile_internal(user_id)
    if not profile:
        return f"Error: No Nightscout profile found for user {user_id}. Please ask the user to provide their Nightscout URL."

    url = profile.get("nightscout_url", "").rstrip("/")
    token = profile.get("access_token", "")

    if not url:
        return "Error: Nightscout URL is missing from the user's profile."

    api_url = f"{url}/api/v1/entries.json?count={count}"
    if token:
        api_url += f"&token={token}"

    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data:
            return "No glucose records found in Nightscout."

        target_low = float(profile.get("target_low", 70))
        target_high = float(profile.get("target_high", 180))

        valid_entries = []
        for e in data:
            sgv = e.get("sgv")
            if sgv is not None and isinstance(sgv, (int, float)):
                valid_entries.append(e)

        if not valid_entries:
            return "No valid numeric glucose entries found in the retrieved Nightscout window."

        latest = valid_entries[0]
        latest_sgv = latest.get("sgv")
        latest_dir = latest.get("direction", "Flat")
        latest_time = latest.get("dateString", "")
        formatted_latest_time = latest_time[11:16] + " UTC" if len(latest_time) >= 16 else latest_time

        all_sgvs = [e["sgv"] for e in valid_entries]
        avg_sgv = round(sum(all_sgvs) / len(all_sgvs))
        min_sgv = min(all_sgvs)
        max_sgv = max(all_sgvs)

        in_range_count = sum(1 for s in all_sgvs if target_low <= s <= target_high)
        tir_pct = round((in_range_count / len(all_sgvs)) * 100)
        above_range_count = sum(1 for s in all_sgvs if s > target_high)
        above_pct = round((above_range_count / len(all_sgvs)) * 100)
        below_range_count = sum(1 for s in all_sgvs if s < target_low)
        below_pct = round((below_range_count / len(all_sgvs)) * 100)

        timeline = []
        for e in valid_entries[:6]:
            t_str = e.get("dateString", "")
            t_fmt = t_str[11:16] + " UTC" if len(t_str) >= 16 else t_str
            d = e.get("direction", "Flat")
            arrow = {
                "DoubleUp": "⇈",
                "SingleUp": "↑",
                "FortyFiveUp": "↗",
                "Flat": "→",
                "FortyFiveDown": "↘",
                "SingleDown": "↓",
                "DoubleDown": "⇊"
            }.get(d, "→")
            val = e.get("sgv")
            timeline.append(f"{t_fmt}: {val} mg/dL ({arrow} {d})")

        timeline_str = " | ".join(timeline)

        delta_str = ""
        if len(valid_entries) >= 2:
            prev_sgv = valid_entries[1].get("sgv")
            diff = latest_sgv - prev_sgv
            sign = "+" if diff > 0 else ""
            delta_str = f", 5-min change: {sign}{diff} mg/dL"

        return (
            f"Glucose Trend Analysis ({len(valid_entries)} readings, ~{round(len(valid_entries)*5/60, 1)} hrs):\n"
            f"- Current Glucose: {latest_sgv} mg/dL ({latest_dir}{delta_str}) at {formatted_latest_time}\n"
            f"- Statistics: Average: {avg_sgv} mg/dL, Min: {min_sgv} mg/dL, Max: {max_sgv} mg/dL\n"
            f"- Target Range: {int(target_low)}-{int(target_high)} mg/dL\n"
            f"- Time In Range: {tir_pct}% in range ({above_pct}% high, {below_pct}% low)\n"
            f"- Recent Timeline: {timeline_str}"
        )
    except requests.RequestException:
        return "Failed to fetch glucose trends from Nightscout. Please check connection."

def fetch_recent_treatments(user_id: str, count: int = 50) -> str:
    """
    Fetches recent treatments (bolus insulin deliveries, temporary basal rates, and carb intakes)
    from the user's Nightscout instance to analyze insulin trends and history.

    Args:
        user_id: The ID of the user.
        count: The number of recent treatment records to retrieve (default: 50).

    Returns:
        A summary of recent boluses, basals, and carbs, or an error message.
    """
    profile = _get_profile_internal(user_id)
    if not profile:
        return f"Error: No Nightscout profile found for user {user_id}. Please ask the user to provide their Nightscout URL."

    url = profile.get("nightscout_url", "").rstrip("/")
    token = profile.get("access_token", "")
    
    if not url:
        return "Error: Nightscout URL is missing from the user's profile."

    api_url = f"{url}/api/v1/treatments.json?count={count}"
    if token:
        api_url += f"&token={token}"

    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            return "No recent treatments found in Nightscout."

        boluses = []
        temp_basals = []
        carbs_list = []
        total_bolus_units = 0.0

        for entry in data:
            event = entry.get("eventType", "Treatment")
            ts = entry.get("created_at") or entry.get("timestamp") or "Unknown time"
            ins = entry.get("insulin")
            carbs = entry.get("carbs")
            notes = entry.get("notes") or entry.get("reason") or ""
            rate = entry.get("rate") if entry.get("rate") is not None else entry.get("absolute")

            if ins is not None:
                try:
                    ins_float = float(ins)
                    if ins_float > 0:
                        total_bolus_units += ins_float
                        boluses.append(f"- {ts}: {event} of {ins_float} U ({notes})")
                except (ValueError, TypeError):
                    pass

            if carbs is not None:
                try:
                    carbs_float = float(carbs)
                    if carbs_float > 0:
                        carbs_list.append(f"- {ts}: {carbs_float}g carbs ({notes})")
                except (ValueError, TypeError):
                    pass

            if "basal" in event.lower() or rate is not None:
                dur = entry.get("duration", "")
                temp_basals.append(f"- {ts}: Basal rate {rate} U/hr (duration: {dur} min)")

        summary = [f"Retrieved {len(data)} recent treatment events from Nightscout."]
        if boluses:
            summary.append(
                f"\nRecent Boluses / Insulin Deliveries ({len(boluses)} events, total {round(total_bolus_units, 2)} U):\n"
                + "\n".join(boluses[:8])
            )
        else:
            summary.append("\nNo recent bolus deliveries found.")

        if temp_basals:
            summary.append(f"\nRecent Basal Changes ({len(temp_basals)} events):\n" + "\n".join(temp_basals[:5]))

        if carbs_list:
            summary.append(f"\nRecent Carbs ({len(carbs_list)} events):\n" + "\n".join(carbs_list[:5]))

        return "\n".join(summary)

    except requests.RequestException:
        return "Failed to fetch treatments from Nightscout. Please check connection and URL."
