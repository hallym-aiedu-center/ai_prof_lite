from core.moodle.client import get_moodle_client
from modules.credentials.required import require_user_moodle_credential


async def get_user_moodle_client(user_id: int):
    """Build a Moodle client strictly from the current user's credential."""
    base_url, token = await require_user_moodle_credential(user_id)
    return get_moodle_client(base_url=base_url, token=token)
