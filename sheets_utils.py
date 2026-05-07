"""
Google Sheets Backend Utilities
Handles saving and loading annotations from Google Sheets via Apps Script

Pattern based on: https://github.com/Ines-Abdelaziz/feedback-bluesky
"""

import requests
import time
import json
from typing import Dict, List, Tuple, Optional
import streamlit as st


def get_retry_with_backoff(
    url: str,
    method: str = "GET",
    data: Optional[Dict] = None,
    max_retries: int = 3,
    initial_backoff: float = 2.0,
) -> Tuple[bool, Optional[Dict]]:
    """
    Make HTTP request with exponential backoff retry logic.
    
    Args:
        url: Endpoint URL
        method: HTTP method (GET, POST)
        data: JSON payload for POST requests
        max_retries: Number of retry attempts
        initial_backoff: Initial backoff time in seconds
    
    Returns:
        (success: bool, response_json: dict | None)
    """
    backoff = initial_backoff
    
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                response = requests.post(
                    url,
                    json=data,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )
            else:  # GET
                response = requests.get(url, timeout=30)
            
            response.raise_for_status()
            return True, response.json()
        
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                # Sleep before retry
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff
            else:
                # Last attempt failed
                st.warning(f"⚠️ Save failed after {max_retries} attempts: {str(e)}")
                return False, None
    
    return False, None


def append_to_sheet(
    user_name: str,
    cluster_cid: str,
    annotation_dict: Dict,
    max_retries: int = 3,
) -> Tuple[bool, str]:
    """
    Save a single annotation to Google Sheets via Apps Script.
    
    Args:
        user_name: Name of the annotator
        cluster_cid: Unique cluster identifier (e.g., "nudity_cluster_5")
        annotation_dict: Annotation data {
            "appropriateness_rating": int,
            "follow_up_answers": dict,
            "suggested_name": str,
            "notes": str
        }
        max_retries: Number of retry attempts
    
    Returns:
        (success: bool, message: str)
    """
    # Get endpoint from secrets
    endpoint = st.secrets.get("GOOGLE_APPS_SCRIPT_URL")
    if not endpoint:
        return False, "❌ GOOGLE_APPS_SCRIPT_URL not configured in secrets"
    
    # Prepare payload
    payload = {
        "user_name": user_name,
        "cluster_cid": cluster_cid,
        "appropriateness_rating": annotation_dict.get("appropriateness_rating"),
        "follow_up_answers": json.dumps(annotation_dict.get("follow_up_answers", {})),
        "suggested_name": annotation_dict.get("suggested_name", ""),
        "notes": annotation_dict.get("notes", ""),
        "timestamp": annotation_dict.get("timestamp", ""),
    }
    
    success, response = get_retry_with_backoff(
        endpoint,
        method="POST",
        data=payload,
        max_retries=max_retries,
    )
    
    if success:
        return True, "✅ Saved"
    else:
        return False, "❌ Save failed (retried multiple times)"


def fetch_saved_progress(user_name: str) -> Dict[str, Dict]:
    """
    Fetch all saved annotations for a user from Google Sheets via Apps Script.
    Used to support resume functionality.
    
    Args:
        user_name: Name of the annotator
    
    Returns:
        Dictionary of {cluster_cid: annotation_dict}
        Returns empty dict if no data found or endpoint not configured
    """
    # Get read endpoint from secrets
    read_endpoint = st.secrets.get("GOOGLE_SHEET_READ_URL")
    if not read_endpoint:
        # Fallback: try to use main endpoint with query parameter
        endpoint = st.secrets.get("GOOGLE_APPS_SCRIPT_URL")
        if not endpoint:
            return {}
        read_endpoint = endpoint
    
    try:
        success, response = get_retry_with_backoff(
            read_endpoint,
            method="GET",
            max_retries=2,
        )
        
        if not success or not response:
            return {}
        
        # Parse response - expect: {"rows": [{"cluster_cid": "...", "user_name": "...", ...}, ...]}
        rows = response.get("rows", [])
        
        # Filter rows for this user and reconstruct annotation dict
        user_annotations = {}
        for row in rows:
            if row.get("user_name") == user_name:
                cluster_cid = row.get("cluster_cid")
                if cluster_cid:
                    try:
                        follow_up = json.loads(row.get("follow_up_answers", "{}"))
                    except:
                        follow_up = {}
                    
                    user_annotations[cluster_cid] = {
                        "appropriateness_rating": int(row.get("appropriateness_rating", 0)) or None,
                        "follow_up_answers": follow_up,
                        "suggested_name": row.get("suggested_name", ""),
                        "notes": row.get("notes", ""),
                    }
        
        return user_annotations
    
    except Exception as e:
        st.warning(f"⚠️ Could not fetch saved progress: {str(e)}")
        return {}


def get_user_annotation_count(user_name: str) -> int:
    """
    Get count of saved annotations for a user (for resume message).
    
    Args:
        user_name: Name of the annotator
    
    Returns:
        Count of saved annotations; 0 if error or no data
    """
    annotations = fetch_saved_progress(user_name)
    return len(annotations)
