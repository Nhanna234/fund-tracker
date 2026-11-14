"""Google sign-in (Streamlit native OIDC) with an e-mail allow-list.

If no [auth] block exists in secrets (local development), the app runs in
single-user dev mode as LOCAL_OWNER.
"""
import streamlit as st

LOCAL_OWNER = "local@dev"


def _secrets_get(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:  # no secrets.toml at all
        return default


def auth_configured() -> bool:
    return bool(_secrets_get("auth"))


def require_login() -> str:
    """Block the page until the user is signed in; return the owner e-mail."""
    if not auth_configured():
        return LOCAL_OWNER

    if not st.user.is_logged_in:
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            st.markdown("## 📈 Fund Tracker")
            st.write("Pooled-money tracker: NAV and units for every investor, plus holdings, trades and analytics.")
            st.button("Sign in with Google", type="primary", icon=":material/login:",
                      on_click=st.login, args=("google",), use_container_width=True)
        st.stop()

    email = (st.user.get("email") or "").lower()
    allowed = [e.lower() for e in (_secrets_get("allowed_emails") or [])]
    if allowed and email not in allowed:
        st.error(f"{email} is not authorised to use this app.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    return email


def sidebar_user(owner: str):
    with st.sidebar:
        if auth_configured():
            st.caption(f"Signed in as **{owner}**")
            st.button("Sign out", on_click=st.logout, icon=":material/logout:", use_container_width=True)
        else:
            st.caption("Local dev mode — no sign-in configured")
