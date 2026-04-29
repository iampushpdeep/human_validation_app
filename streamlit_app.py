import streamlit as st
import json
import jsonlines
import numpy as np
import os
import shutil
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageFilter

# Optional imports
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
            "unblurred_images": list(st.session_state.unblurred_images),
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
    st.session_state.unblurred_images = set(session_data.get("unblurred_images", []))
if "user_name" not in st.session_state:
    st.session_state.user_name = session_data.get("user_name", "")
if "app_page" not in st.session_state:
    st.session_state.app_page = "dashboard" if st.session_state.user_name else "login"
if "last_saved" not in st.session_state:
    st.session_state.last_saved = session_data.get("last_saved", "Never")
if "auto_save_enabled" not in st.session_state:
    st.session_state.auto_save_enabled = True
if "show_confirm_clear" not in st.session_state:
    st.session_state.show_confirm_clear = False

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_cluster_evaluated(annotations, cluster_cid):
    """Check if a cluster has been genuinely evaluated (not just pre-selected defaults)"""
    if cluster_cid not in annotations:
        return False
    ann = annotations[cluster_cid]
    # Only count as evaluated if rating is explicitly set to a value
    return ann.get("appropriateness_rating") is not None

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
        
        if isinstance(data, dict):
            if "annotations" in data:
                return data["annotations"]
            return data
        return {}
    except Exception as e:
        return {}

def save_user_annotations(user_name, annotations):
    """Save user's annotations with timestamp"""
    filepath = get_user_annotation_file(user_name)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "user_name": user_name,
        "timestamp": datetime.now().isoformat(),
        "annotations": annotations
    }
    
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        st.session_state.last_saved = datetime.now().isoformat()
        return True
    except Exception as e:
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

@st.cache_data
def load_clusters_from_validation_data():
    """Load clusters from human_validation_samples/intolerant directory"""
    base_path = Path("human_validation_samples/intolerant")
    
    if not base_path.exists():
        return None
    
    metadata_path = base_path / "metadata.json"
    if not metadata_path.exists():
        return None
    
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    
    clusters_list = []
    
    for cluster_str_id, cluster_info in sorted(metadata.get("clusters", {}).items()):
        try:
            cluster_id = int(cluster_str_id)
            cluster_dir = base_path / f"cluster_{cluster_id}"
            samples_file = cluster_dir / "samples.jsonl"
            
            if not samples_file.exists():
                continue
            
            examples = []
            with open(samples_file, "r") as f:
                for line in f:
                    if line.strip():
                        examples.append(json.loads(line))
            
            cluster_obj = {
                "id": cluster_id,
                "cid": f"cluster_{cluster_id}",
                "label": cluster_info.get("name", f"Cluster {cluster_id}"),
                "summary": cluster_info.get("summary", ""),
                "total_samples": cluster_info.get("num_samples", len(examples)),
                "total_in_cluster": cluster_info.get("total_in_cluster", 0),
                "examples": examples,
                "sample_fraction": cluster_info.get("sample_fraction", 0.0),
            }
            
            clusters_list.append(cluster_obj)
        except Exception as e:
            continue
    
    return clusters_list

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

def display_media(cluster_id, example_num, images, videos):
    """Display images and videos with blur/reveal toggles"""
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
                image_path = Path(f"human_validation_samples/intolerant/cluster_{cluster_id}") / img_path
                
                with cols[img_idx % len(cols)]:
                    if image_path.exists():
                        try:
                            img = Image.open(image_path)
                            if image_key in st.session_state.unblurred_images:
                                st.image(img, use_container_width=True)
                                if st.button("🔒 Blur", key=f"blur_{image_key}", use_container_width=True):
                                    st.session_state.unblurred_images.discard(image_key)
                                    save_session_state()
                                    st.rerun()
                            else:
                                blurred_img = img.filter(ImageFilter.GaussianBlur(radius=20))
                                st.image(blurred_img, use_container_width=True)
                                if st.button("👁️ Reveal", key=f"unblur_{image_key}", use_container_width=True):
                                    st.session_state.unblurred_images.add(image_key)
                                    save_session_state()
                                    st.rerun()
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
                
                video_path = Path(f"human_validation_samples/intolerant/cluster_{cluster_id}") / video_path_str
                video_key = f"{cluster_id}_{example_num}_vid_0"
                
                if video_path.exists():
                    try:
                        with open(video_path, 'rb') as f:
                            video_bytes = f.read()
                            if video_key in st.session_state.unblurred_images:
                                st.video(video_bytes)
                                if st.button("🔒 Blur", key=f"blur_vid_{video_key}", use_container_width=True):
                                    st.session_state.unblurred_images.discard(video_key)
                                    save_session_state()
                                    st.rerun()
                            else:
                                blurred_frame = get_blurred_video_frame(video_path)
                                if blurred_frame:
                                    st.image(blurred_frame, use_container_width=True)
                                else:
                                    st.info("🎬 Video (Blurred)")
                                if st.button("👁️ Reveal Video", key=f"reveal_vid_{video_key}", use_container_width=True):
                                    st.session_state.unblurred_images.add(video_key)
                                    save_session_state()
                                    st.rerun()
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
                    
                    video_path = Path(f"human_validation_samples/intolerant/cluster_{cluster_id}") / video_path_str
                    video_key = f"{cluster_id}_{example_num}_vid_{vid_idx}"
                    
                    with cols[vid_idx % len(cols)]:
                        if video_path.exists():
                            try:
                                with open(video_path, 'rb') as f:
                                    video_bytes = f.read()
                                    if video_key in st.session_state.unblurred_images:
                                        st.video(video_bytes)
                                        if st.button("🔒", key=f"blur_vid_{video_key}", use_container_width=True):
                                            st.session_state.unblurred_images.discard(video_key)
                                            save_session_state()
                                            st.rerun()
                                    else:
                                        blurred_frame = get_blurred_video_frame(video_path)
                                        if blurred_frame:
                                            st.image(blurred_frame, use_container_width=True)
                                        else:
                                            st.info("🎬 Blurred")
                                        if st.button("👁️", key=f"reveal_vid_{video_key}", use_container_width=True):
                                            st.session_state.unblurred_images.add(video_key)
                                            save_session_state()
                                            st.rerun()
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
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("▶️ Start Evaluation", use_container_width=True, key="start_eval"):
            st.session_state.app_page = "evaluation"
            st.rerun()
    
    with col2:
        if st.button("📊 View Summary", use_container_width=True, key="view_summary"):
            st.session_state.app_page = "summary"
            st.rerun()
    
    with col3:
        if st.button("👤 Logout", use_container_width=True, key="logout_btn"):
            st.session_state.user_name = ""
            st.session_state.app_page = "login"
            save_session_state()
            st.rerun()
    
    st.divider()
    
    # Session info
    st.markdown("**Session Information:**")
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"👤 User: {st.session_state.user_name}")
    with col2:
        if st.session_state.last_saved != "Never":
            st.caption(f"⏱️ Last saved: {st.session_state.last_saved}")
        else:
            st.caption("Not saved yet")
    
    st.divider()
    
    # Admin/Settings section
    with st.expander("⚙️ Settings & Data Management"):
        st.markdown("### Clear Data")
        st.warning("⚠️ This action cannot be undone!")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Clear My Annotations", use_container_width=True, key="clear_my_data"):
                # Clear current user's annotations
                user_file = get_user_annotation_file(st.session_state.user_name)
                if user_file.exists():
                    os.remove(user_file)
                st.session_state.annotations = {}
                st.success(f"✅ Cleared all annotations for {st.session_state.user_name}")
                st.rerun()
        
        with col2:
            if st.button("🗑️ Clear ALL Data", use_container_width=True, key="clear_all_data"):
                st.session_state.show_confirm_clear = True
        
        if st.session_state.get("show_confirm_clear", False):
            st.error("🚨 Are you sure? This will delete ALL user data!")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ YES, Delete Everything", use_container_width=True, key="confirm_clear"):

                    if SESSION_DIR.exists():
                        shutil.rmtree(SESSION_DIR)
                    # Clear all annotation files
                    anno_dir = Path("human_validation_samples/intolerant")
                    if anno_dir.exists():
                        for f in anno_dir.glob("annotations_*.json"):
                            os.remove(f)
                        export_file = anno_dir / "annotations_export.json"
                        if export_file.exists():
                            os.remove(export_file)
                    st.session_state.annotations = {}
                    st.session_state.user_name = ""
                    st.session_state.show_confirm_clear = False
                    st.success("✅ All data cleared!")
                    st.rerun()
            
            with col2:
                if st.button("❌ Cancel", use_container_width=True, key="cancel_clear"):
                    st.session_state.show_confirm_clear = False
                    st.rerun()

def show_summary_page():
    """Show evaluation summary and statistics"""
    clusters = st.session_state.clusters
    annotations = st.session_state.annotations
    
    st.title("📊 Evaluation Summary")
    st.divider()
    
    completed = sum(1 for c in clusters if is_cluster_evaluated(annotations, c.get("cid", f"cluster_{clusters.index(c)}")))
    st.metric("Completed Evaluations", f"{completed}/{len(clusters)}")
    
    st.divider()
    
    # Evaluation breakdown
    st.markdown("### Evaluation Breakdown")
    
    ratings = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, "none": 0}
    
    for c in clusters:
        cid = c.get("cid", f"cluster_{clusters.index(c)}")
        if is_cluster_evaluated(annotations, cid):
            rating = annotations[cid].get("appropriateness_rating")
            if rating:
                ratings[rating] += 1
        else:
            ratings["none"] += 1
    
    if completed > 0:
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown(f"**⭐ Highly Appropriate**\n{ratings[5]}")
        with col2:
            st.markdown(f"**⭐ Somewhat Appropriate**\n{ratings[4]}")
        with col3:
            st.markdown(f"**⭐ Neutral**\n{ratings[3]}")
        with col4:
            st.markdown(f"**⭐ Somewhat Inappropriate**\n{ratings[2]}")
        with col5:
            st.markdown(f"**⭐ Not Appropriate**\n{ratings[1]}")
    
    st.divider()
    
    # Evaluated clusters list
    st.markdown("### Evaluated Clusters")
    
    for idx, c in enumerate(clusters):
        cid = c.get("cid", f"cluster_{idx}")
        if is_cluster_evaluated(annotations, cid):
            ann = annotations[cid]
            rating = ann.get("appropriateness_rating", "N/A")
            
            # Star representation
            stars = "⭐" * (rating if isinstance(rating, int) else 0)
            
            col1, col2, col3 = st.columns([1, 3, 1])
            with col1:
                st.caption(f"ID: {c.get('id', idx)}")
            with col2:
                st.caption(f"{c.get('label', 'N/A')}")
            with col3:
                st.caption(stars)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back to Dashboard", use_container_width=True):
            st.session_state.app_page = "dashboard"
            st.rerun()
    
    with col2:
        if st.button("💾 Export Results", use_container_width=True):
            output_path = Path("human_validation_samples/intolerant/annotations_export.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tasks = []
            for idx, c in enumerate(clusters):
                cid = c.get("cid", f"cluster_{idx}")
                if is_cluster_evaluated(annotations, cid):
                    a = annotations[cid]
                    tasks.append({
                        "id": idx + 1,
                        "cluster_id": cid,
                        "cluster_name": c.get("label", f"Cluster {idx}"),
                        "annotation": a,
                        "timestamp": datetime.now().isoformat(),
                    })
            
            with open(output_path, "w") as f:
                json.dump(tasks, f, indent=2)
            st.success(f"✅ Exported {len(tasks)} annotations")

def show_evaluation_page():
    """Show cluster evaluation page"""
    clusters = st.session_state.clusters
    
    if not clusters:
        st.error("❌ No clusters found. Check human_validation_samples/intolerant/")
        st.stop()
    
    if not st.session_state.annotations:
        st.session_state.annotations = load_user_annotations(st.session_state.user_name)
    
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
            
            if st.button(f"{is_current} [{idx+1}] {is_completed} {c.get('label', 'N/A')[:30]}", 
                        use_container_width=True, key=f"nav_cluster_{idx}"):
                st.session_state.current_cluster_idx = idx
                st.rerun()
        
        st.divider()
        
        # Auto-save toggle
        st.markdown("### Settings")
        st.session_state.auto_save_enabled = st.toggle("Auto-save", st.session_state.auto_save_enabled)
        
        if st.session_state.last_saved != "Never":
            st.caption(f"Last saved: {st.session_state.last_saved}")
    
    # Main content
    cluster = clusters[st.session_state.current_cluster_idx]
    cluster_id = cluster.get("id", st.session_state.current_cluster_idx)
    cluster_cid = cluster.get("cid", f"cluster_{cluster_id}")
    cluster_label = cluster.get("label", "N/A")
    
    # Header with navigation
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("⬅️ Previous", use_container_width=True):
            if st.session_state.current_cluster_idx > 0:
                st.session_state.current_cluster_idx -= 1
                save_session_state()
                st.rerun()

    with col2:
        cluster_num = st.session_state.current_cluster_idx + 1
        st.markdown(f"<h3 style='text-align: center;'>Cluster {cluster_num} / {len(clusters)}</h3>", unsafe_allow_html=True)

    with col3:
        if st.button("Next ➡️", use_container_width=True):
            if st.session_state.current_cluster_idx < len(clusters) - 1:
                st.session_state.current_cluster_idx += 1
                save_session_state()
                st.rerun()

    st.divider()

    # Display cluster metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Cluster ID", cluster_id)
    with col2:
        st.metric("Total Samples", cluster.get("total_samples", len(cluster.get("examples", []))))
    with col3:
        if cluster.get("examples"):
            avg_prob = np.mean([ex.get("cluster_probability", 0.85) for ex in cluster.get("examples", [])])
            st.metric("Avg Probability", f"{float(avg_prob):.2f}")
        else:
            st.metric("Avg Probability", "N/A")

    st.markdown(f"### **Label:** `{cluster_label}`")
    st.caption(f"Summary: {cluster.get('summary', 'No summary available')}")

    # Display examples
    st.markdown(f"#### Examples ({len(cluster.get('examples', []))} samples):")
    examples = cluster.get("examples", [])
    if examples:
        for i, ex in enumerate(examples, 1):
            with st.container(border=True):
                if isinstance(ex, dict):
                    images = ex.get("images", []) or ([ex.get("image")] if ex.get("image") else [])
                    videos = ex.get("videos", []) or ([ex.get("video")] if ex.get("video") else [])
                    
                    # Display media
                    if images or videos:
                        display_media(cluster_id, i, images, videos)
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

    # Annotation form with evaluation criteria
    st.markdown("### Your Evaluation")

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
    
    # Create 5 columns for radio-like buttons
    col1, col2, col3, col4, col5 = st.columns(5)
    
    rating_selected = None
    
    with col1:
        if st.button("⭐\n**1 - Not\nAppropriate**", use_container_width=True, key=f"rate_1_{cluster_cid}"):
            ann["appropriateness_rating"] = 1
            st.rerun()
    
    with col2:
        if st.button("⭐⭐\n**2 - Somewhat\nInappropriate**", use_container_width=True, key=f"rate_2_{cluster_cid}"):
            ann["appropriateness_rating"] = 2
            st.rerun()
    
    with col3:
        if st.button("⭐⭐⭐\n**3 - Neutral**", use_container_width=True, key=f"rate_3_{cluster_cid}"):
            ann["appropriateness_rating"] = 3
            st.rerun()
    
    with col4:
        if st.button("⭐⭐⭐⭐\n**4 - Somewhat\nAppropriate**", use_container_width=True, key=f"rate_4_{cluster_cid}"):
            ann["appropriateness_rating"] = 4
            st.rerun()
    
    with col5:
        if st.button("⭐⭐⭐⭐⭐\n**5 - Highly\nAppropriate**", use_container_width=True, key=f"rate_5_{cluster_cid}"):
            ann["appropriateness_rating"] = 5
            st.rerun()

    score = ann["appropriateness_rating"]
    
    # Show selected rating with visual feedback
    if score is not None:
        st.divider()
        st.success(f"✅ You selected: {appropriateness_options[score]}")
        st.divider()
        
        # Show the scoring guide table
        st.markdown("""
| Score | Meaning |
|-------|---------|
| 5 | ✅ **Highly appropriate** - The name clearly and accurately represents all the content in this cluster. It's specific, unambiguous, and perfectly captures the essence of the posts. |
| 4 | 👍 **Somewhat appropriate** - The name is mostly accurate and describes the general theme well, though there might be minor issues or slight room for improvement. |
| 3 | 🤷 **Neutral** - The name is partially accurate but has noticeable gaps or ambiguities. Some posts fit well, others don't. Improvements would be beneficial. |
| 2 | 👎 **Somewhat inappropriate** - The name has significant issues. Many posts don't fit well, or the name is confusing/misleading in important ways. |
| 1 | ❌ **Not appropriate** - The name is misleading, irrelevant, or completely misrepresents the content. It fails to capture what these posts are about. |
""")
        
        st.divider()
    else:
        st.info("👆 **Click one of the 5 options above to rate this cluster**")
        st.stop()

    # ============================================================================
    # IF LOW/NEUTRAL SCORE (1-3): Show follow-up questions
    # ============================================================================
    if ann["appropriateness_rating"] in [1, 2, 3]:
        st.markdown("### Step 2: Help Us Improve")
        st.warning("📝 Please answer these questions to help us refine the label")
        st.markdown("---")
        
        st.markdown("#### 1️⃣ What is the main issue with this name?")
        ann["follow_up_answers"]["main_issue"] = st.radio(
            "Select the primary concern:",
            options=[
                "too_broad",
                "too_narrow",
                "misleading",
                "unclear",
                "other"
            ],
            format_func=lambda x: {
                "too_broad": "📊 Too broad - covers too many different types of content",
                "too_narrow": "🔍 Too narrow - too specific for some examples",
                "misleading": "⚠️ Misleading - doesn't accurately reflect the content",
                "unclear": "❓ Unclear - confusing or ambiguous phrasing",
                "other": "🤔 Other reason"
            }[x],
            horizontal=False,
            key=f"main_issue_{cluster_cid}",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        if ann["follow_up_answers"]["main_issue"] == "other":
            st.markdown("#### 2️⃣ What's the specific issue with this name?")
            ann["follow_up_answers"]["missing_element"] = st.text_area(
                "Please describe the issue:",
                value=ann["follow_up_answers"].get("missing_element", ""),
                placeholder="E.g., 'Should mention cryptocurrency scams' or 'Too vague about the specific activity'...",
                height=80,
                key=f"missing_{cluster_cid}",
                label_visibility="collapsed"
            )
            
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
                key=f"suggested_name_{cluster_cid}",
                label_visibility="collapsed"
            )
            
            if suggested_text:
                char_count = len(suggested_text)
                st.caption(f"Characters: {char_count}/90")
            
            ann["suggested_name"] = suggested_text
        
        st.divider()
        
        st.markdown("#### 📝 Additional observations (optional)")
        ann["notes"] = st.text_area(
            "Notes:",
            value=ann["notes"],
            placeholder="Any other feedback or observations?",
            height=80,
            key=f"notes_{cluster_cid}",
            label_visibility="collapsed"
        )

    st.divider()

    # Save/Export buttons
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 Save Progress", use_container_width=True):
            if save_user_annotations(st.session_state.user_name, st.session_state.annotations):
                save_session_state()
                st.success("✅ Progress saved!")
            else:
                st.error("❌ Failed to save progress")

    with col2:
        if st.button("⬆️ Auto-save", use_container_width=True):
            if st.session_state.auto_save_enabled:
                if save_user_annotations(st.session_state.user_name, st.session_state.annotations):
                    save_session_state()
                    st.toast("Auto-saved!")

    with col3:
        if st.button("🔄 Reset Cluster", use_container_width=True):
            if cluster_cid in st.session_state.annotations:
                del st.session_state.annotations[cluster_cid]
                save_session_state()
                st.rerun()

    st.divider()
    completed = sum(1 for c in clusters if is_cluster_evaluated(st.session_state.annotations, c.get("cid", f"cluster_{clusters.index(c)}")))
    st.progress(completed / len(clusters) if clusters else 0)
    st.caption(f"Progress: {completed}/{len(clusters)} clusters evaluated")

# ============================================================================
# MAIN APP ROUTER
# ============================================================================

# Load clusters
if not st.session_state.clusters:
    clusters_data = load_clusters_from_validation_data()
    if clusters_data:
        st.session_state.clusters = clusters_data

# Title
st.title("🏷️ Cluster Label Validator")

# Page routing
if st.session_state.app_page == "login":
    show_login_page()
elif st.session_state.app_page == "dashboard":
    show_dashboard_page()
elif st.session_state.app_page == "evaluation":
    show_evaluation_page()
elif st.session_state.app_page == "summary":
    show_summary_page()
else:
    show_login_page()

# Auto-save functionality
if st.session_state.user_name and st.session_state.auto_save_enabled and st.session_state.annotations:
    save_user_annotations(st.session_state.user_name, st.session_state.annotations)
    save_session_state()
