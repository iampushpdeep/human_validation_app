"""
Cluster Label Validation App
Multi-user human validation interface with per-user annotation persistence
"""

import streamlit as st
import json
import jsonlines
import numpy as np
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageFilter
import os

# Optional imports - graceful fallback for Streamlit Cloud
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import gdown
    HAS_GDOWN = True
except ImportError:
    HAS_GDOWN = False

# ============================================================================
# PAGE CONFIG & INITIALIZATION
# ============================================================================

st.set_page_config(page_title="Cluster Label Validator", layout="wide")
st.title("🏷️ Cluster Label Validation")

# Initialize session state
if "annotations" not in st.session_state:
    st.session_state.annotations = {}
if "current_cluster_idx" not in st.session_state:
    st.session_state.current_cluster_idx = 0
if "clusters" not in st.session_state:
    st.session_state.clusters = []
if "unblurred_images" not in st.session_state:
    st.session_state.unblurred_images = set()
if "view_similar" not in st.session_state:
    st.session_state.view_similar = False


# ============================================================================
# SIMPLE USER IDENTIFICATION
# ============================================================================

def identify_user():
    """Simple user identification - choose or create username"""
    
    # Use session state to persist username across refreshes
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""
    
    # If user already identified, return
    if st.session_state.user_name:
        return st.session_state.user_name
    
    # Show identification form
    st.markdown("### 👤 Identify Yourself")
    st.markdown("Choose or create your identifier:")
    
    user_name = st.text_input(
        "Your name/identifier:",
        placeholder="e.g. alice, bob, annotator_1",
        key="user_name_input"
    )
    
    if user_name and len(user_name.strip()) > 0:
        user_name = user_name.strip()
        st.session_state.user_name = user_name
        st.success(f"✅ Welcome, {user_name}!")
        st.rerun()
    else:
        st.info("👤 Please enter your name to continue")
        st.stop()


# Identify user
user_name = identify_user()

# ============================================================================
# USER INFO SIDEBAR
# ============================================================================

with st.sidebar:
    st.markdown("---")
    st.markdown(f"**👤 {user_name}**")
    st.markdown("---")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def sanitize_name(name):
    """Convert name to safe filename"""
    return name.lower().replace(" ", "_")


def get_user_annotation_file(user_name):
    """Get per-user annotation file path"""
    safe_name = sanitize_name(user_name)
    return Path("human_validation_samples/intolerant") / f"annotations_{safe_name}.json"


def load_user_annotations(user_name):
    """Load user's previous annotations"""
    filepath = get_user_annotation_file(user_name)
    
    if not filepath.exists():
        return {}
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        
        # Handle both formats: {cluster_id: annotation} or {cluster_id: {rating, feedback, etc}}
        if isinstance(data, dict):
            # If it has metadata, extract annotations
            if "annotations" in data:
                return data["annotations"]
            # Otherwise assume the whole dict is annotations
            return data
        return {}
    except Exception as e:
        st.error(f"Error loading annotations: {e}")
        return {}


def save_user_annotations(user_name, annotations):
    """Save user's annotations with timestamp"""
    filepath = get_user_annotation_file(user_name)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # Prepare data with metadata
    data = {
        "user_name": user_name,
        "timestamp": datetime.now().isoformat(),
        "annotations": annotations
    }
    
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving annotations: {e}")
        return False


def download_from_google_drive(folder_id, save_path="human_validation_samples"):
    """Download folder from Google Drive using gdown"""
    if not HAS_GDOWN:
        st.error("gdown not installed. Cannot download from Google Drive.")
        return False
    
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        with st.spinner("📥 Downloading from Google Drive..."):
            url = f"https://drive.google.com/drive/folders/{folder_id}"
            gdown.download_folder(url, output=str(save_path), quiet=True)
        st.success("✅ Downloaded successfully!")
        return True
    except Exception as e:
        st.error(f"Error downloading: {e}")
        return False


def load_clusters_from_validation_data():
    """Load clusters from human_validation_samples directory"""
    data_dir = Path("human_validation_samples/intolerant")
    
    if not data_dir.exists():
        st.warning("Data directory not found. Attempting download from Google Drive...")
        google_folder_id = "1ALgCnMWeFumIE9_9O9-MkwojgirYY4Fp"
        if download_from_google_drive(google_folder_id):
            return load_clusters_from_validation_data()
        else:
            return []
    
    clusters = []
    
    # Look for cluster_X directories
    for cluster_dir in sorted(data_dir.glob("cluster_*")):
        if not cluster_dir.is_dir():
            continue
        
        cluster_id = cluster_dir.name
        
        # Read metadata
        metadata_file = cluster_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
        else:
            metadata = {}
        
        # Read samples
        samples_file = cluster_dir / "samples.jsonl"
        samples = []
        if samples_file.exists():
            with jsonlines.open(samples_file) as reader:
                samples = [dict(obj) for obj in reader]
        
        # Collect media files
        images_dir = cluster_dir / "images"
        videos_dir = cluster_dir / "videos"
        
        images = sorted([str(p) for p in images_dir.glob("*")] if images_dir.exists() else [])
        videos = sorted([str(p) for p in videos_dir.glob("*")] if videos_dir.exists() else [])
        
        cluster = {
            "id": cluster_id,
            "metadata": metadata,
            "samples": samples,
            "images": images,
            "videos": videos
        }
        clusters.append(cluster)
    
    return clusters


def get_blurred_video_frame(video_path, blur_radius=20):
    """Extract first frame from video and apply blur"""
    if not HAS_CV2 or not Path(video_path).exists():
        return None
    
    try:
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        
        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL Image
        pil_image = Image.fromarray(frame_rgb)
        
        # Apply blur
        blurred = pil_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        return blurred
    except:
        return None


def display_media(cluster, unblur=False):
    """Display images and videos for a cluster"""
    
    col1, col2 = st.columns([1, 1])
    
    # Display images
    with col1:
        if cluster["images"]:
            st.subheader("📸 Images")
            for img_path in cluster["images"][:6]:  # Limit to 6
                if not Path(img_path).exists():
                    st.warning(f"Image not found: {img_path}")
                    continue
                
                # Load and potentially blur image
                img = Image.open(img_path)
                
                # Check if this image should be unblurred
                img_key = f"img_{img_path}"
                if img_key not in st.session_state.unblurred_images:
                    # Apply blur
                    blurred_img = img.filter(ImageFilter.GaussianBlur(radius=20))
                    st.image(blurred_img, use_container_width=True)
                    if st.button("🔍 Reveal", key=f"reveal_{img_path}"):
                        st.session_state.unblurred_images.add(img_key)
                        st.rerun()
                else:
                    # Show unblurred
                    st.image(img, use_container_width=True)
                    if st.button("👁️ Hide", key=f"hide_{img_path}"):
                        st.session_state.unblurred_images.discard(img_key)
                        st.rerun()
        else:
            st.info("No images in this cluster")
    
    # Display videos
    with col2:
        if cluster["videos"]:
            st.subheader("🎬 Videos")
            for video_path in cluster["videos"][:3]:  # Limit to 3
                if not Path(video_path).exists():
                    st.warning(f"Video not found: {video_path}")
                    continue
                
                # Try to show blurred first frame
                video_key = f"video_{video_path}"
                if video_key not in st.session_state.unblurred_images:
                    blurred_frame = get_blurred_video_frame(video_path)
                    if blurred_frame:
                        st.image(blurred_frame, use_container_width=True)
                    if st.button("▶️ Play", key=f"play_{video_path}"):
                        st.session_state.unblurred_images.add(video_key)
                        st.rerun()
                else:
                    # Show actual video
                    with open(video_path, "rb") as f:
                        st.video(f)
                    if st.button("⏹️ Hide", key=f"stop_{video_path}"):
                        st.session_state.unblurred_images.discard(video_key)
                        st.rerun()
        else:
            st.info("No videos in this cluster")


# ============================================================================
# MAIN APP
# ============================================================================

# Load clusters
if not st.session_state.clusters:
    st.session_state.clusters = load_clusters_from_validation_data()

clusters = st.session_state.clusters

if not clusters:
    st.error("❌ No clusters found. Please ensure data is available.")
    st.stop()

# Load user's annotations
if not st.session_state.annotations:
    st.session_state.annotations = load_user_annotations(user_name)

# Sidebar: Navigation
with st.sidebar:
    st.markdown("### 📋 Cluster Navigator")
    
    # Navigation buttons
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        if st.button("⬅️ Prev", width="stretch"):
            st.session_state.current_cluster_idx = max(0, st.session_state.current_cluster_idx - 1)
            st.rerun()
    
    with col2:
        st.metric("Cluster", f"{st.session_state.current_cluster_idx + 1}/{len(clusters)}")
    
    with col3:
        if st.button("Next ➡️", width="stretch"):
            st.session_state.current_cluster_idx = min(
                len(clusters) - 1, st.session_state.current_cluster_idx + 1
            )
            st.rerun()
    
    # Cluster selector
    cluster_labels = [f"{c['id']}" for c in clusters]
    selected_idx = st.selectbox(
        "Jump to cluster:",
        range(len(clusters)),
        format_func=lambda i: cluster_labels[i],
        index=st.session_state.current_cluster_idx
    )
    st.session_state.current_cluster_idx = selected_idx
    
    # Progress
    st.markdown("---")
    annotated_count = sum(1 for cid in st.session_state.annotations if st.session_state.annotations[cid])
    st.progress(annotated_count / len(clusters), text=f"{annotated_count}/{len(clusters)} labeled")
    
    # Save stats
    if st.button("💾 Force Save", width="stretch"):
        if save_user_annotations(user_name, st.session_state.annotations):
            st.success("✅ Saved!")
        else:
            st.error("❌ Save failed")

# Main content
current_cluster = clusters[st.session_state.current_cluster_idx]
cluster_id = current_cluster["id"]

st.markdown(f"## {cluster_id}")

if current_cluster["metadata"]:
    with st.expander("📝 Cluster Info"):
        st.json(current_cluster["metadata"])

# Display media
display_media(current_cluster)

# Annotation form
st.markdown("---")
st.subheader("📊 Your Assessment")

col1, col2 = st.columns([2, 1])

with col1:
    cluster_name = st.text_input(
        "Cluster name/label:",
        value=st.session_state.annotations.get(cluster_id, {}).get("label", "")
        if isinstance(st.session_state.annotations.get(cluster_id), dict)
        else "",
        placeholder="e.g., 'Pride flags', 'Rainbow symbols'"
    )

with col2:
    rating = st.selectbox(
        "Label quality:",
        [0, 1, 2, 3, 4, 5],
        index=st.session_state.annotations.get(cluster_id, {}).get("rating", 0)
        if isinstance(st.session_state.annotations.get(cluster_id), dict)
        else 0,
        format_func=lambda x: ["N/A", "Poor", "Fair", "Good", "Very Good", "Excellent"][x]
    )

feedback = st.text_area(
    "Additional feedback:",
    value=st.session_state.annotations.get(cluster_id, {}).get("feedback", "")
    if isinstance(st.session_state.annotations.get(cluster_id), dict)
    else "",
    placeholder="Any issues or suggestions?"
)

# Save annotation
if st.button("✅ Save Annotation", width="stretch", type="primary"):
    st.session_state.annotations[cluster_id] = {
        "label": cluster_name,
        "rating": rating,
        "feedback": feedback
    }
    
    if save_user_annotations(user_name, st.session_state.annotations):
        st.success(f"✅ Annotation saved for {cluster_id}")
        st.balloons()
    else:
        st.error("❌ Failed to save")
