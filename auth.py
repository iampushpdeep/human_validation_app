import streamlit as st

def check_user_credentials(email, password):
    """Check if user is in allowed list"""
    allowed_users = st.secrets.get("allowed_users", {})
    return allowed_users.get(email) == password

def login():
    """Display login page"""
    st.set_page_config(page_title="Cluster Validator - Login", layout="centered")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🏷️ Cluster Validator")
        st.markdown("---")
        
        email = st.text_input("Email", placeholder="user@example.com")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        
        if st.button("Login", use_container_width=True):
            if email and password:
                if check_user_credentials(email, password):
                    st.session_state.authenticated = True
                    st.session_state.user_email = email
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error("❌ Invalid email or password")
            else:
                st.warning("⚠️ Please enter email and password")

def logout():
    """Logout button"""
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.session_state.user_email = None
        st.rerun()
