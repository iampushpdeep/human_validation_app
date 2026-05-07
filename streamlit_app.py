import streamlit as st
import json
import jsonlines
import numpy as np
import os
import shutil
import requests
import zipfile
import io
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageFilter

# Import Google Sheets utilities
from sheets_utils import append_to_sheet, fetch_saved_progress, get_user_annotation_count
import time

# Cached blur function for performance
@st.cache_data
def load_image(image_path_str):
    """Cache and load images to avoid repeated disk I/O."""
    try:
        return Image.open(image_path_str)
    except:
        return None

@st.cache_data
def blur_image(image_path_str):
    """Cache blurred images to avoid recomputing on every render."""
    try:
        img = Image.open(image_path_str)
        return img.filter(ImageFilter.GaussianBlur(radius=20))
    except:
        return None

# Optional imports
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# Page config
st.set_page_config(page_title="Cluster Label Validator", layout="wide", initial_sidebar_state="expanded")

# ============================================================================
# SESSION STATE PERSISTENCE
# ============================================================================

SESSION_DIR = Path(".session_data")
SESSION_DIR.mkdir(exist_ok=True)

def get_session_file():
    """Get the session file path"""
    return SESSION_DIR / "app_session.json"

def load_session_state():
    """Load session state from disk"""
    session_file = get_session_file()
    if session_file.exists():
        try:
            with open(session_file, "r") as f:
                data = json.load(f)
            return data
        except Exception as e:
            pass
    return {}

def save_session_state():
    """Save current session state to disk"""
    try:
        session_data = {
            "user_name": st.session_state.user_name,
            "current_cluster_idx": st.session_state.current_cluster_idx,
            "annotations": st.session_state.annotations,
            "last_saved": datetime.now().isoformat()
        }
        with open(get_session_file(), "w") as f:
            json.dump(session_data, f, indent=2)
        st.session_state.last_saved = datetime.now().isoformat()
        return True
    except Exception as e:
        return False

# Load session state on startup
session_data = load_session_state()

# Initialize session state variables
if "annotations" not in st.session_state:
    st.session_state.annotations = session_data.get("annotations", {})
if "current_cluster_idx" not in st.session_state:
    st.session_state.current_cluster_idx = session_data.get("current_cluster_idx", 0)
if "clusters" not in st.session_state:
    st.session_state.clusters = []
if "unblurred_images" not in st.session_state:
    # Always start with empty set - blur state should not persist across sessions
    # This ensures each user session has a fresh blur/unblur state
    st.session_state.unblurred_images = set()
if "user_name" not in st.session_state:
    # IMPORTANT: Never auto-restore user_name from session file
    # Always start at login page for security/privacy
    st.session_state.user_name = ""
if "app_page" not in st.session_state:
    # Always start at login page, regardless of what's in session file
    st.session_state.app_page = "login"
if "last_saved" not in st.session_state:
    st.session_state.last_saved = session_data.get("last_saved", "Never")
if "auto_save_enabled" not in st.session_state:
    st.session_state.auto_save_enabled = True
if "show_confirm_clear" not in st.session_state:
    st.session_state.show_confirm_clear = False
if "export_data" not in st.session_state:
    st.session_state.export_data = None
if "export_count" not in st.session_state:
    st.session_state.export_count = 0
if "clusters_loaded_attempted" not in st.session_state:
    st.session_state.clusters_loaded_attempted = False
if "rating_clear_counter" not in st.session_state:
    st.session_state.rating_clear_counter = {}
if "_do_autosave" not in st.session_state:
    st.session_state._do_autosave = False
if "saved_annotation_ids" not in st.session_state:
    st.session_state.saved_annotation_ids = set()

# ============================================================================
# SYNC WITH GOOGLE SHEETS (runs on every app reload)
# ============================================================================

def sync_with_sheets():
    """
    Sync with Google Sheets on first app load for logged-in user.
    Only runs once per user session to avoid repeated HTTP calls.
    """
    # Only sync once per user session to avoid repeated HTTP calls
    if "_synced_with_sheets" in st.session_state:
        return
    
    if st.session_state.user_name and st.session_state.user_name.lower() != "admin":
        try:
            # Fetch saved progress from Google Sheets
            saved_annotations = fetch_saved_progress(st.session_state.user_name)
            
            if saved_annotations:
                # Update local state with saved annotations
                # Only add missing entries to preserve any local changes
                for cid, annotation in saved_annotations.items():
                    if cid not in st.session_state.annotations or st.session_state.annotations[cid].get("appropriateness_rating") is None:
                        st.session_state.annotations[cid] = annotation
                
                st.session_state.saved_annotation_ids = set(saved_annotations.keys())
                
                # Initialize _last_saved_annotations with the loaded data so autosave detects changes correctly
                if "_last_saved_annotations" not in st.session_state:
                    st.session_state._last_saved_annotations = {}
                
                for cid, annotation in saved_annotations.items():
                    st.session_state._last_saved_annotations[cid] = annotation.copy()
        except Exception as e:
            # Log error for debugging
            import traceback
            pass
    
    # Mark as synced so we don't repeat this on every rerun
    st.session_state._synced_with_sheets = True

# Run sync on app startup if user is logged in
sync_with_sheets()

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_available_labels():
    """Get all available label categories (subdirectories in human_validation_samples)"""
    base_path = Path("human_validation_samples")
    if not base_path.exists():
        return []
    labels = [d.name for d in base_path.iterdir() if d.is_dir()]
    return sorted(labels)

def is_cluster_evaluated(annotations, cluster_cid):
    """Check if a cluster has been genuinely evaluated (not just pre-selected defaults)"""
    if cluster_cid not in annotations:
        return False
    ann = annotations[cluster_cid]
    # Only count as evaluated if rating is explicitly set to a value
    return ann.get("appropriateness_rating") is not None

def get_next_unannotated_cluster(current_idx, clusters, annotations):
    """Find the next cluster that hasn't been annotated yet."""
    for idx in range(current_idx, len(clusters)):
        cid = clusters[idx].get("cid", f"cluster_{idx}")
        if not is_cluster_evaluated(annotations, cid):
            return idx
    # If all from current_idx onwards are done, wrap to start
    for idx in range(0, current_idx):
        cid = clusters[idx].get("cid", f"cluster_{idx}")
        if not is_cluster_evaluated(annotations, cid):
            return idx
    # All done
    return current_idx

def get_prev_unannotated_cluster(current_idx, clusters, annotations):
    """Find the previous cluster that hasn't been annotated yet."""
    for idx in range(current_idx, -1, -1):
        cid = clusters[idx].get("cid", f"cluster_{idx}")
        if not is_cluster_evaluated(annotations, cid):
            return idx
    # If all before current_idx are done, wrap to end
    for idx in range(len(clusters) - 1, current_idx, -1):
        cid = clusters[idx].get("cid", f"cluster_{idx}")
        if not is_cluster_evaluated(annotations, cid):
            return idx
    # All done
    return current_idx

def sanitize_name(name):
    """Convert name to safe filename"""
    return name.lower().replace(" ", "_")

def load_user_annotations(user_name):
    """Load user's annotations from consolidated file (all labels) - FALLBACK only, Google Sheets is primary"""
    filepath = Path("human_validation_samples") / f"annotations_{sanitize_name(user_name)}.json"
    
    if not filepath.exists():
        return {}
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            if "annotations" in data:
                return data["annotations"]
            return data
        return {}
    except Exception as e:
        return {}

# Note: save_user_annotations removed - now using Google Sheets only
# Keeping load_user_annotations as fallback for offline/legacy support

def download_and_extract_nextcloud(zip_url, extract_path="human_validation_samples"):
    """Download zipped data from Nextcloud and extract it"""
    extract_path = Path(extract_path)
    
    # Check if data already exists locally
    if extract_path.exists() and list(extract_path.glob("*/metadata.json")):
        st.info("✅ Cluster data already exists locally, skipping download.")
        return True
    
    try:
        # Ensure the URL includes /download to get the actual file
        if not zip_url.endswith("/download"):
            zip_url = zip_url.rstrip("/") + "/download"
        
        with st.spinner("📥 Downloading cluster data from Nextcloud..."):
            response = requests.get(zip_url, timeout=60)
            response.raise_for_status()
            
            # Extract zip file
            extract_path.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                zip_ref.extractall(extract_path)
        
        # Handle nested folder structure (if zip had a single parent folder)
        items = list(extract_path.iterdir())
        non_annotation_items = [item for item in items if not item.name.startswith("annotations_")]
        
        if len(non_annotation_items) == 1 and non_annotation_items[0].is_dir():
            nested_dir = non_annotation_items[0]
            nested_items = list(nested_dir.iterdir())
            
            # If the nested folder contains label directories, move them up
            if nested_items and any((nested_dir / item.name / "metadata.json").exists() for item in nested_items if (nested_dir / item.name).is_dir()):
                for item in nested_items:
                    src = nested_dir / item.name
                    dst = extract_path / item.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    src.rename(dst)
                nested_dir.rmdir()
        
        st.success("✅ Data downloaded and extracted successfully!")
        return True
    except Exception as e:
        st.error(f"❌ Error downloading data: {str(e)}")
        return False

def load_clusters_from_validation_data():
    """Load clusters from all label directories in human_validation_samples"""
    base_path = Path("human_validation_samples")
    
    if not base_path.exists():
        return None
    
    clusters_list = []
    label_dirs = [item for item in base_path.iterdir() if item.is_dir() and not item.name.startswith(".") and not item.name.startswith("annotations_")]
    
    # Iterate through all label directories
    for label_dir in sorted(label_dirs):
        label_name = label_dir.name
        metadata_path = label_dir / "metadata.json"
        
        if not metadata_path.exists():
            continue
        
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        except Exception as e:
            continue
        
        for cluster_str_id, cluster_info in sorted(metadata.get("clusters", {}).items()):
            try:
                cluster_id = int(cluster_str_id)
                cluster_dir = label_dir / f"cluster_{cluster_id}"
                samples_file = cluster_dir / "samples.jsonl"
                
                if not samples_file.exists():
                    continue
                
                examples = []
                with open(samples_file, "r") as f:
                    for line in f:
                        if line.strip():
                            examples.append(json.loads(line))
                
                # Create unique cluster ID that includes label
                unique_cid = f"{label_name}_cluster_{cluster_id}"
                
                cluster_obj = {
                    "id": cluster_id,
                    "cid": unique_cid,
                    "cluster_name": cluster_info.get("name", f"Cluster {cluster_id}"),
                    "label_category": label_name,
                    "summary": cluster_info.get("summary", ""),
                    "total_samples": cluster_info.get("num_samples", len(examples)),
                    "total_in_cluster": cluster_info.get("total_in_cluster", 0),
                    "examples": examples,
                    "sample_fraction": cluster_info.get("sample_fraction", 0.0),
                }
                
                clusters_list.append(cluster_obj)
            except Exception as e:
                continue
    
    return clusters_list if clusters_list else None

@st.cache_data
def get_video_frame(video_path: Path):
    """Extract first frame from video (unblurred) - cached for instant reveal"""
    if not HAS_CV2:
        return None
    
    try:
        cap = cv2.VideoCapture(str(video_path))
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame)
        return img
    except Exception as e:
        return None

@st.cache_data
def get_blurred_video_frame(video_path: Path, blur_radius: int = 20):
    """Extract first frame from video and blur it"""
    if not HAS_CV2:
        return None
    
    try:
        cap = cv2.VideoCapture(str(video_path))
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame)
        blurred_img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        return blurred_img
    except Exception as e:
        return None

def display_media(cluster_id, example_num, images, videos, label_category):
    """Display images and videos with blur/reveal toggles"""
    # Labels where blur/reveal should be hidden
    no_blur_labels = {"rude", "intolerant", "threat", "sexual-figurative", "porn", "nudity", "sexual"}
    show_blur_controls = label_category not in no_blur_labels
    
    col_left, col_media, col_right = st.columns([1, 2, 1])
    
    with col_media:
        if images:
            cols = st.columns(min(len(images), 2))
            for img_idx, img_item in enumerate(images):
                if isinstance(img_item, dict):
                    img_path = img_item.get("file", "")
                else:
                    img_path = img_item
                
                image_key = f"{cluster_id}_{example_num}_img_{img_idx}"
                image_path = Path(f"human_validation_samples/{label_category}/cluster_{cluster_id}") / img_path
                
                with cols[img_idx % len(cols)]:
                    if image_path.exists():
                        try:
                            if show_blur_controls:
                                # Show blur/reveal buttons for allowed labels
                                if image_key in st.session_state.unblurred_images:
                                    img = load_image(str(image_path))
                                    if img:
                                        st.image(img, use_container_width=True)
                                    if st.button("🔒 Blur", key=f"blur_{image_key}", use_container_width=True):
                                        st.session_state.unblurred_images.discard(image_key)
                                        st.rerun()
                                else:
                                    blurred_img = blur_image(str(image_path))
                                    if blurred_img:
                                        st.image(blurred_img, use_container_width=True)
                                    if st.button("👁️ Reveal", key=f"unblur_{image_key}", use_container_width=True):
                                        st.session_state.unblurred_images.add(image_key)
                                        st.rerun()
                            else:
                                # For protected labels, show image without blur controls
                                img = load_image(str(image_path))
                                if img:
                                    st.image(img, use_container_width=True)
                        except Exception as e:
                            st.caption(f"Could not load image")
                    else:
                        st.caption(f"Image not found")
        
        if videos:
            if len(videos) == 1:
                st.markdown("**Video:**")
                if isinstance(videos[0], dict):
                    video_path_str = videos[0].get("file", videos[0].get("video", ""))
                else:
                    video_path_str = videos[0]
                
                video_path = Path(f"human_validation_samples/{label_category}/cluster_{cluster_id}") / video_path_str
                video_key = f"{cluster_id}_{example_num}_vid_0"
                
                if video_path.exists():
                    try:
                        with open(video_path, 'rb') as f:
                            video_bytes = f.read()
                            if show_blur_controls:
                                # Show blur/reveal buttons for allowed labels
                                if video_key in st.session_state.unblurred_images:
                                    st.video(video_bytes)
                                    if st.button("🔒 Blur", key=f"blur_vid_{video_key}", use_container_width=True):
                                        st.session_state.unblurred_images.discard(video_key)
                                        st.rerun()
                                else:
                                    blurred_frame = get_blurred_video_frame(video_path)
                                    if blurred_frame:
                                        st.image(blurred_frame, use_container_width=True)
                                    else:
                                        st.info("🎬 Video (Blurred)")
                                    if st.button("👁️ Reveal Video", key=f"reveal_vid_{video_key}", use_container_width=True):
                                        st.session_state.unblurred_images.add(video_key)
                                        st.rerun()
                            else:
                                # For protected labels, show video without blur controls
                                st.video(video_bytes)
                    except Exception as e:
                        pass
                else:
                    st.caption(f"Video not found")
            else:
                st.markdown(f"**Videos ({len(videos)}):**")
                cols = st.columns(min(len(videos), 2))
                for vid_idx, vid_item in enumerate(videos):
                    if isinstance(vid_item, dict):
                        video_path_str = vid_item.get("file", vid_item.get("video", ""))
                    else:
                        video_path_str = vid_item
                    
                    video_path = Path(f"human_validation_samples/{label_category}/cluster_{cluster_id}") / video_path_str
                    video_key = f"{cluster_id}_{example_num}_vid_{vid_idx}"
                    
                    with cols[vid_idx % len(cols)]:
                        if video_path.exists():
                            try:
                                with open(video_path, 'rb') as f:
                                    video_bytes = f.read()
                                    if show_blur_controls:
                                        # Show blur/reveal buttons for allowed labels
                                        if video_key in st.session_state.unblurred_images:
                                            st.video(video_bytes)
                                            if st.button("🔒", key=f"blur_vid_{video_key}", use_container_width=True):
                                                st.session_state.unblurred_images.discard(video_key)
                                                st.rerun()
                                        else:
                                            blurred_frame = get_blurred_video_frame(video_path)
                                            if blurred_frame:
                                                st.image(blurred_frame, use_container_width=True)
                                            else:
                                                st.info("🎬 Blurred")
                                            if st.button("👁️", key=f"reveal_vid_{video_key}", use_container_width=True):
                                                st.session_state.unblurred_images.add(video_key)
                                                st.rerun()
                                    else:
                                        # For protected labels, show video without blur controls
                                        st.video(video_bytes)
                            except Exception as e:
                                pass
                        else:
                            st.caption(f"Not found")

# ============================================================================
# PAGE FUNCTIONS
# ============================================================================

def show_login_page():
    """Show user login/registration page"""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<h1 style='text-align: center;'>🏷️ Cluster Label Validator</h1>", unsafe_allow_html=True)
        st.divider()
        st.markdown("<h3 style='text-align: center;'>Welcome</h3>", unsafe_allow_html=True)
        
        user_name = st.text_input(
            "Enter your name or identifier:",
            placeholder="e.g. alice, bob, annotator_1",
            key="login_user_name_input"
        )
        
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("✅ Continue", use_container_width=True):
                if user_name and len(user_name.strip()) > 0:
                    st.session_state.user_name = user_name.strip()
                    
                    # Check if this is admin user
                    if st.session_state.user_name.lower() == "admin":
                        st.session_state.annotations = {}  # Admin should not have annotations
                        st.session_state.app_page = "admin"
                    else:
                        # Try to load saved progress from Google Sheets first
                        saved_annotations = fetch_saved_progress(st.session_state.user_name)
                        
                        if saved_annotations:
                            # Resume: Load saved annotations and show message
                            st.session_state.annotations = saved_annotations
                            st.session_state.saved_annotation_ids = set(saved_annotations.keys())
                            # Find first unannotated cluster to resume from
                            clusters = st.session_state.clusters or []
                            if clusters:
                                for idx, cluster in enumerate(clusters):
                                    cid = cluster.get("cid", f"cluster_{idx}")
                                    if cid not in saved_annotations:
                                        st.session_state.current_cluster_idx = idx
                                        break
                                else:
                                    # All clusters are annotated
                                    st.session_state.current_cluster_idx = 0
                            
                            # Show resume message
                            resume_count = len(saved_annotations)
                            st.success(f"✅ Resumed — {resume_count} annotations already saved. Continuing from cluster {st.session_state.current_cluster_idx + 1}.")
                        else:
                            # Fresh start: Load from local file as fallback (legacy support)
                            st.session_state.annotations = load_user_annotations(st.session_state.user_name)
                            st.session_state.current_cluster_idx = 0
                        
                        st.session_state.app_page = "dashboard"
                    
                    save_session_state()
                    st.rerun()
                else:
                    st.error("❌ Please enter a valid name")
        
        with col_b:
            st.markdown("")  # Spacer
        
        st.divider()
        st.markdown("""
        **How it works:**
        1. Enter your name to get started
        2. Review and evaluate cluster labels
        3. Your progress is automatically saved
        4. Return anytime to continue where you left off
        """)

def show_dashboard_page():
    """Show dashboard with progress and options"""
    # Ensure annotations are loaded for current user
    if st.session_state.user_name:
        if not st.session_state.annotations:
            # Try Google Sheets first, then fallback to local
            saved_annotations = fetch_saved_progress(st.session_state.user_name)
            st.session_state.annotations = saved_annotations if saved_annotations else load_user_annotations(st.session_state.user_name)
            st.session_state.saved_annotation_ids = set(saved_annotations.keys()) if saved_annotations else set()
    
    clusters = st.session_state.clusters
    annotations = st.session_state.annotations
    
    col1, col2, col3 = st.columns([1, 3, 1])
    
    with col2:
        st.markdown(f"<h2 style='text-align: center;'>👋 Welcome, {st.session_state.user_name}!</h2>", unsafe_allow_html=True)
    
    st.divider()
    
    # Progress summary
    col1, col2, col3 = st.columns(3)
    completed = sum(1 for c in clusters if is_cluster_evaluated(annotations, c.get("cid", f"cluster_{clusters.index(c)}")))
    
    with col1:
        st.metric("Total Clusters", len(clusters))
    with col2:
        st.metric("Completed", completed)
    with col3:
        progress_pct = (completed / len(clusters) * 100) if clusters else 0
        st.metric("Progress", f"{progress_pct:.1f}%")
    
    st.divider()
    
    # Progress bar
    st.progress(completed / len(clusters) if clusters else 0)
    
    st.divider()
    
    # Quick actions
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("▶️ Start Evaluation", use_container_width=True, key="start_eval"):
            st.session_state.app_page = "evaluation"
            st.rerun()
    
    with col2:
        if st.button("👤 Logout", use_container_width=True, key="logout_btn"):
            # Clear session data for next user
            st.session_state.user_name = ""
            st.session_state.annotations = {}
            st.session_state.current_cluster_idx = 0
            st.session_state.app_page = "login"
            st.session_state.saved_annotation_ids = set()
            # Clear the session file
            session_file = get_session_file()
            if session_file.exists():
                session_file.unlink()
            st.rerun()
    
    st.divider()
    
    # Session info with Google Sheets status
    st.markdown("**Session Information:**")
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"👤 User: {st.session_state.user_name}")
    with col2:
        saved_count = len(st.session_state.saved_annotation_ids)
        if saved_count > 0:
            st.caption(f"☁️ Saved to Google Sheets: {saved_count} annotations")
        elif st.session_state.last_saved != "Never":
            st.caption(f"⏱️ Last saved: {st.session_state.last_saved}")
        else:
            st.caption("Not saved yet")
    


# Admin page removed - use Google Sheets directly for data management

# Summary page removed - dashboard shows progress directly

def show_evaluation_page():
    """Show cluster evaluation page"""
    clusters = st.session_state.clusters
    
    if not clusters:
        st.error("❌ No clusters found. Check human_validation_samples/ for label categories")
        st.stop()
    
    if not st.session_state.annotations:
        # Try Google Sheets first, then fallback to local
        saved_annotations = fetch_saved_progress(st.session_state.user_name)
        st.session_state.annotations = saved_annotations if saved_annotations else load_user_annotations(st.session_state.user_name)
        st.session_state.saved_annotation_ids = set(saved_annotations.keys()) if saved_annotations else set()
    
    # Sidebar navigation
    with st.sidebar:
        st.markdown(f"## 👤 {st.session_state.user_name}")
        st.divider()
        
        # Navigation
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🏠 Dashboard", use_container_width=True):
                st.session_state.app_page = "dashboard"
                save_session_state()
                st.rerun()
        with col2:
            if st.button("📊 Summary", use_container_width=True):
                st.session_state.app_page = "summary"
                st.rerun()
        
        st.divider()
        
        # Progress
        completed = sum(1 for c in clusters if is_cluster_evaluated(st.session_state.annotations, c.get("cid", f"cluster_{clusters.index(c)}")))
        st.markdown(f"**Progress:** {completed}/{len(clusters)}")
        st.progress(completed / len(clusters))
        
        st.divider()
        
        # Cluster navigation list
        st.markdown("### Clusters")
        for idx, c in enumerate(clusters):
            cid = c.get("cid", f"cluster_{idx}")
            is_completed = "✅" if is_cluster_evaluated(st.session_state.annotations, cid) else "⭕"
            is_current = "→" if st.session_state.current_cluster_idx == idx else " "
            
            if st.button(f"{is_current} [{idx+1}] {is_completed} {c.get('cluster_name', 'N/A')[:30]}", 
                        use_container_width=True, key=f"nav_cluster_{idx}"):
                st.session_state.current_cluster_idx = idx
                st.rerun()
        
        st.divider()
    
    # Main content
    cluster = clusters[st.session_state.current_cluster_idx]
    cluster_id = cluster.get("id", st.session_state.current_cluster_idx)
    cluster_cid = cluster.get("cid", f"cluster_{cluster_id}")
    cluster_label = cluster.get("cluster_name", "N/A")
    label_category = cluster.get("label_category", "N/A")
    
    # Navigation buttons at top with scroll to top behavior
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", use_container_width=True, key="nav_prev_top"):
            next_idx = get_prev_unannotated_cluster(st.session_state.current_cluster_idx, clusters, st.session_state.annotations)
            if next_idx != st.session_state.current_cluster_idx:
                st.session_state.current_cluster_idx = next_idx
                save_session_state()
            st.rerun()

    with col2:
        cluster_num = st.session_state.current_cluster_idx + 1
        st.markdown(f"<h3 style='text-align: center;'>Cluster {cluster_num} / {len(clusters)}</h3>", unsafe_allow_html=True)

    with col3:
        if st.button("Next ➡️", use_container_width=True, key="nav_next_top"):
            next_idx = get_next_unannotated_cluster(st.session_state.current_cluster_idx + 1, clusters, st.session_state.annotations)
            if next_idx != st.session_state.current_cluster_idx or st.session_state.current_cluster_idx < len(clusters) - 1:
                st.session_state.current_cluster_idx = next_idx
                save_session_state()
            st.rerun()
    
    st.divider()
    
    # Show cluster info prominently at top
    st.markdown(f"<h2 style='text-align: center;'>Label Category: <span style='color: #1f77b4;'>{label_category}</span> | Cluster Name: <span style='color: #ff7f0e;'>{cluster_label}</span></h2>", unsafe_allow_html=True)

    st.divider()
    
    # Show summary at top
    st.markdown("#### 📋 Cluster Summary")
    st.write(cluster.get('summary', 'No summary available'))

    st.divider()

    # Display examples in 2 columns
    st.markdown(f"#### Examples ({len(cluster.get('examples', []))} samples):")
    examples = cluster.get("examples", [])
    if examples:
        # Create 2-column layout for examples
        cols = st.columns(2)
        for i, ex in enumerate(examples, 1):
            col_idx = (i - 1) % 2
            with cols[col_idx]:
                with st.container(border=True):
                    if isinstance(ex, dict):
                        images = ex.get("images", []) or ([ex.get("image")] if ex.get("image") else [])
                        videos = ex.get("videos", []) or ([ex.get("video")] if ex.get("video") else [])
                        
                        # Display media
                        if images or videos:
                            cluster_label_cat = cluster.get("label_category", "")
                            display_media(cluster_id, i, images, videos, cluster_label_cat)
                            st.divider()
                    
                    # Display text
                    text = ex.get("text", str(ex))
                    if text:
                        st.write(f"**#{i}** {text}")
                    
                    # Display cluster probability
                    if isinstance(ex, dict) and "cluster_probability" in ex:
                        prob = ex.get("cluster_probability", 0.0)
                        bar_length = int(prob * 30)
                        bar = "█" * bar_length + "░" * (30 - bar_length)
                        st.caption(f"Confidence: {bar} {prob:.4f}")
    else:
        st.info("No examples available")

    st.divider()
    
    # Show cluster info and summary before evaluation
    st.markdown(f"#### Label Category: `{label_category}` | Cluster Name: `{cluster_label}`")
    st.markdown("#### 📋 Summary")
    st.write(cluster.get('summary', 'No summary available'))
    
    st.divider()
    
    st.markdown("### Your Evaluation")
    
    # Check if this cluster is already completed
    ann = st.session_state.annotations.get(cluster_cid, {})
    if ann.get("appropriateness_rating") is not None:
        st.success(f"✅ **Already completed!** You rated this cluster: {ann.get('appropriateness_rating')}/5")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬇️ Skip to next", use_container_width=True):
                next_idx = get_next_unannotated_cluster(st.session_state.current_cluster_idx + 1, clusters, st.session_state.annotations)
                st.session_state.current_cluster_idx = next_idx
                st.rerun()
        with col2:
            if st.button("🔄 Re-evaluate", use_container_width=True):
                st.session_state.annotations[cluster_cid] = {
                    "appropriateness_rating": None,
                    "follow_up_answers": {},
                    "suggested_name": "",
                    "notes": "",
                }
                st.rerun()
        st.divider()
    
    # Show scores reference table
    st.markdown("#### Rating Guide")
    st.markdown("""
| Score | Meaning |
|-------|---------|
| 5 | ✅ **Highly appropriate** - The name clearly and accurately represents all the content in this cluster. It's specific, unambiguous, and perfectly captures the essence of the posts. |
| 4 | 👍 **Somewhat appropriate** - The name is mostly accurate and describes the general theme well, though there might be minor issues or slight room for improvement. |
| 3 | 🤷 **Neutral** - The name is partially accurate but has noticeable gaps or ambiguities. Some posts fit well, others don't. Improvements would be beneficial. |
| 2 | 👎 **Somewhat inappropriate** - The name has significant issues. Many posts don't fit well, or the name is confusing/misleading in important ways. |
| 1 | ❌ **Not appropriate** - The name is misleading, irrelevant, or completely misrepresents the content. It fails to capture what these posts are about. |
""")

    # Initialize annotation if doesn't exist
    if cluster_cid not in st.session_state.annotations:
        st.session_state.annotations[cluster_cid] = {
            "appropriateness_rating": None,
            "follow_up_answers": {},
            "suggested_name": "",
            "notes": "",
        }

    ann = st.session_state.annotations[cluster_cid]
    
    # Only show previous evaluation if it was actually completed
    if ann["appropriateness_rating"] is None:
        # Reset form if not evaluated yet
        ann = {
            "appropriateness_rating": None,
            "follow_up_answers": {},
            "suggested_name": "",
            "notes": "",
        }
        st.session_state.annotations[cluster_cid] = ann

    # ============================================================================
    # STEP 1: Likert Scale - Is the cluster name appropriate?
    # ============================================================================
    st.markdown("### Step 1: Cluster Name Appropriateness")
    st.info("🎯 Is the cluster name appropriate for these social media posts?")

    appropriateness_options = {
        5: "✅ Highly appropriate - Name perfectly describes the content",
        4: "👍 Somewhat appropriate - Name mostly fits with minor issues",
        3: "🤷 Neutral - Name is partially accurate",
        2: "👎 Somewhat inappropriate - Significant issues with the name",
        1: "❌ Not appropriate - Name is misleading or irrelevant"
    }
    
    st.markdown("**Choose one rating:**")
    
    score = ann["appropriateness_rating"]
    
    # Initialize clear counter to force new widget key on clear
    if "rating_clear_counter" not in st.session_state:
        st.session_state.rating_clear_counter = {}
    
    if cluster_cid not in st.session_state.rating_clear_counter:
        st.session_state.rating_clear_counter[cluster_cid] = 0
    
    # Use counter in key to force widget reset on clear
    rating_key = f"rating_{cluster_cid}_{st.session_state.rating_clear_counter[cluster_cid]}"
    
    # Use radio buttons with horizontal layout for instant selection
    selected = st.radio(
        "Select rating:",
        options=[1, 2, 3, 4, 5],
        format_func=lambda x: {
            1: "⭐ Not Appropriate",
            2: "⭐⭐ Somewhat Inapp.",
            3: "⭐⭐⭐ Neutral",
            4: "⭐⭐⭐⭐ Somewhat App.",
            5: "⭐⭐⭐⭐⭐ Highly App.",
        }[x],
        index=(score - 1 if score else None),
        horizontal=True,
        key=rating_key,
        label_visibility="collapsed"
    )
    
    # Only update and trigger autosave if rating actually changed
    if selected is not None and selected != ann["appropriateness_rating"]:
        ann["appropriateness_rating"] = selected
        st.session_state._do_autosave = True  # Trigger autosave on next render
        save_session_state()

    score = ann["appropriateness_rating"]
    
    # Conditionally show success message and clear button
    if score is not None:
        st.divider()
        st.success(f"✅ You selected: {appropriateness_options[score]}")
        
        if st.button("❌ Clear Selection", use_container_width=True, key=f"clear_rating_{cluster_cid}"):
            ann["appropriateness_rating"] = None
            save_session_state()
            st.session_state.rating_clear_counter[cluster_cid] += 1
            st.rerun()
    
    # Show follow-up questions if rated 1-3
    score = ann["appropriateness_rating"]
    if score in [1, 2, 3]:
        st.divider()
        st.markdown("### Step 2: Help Us Improve")
        st.warning("📝 Please answer these questions to help us refine the label")
        st.markdown("---")
        
        # Ensure follow_up_answers has the needed keys
        if "main_issue" not in ann["follow_up_answers"]:
            ann["follow_up_answers"]["main_issue"] = None
        
        st.markdown("#### 1️⃣ What is the main issue with this name?")
        
        # Determine which option is currently selected (for display)
        issue_options = ["too_broad", "too_narrow", "misleading", "unclear", "other"]
        current_issue = ann["follow_up_answers"].get("main_issue")
        try:
            current_index = issue_options.index(current_issue) if current_issue in issue_options else None
        except ValueError:
            current_index = None
        
        selected_issue = st.radio(
            "Select the primary concern:",
            options=issue_options,
            format_func=lambda x: {
                "too_broad": "📊 Too broad - covers too many different types of content",
                "too_narrow": "🔍 Too narrow - too specific for some examples",
                "misleading": "⚠️ Misleading - doesn't accurately reflect the content",
                "unclear": "❓ Unclear - confusing or ambiguous phrasing",
                "other": "🤔 Other reason"
            }[x],
            horizontal=False,
            key=f"main_issue_{cluster_cid}_{st.session_state.rating_clear_counter.get(cluster_cid, 0)}",
            label_visibility="collapsed",
            index=current_index  # Show currently selected value
        )
        
        # Only update and trigger autosave if selection actually changed
        if selected_issue is not None and ann["follow_up_answers"].get("main_issue") != selected_issue:
            ann["follow_up_answers"]["main_issue"] = selected_issue
            st.session_state._do_autosave = True  # Trigger autosave on next rerun
        
        st.markdown("---")
        
        if ann["follow_up_answers"].get("main_issue") == "other":
            st.markdown("#### 2️⃣ What's the specific issue with this name?")
            missing_text = st.text_area(
                "Please describe the issue:",
                value=ann["follow_up_answers"].get("missing_element", ""),
                placeholder="E.g., 'Should mention cryptocurrency scams' or 'Too vague about the specific activity'...",
                height=80,
                key=f"missing_{cluster_cid}_{st.session_state.rating_clear_counter.get(cluster_cid, 0)}",
                label_visibility="collapsed"
            )
            
            # Trigger autosave if missing_element changed
            if missing_text != ann["follow_up_answers"].get("missing_element", ""):
                ann["follow_up_answers"]["missing_element"] = missing_text
                st.session_state._do_autosave = True
            else:
                ann["follow_up_answers"]["missing_element"] = missing_text
            
            st.markdown("---")
        
        st.markdown("#### 💡 Suggest a Better Name")
        st.caption("Enter your suggested name (max 90 characters)")
        
        suggested_text = st.text_input(
            "Better name for this cluster:",
            value=ann["suggested_name"],
            placeholder="Type a more appropriate name for this cluster...",
            max_chars=90,
            key=f"suggested_name_{cluster_cid}",
            label_visibility="collapsed"
        )
        
        if suggested_text:
            char_count = len(suggested_text)
            st.caption(f"Characters: {char_count}/90")
        
        # Trigger autosave if suggested name changed
        if suggested_text != ann["suggested_name"]:
            ann["suggested_name"] = suggested_text
            st.session_state._do_autosave = True
        else:
            ann["suggested_name"] = suggested_text

    # ============================================================================
    # IF HIGH SCORE (4-5): Show confirmation or light follow-up
    # ============================================================================
    elif ann["appropriateness_rating"] in [4, 5]:
        if ann["appropriateness_rating"] == 5:
            st.markdown("### ✅ Excellent!")
            st.success(f"Great! The name **'{cluster_label}'** is well-suited for this cluster.")
        else:
            st.markdown("### Step 2: Optional Refinement")
            st.markdown("Would you like to suggest a slightly better name?")
            
            st.caption("Enter your suggestion (optional, max 90 characters)")
            suggested_text = st.text_input(
                "Alternative name (optional):",
                value=ann["suggested_name"],
                placeholder="Leave empty if you're satisfied with the current name...",
                max_chars=90,
                key=f"suggested_name_{cluster_cid}_{st.session_state.rating_clear_counter.get(cluster_cid, 0)}",
                label_visibility="collapsed"
            )
            
            if suggested_text:
                char_count = len(suggested_text)
                st.caption(f"Characters: {char_count}/90")
            
            # Trigger autosave if suggested name changed
            if suggested_text != ann["suggested_name"]:
                ann["suggested_name"] = suggested_text
                st.session_state._do_autosave = True
            else:
                ann["suggested_name"] = suggested_text
        
        st.divider()
        
        st.markdown("#### 📝 Additional observations (optional)")
        notes_text = st.text_area(
            "Notes:",
            value=ann["notes"],
            placeholder="Any other feedback or observations?",
            height=80,
            key=f"notes_{cluster_cid}",
            label_visibility="collapsed"
        )
        
        # Trigger autosave if notes changed
        if notes_text != ann["notes"]:
            ann["notes"] = notes_text
            st.session_state._do_autosave = True
        else:
            ann["notes"] = notes_text

    st.divider()


    st.divider()
    completed = sum(1 for c in clusters if is_cluster_evaluated(st.session_state.annotations, c.get("cid", f"cluster_{clusters.index(c)}")))
    st.progress(completed / len(clusters) if clusters else 0)
    st.caption(f"Progress: {completed}/{len(clusters)} clusters evaluated")
    
    st.divider()
    
    # Navigation buttons at bottom
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", use_container_width=True, key="nav_prev_bottom"):
            if st.session_state.current_cluster_idx > 0:
                st.session_state.current_cluster_idx -= 1
                save_session_state()
                st.rerun()

    with col2:
        cluster_num = st.session_state.current_cluster_idx + 1
        st.markdown(f"<h3 style='text-align: center;'>Cluster {cluster_num} / {len(clusters)}</h3>", unsafe_allow_html=True)

    with col3:
        if st.button("Next ➡️", use_container_width=True, key="nav_next_bottom"):
            if st.session_state.current_cluster_idx < len(clusters) - 1:
                st.session_state.current_cluster_idx += 1
                save_session_state()
                st.rerun()

# ============================================================================
# MAIN APP ROUTER
# ============================================================================

# Load clusters (only attempt once per session)
if not st.session_state.clusters and not st.session_state.clusters_loaded_attempted:
    st.session_state.clusters_loaded_attempted = True
    
    clusters_data = load_clusters_from_validation_data()
    if clusters_data:
        st.session_state.clusters = clusters_data
    else:
        # No clusters found locally - try to download from Nextcloud
        nextcloud_url = st.secrets.get("sharecloudlink")
        if nextcloud_url:
            if download_and_extract_nextcloud(nextcloud_url):
                # Reload clusters after download
                clusters_data = load_clusters_from_validation_data()
                if clusters_data:
                    st.session_state.clusters = clusters_data

# If clusters still missing, show error
if not st.session_state.clusters and st.session_state.app_page != "login":
    st.title("🏷️ Cluster Label Validator")
    st.divider()
    st.error("❌ No cluster data available!")
    st.markdown("""
    **Problem:** Cluster validation data could not be found or downloaded.
    
    **To fix (on Streamlit Cloud):**
    1. Get your Nextcloud share URL (the folder containing all label categories)
    2. Go to your app settings → **Secrets**
    3. Add this line:
    ```
    sharecloudlink = "YOUR_NEXTCLOUD_SHARE_URL_HERE"
    ```
    4. Restart the app
    
    **To fix (locally):**
    1. Ensure the `human_validation_samples/` directory exists
    2. Run: `streamlit run streamlit_app.py`
    """)
    st.stop()

# Title
st.title("🏷️ Cluster Label Validator")

# Page routing
if st.session_state.app_page == "login":
    show_login_page()
elif st.session_state.app_page == "dashboard":
    show_dashboard_page()
elif st.session_state.app_page == "evaluation":
    show_evaluation_page()
else:
    show_login_page()

# Auto-save functionality with Google Sheets integration (but not for admin user)
if st.session_state.user_name and st.session_state.user_name.lower() != "admin" and st.session_state._do_autosave and st.session_state.annotations:
    # Throttle autosave - only save if enough time has passed
    current_time = time.time()
    last_autosave = st.session_state.get("_last_autosave_time", 0)
    
    # Only autosave every 1 second minimum to avoid excessive API calls
    if current_time - last_autosave > 1:
        # Track last saved state to detect changes
        if "_last_saved_annotations" not in st.session_state:
            st.session_state._last_saved_annotations = {}
        
        # Find annotations that need to be saved (new or changed)
        for cluster_cid, annotation in st.session_state.annotations.items():
            # Only save if rating is set (completed annotation)
            if annotation.get("appropriateness_rating") is not None:
                import copy
                
                # Check if this is a new annotation or an updated one
                if cluster_cid not in st.session_state._last_saved_annotations:
                    # First time seeing this annotation - SAVE IT immediately
                    success, message = append_to_sheet(
                        st.session_state.user_name,
                        cluster_cid,
                        annotation
                    )
                    
                    if success:
                        st.session_state.saved_annotation_ids.add(cluster_cid)
                        st.session_state._last_saved_annotations[cluster_cid] = copy.deepcopy(annotation)
                        st.toast(f"✅ Progress saved ({len(st.session_state.saved_annotation_ids)}/{len([a for a in st.session_state.annotations.values() if a.get('appropriateness_rating') is not None])} annotations)")
                    else:
                        st.toast(message, icon="⚠️")
                else:
                    # Existing annotation - check if it has changed since last save
                    last_saved = st.session_state._last_saved_annotations[cluster_cid]
                    has_changed = copy.deepcopy(last_saved) != copy.deepcopy(annotation)
                    
                    if has_changed:
                        # Send to Google Sheets via Apps Script (will create new row even if cluster_cid exists)
                        success, message = append_to_sheet(
                            st.session_state.user_name,
                            cluster_cid,
                            annotation
                        )
                        
                        if success:
                            st.session_state.saved_annotation_ids.add(cluster_cid)
                            st.session_state._last_saved_annotations[cluster_cid] = copy.deepcopy(annotation)
                            st.toast(f"✅ Progress saved ({len(st.session_state.saved_annotation_ids)}/{len([a for a in st.session_state.annotations.values() if a.get('appropriateness_rating') is not None])} annotations)")
                        else:
                            st.toast(message, icon="⚠️")
        
        # Clear autosave flag after processing and update throttle timer
        st.session_state._do_autosave = False
        st.session_state._last_autosave_time = current_time
        save_session_state()
